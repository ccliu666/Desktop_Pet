"""Edge-TTS 语音合成与播放。

免费微软语音，无需 Key。播放采用"一句超前预取"流水线：正在播第 N 句时，
后台线程已开始合成第 N+1 句（Windows 上再解码成 wav），播完立刻接上，
句间几乎无停顿。静音模式下不发声音但照常发 started/finished 信号——口型照动。

Windows 播放：Qt 的 QMediaPlayer 音频后端在部分电脑/白板上无声（事件流正常
但扬声器不响），因此走 winsound(waveOut) 通道——QAudioDecoder 把 mp3 解码成
wav 后异步播放，按 wav 时长定时收尾。其他平台仍用 QMediaPlayer。
"""
import asyncio
import os
import sys
import tempfile
import threading
import wave

try:
    import winsound                # 仅 Windows
except ImportError:
    winsound = None

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QAudioDecoder, QAudioFormat

SYNTH_TIMEOUT = 25     # 单句合成超时（秒）


class Speaker(QObject):
    started = Signal()          # 一句开始播放（含静音模拟）
    finished = Signal()         # 一句播放结束
    failed = Signal(str)        # 合成失败（网络/服务问题）
    _synth_done = Signal(bool, str, int)   # 合成线程 → 主线程：(ok, mp3路径或错误, 代际)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.muted = False
        self._queue = []         # 待朗读的句子文本
        self._playing = False
        self._player = None
        self._threads = []       # 仍在合成中的线程引用
        self._decoder = None     # 正在解码的 QAudioDecoder（Windows 路径）
        self._dec_mp3 = None     # 解码中的 mp3 路径（失败/打断时清理）
        self._pcm = bytearray()
        self._dec_fmt = None
        self._ready = None       # 已合成（并解码）好、待播的文件
        self._ready_dur = 0.0    # 该文件时长（winsound 定时收尾用）
        self._current_path = None  # 正在播放的文件（播完删除）
        self._prefetching = False  # 是否正在为下一句做合成/解码
        self._gen = 0            # 代际：stop() 后作废迟到的合成结果
        self._done_timer = QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(self._on_wav_done)
        self._synth_done.connect(self._on_synth_done)

    # ---------- 对外接口 ----------

    def speak(self, text: str):
        """排队朗读一句话（不会阻塞）"""
        text = text.strip()
        if not text:
            return
        self._queue.append(text)
        self._pump()

    def stop(self):
        """打断：清空队列并停止当前播放"""
        self._gen += 1
        self._queue.clear()
        self._done_timer.stop()
        if self._decoder is not None:
            self._decoder = None      # 丢弃引用，解码随即终止
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except RuntimeError:
                pass
        if self._player is not None:
            self._player.stop()
        for p in (self._current_path, self._ready, self._dec_mp3):
            self._remove_file(p)
        self._current_path = None
        self._ready = None
        self._dec_mp3 = None
        self._prefetching = False
        self._playing = False

    def set_muted(self, muted: bool):
        self.muted = muted

    def close(self):
        """应用退出前调用：等仍在合成的线程结束（最多 1 秒）"""
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=1)

    @property
    def busy(self):
        # 预取合成中的句子也算"还没说完"，否则聊天回合会过早结束
        return self._playing or bool(self._queue) or self._ready is not None or self._prefetching

    @property
    def playing(self):
        """音频是否正在真实播放（口型动画跟随它，合成预取阶段不算）"""
        return self._playing

    # ---------- 队列调度 ----------

    def _pump(self):
        """流水线调度：播放中→预取下一句；空闲→播就绪句或开始合成第一句"""
        if self._playing:
            if self._ready is None and not self._prefetching and self._queue and not self.muted:
                self._start_prefetch(self._queue.pop(0))
            return
        if self._ready is not None:
            self._play_ready()
            return
        if self._queue and not self._prefetching:
            if self.muted:
                text = self._queue.pop(0)
                self._playing = True
                self.started.emit()
                ms = int(max(800, min(5000, len(text) * 130)))
                QTimer.singleShot(ms, self._on_muted_done)
                return
            self._start_prefetch(self._queue.pop(0))

    def _start_prefetch(self, text: str):
        """后台合成一句（播放当前句的同时进行，播完即接上）"""
        self._prefetching = True
        gen = self._gen
        t = threading.Thread(target=self._synth_thread, args=(text, gen), daemon=True)
        self._threads.append(t)
        t.start()

    # ---------- 合成 ----------

    def _synth_thread(self, text: str, gen: int):
        """短命线程：建一个临时事件循环，合成完就退出"""
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            path = loop.run_until_complete(
                asyncio.wait_for(self._synth(text), timeout=SYNTH_TIMEOUT))
            self._synth_done.emit(True, path, gen)
        except Exception as e:
            self._synth_done.emit(False, f"{e.__class__.__name__}: {e}", gen)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _synth(self, text: str) -> str:
        import edge_tts
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        voice = self.cfg["tts"]["voice"]
        rate = self.cfg["tts"].get("rate", "+8%")
        await edge_tts.Communicate(text, voice=voice, rate=rate).save(tmp.name)
        return tmp.name

    def _on_synth_done(self, ok: bool, path: str, gen: int):
        if gen != self._gen:
            # stop() 之后迟到的结果：丢弃并清理临时文件
            if ok:
                self._remove_file(path)
            return
        if not ok:
            self._prefetching = False
            self.failed.emit(path)
            self._pump()
            return
        if sys.platform == "win32" and winsound is not None:
            self._decode(path)
        else:
            self._on_ready(path, 0.0)

    # ---------- Windows：解码 ----------

    def _decode(self, mp3_path: str):
        self._decoder = QAudioDecoder()
        self._dec_mp3 = mp3_path
        self._pcm = bytearray()
        self._dec_fmt = None
        self._decoder.bufferReady.connect(self._on_decode_buffer)
        self._decoder.finished.connect(self._on_decode_finished)
        self._decoder.error.connect(self._on_decode_error)
        self._decoder.setSource(QUrl.fromLocalFile(mp3_path))
        self._decoder.start()

    def _on_decode_buffer(self):
        if self._decoder is None:
            return
        buf = self._decoder.read()
        if buf is None or not buf.isValid():
            return
        fmt = buf.format()
        if self._dec_fmt is None:
            self._dec_fmt = (fmt.channelCount(), fmt.sampleRate(), fmt.sampleFormat())
        self._pcm += bytes(buf.constData())

    def _on_decode_finished(self):
        self._decoder = None
        try:
            wav_path, dur = self._make_wav()
        except Exception as e:
            self._remove_file(self._dec_mp3)
            self._dec_mp3 = None
            self._prefetching = False
            self.failed.emit(f"解码失败: {e.__class__.__name__}: {e}")
            self._pump()
            return
        self._dec_mp3 = None
        self._on_ready(wav_path, dur)

    def _make_wav(self):
        """把解码出的 PCM 写成 wav，删除 mp3，返回 (wav路径, 时长秒)"""
        if not self._pcm or self._dec_fmt is None:
            raise RuntimeError("解码结果为空")
        channels, rate, sfmt = self._dec_fmt
        if sfmt == QAudioFormat.SampleFormat.Float:
            import array as _array
            floats = _array.array("f")
            floats.frombytes(bytes(self._pcm))
            pcm16 = _array.array("h", (
                max(-32768, min(32767, int(v * 32767))) for v in floats)).tobytes()
        elif sfmt == QAudioFormat.SampleFormat.Int16:
            pcm16 = bytes(self._pcm)
        else:
            raise RuntimeError(f"不支持的采样格式: {sfmt}")
        wav_path = self._dec_mp3 + ".wav"
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm16)
        dur = len(pcm16) / (2 * channels * rate)
        self._remove_file(self._dec_mp3)
        return wav_path, dur

    def _on_decode_error(self, error, msg=None):
        print("解码错误:", error, msg)
        self._decoder = None
        self._remove_file(self._dec_mp3)
        self._dec_mp3 = None
        self._prefetching = False
        self.failed.emit(f"解码失败: {msg}")
        self._pump()

    # ---------- 播放 ----------

    def _on_ready(self, path: str, dur: float):
        self._prefetching = False
        self._ready = path
        self._ready_dur = dur
        self._pump()

    def _play_ready(self):
        self._current_path = self._ready
        self._ready = None
        self._playing = True
        self.started.emit()
        if sys.platform == "win32" and winsound is not None:
            winsound.PlaySound(self._current_path,
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self._done_timer.start(int(self._ready_dur * 1000) + 150)
        else:
            player = self._get_player()
            player.setSource(QUrl.fromLocalFile(self._current_path))
            player.play()
        self._pump()          # 播放已开始，立即为下一句开工（无缝衔接的关键）

    def _on_wav_done(self):
        """winsound 定时收尾：按 wav 时长播完即接下一句"""
        self._remove_file(self._current_path)
        self._current_path = None
        # 注意顺序：先把 _playing 复位再发 finished（收尾方要查 busy）
        self._playing = False
        self.finished.emit()
        self._pump()

    def _on_muted_done(self):
        self._playing = False
        self.finished.emit()
        self._pump()

    # ---------- 非 Windows：QMediaPlayer ----------

    def _get_player(self):
        if self._player is None:
            self._player = QMediaPlayer()
            self._audio = QAudioOutput()
            self._audio.setVolume(float(self.cfg["tts"].get("volume", 0.9)))
            self._player.setAudioOutput(self._audio)
            self._player.mediaStatusChanged.connect(self._on_status)
            self._player.errorOccurred.connect(self._on_player_error)
        return self._player

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._remove_file(self._current_path)
            self._current_path = None
            self._playing = False
            self.finished.emit()
            self._pump()

    def _on_player_error(self, error, msg):
        print("播放器错误:", error, msg)
        self._remove_file(self._current_path)
        self._current_path = None
        self._playing = False
        self.failed.emit(f"播放失败: {msg}")
        self._pump()

    # ---------- 工具 ----------

    @staticmethod
    def _remove_file(path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class PromptPlayer(Speaker):
    """固定提示语（"我在听"）的即时播放器。

    启动时后台合成+解码一次并缓存 wav（预热期静音不发声），之后每次
    play() 用 winsound 立即播放缓存，零合成延迟。合成失败（没联网）
    不重试，静默降级为只显示文字。
    """

    def __init__(self, cfg, text):
        super().__init__(cfg)
        self._warm = True            # 预热期：缓存但不出声
        self.speak(text)

    def _on_synth_done(self, ok, path, gen):
        if not ok:
            self._prefetching = False
            self._queue.clear()      # 失败不重试：没网络就只显示文字
            return
        super()._on_synth_done(ok, path, gen)

    def _play_ready(self):
        if self._warm:
            # 预热：只把 wav 留在缓存里，不发声、不发信号
            self._warm = False
            self._current_path = self._ready
            self._ready = None
            self._playing = False
            return
        super()._play_ready()

    @staticmethod
    def _remove_file(path):
        pass        # 缓存常驻（进程退出时由临时目录统一清理）

    def play(self) -> int:
        """立即播放缓存提示音，返回时长毫秒（用于"播完再开麦"）；未就绪返回 0"""
        if winsound is None or not self._current_path or not os.path.exists(self._current_path):
            return 0
        winsound.PlaySound(self._current_path,
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return int(self._ready_dur * 1000)

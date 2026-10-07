"""讯飞语音听写（流式）+ 麦克风采集 + 唤醒词监听。

MicClient    一次"听一句"的会话：sounddevice 采集 16kHz 单声道 PCM，
             经 WebSocket 流式发往讯飞云端，实时回传中间结果，静音/停止后回最终结果。
WakeListener 循环听写，识别文本命中唤醒词时发出 wake_detected。

讯飞接口：https://www.xfyun.cn/doc/asr/voicedictation/API.html
"""
import array
import base64
import collections
import datetime
import hashlib
import hmac
import json
import os
import queue
import threading
import time
from urllib.parse import urlencode

_DEBUG = os.environ.get("XYB_WAKE_DEBUG") == "1"   # 唤醒链路调试开关（开发排障用）

from PySide6.QtCore import QObject, QTimer, Signal

XF_APP_ID = "app_id"
XF_API_KEY = "api_key"
XF_API_SECRET = "api_secret"
XF_HOST = "iat-api.xfyun.cn"
XF_PATH = "/v2/iat"


def send_frame(ws, xf_cfg: dict, pcm: bytes, status: int):
    """给讯飞发一帧音频（status: 0 首帧 / 1 中间帧 / 2 末帧）"""
    data = {
        "common": {"app_id": xf_cfg[XF_APP_ID]},
        "business": {
            "language": "zh_cn", "domain": "iat",
            "accent": "mandarin", "vad_eos": 3000, "dwa": "wpgs",
        },
        "data": {
            "status": status, "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(pcm).decode(),
        },
    }
    ws.send(json.dumps(data))


def parse_iat(raw: str):
    """解析一条讯飞响应。返回 (error, words, pgs, is_partial, is_final)"""
    try:
        msg = json.loads(raw)
    except ValueError:
        return None, "", "apd", False, False
    if msg.get("code") != 0:
        return msg.get("message", "讯飞返回错误"), "", "apd", False, False
    data = msg.get("data", {})
    result = data.get("result") or {}
    pgs = result.get("pgs", "apd")
    words = "".join(
        cw.get("w", "")
        for ws in result.get("ws", [])
        if ws.get("cw") is not None
        for cw in ws["cw"]
    )
    return None, words, pgs, result.get("sn") is not None, data.get("status") == 2


def _rms(pcm: bytes) -> int:
    """int16 PCM 的均方根能量（判断有没有人说话）"""
    if not pcm:
        return 0
    a = array.array("h")
    a.frombytes(pcm)
    n = len(a)
    if not n:
        return 0
    return int((sum(x * x for x in a) / n) ** 0.5)


class MicClient(QObject):
    """一次语音听写会话（后台线程运行）。"""

    partial = Signal(str)    # 实时中间结果
    final = Signal(str)      # 最终识别文本
    failed = Signal(str)     # 出错（Key 未配置 / 网络 / 麦克风）

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg["xfyun"]
        # 可选麦克风设备（设备名或索引），None=系统默认输入设备
        self._mic_device = cfg.get("classroom", {}).get("mic_device")
        self.ready = bool(
            self._cfg.get("app_id", "").strip()
            and self._cfg.get("api_key", "").strip()
            and self._cfg.get("api_secret", "").strip()
        )
        self._ws = None
        self._stream = None
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._partial = ""
        self._got_final = False

    # ---------- 对外接口 ----------

    def start(self):
        if not self.ready:
            self.failed.emit("还没有配置讯飞语音识别 Key（config.json → xfyun）")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._partial = ""
        self._got_final = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ---------- 线程内部 ----------

    def _run(self):
        stream = None
        try:
            import sounddevice as sd
            import websocket

            self._ws = websocket.create_connection(self._auth_url(), timeout=10)
            self._ws.settimeout(0.1)    # 快轮询：中间结果（唤醒命中）尽量早收到

            def cb(indata, frames, t, status):
                if self._stop.is_set():
                    raise sd.CallbackStop
                # 有 numpy 时 indata 是 ndarray（有 tobytes），打包版没有 numpy
                # 则是原生 cffi 缓冲区（用 bytes() 取字节）
                data = indata.tobytes() if hasattr(indata, "tobytes") else bytes(indata)
                self._q.put(data)

            stream = sd.RawInputStream(
                samplerate=16000, channels=1, dtype="int16",
                blocksize=3200, callback=cb,
                device=self._mic_device,
            )
            self._stream = stream
            stream.start()

            first = True
            while not self._stop.is_set():
                # 发音频帧
                chunks = []
                while True:
                    try:
                        chunks.append(self._q.get_nowait())
                    except queue.Empty:
                        break
                if chunks:
                    self._send_frame(b"".join(chunks), 0 if first else 1)
                    first = False
                # 收结果
                try:
                    self._on_msg(self._ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
            # 收尾：最后一帧 + 等服务器回最终结果（最多 4 秒）
            try:
                self._send_frame(b"", 2)
                deadline = time.time() + 4.0
                while time.time() < deadline and not self._got_final:
                    try:
                        self._on_msg(self._ws.recv())
                    except websocket.WebSocketTimeoutException:
                        continue
                if not self._got_final:
                    # 服务器没回最终结果：用已收到的文字兜底（可能是空的）
                    self.final.emit(self._partial)
                    self._partial = ""
            except Exception:
                pass
        except Exception as e:
            if e.__class__.__name__ == "WebSocketBadStatusException":
                # 401：讯飞不认这套密钥（最常见：开通服务后没"领取免费包"）
                self.failed.emit("讯飞拒绝请求：请到讯飞控制台确认已开通并领取「语音听写」免费额度，且三个密钥复制无误")
            else:
                self.failed.emit(f"{e.__class__.__name__}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._stream = None
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None

    def _auth_url(self) -> str:
        cfg = self._cfg
        date = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S GMT")
        origin = f"host: {XF_HOST}\ndate: {date}\nGET {XF_PATH} HTTP/1.1"
        sig = base64.b64encode(
            hmac.new(cfg[XF_API_SECRET].encode(), origin.encode(),
                     hashlib.sha256).digest()
        ).decode()
        # 讯飞新版鉴权格式：authorization 内注明算法/参与签名的头/密钥，
        # 再整体 base64（旧格式 base64(api_key:sig) 会被 401 拒绝）
        auth_origin = (f'api_key="{cfg[XF_API_KEY]}", algorithm="hmac-sha256", '
                       f'headers="host date request-line", signature="{sig}"')
        auth = base64.b64encode(auth_origin.encode()).decode()
        params = urlencode({"authorization": auth, "date": date, "host": XF_HOST})
        return f"wss://{XF_HOST}{XF_PATH}?{params}"

    def _send_frame(self, pcm: bytes, status: int):
        send_frame(self._ws, self._cfg, pcm, status)

    def _on_msg(self, raw: str):
        error, words, pgs, is_partial, is_final = parse_iat(raw)
        if error:
            self.failed.emit(error)
            self._stop.set()
            return
        if pgs == "rpl":
            self._partial = words
        else:
            self._partial += words
        if is_partial:
            self.partial.emit(self._partial)
        if is_final:
            self._got_final = True
            self.final.emit(self._partial)
            self._partial = ""
            self._stop.set()


class WakeListener(QObject):
    """唤醒词监听（节能版）：本地麦克风常开 + 能量检测。

    静音时完全不走云端，不消耗讯飞免费额度；检测到持续说话声才开识别会话，
    并把触发前约 1.2 秒的预录音频一起送去识别（不漏唤醒词开头）。
    识别文字命中唤醒词（含同音容错）才发 wake_detected；
    识别失败退避 30 秒再试，避免失败风暴。
    """

    wake_detected = Signal()
    failed = Signal(str)

    GATE_RMS = 150        # "有人说话"的能量阈值（int16 RMS），config classroom.wake_gate_rms 可覆盖
    GATE_CHUNKS = 2       # 最近 3 块（0.1 秒/块）中至少 2 块超阈值才开识别会话
    PRE_ROLL = 12         # 预录音频块数（≈1.2 秒）
    SESSION_MAX_S = 30    # 单次识别会话上限（秒）
    BACKOFF_S = 30        # 识别失败后的退避（秒）

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.wake_word = cfg["pet"]["wake_word"]
        self._aliases = cfg["pet"].get("wake_aliases", [])   # 同音容错表
        self.ready = bool(
            cfg["xfyun"].get("app_id", "").strip()
            and cfg["xfyun"].get("api_key", "").strip()
            and cfg["xfyun"].get("api_secret", "").strip()
        )
        self._mic_device = cfg.get("classroom", {}).get("mic_device")
        self._gate_rms = int(cfg.get("classroom", {}).get("wake_gate_rms", self.GATE_RMS))
        self._client = MicClient(cfg)      # 复用鉴权 URL 生成
        self._active = False
        self._stop = threading.Event()
        self._q = queue.Queue()
        self._stream = None
        self._thread = None

    def set_active(self, on: bool):
        self._active = on
        if on:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        else:
            self._stop.set()
            self._q.put(b"")             # 唤醒阻塞中的 get

    # ---------- 线程内部 ----------

    def _run(self):
        """常开本地麦克风（不联网），能量检测 + 识别会话循环"""
        stream = None
        try:
            import sounddevice as sd

            def cb(indata, frames, t, status):
                if self._stop.is_set():
                    raise sd.CallbackStop
                data = indata.tobytes() if hasattr(indata, "tobytes") else bytes(indata)
                self._q.put(data)

            stream = sd.RawInputStream(
                samplerate=16000, channels=1, dtype="int16",
                blocksize=1600, callback=cb, device=self._mic_device,
            )
            self._stream = stream
            stream.start()
            self._gate_loop()
        except Exception as e:
            self.failed.emit(f"{e.__class__.__name__}: {e}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._stream = None

    def _gate_loop(self):
        """静音时完全不碰云端；检测到持续说话声才开识别会话"""
        ring = collections.deque(maxlen=self.PRE_ROLL)
        recent = collections.deque(maxlen=3)   # 最近 3 块的超阈值标记（2/3 多数判定，抗音量波动）
        last_report = time.time()
        max_rms = 0
        while not self._stop.is_set():
            try:
                chunk = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if not chunk:
                continue
            ring.append(chunk)
            rms = _rms(chunk)
            recent.append(1 if rms >= self._gate_rms else 0)
            if _DEBUG:
                max_rms = max(max_rms, rms)
                if self._gate_rms // 2 <= rms < self._gate_rms:
                    print(f"[wake] 弱音量 RMS={rms}（未达阈值 {self._gate_rms}）", flush=True)
                if time.time() - last_report >= 2:
                    print(f"[wake] 近2秒最大音量 RMS={max_rms}（触发阈值 {self._gate_rms}）", flush=True)
                    max_rms = 0
                    last_report = time.time()
            if sum(recent) >= self.GATE_CHUNKS:
                if _DEBUG:
                    print("[wake] ▶ 检测到说话声，开启讯飞识别会话", flush=True)
                self._run_session(ring)
                ring.clear()
                recent.clear()
                if self._stop.is_set():
                    break

    def _run_session(self, ring):
        """把预录音频（约 1.2 秒）+ 后续音频送讯飞，识别文字里找唤醒词"""
        import websocket
        try:
            ws = websocket.create_connection(self._client._auth_url(), timeout=10)
            ws.settimeout(0.1)
        except Exception as e:
            self._backoff(f"连接失败: {e.__class__.__name__}")
            return
        first = True
        partial = ""
        try:
            for c in ring:                          # 先发预录音频，避免漏掉唤醒词开头
                send_frame(ws, self.cfg["xfyun"], c, 0 if first else 1)
                first = False
            start = time.time()
            while not self._stop.is_set() and time.time() - start < self.SESSION_MAX_S:
                while True:
                    try:
                        send_frame(ws, self.cfg["xfyun"], self._q.get_nowait(), 1)
                    except queue.Empty:
                        break
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                error, words, pgs, is_partial, is_final = parse_iat(raw)
                if error:
                    raise RuntimeError(error)
                if pgs == "rpl":
                    partial = words
                else:
                    partial += words
                if partial and self._match(partial):
                    if _DEBUG:
                        print(f"[wake] ★ 命中: {partial!r}", flush=True)
                    self._active = False
                    self.wake_detected.emit()
                    self._stop.set()                # 交给 VoiceController 后续恢复
                    break
                if is_final:
                    if _DEBUG:
                        print(f"[wake] ◼ 会话结束: {partial!r}  未命中", flush=True)
                    break
        except RuntimeError as e:
            self._backoff(str(e))
        except Exception as e:
            self._backoff(f"{e.__class__.__name__}")
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _backoff(self, msg):
        """识别失败（额度/网络/服务端拒绝）：退避一段时间再试，避免失败风暴"""
        if _DEBUG:
            print(f"[wake] ✗ 识别失败（退避 {self.BACKOFF_S} 秒）: {msg}", flush=True)
        while True:                             # 丢弃退避期间积压的旧音频，避免误触发下一轮
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        deadline = time.time() + self.BACKOFF_S
        while not self._stop.is_set() and time.time() < deadline:
            time.sleep(0.5)

    def _match(self, text):
        """唤醒词匹配：精确 + 同音容错（孩子发音不准，讯飞常听成同音字）"""
        return self.wake_word in text or any(a in text for a in self._aliases)

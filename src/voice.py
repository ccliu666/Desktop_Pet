"""语音交互编排：麦克风按钮 + 唤醒词监听 + 打断式提问。

流程：按大按钮（或喊唤醒词）→ 打断正在说的话 → 开麦听 →
      气泡实时显示识别文本 → 说完自动提交给 ChatSession。
结束方式三种：服务器 3 秒静音自动结束 / 再按一次按钮手动结束 /
      8 秒没收到任何识别结果自动结束（防麦克风没声一直红）。
"""
import os

from PySide6.QtCore import QObject, QTimer

from asr import MicClient, WakeListener
from mic import MicButtonWidget
from tts import PromptPlayer

_DEBUG = os.environ.get("XYB_WAKE_DEBUG") == "1"   # 唤醒链路调试开关（开发排障用）

LISTEN_STALL_MS = 8000     # 开麦后这么久没收到任何识别结果 → 自动收尾
PROC_STALL_MS = 6000       # 收尾后这么久还没出最终结果 → 兜底放弃
CONT_IDLE_EXIT_MS = 90000  # 连续对话：安静这么久自动退出（回到普通唤醒监听）


class VoiceController(QObject):
    def __init__(self, cfg, session, fx=None):
        super().__init__()
        self.cfg = cfg
        self.session = session
        self.fx = fx                  # 音效播放器（唤醒提示音）
        self.mic = MicClient(cfg)
        self.wake = WakeListener(cfg)
        self.button = MicButtonWidget(cfg)
        self.prompt = PromptPlayer(cfg, "我在听")   # 唤醒触发的语音提示（启动预合成缓存）
        self.wake_enabled = bool(cfg["classroom"]["auto_wake"])
        if self.wake_enabled:
            self.wake.set_active(True)              # 启动时自动开启唤醒词监听

        self.button.clicked.connect(self.start_listen)
        self.mic.partial.connect(self._on_partial)
        self.mic.final.connect(self._on_final)
        self.mic.failed.connect(self._on_failed)
        self.wake.wake_detected.connect(self._on_wake)
        self.wake.failed.connect(self._on_wake_failed)
        session.speaker.started.connect(lambda: self.button.set_state("speaking"))
        session.speaker.finished.connect(self._on_speak_end)
        session.state_changed.connect(self._on_session_state)

        self._listening = False
        self._processing = False      # 已停止收音、等最终结果
        self.cont_mode = False        # 连续对话模式开关（右键；开启后喊一次小云宝进入）
        self.cont_active = False      # 已进入连续对话循环中
        self._cont_timer = QTimer(self)
        self._cont_timer.setSingleShot(True)
        self._cont_timer.timeout.connect(self._on_cont_idle)
        self._listen_watchdog = QTimer(self)
        self._listen_watchdog.setSingleShot(True)
        self._listen_watchdog.timeout.connect(self._on_listen_stall)
        self._proc_watchdog = QTimer(self)
        self._proc_watchdog.setSingleShot(True)
        self._proc_watchdog.timeout.connect(self._on_proc_stall)
        self.button.setVisible(bool(cfg["classroom"]["mic_button"]))

    # ---------- 对外接口 ----------

    def start_listen(self, play_prompt: bool = False):
        """大按钮：开始听一句；正在听时再按 = 手动收尾并处理。

        play_prompt=True（唤醒触发）时先语音说"我在听"（预合成缓存，
        零延迟），说完再开麦克风——避免把自己说的提示音录进去。
        """
        if _DEBUG:
            print(f"[voice] start_listen 入口: listening={self._listening} processing={self._processing} mic_ready={self.mic.ready} prompt={play_prompt}", flush=True)
        if self._listening:
            self.stop_listen()
            return
        if self._processing:
            return
        if not self.mic.ready:
            self.session.bubble.show_alert("语音识别还没配置：请管理员在 config.json → xfyun 填上 AppID/APIKey/APISecret")
            return
        # 听的时候暂停唤醒避免抢麦（只暂停，不动用户开关；说完后自动恢复）
        self.wake.set_active(False)
        self.session.stop_reply()             # 打断正在说的话（含 winsound purge，须在提示音之前）
        self._listening = True
        self.button.set_state("listening")
        self._say("我在听……")
        if play_prompt:
            delay_ms = self.prompt.play()
            if delay_ms > 0:
                QTimer.singleShot(delay_ms + 200, self._mic_start)
                return
        self._mic_start()

    def _mic_start(self):
        """真正开麦（唤醒路径下等"我在听"播完，避免把提示音录进去）"""
        if not self._listening:
            return
        self.mic.start()
        self._listen_watchdog.start(LISTEN_STALL_MS)

    def stop_listen(self):
        """手动收尾：把已收到的语音提交处理"""
        self._listen_watchdog.stop()
        if not self._listening:
            return
        self._listening = False
        self._processing = True
        self.button.set_state("speaking")     # 灰色 = 处理中
        self.mic.stop()                       # 最终结果会经 _on_final 提交
        self._proc_watchdog.start(PROC_STALL_MS)

    def set_wake_enabled(self, on: bool):
        self.wake_enabled = on
        if _DEBUG:
            print(f"[voice] set_wake_enabled({on})  ready={self.wake.ready}", flush=True)
        if on and not self.wake.ready:
            self._say("唤醒监听需要先配置讯飞 Key（config.json → xfyun）")
        self.wake.set_active(on)

    def set_button_visible(self, on: bool):
        self.button.setVisible(on)

    def set_cont_mode(self, on: bool):
        """连续对话模式：开启后自动打开唤醒监听，喊一次"小云宝"进入；
        之后每句都回答、说完自动再听，安静 90 秒自动退回普通唤醒监听。"""
        self.cont_mode = bool(on)
        if _DEBUG:
            print(f"[voice] set_cont_mode({on})", flush=True)
        if on:
            self.set_wake_enabled(True)     # 第一次进入要靠唤醒词
        else:
            self.cont_active = False
            self._cont_timer.stop()
            if self._listening or self._processing:
                self._cancel_listen_silent()

    # ---------- 内部 ----------

    def _on_partial(self, text):
        self._say("🎤 " + text)
        if self._listening:
            self._listen_watchdog.start(LISTEN_STALL_MS)   # 有识别结果就重新计时
        if self.cont_active:
            self._cont_timer.start(CONT_IDLE_EXIT_MS)      # 有说话声就重置安静计时

    def _on_listen_stall(self):
        """开麦后一直没有任何识别结果（麦克风没声/被占用）：自动收尾"""
        if self._listening:
            self.stop_listen()

    def _on_proc_stall(self):
        """收尾后服务器一直没回最终结果：兜底放弃，恢复可再试"""
        if self._processing:
            self._processing = False
            self.button.set_state("idle")
            if self.cont_active:
                self.start_listen(play_prompt=False)   # 连续对话：安静地继续听
                return
            self._say("没听清，再说一次好吗？")
            self.session.bubble.auto_hide(4000)
            # 唤醒恢复不在这里：等本轮状态回到 idle（避免听到自己的声音）

    def _on_final(self, text):
        if not (self._listening or self._processing):
            return
        self._listening = False
        self._processing = False
        self._listen_watchdog.stop()
        self._proc_watchdog.stop()
        self.button.set_state("idle")
        text = text.strip().strip("，。,. ")
        if text:
            self.session.ask(text, from_voice=True)
            if self.cont_active:
                self._cont_timer.start(CONT_IDLE_EXIT_MS)   # 有提问就重置安静计时
        elif self.cont_active:
            self.start_listen(play_prompt=False)   # 连续对话：没听清就安静地继续听
        else:
            self._say("没听清，再说一次好吗？")
            self.session.bubble.auto_hide(4000)
        # 唤醒恢复不在这里：等本轮状态回到 idle（避免听到自己的声音）

    def _on_failed(self, msg):
        if not (self._listening or self._processing):
            return
        self._listening = False
        self._processing = False
        self._listen_watchdog.stop()
        self._proc_watchdog.stop()
        self.button.set_state("idle")
        if self.cont_active:
            self.start_listen(play_prompt=False)   # 连续对话：安静地继续听（失败由安静计时兜底退出）
            return
        # 气泡可能被关闭，错误必须强制显示（额度用完/网络问题时老师才看得到原因）
        self.session.bubble.show_alert(
            msg if "还没有配置" in msg else f"语音识别出错：{msg}，请检查讯飞额度或网络后重试")
        # 唤醒恢复不在这里：等本轮状态回到 idle（避免听到自己的声音）

    def _on_wake(self):
        if _DEBUG:
            print("[voice] ★ 唤醒命中，转开始听", flush=True)
        if self.cont_mode:
            self.cont_active = True     # 进入连续对话循环
            self._cont_timer.start(CONT_IDLE_EXIT_MS)
            if _DEBUG:
                print("[voice] 连续对话模式进入", flush=True)
        # 唤醒触发：语音说"我在听"（fx 提示音与提示语音共用 winsound 单通道，只留语音）
        self.start_listen(play_prompt=True)

    def _on_wake_failed(self, msg):
        pass    # 唤醒监听失败静默重试，不弹气泡刷屏

    def _on_speak_end(self):
        if not self._listening:
            self.button.set_state("idle")

    def _on_session_state(self, state):
        if state == "speaking" or state == "thinking":
            self.button.set_state("speaking")
        elif state == "idle":
            # 整轮对话彻底结束（语音也播完了）才恢复唤醒监听，
            # 否则唤醒会在小云宝自己说话时听到"小云宝"而自我触发
            if self.cont_active:
                # 连续对话：说完这一轮，自动开始听下一句（说完再听）
                self.start_listen(play_prompt=False)
            else:
                self._resume_wake()

    def _on_cont_idle(self):
        """连续对话安静太久：自动退出循环，回到普通唤醒监听（再喊"小云宝"进入）"""
        if not (self.cont_active and self.cont_mode):
            return
        self.cont_active = False
        if _DEBUG:
            print("[voice] 连续对话安静超时，退回普通唤醒监听", flush=True)
        self._cancel_listen_silent()
        self._resume_wake()

    def _cancel_listen_silent(self):
        """安静地取消当前收听（不弹提示、不触发收尾流程）"""
        self._listening = False
        self._processing = False
        self._listen_watchdog.stop()
        self._proc_watchdog.stop()
        self.mic.stop()
        self.button.set_state("idle")

    def _resume_wake(self):
        if self.wake_enabled:
            self.wake.set_active(True)

    def _say(self, text):
        if self.session.bubble:
            self.session.bubble.set_text(text)

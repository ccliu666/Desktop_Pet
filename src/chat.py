"""DeepSeek 聊天客户端与对话编排。

ChatBot    流式请求 + 幼儿安全护栏 + 按句切分
ChatSession 编排一轮对话：气泡打字机 + 逐句 TTS + 口型动画 + 打断

注意：reply_stream 在后台线程执行（httpx 同步流式会阻塞），
句回调通过 Qt 信号送回主线程，UI 不卡顿。
"""
import json
import math
import threading

import httpx
from PySide6.QtCore import QObject, QTimer, Signal

BANNED_WORDS = ("自杀", "血腥", "恐怖故事", "杀人", "赌博", "砍头", "鬼故事")
FALLBACK = "我们聊点开心的事情吧！"


class ChatBot:
    """DeepSeek 对话客户端。ready=False 时只回友好提示（Key 未配置）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.key = cfg["deepseek"]["api_key"].strip()
        self.ready = bool(self.key)
        self.history = []          # [{"role":..., "content":...}, ...] 最近若干条
        self._carry = ""           # 流式分句的残留文字

    def _system_prompt(self):
        pet = self.cfg["pet"]
        return (
            f"{pet['persona']}\n"
            "你的说话要求：\n"
            "1. 说话要像亲切、专业的幼儿园老师：语言干净、自然、成熟，"
            "温和有耐心；不用叠词、拟声词、娃娃腔装可爱，也不冷冰冰；\n"
            "2. 自称\"小云宝\"，不称\"老师\"，少用\"我\"——多说\"小云宝来给大家……\"这样的说法；\n"
            "3. 称呼听众用\"大家\"\"小朋友们\"\"你们\"，不要单独用\"你\"——课堂上面对的是全班孩子；\n"
            "4. 句子简明完整，每句不超过 50 个字，每次回复 3~5 句，把知识点讲清楚；\n"
            "5. 讲知识用打比方和提问引导，先讲结论再展开，层次清楚；讲故事按情节慢慢展开；\n"
            "6. 绝对不说不适合幼儿的内容（暴力、恐怖、粗俗等），被问到就自然转移到安全话题；\n"
            "7. 只输出纯文字，不要 Markdown、表情符号、网址或代码；\n"
            "8. 内容必须准确：背古诗、唱儿歌、讲常识时只输出你确定的内容，"
            "记不全就诚实地说记不全、邀请大家一起想，绝不编造诗句或答案；\n"
            "9. 小朋友请你背诗或唱歌时，可以打破第 4 条的字数限制，按原文完整背诵；\n"
            "10. 小朋友问你是谁、让你自我介绍时，必须说出完整名称：\"我叫小云宝，是余杭区未来科技城海云幼儿园的AI助教\"，"
            "再说一两样本领（讲故事、唱儿歌、回答小问题），两三句即可，不要展开。"
        )

    def _sanitize(self, text: str):
        for ch in ("*", "#", "`", ">", "|"):
            text = text.replace(ch, "")
        text = text.replace("\\n", "\n")
        return text.strip()

    def _split_sentences(self, chunk: str, flush: bool):
        """流式累积，按句号/叹号/问号/分号/换行切出完整句"""
        self._carry += chunk
        enders = "。！？!?；;\n"
        while True:
            idx = -1
            for c in enders:
                i = self._carry.find(c)
                if i >= 0 and (idx < 0 or i < idx):
                    idx = i
            if idx < 0:
                break
            sentence = self._carry[: idx + 1]
            self._carry = self._carry[idx + 1 :]
            if sentence.strip():
                yield sentence.strip()
        if flush and self._carry.strip():
            yield self._carry.strip()
            self._carry = ""

    def reply_stream(self, user_text: str, on_sentence):
        """流式请求，每切出一句就回调 on_sentence(句子)。后台线程调用。"""
        if not self.ready:
            on_sentence("我还没有大脑呢，请老师帮我在 config.json 里填上 DeepSeek API Key～")
            return
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages += self.history[-8:]
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.cfg["deepseek"]["model"],
            "messages": messages,
            "stream": True,
            "temperature": 0.7,       # 0.9 太随机，背诗/常识容易编造；0.7 兼顾活泼与准确
            "max_tokens": 600,        # 整首诗/整首儿歌放得下
        }
        self._carry = ""
        base = self.cfg["deepseek"]["base_url"].rstrip("/")
        try:
            with httpx.stream(
                "POST",
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=60.0,
            ) as resp:
                if resp.status_code != 200:
                    on_sentence(f"大脑开小差了（HTTP {resp.status_code}），再试一次吧～")
                    return
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                    except (ValueError, KeyError):
                        continue
                    if not delta:
                        continue
                    for sentence in self._split_sentences(delta, flush=False):
                        on_sentence(self._sanitize(sentence))
            for sentence in self._split_sentences("", flush=True):
                on_sentence(self._sanitize(sentence))
        except httpx.HTTPError as e:
            on_sentence(f"哎呀，网络开小差了（{e.__class__.__name__}），再试一次吧～")

    def remember(self, user_text: str, reply_text: str):
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply_text})
        self.history = self.history[-16:]


class ChatSession(QObject):
    """一轮对话的编排：气泡 + TTS + 口型 + 打断。"""

    sentence_shown = Signal(str)     # 当前累计回复文本（舞台字幕用）
    state_changed = Signal(str)      # thinking / speaking / idle
    _got_sentence = Signal(str)      # 后台线程 → 主线程的句回调
    _stream_finished = Signal(int)   # 后台线程 → 主线程的流结束回调

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.bot = ChatBot(cfg)
        self.speaker = None          # 由外部注入（避免循环引用）
        self.bubble = None           # BubbleWidget
        self.input = None            # ChatInputWidget
        self.pet_view = None         # 提供 set_mouth 的视图（桌面宠物或舞台怪兽）
        self.stage_mode = False

        self._turn = 0               # 对话轮次（打断用）
        self._busy = False
        self._stream_done = False
        self._reply_text = ""
        self._last_user = ""
        self._from_voice = False    # 本轮是否来自语音提问（决定说完后的气泡/输入框行为）
        self._pending = []          # 等待"对应语音开始"才显示的句子文字
        self._shown_any = False     # 本轮是否已显示过回复文字（第一条用替换，其余追加）
        self._t = 0.0
        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(60)
        self._mouth_timer.timeout.connect(self._tick_mouth)
        self._mouth_timer.start()
        self._finish_watchdog = QTimer(self)
        self._finish_watchdog.setSingleShot(True)
        self._finish_watchdog.timeout.connect(self._force_finish)

        self._got_sentence.connect(self._on_sentence)
        self._stream_finished.connect(self._on_stream_finished)

    # ---------- 组装 ----------

    def attach(self, pet_view, bubble, speaker, input_widget):
        self.pet_view = pet_view
        self.bubble = bubble
        bubble.attach(pet_view)
        self.speaker = speaker
        self.input = input_widget
        input_widget.submitted.connect(self.ask)
        # 关键：语音播完（或合成失败）也要触发收尾。
        # 否则"流已结束但语音还在播"时 _finish_turn 永远不会被调用，气泡不消失、状态卡死。
        speaker.finished.connect(self._on_speak_finished)
        speaker.failed.connect(self._on_speak_failed)
        # 声音真正响起时才显示对应句子的文字（文字/嘴巴/声音三者同步）
        speaker.started.connect(self._on_speak_started)

    def set_pet_view(self, view):
        """切换口型动画对象（桌面 ↔ 舞台）"""
        self.pet_view = view

    def set_stage_mode(self, on: bool):
        self.stage_mode = on
        if on:
            self.bubble.hide_bubble()
        else:
            self._mouth_to(0.0)

    # ---------- 对外接口 ----------

    def ask(self, user_text: str, from_voice: bool = False):
        user_text = user_text.strip()
        if not user_text:
            return
        self.stop_reply()
        self._turn += 1
        turn = self._turn
        self._busy = True
        self._stream_done = False
        self._reply_text = ""
        self._last_user = user_text
        self._from_voice = from_voice
        self._pending = []
        self._shown_any = False
        self._mouth_to(0.0)
        self.state_changed.emit("thinking")
        self._show_bubble("嗯…" if from_voice else "让我想一想…")
        threading.Thread(
            target=self._run_bot, args=(turn, user_text), daemon=True
        ).start()

    def stop_reply(self):
        """打断当前回复（新提问/麦克风按下时调用）"""
        self._turn += 1
        self._busy = False
        self._stream_done = True
        self._finish_watchdog.stop()
        self._pending = []
        if self.speaker:
            self.speaker.stop()
        self._mouth_to(0.0)

    def open_input(self):
        """打开打字输入框"""
        if self.input and self.pet_view:
            self.input.open_near(self.pet_view)

    def toggle_input(self):
        """双击宠物：打字输入框开↔关切换"""
        if self.input and self.input.isVisible():
            self.input.hide()
        else:
            self.open_input()

    # ---------- 内部 ----------

    def _run_bot(self, turn, user_text):
        def on_sentence(sentence):
            if turn != self._turn:
                return
            self._got_sentence.emit(sentence)

        self.bot.reply_stream(user_text, on_sentence)
        self._stream_finished.emit(turn)

    def _on_sentence(self, sentence):
        if not self._busy:
            return
        sentence = sentence.strip()
        if not sentence:
            return
        self._reply_text += sentence + "\n"
        # 文字先排队，等这句的语音真正响起时再显示（文字/嘴巴/声音同步）
        self._pending.append(sentence)
        self.speaker.speak(sentence)

    def _on_speak_started(self):
        """某句语音开始播放：显示对应文字"""
        if not self._busy:
            return
        self._display_next()

    def _on_speak_failed(self, msg):
        """某句合成失败：文字照常显示（内容不丢），然后继续收尾判断"""
        if self._busy:
            self._display_next()
        self._on_speak_finished(msg)

    def _display_next(self):
        """把队首句子的文字显示到气泡/字幕"""
        if not self._pending:
            return
        text = self._pending.pop(0)
        if self.bubble:
            if self._shown_any:
                self.bubble.feed_text(text + "\n")
            else:
                self.bubble.set_text(text + "\n")      # 替换掉"让我想一想"
        self._shown_any = True
        self.sentence_shown.emit(self._reply_text.strip())

    def _on_stream_finished(self, turn):
        if turn != self._turn or not self._busy:
            return
        self._stream_done = True
        if self._reply_text:
            self.bot.remember(self._last_user, self._reply_text.strip())
        if not (self.speaker and self.speaker.busy):
            self._finish_turn()
        else:
            self._finish_watchdog.start(45000)   # 兜底：语音 45 秒还没播完就强制收尾

    def _on_speak_finished(self, *args):
        """一句播完（args 无参数）或合成失败（args=错误信息）时回调。

        等语音队列全部播完、且文字流已结束时才收尾；中途播完一句不算。
        """
        if self._busy and self._stream_done and not (self.speaker and self.speaker.busy):
            self._finish_turn()

    def _force_finish(self):
        """兜底：TTS 长时间无进展（卡死/静默失败）时强制收尾，气泡绝不永远卡住"""
        if self._busy and self._stream_done:
            print("警告：语音合成超时，强制结束本轮")
            if self.speaker:
                self.speaker.stop()
            while self._pending:
                self._display_next()          # 剩余文字不丢，一次性补显示
            self._finish_turn()

    def _finish_turn(self):
        if not self._busy:
            return
        self._finish_watchdog.stop()
        self._busy = False
        self.state_changed.emit("idle")
        self._mouth_to(0.0)
        if not self.stage_mode and self.bubble:
            if self._from_voice:
                # 语音提问：说完让气泡停留几秒再消失
                self.bubble.auto_hide(4000)
            else:
                # 打字提问：说完立刻关掉聊天框，输入框再次出现，继续输入下一句
                self.bubble.hide_bubble()
                self.open_input()
        self.sentence_shown.emit(self._reply_text.strip())

    def _show_bubble(self, text):
        if self.stage_mode:
            self.sentence_shown.emit(text if text else "……")
            return
        if self.bubble:
            self.bubble.set_text(text)

    def _mouth_to(self, v: float):
        if self.pet_view:
            self.pet_view.set_mouth(v)

    def _tick_mouth(self):
        self._t += 0.06
        if not self.pet_view:
            return
        # 口型严格跟随"音频正在播放"（playing），合成预取期间不动嘴
        speaking = bool(self.speaker and self.speaker.playing) and self._busy
        self.pet_view.speaking = speaking   # 同步"说话中"标志：说话时不眨眼
        if speaking:
            # 说话口型：按节奏张合
            self.pet_view.set_mouth(0.15 + 0.65 * abs(math.sin(self._t * 13)))
        elif self._busy:
            self.pet_view.set_mouth(0.05)     # 思考中微微张口（静态）

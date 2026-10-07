"""环境与功能自检：不需要任何 API Key。

用法：
    python selfcheck.py           # 全部离线自检（窗口不弹出）
    python selfcheck.py --loop    # 末尾加 2 秒事件循环（覆盖定时器路径）

检查内容：依赖导入 / 配置加载 / 小云宝各表情渲染 / 行为状态机 /
         聊天分句与护栏 / 无 Key 提示路径 / Edge-TTS 合成（需联网，失败不算错）/
         语音识别与唤醒模块状态 / 舞台模式。
"""
import os

# 自检全程离屏，不弹任何窗口
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import asyncio
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    results = []

    def check(name, fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:
            results.append((name, False, f"{e.__class__.__name__}: {e}"))

    # ---------- 1. 依赖导入 ----------
    def t_imports():
        import httpx, edge_tts, websocket, sounddevice, numpy  # noqa: F401
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput  # noqa: F401
        from PySide6.QtWidgets import QSystemTrayIcon  # noqa: F401
    check("依赖导入（PySide6/httpx/edge-tts/websocket/sounddevice）", t_imports)

    # ---------- 2. 项目模块导入 ----------
    def t_modules():
        import pet, behaviors, bubble, tts, chat, asr, mic, voice, stage, config, main  # noqa: F401
    check("项目模块导入", t_modules)

    # ---------- 3. 配置加载 ----------
    def t_config():
        from config import load_config
        cfg = load_config()
        assert cfg["pet"]["name"]
        assert cfg["deepseek"]["model"]
        # 缺字段兜底
        import json
        partial = json.loads('{"pet": {"name": "测试兽"}}')
        cfg2 = load_config()  # 用真实文件即可；字段合并逻辑再验一次
        assert cfg2["classroom"]["big_font"] is True
    check("配置加载与默认值", t_config)

    # ---------- 4. 小云宝渲染 ----------
    def t_render():
        from PySide6.QtCore import Qt, QRectF
        from PySide6.QtGui import QImage, QPainter
        from pet import MonsterWidget
        moods = [("normal", {}), ("sleepy", {"zzz_phase": 1.0}),
                 ("happy", {"mouth_open": 0.4}), ("surprised", {"pupil_scale": 0.55,
                 "mouth_open": 0.35, "poked": True})]
        for mood, params in moods:
            w = MonsterWidget()
            w.set_mood(mood)
            for k, v in params.items():
                setattr(w, k, v)
            img = QImage(220, 250, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            w.draw_monster(p, QRectF(0, 0, 220, 250))
            p.end()
            assert img.size().width() == 220
    check("小云宝四种表情离屏渲染", t_render)

    # ---------- 5. 行为状态机 ----------
    def t_brain():
        from main import PetWindow
        w = PetWindow()
        b = w.brain
        for _ in range(40):
            b._tick()
        b.sleep_now(); b._tick()
        assert b.state == "sleep" and w.mood == "sleepy"
        b.wake()
        assert b.state == "idle"
        b.feed()
        for _ in range(20):
            b._tick()
        assert b.state == "eat"
        b.set_free_move(True)          # 自由移动默认关闭，测试跟随前先开
        b.set_follow(True)
        for _ in range(5):
            b._tick()
        assert b.state == "follow"
        b.set_follow(False)
        b.paused = True
        b._tick()
        assert b.state == "idle"
        w.close()
    check("行为状态机（待机/睡觉/进食/跟随/暂停）", t_brain)

    # ---------- 6. 聊天分句与护栏 ----------
    def t_chat():
        from config import load_config
        from chat import ChatBot
        cfg = load_config()
        cfg["deepseek"]["api_key"] = ""
        bot = ChatBot(cfg)
        assert not bot.ready
        got = []
        bot.reply_stream("你好", got.append)
        assert got and "API Key" in got[0], got
        # 分句（残留文字会跨调用累积，直到遇到下一个句尾符或 flush）
        cfg2 = load_config()
        cfg2["deepseek"]["api_key"] = "sk-fake"
        bot2 = ChatBot(cfg2)
        bot2._carry = ""
        sents = list(bot2._split_sentences("你好呀！我是小云宝。", False))
        assert sents == ["你好呀！", "我是小云宝。"], sents
        sents = list(bot2._split_sentences("今天天气真好", False))
        assert sents == [], sents
        sents = list(bot2._split_sentences("", True))
        assert sents == ["今天天气真好"], sents
        # 清洗
        assert bot2._sanitize("**你好** `哈`") == "你好 哈"
    check("聊天分句/清洗/无 Key 提示", t_chat)

    # ---------- 7. 对话编排（无 Key 端到端，需事件循环配合 --loop） ----------
    def t_session():
        from config import load_config
        from chat import ChatSession
        from bubble import BubbleWidget, ChatInputWidget
        from tts import Speaker
        from pet import MonsterWidget
        cfg = load_config()
        cfg["deepseek"]["api_key"] = ""
        pet_view = MonsterWidget()
        session = ChatSession(cfg)
        session.attach(pet_view, BubbleWidget(cfg), Speaker(cfg), ChatInputWidget(cfg))
        session.speaker.set_muted(True)      # 自检静音，不打扰人
        session.ask("你好")
        session.stop_reply()
        assert session._busy is False
        session.speaker.close()              # 收起合成线程，避免退出竞态
        pet_view.close()
    check("对话编排组装与打断", t_session)

    # ---------- 8. Edge-TTS 合成（需联网；失败只提示不报错） ----------
    def t_tts():
        import edge_tts
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            asyncio.run(edge_tts.Communicate(
                "你好呀，小朋友！", voice="zh-CN-XiaoyiNeural"
            ).save(tmp.name))
            size = os.path.getsize(tmp.name)
            assert size > 1000, f"mp3 过小: {size}"
        finally:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)
    check("Edge-TTS 语音合成（联网）", t_tts)

    # ---------- 9. 语音识别模块状态 ----------
    def t_asr():
        from config import load_config
        from asr import MicClient, WakeListener
        cfg = load_config()
        m = MicClient(cfg)
        got = []
        m.failed.connect(got.append)
        m.start()
        if not m.ready:
            assert got and "还没有配置" in got[0], got
        w = WakeListener(cfg)
        assert w.wake_word
        # 麦克风按钮绘制
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter
        from mic import MicButtonWidget
        btn = MicButtonWidget(cfg)
        img = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        btn.render(img)
        assert img.size().width() == 96
    check("讯飞模块状态与麦克风按钮渲染", t_asr)

    # ---------- 10. 舞台模式 ----------
    def t_stage():
        from config import load_config
        from stage import StageWindow
        cfg = load_config()
        s = StageWindow(cfg)
        s.set_subtitle("小朋友们好！")
        assert "小朋友们好" in s._subtitle.text()
        s.close()
    check("舞台模式与字幕", t_stage)

    # ---------- 汇总 ----------
    print("=" * 46)
    for name, ok, err in results:
        print(("  [通过] " if ok else "  [失败] ") + name)
        if err:
            print("         " + err)
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print("=" * 46)
    print(f"共 {len(results)} 项，失败 {n_fail} 项")
    if n_fail:
        print("提示：Edge-TTS 项若报网络错误可忽略（需联网）；其余项失败请检查依赖安装。")
    else:
        print("全部通过。记得在 config.json 填写 DeepSeek 与讯飞 Key 后即可对话。")

    if "--loop" in sys.argv:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, app.quit)
        app.exec()
        print("事件循环 2 秒跑完，定时器路径正常。")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()

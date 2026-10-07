"""唤醒监听诊断（节能版）：连接信号观察唤醒命中和失败。

用法：python scripts/wake_probe_loop.py
8 秒倒计时后进入 60 秒窗口。静音期间不会开讯飞会话（不耗额度），
检测到说话声才开识别会话。请说 2~3 次唤醒词（如"小云宝"），每次隔几秒。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from asr import WakeListener
from config import load_config

app = QApplication(sys.argv)
cfg = load_config()
t0 = time.time()


def ts():
    return f"{time.time() - t0:6.1f}s"


wl = WakeListener(cfg)
wl.wake_detected.connect(lambda: print(f"[{ts()}] ★★★ 唤醒命中！"))
wl.failed.connect(lambda m: print(f"[{ts()}] ✗ 出错: {m}"))

print(f"8 秒后开始 60 秒监听窗口。静音期间不耗讯飞额度；说「{cfg['pet']['wake_word']}」2~3 次，每次隔几秒…")
for i in range(8, 0, -1):
    print(f"        {i}…")
QTimer.singleShot(8000, lambda: wl.set_active(True))
QTimer.singleShot(68000, app.quit)
app.exec()
print(f"[{ts()}] 结束")

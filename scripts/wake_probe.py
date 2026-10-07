"""唤醒词诊断：录一轮音，打印讯飞识别的实时中间结果与最终结果。

用法：python scripts/wake_probe.py
运行后 5 秒倒计时开始录音，请对着麦克风说一遍唤醒词（如"小云宝"），
说完安静等待；收到最终结果后打印并退出（30 秒超时）。

目的：看讯飞把唤醒词实际识别成了什么（精确匹配是否命中）。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from asr import MicClient
from config import load_config

app = QApplication(sys.argv)
cfg = load_config()
t0 = time.time()


def ts():
    return f"{time.time() - t0:6.1f}s"


client = MicClient(cfg)
print(f"[{ts()}] 讯飞 Key 就绪: {client.ready}（False=config.json 三件套没填）")
if not client.ready:
    print("Key 未配置，退出")
    sys.exit(1)

client.partial.connect(lambda t: print(f"[{ts()}] 中间结果: {t}"))
client.failed.connect(lambda m: print(f"[{ts()}] 出错: {m}"))

got_final = [False]


def on_final(text):
    got_final[0] = True
    wake = cfg["pet"]["wake_word"]
    print(f"[{ts()}] 最终结果: {text!r}")
    print(f"[{ts()}] 精确匹配 {wake!r} in 结果: {wake in text}")
    app.quit()


client.final.connect(on_final)

print(f"[{ts()}] 8 秒后开始录音，请对着麦克风清楚地说一遍「{cfg['pet']['wake_word']}」，说完保持安静…")
for i in range(8, 0, -1):
    print(f"        {i}…")
QTimer.singleShot(8000, client.start)
QTimer.singleShot(35000, lambda: (
    print(f"[{ts()}] 30 秒内未收到最终结果（轮次未结束/服务器未回）") if not got_final[0] else None,
    app.quit(),
))
app.exec()

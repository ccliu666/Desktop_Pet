"""对话风格测试：用当前提示词真实提问几个典型问题，打印回复。

用法：python scripts/chat_probe.py
用途：调人设/提示词时快速看效果（不需要启动完整程序）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.stdout.reconfigure(encoding="utf-8")

from chat import ChatBot
from config import load_config

QUESTIONS = [
    "介绍一下你自己吧",
    "给我们讲一个关于分享的小故事吧",
    "为什么天会下雨？",
    "背一首李白的诗",
]

bot = ChatBot(load_config())
if not bot.ready:
    print("DeepSeek Key 未配置")
    sys.exit(1)

for i, q in enumerate(QUESTIONS, 1):
    print(f"【问题 {i}】{q}")
    print("-" * 46)
    got = []
    bot.reply_stream(q, got.append)
    reply = "\n".join(got)
    print(reply if reply else "(无回复)")
    bot.remember(q, reply)
    print()

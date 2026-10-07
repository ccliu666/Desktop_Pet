"""生成加密 Key 文件 keys.dat（发给别人的包里用它代替明文 Key）。

用法：
    python scripts/make_keys.py                  # 读 character/config.json 的 Key → 写 character/keys.dat
    python scripts/make_keys.py 输出目录          # 读 character/config.json 的 Key → 写 输出目录/keys.dat（制作分发包用）

原理：XOR+Base64 简单混淆（防普通用户直接看到明文；懂技术的人仍能解出，
本地程序无法做到绝对保密）。程序运行时 keys.dat 优先于 config.json 的明文 Key；
收件人删掉 keys.dat 后即可在 config.json 里填自己的 Key。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from config import encrypt_keys, load_config

SRC = os.path.join(ROOT, "character", "config.json")
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "character")


def main():
    cfg = load_config(SRC)      # 注意：这里只读明文，不做 keys.dat 覆盖，避免旧文件干扰
    keys = {
        "deepseek_api_key": cfg["deepseek"]["api_key"].strip(),
        "xfyun_app_id": cfg["xfyun"]["app_id"].strip(),
        "xfyun_api_key": cfg["xfyun"]["api_key"].strip(),
        "xfyun_api_secret": cfg["xfyun"]["api_secret"].strip(),
    }
    missing = [k for k, v in keys.items() if not v]
    if missing:
        print(f"警告：以下 Key 为空，将按原样写入：{missing}")
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "keys.dat")
    with open(out, "w", encoding="utf-8") as f:
        f.write(encrypt_keys(keys))
    print(f"已生成 {out}（加密，可随成品包分发）")


if __name__ == "__main__":
    main()

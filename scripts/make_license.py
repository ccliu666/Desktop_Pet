"""生成/追加点位授权文件 license.dat。

用法：
    python scripts/make_license.py                    # 交互输入机器码，输出到当前目录
    python scripts/make_license.py 输出目录            # 交互输入，输出到指定目录
    python scripts/make_license.py 输出目录 机器码1 机器码2 ...   # 直接带码生成

机器码形如 A4BB-6D31-9F02（未授权电脑打开 exe 时弹窗里显示的就是它）。
自动合并：目标位置已有 license.dat 时，原有机器码会保留，与新输入的合并去重。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from license import decrypt_license, encrypt_license


def _norm(code):
    return code.replace(" ", "").replace("-", "").upper()


def main():
    args = sys.argv[1:]
    out_dir, new_codes = None, []
    if args:
        out_dir = args[0]
        new_codes = [a for a in args[1:] if a.strip()]
    if not new_codes:
        print("请输入机器码（形如 A4BB-6D31-9F02，多台机器用空格分隔，输完回车）：")
        new_codes = input().split()

    new_codes = [_norm(c) for c in new_codes if c.strip()]
    bad = [c for c in new_codes if len(c) != 12]
    if bad:
        print(f"格式不对的机器码：{bad}（应为 12 位十六进制，如 A4BB-6D31-9F02）")
        sys.exit(1)
    if not new_codes:
        print("未输入任何机器码，已取消。")
        sys.exit(1)

    out = os.path.join(out_dir, "license.dat") if out_dir else "license.dat"

    # 已有授权文件 → 合并保留旧机器码
    existing = []
    if os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as f:
                existing = [_norm(c) for c in decrypt_license(f.read()) if c.strip()]
        except (OSError, ValueError):
            print("警告：旧 license.dat 无法解析，将重新生成。")

    merged = list(dict.fromkeys(existing + new_codes))   # 去重且保持顺序
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(encrypt_license(merged))
    print(f"已生成 {os.path.abspath(out)}：共授权 {len(merged)} 台机器"
          f"（原有 {len(existing)} 台，本次新增 {len(merged) - len(existing)} 台）")


if __name__ == "__main__":
    main()

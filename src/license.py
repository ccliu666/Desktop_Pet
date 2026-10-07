"""按点位（机器）授权：exe 只能在与 license.dat 匹配的电脑上运行。

机器码：本机最低网卡 MAC 地址的格式化串（如 A4BB-6D31-9F02）。
授权文件 license.dat（加密）内是一组机器码；本机任一网卡 MAC 与其中任一
机器码对应，即视为已授权。

流程：
  1. 未授权电脑双击 exe → 弹窗显示本机机器码，用户拍照发给园方
  2. 园方双击「生成授权.bat」输入机器码（可多个，空格分隔）→ 生成 license.dat
  3. 把 license.dat 放进程序文件夹，重启 exe 即用

安全说明：与 keys.dat 同为 XOR+Base64 混淆，防君子不防小人——
目标是防止随意拷贝传播，挡不住专业破解（离线程序无法做到绝对控制）。
"""
import base64
import os
import re
import subprocess
import sys

_LICENSE_XOR = bytes([0x7C, 0x1B, 0xA4, 0x5E, 0xD9, 0x30, 0x86, 0xE2])   # 与 keys.dat 不同密钥

_MAC_RE = re.compile(r"^[0-9A-F]{12}$")


# ---------- 机器码 ----------

def get_macs():
    """收集本机所有已启用网卡的 MAC 地址（大写、无分隔符，12 位十六进制）"""
    macs = set()
    # getmac 列出全部物理适配器（含断线但启用的网卡）；
    # 输出是系统 OEM 编码（中文 Windows 为 GBK），必须按字节读再 mbcs 解码
    try:
        out = subprocess.run(["getmac", "/fo", "csv", "/nh"],
                             capture_output=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
        text = (out or b"").decode("mbcs", errors="ignore")
        for line in text.splitlines():
            for field in line.split(","):
                m = field.strip().strip('"').replace("-", "").replace(":", "").upper()
                if _MAC_RE.match(m):
                    macs.add(m)
    except (OSError, subprocess.SubprocessError):
        pass
    # uuid.getnode 兜底（getmac 失败时）
    try:
        import uuid
        node = uuid.getnode()
        if node < (1 << 48) and node != 0:
            macs.add(f"{node:012X}")
    except Exception:
        pass
    return macs


def machine_code():
    """本机机器码：取最低的 MAC（稳定，不受网卡顺序影响），格式 XXXX-XXXX-XXXX"""
    macs = get_macs()
    if not macs:
        return "0000-0000-0000"
    m = min(sorted(macs))
    return f"{m[:4]}-{m[4:8]}-{m[8:12]}"


def _code_to_mac(code):
    c = code.replace("-", "").replace(" ", "").upper()
    return c if _MAC_RE.match(c) else ""


# ---------- 授权文件 ----------

def encrypt_license(codes):
    """机器码列表 → license.dat 内容（加密）"""
    data = ",".join(c.replace(" ", "").upper() for c in codes if c.strip())
    raw = data.encode("utf-8")
    return base64.b64encode(
        bytes(b ^ _LICENSE_XOR[i % len(_LICENSE_XOR)] for i, b in enumerate(raw))
    ).decode("ascii")


def decrypt_license(text):
    """license.dat 内容 → 机器码列表"""
    raw = base64.b64decode(text.strip().encode("ascii"))
    data = bytes(b ^ _LICENSE_XOR[i % len(_LICENSE_XOR)] for i, b in enumerate(raw))
    return [c for c in data.decode("utf-8").split(",") if c]


def find_license():
    script = os.path.dirname(os.path.abspath(__file__))
    proot = os.path.dirname(script) if os.path.basename(script) == "src" else script
    bases = [os.getcwd(), proot, os.path.join(proot, "character")]
    if getattr(sys, "frozen", False):
        bases.insert(1, os.path.dirname(sys.executable))   # 打包后：exe 所在目录
    for base in bases:
        p = os.path.join(base, "license.dat")
        if os.path.exists(p):
            return p
    return None


def check_authorized():
    """本机任一 MAC 与授权文件中任一机器码匹配 → True"""
    p = find_license()
    if not p:
        return False
    try:
        with open(p, encoding="utf-8") as f:
            codes = decrypt_license(f.read())
    except (OSError, ValueError):
        return False
    licensed = {_code_to_mac(c) for c in codes}
    licensed.discard("")
    if not licensed:
        return False
    return bool(get_macs() & licensed)


def should_check():
    """只在打包 exe 里校验；--smoke/--selftest 诊断模式跳过"""
    return bool(getattr(sys, "frozen", False)) \
        and "--smoke" not in sys.argv and "--selftest" not in sys.argv

"""配置加载：config.json 缺失或字段不全时用默认值兜底。

配置查找顺序：CWD/config.json（exe 旁，可直接编辑）→ character/config.json（开发）。
API Key 双来源：keys.dat（简单加密，发给别人的包里用它防明文泄露）优先，
删掉 keys.dat 则直接用 config.json 里的明文 Key（方便换自己的 Key）。
加密只是"防君子不防小人"——本地程序无法对懂技术的人完全保密。
"""
import base64
import copy
import json
import os
import sys

DEFAULTS = {
    "pet": {
        "name": "小云宝",
        "wake_word": "小云宝",
        "wake_aliases": ["小元宝", "小圆宝", "小玉宝", "小雨宝", "小宇宝", "小鱼宝"],   # 同音容错（孩子发音不准/识别偏差），可自行增删
        "persona": "你叫小云宝，是余杭区未来科技城海云幼儿园的吉祥物 AI 助教，像一位亲切、专业的幼儿园老师，面对的是全班 3~6 岁的孩子。",
    },
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "xfyun": {
        "app_id": "",
        "api_key": "",
        "api_secret": "",
    },
    "tts": {
        "voice": "zh-CN-XiaoxiaoNeural",   # 晓晓（温柔成熟女声，专业助教）；备选 zh-CN-XiaoyiNeural（小艺）
        "rate": "+8%",
        "volume": 0.9,
    },
    "classroom": {
        "big_font": True,      # 气泡/字幕大字体（教室后排可读）
        "mic_button": True,    # 启动时显示麦克风按钮
        "auto_wake": False,    # 启动时自动开启唤醒词监听（上课时手动开更省额度）
        "mic_device": None,    # 指定麦克风（设备名或索引），None=系统默认
        "show_bubble": False,  # 对话气泡默认不显示（纯语音交互；右键菜单可开，状态会记住）
        "free_move": False,    # 自由移动默认关（散步/跟随；右键可开，状态会记住）
        "wake_gate_rms": 100,  # 唤醒能量阈值（安静底噪约 10~20）：喊不醒就调小（如 100），环境吵误触发就调大
    },
}

# keys.dat 混淆密钥（XOR+Base64，防普通用户直接看到明文）
_KEYS_XOR = bytes([0x3A, 0x8F, 0x51, 0xC7, 0x9E, 0x24, 0xB3, 0x6D])

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# src/config.py → 项目根；config.py → 脚本目录本身
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR) if os.path.basename(_SCRIPT_DIR) == "src" else _SCRIPT_DIR
# 打包后：exe 所在目录（开机自启/快捷方式等启动方式下 CWD 可能不是程序目录）
_EXE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None


def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _find_config():
    return _first_existing(
        os.path.join(os.getcwd(), "config.json"),
        os.path.join(_EXE_DIR, "config.json") if _EXE_DIR else "",
        os.path.join(_PROJECT_ROOT, "character", "config.json"),
    )


def _find_keys_dat():
    return _first_existing(
        os.path.join(os.getcwd(), "keys.dat"),
        os.path.join(_EXE_DIR, "keys.dat") if _EXE_DIR else "",
        os.path.join(_PROJECT_ROOT, "character", "keys.dat"),
    )


# ---------- keys.dat 加解密 ----------

def encrypt_keys(d: dict) -> str:
    """把 Key 字典（JSON）加密成 keys.dat 的内容"""
    data = json.dumps(d, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(
        bytes(b ^ _KEYS_XOR[i % len(_KEYS_XOR)] for i, b in enumerate(data))
    ).decode("ascii")


def decrypt_keys(text: str) -> dict:
    data = base64.b64decode(text.strip().encode("ascii"))
    raw = bytes(b ^ _KEYS_XOR[i % len(_KEYS_XOR)] for i, b in enumerate(data))
    return json.loads(raw.decode("utf-8"))


def _overlay_keys(cfg):
    """keys.dat（加密）优先覆盖 config.json 里的 Key"""
    p = _find_keys_dat()
    if not p:
        return
    try:
        with open(p, encoding="utf-8") as f:
            d = decrypt_keys(f.read())
        if d.get("deepseek_api_key"):
            cfg["deepseek"]["api_key"] = d["deepseek_api_key"]
        if d.get("xfyun_app_id"):
            cfg["xfyun"]["app_id"] = d["xfyun_app_id"]
        if d.get("xfyun_api_key"):
            cfg["xfyun"]["api_key"] = d["xfyun_api_key"]
        if d.get("xfyun_api_secret"):
            cfg["xfyun"]["api_secret"] = d["xfyun_api_secret"]
    except (OSError, ValueError, KeyError):
        pass    # keys.dat 损坏就当没有，回退 config.json 明文


def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    p = path or _find_config()
    if p:
        try:
            with open(p, encoding="utf-8") as f:
                _merge(cfg, json.load(f))
        except (OSError, ValueError):
            pass
    _overlay_keys(cfg)
    return cfg

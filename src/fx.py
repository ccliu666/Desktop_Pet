"""操作音效：点击 / 发送 / 唤醒等短提示音。

wav 文件由 scripts/gen_fx.py 生成到 fx/ 目录。Windows 上走 winsound（waveOut，
系统通道最可靠，部分白板/电脑的 Qt 音频后端无声）；其他平台走 QSoundEffect。
缺文件时静默跳过，不影响主流程。静音开关与 TTS 共用右键菜单的"静音"项。
"""
import os
import sys

try:
    import winsound                # 仅 Windows
except ImportError:
    winsound = None

# 音效目录查找：打包目录(_MEIPASS) → 脚本目录 → 项目 character/（开发）
_script = os.path.dirname(os.path.abspath(__file__))
_proot = os.path.dirname(_script) if os.path.basename(_script) == "src" else _script
FX_DIR = ""
for _base in (getattr(sys, "_MEIPASS", ""), _script, os.path.join(_proot, "character")):
    if _base and os.path.isdir(os.path.join(_base, "fx")):
        FX_DIR = os.path.join(_base, "fx")
        break
if not FX_DIR:
    FX_DIR = os.path.join(_script, "fx")


class SoundFx:
    """轻量音效播放器。"""

    def __init__(self):
        self.muted = False
        self._paths = {}
        for name in ("click", "send", "wake"):
            path = os.path.join(FX_DIR, name + ".wav")
            if os.path.exists(path):
                self._paths[name] = path
        self._qt_fx = {}            # 非 Windows 平台：QSoundEffect 缓存

    def play(self, name: str):
        if self.muted or name not in self._paths:
            return
        if winsound is not None:
            winsound.PlaySound(self._paths[name],
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            if name not in self._qt_fx:
                from PySide6.QtCore import QUrl
                from PySide6.QtMultimedia import QSoundEffect
                fx = QSoundEffect()
                fx.setSource(QUrl.fromLocalFile(self._paths[name]))
                fx.setVolume(0.6)
                self._qt_fx[name] = fx
            self._qt_fx[name].play()

    def set_muted(self, muted: bool):
        self.muted = muted

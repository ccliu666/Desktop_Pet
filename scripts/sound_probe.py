"""声音分层测试：依次用三种不同通道播放声音，帮助定位"没声音"在哪一层。

用法：python scripts/sound_probe.py
听的时候数一数自己听到了几声，对照控制台输出告诉开发者。

1) winsound 系统蜂鸣   —— Windows waveOut，与 Qt 无关（验证系统扬声器）
2) QSoundEffect 音效  —— Qt 音频输出 + wav（验证 Qt 发声通道）
3) QMediaPlayer TTS   —— Qt 音频输出 + mp3 解码（验证完整语音链路）
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
FX = os.path.join(ROOT, "character", "fx")

print("【1】系统蜂鸣（winsound，与 Qt 无关）—— 应该听到'滴'一声")
import winsound
winsound.Beep(1200, 400)
winsound.Beep(900, 400)
winsound.Beep(1200, 400)
winsound.Beep(900, 400)
winsound.Beep(1200, 400)
winsound.Beep(900, 400)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput

app = QApplication(sys.argv)

print("【2】Qt 音效（QSoundEffect + wav）—— 应该听到'嗒'一声")
click = QSoundEffect()
click.setSource(QUrl.fromLocalFile(os.path.join(FX, "click.wav")))
click.setVolume(1.0)
click.play()

print("【3】Qt 语音（QMediaPlayer + mp3）—— 应该听到一句人声")
player = QMediaPlayer()
audio = QAudioOutput()
audio.setVolume(1.0)
player.setAudioOutput(audio)
player.mediaStatusChanged.connect(
    lambda s: print("  mediaStatus:", s) if s == QMediaPlayer.MediaStatus.EndOfMedia else None)
player.errorOccurred.connect(lambda e, m: print("  播放错误:", e, m))
player.setSource(QUrl.fromLocalFile(os.path.join(FX, "wake.wav")))
player.play()

QTimer.singleShot(4000, app.quit)
app.exec()
print("测试结束。请回忆：1、2、3 各听到了几声？")

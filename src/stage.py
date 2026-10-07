"""舞台模式：全屏大云宝 + 底部超大字幕，讲故事/上课时用。

按 Esc 或点右上角按钮退出。麦克风按钮（独立置顶窗口）浮在舞台上方可继续用。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from pet import MonsterWidget

MONSTER_W, MONSTER_H = 520, 600


class StageWindow(QWidget):
    closed = Signal()

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.monster = MonsterWidget(self)
        self.monster.setFixedSize(MONSTER_W, MONSTER_H)

        self._subtitle = QLabel(self)
        self._subtitle.setWordWrap(True)
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setFont(QFont("Microsoft YaHei", 40, QFont.Weight.Bold))
        self._subtitle.setStyleSheet(
            "QLabel { background: rgba(0,0,0,60); color: white;"
            " border-radius: 24px; padding: 18px 30px; }"
        )

        self._btn_close = QPushButton("✕ 退出舞台", self)
        self._btn_close.setFont(QFont("Microsoft YaHei", 16))
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,200); color: #555;"
            " border: none; border-radius: 14px; padding: 10px 18px; }"
            "QPushButton:hover { background: rgba(255,255,255,240); }"
        )
        self._btn_close.clicked.connect(self.close)

    # ---------- 对外接口 ----------

    def open_near(self, owner):
        """在宠物所在屏幕上全屏打开"""
        screen = QApplication.screenAt(owner.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.showFullScreen()

    def set_subtitle(self, text: str):
        self._subtitle.setText(text or "")
        self._subtitle.adjustSize()
        self._relayout()

    # ---------- 内部 ----------

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self):
        w, h = self.width(), self.height()
        # 怪兽：底部居中
        mx = w // 2 - MONSTER_W // 2
        my = h - 130 - MONSTER_H
        self.monster.setGeometry(mx, max(0, my), MONSTER_W, MONSTER_H)
        # 字幕：怪兽上方居中
        sub_w = min(int(w * 0.8), 1000)
        self._subtitle.setMaximumWidth(sub_w)
        sh = self._subtitle.sizeHint().height()
        self._subtitle.setGeometry(
            w // 2 - sub_w // 2,
            max(20, self.monster.y() - sh - 40),
            sub_w, sh,
        )
        # 退出按钮：右上角
        self._btn_close.adjustSize()
        self._btn_close.move(w - self._btn_close.width() - 24, 24)

    def paintEvent(self, e):
        p = QPainter(self)
        # 天空渐变
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor("#BFE3FF"))
        grad.setColorAt(0.75, QColor("#F0FAFF"))
        grad.setColorAt(1.0, QColor("#F7FBF2"))
        p.fillRect(self.rect(), grad)
        # 草地
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#CDEBC5"))
        p.drawRect(0, self.height() - 90, self.width(), 90)
        # 标题
        p.setPen(QColor(255, 255, 255, 150))
        font = QFont("Microsoft YaHei", 24, QFont.Weight.Bold)
        p.setFont(font)
        name = self._cfg["pet"]["name"]
        p.drawText(self.rect().adjusted(0, 30, -24, 0),
                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                   f"{name}课堂")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)

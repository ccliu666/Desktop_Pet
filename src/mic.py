"""麦克风大按钮：教室白板上孩子一按就说话。

状态：idle（蓝）/ listening（红 + 波纹扩散）/ speaking（灰）。
可拖拽摆放，位置记忆在 pet_pos.json。
"""
from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QPainter
from PySide6.QtWidgets import QWidget

SIZE = 96


class MicButtonWidget(QWidget):
    clicked = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(SIZE, SIZE)
        self._state = "idle"          # idle / listening / speaking
        self._ripple_t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._down = False
        self._dragging = False
        self._press_global = QPoint()
        self._press_win = QPoint()

    # ---------- 对外接口 ----------

    def set_state(self, state: str):
        self._state = state
        self.update()

    # ---------- 拖拽 / 点击 ----------

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self._dragging = False
            self._press_global = e.globalPosition().toPoint()
            self._press_win = self.pos()

    def mouseMoveEvent(self, e):
        if not self._down:
            return
        delta = e.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() > 6:
            self._dragging = True
        if self._dragging:
            self.move(self._press_win + delta)

    def mouseReleaseEvent(self, e):
        if not self._down:
            return
        self._down = False
        if not self._dragging:
            self.clicked.emit()

    # ---------- 绘制 ----------

    def _tick(self):
        if self._state == "listening":
            self._ripple_t += 0.05
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.width() / 2
        r = c - 6

        if self._state == "listening":
            # 扩散波纹
            for i in range(3):
                frac = (self._ripple_t + i / 3) % 1.0
                ring_r = r - 2 + frac * 26
                alpha = int((1 - frac) * 110)
                p.setPen(QPen(QColor(233, 79, 79, alpha), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPoint(c, c), ring_r, ring_r)
            base, glyph = QColor("#FFE9E9"), QColor("#E94F4F")
        elif self._state == "speaking":
            base, glyph = QColor(255, 255, 255, 235), QColor("#9AA0A6")
        else:
            base, glyph = QColor(255, 255, 255, 240), QColor("#4A90D9")

        # 圆底
        p.setPen(QPen(QColor(0, 0, 0, 40), 2))
        p.setBrush(QBrush(base))
        p.drawEllipse(QPoint(c, c), r, r)

        # 麦克风图标：胶囊 + 下半弧 + 底座
        p.setPen(Qt.PenStyle.NoPen)
        # 弧：先画整圆再遮掉上半
        p.setBrush(QBrush(glyph))
        p.drawEllipse(QPoint(c, c + 16), 17, 17)
        p.setBrush(QBrush(base))
        p.drawRect(int(c - 20), int(c - 8), 40, 24)
        # 胶囊
        p.setBrush(QBrush(glyph))
        p.drawRoundedRect(int(c - 10), int(c - 24), 20, 32, 9, 9)
        # 底座
        p.drawRoundedRect(int(c - 12), int(c + 30), 24, 5, 2, 2)

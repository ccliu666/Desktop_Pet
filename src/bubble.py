"""对话气泡与打字聊天输入框。

BubbleWidget   跟随宠物的圆角气泡，支持打字机效果与瞬时替换（语音识别中间结果）
ChatInputWidget 打字聊天输入框（双击宠物或菜单打开）
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QLabel, QLineEdit, QPushButton,
                               QHBoxLayout, QVBoxLayout, QFrame)

MARGIN = 10


class BubbleWidget(QWidget):
    """跟随宠物的对话气泡。"""

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self.enabled = bool(cfg["classroom"].get("show_bubble", True))  # 气泡总开关（main 会用记忆状态覆盖）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(460)
        size = 28 if cfg["classroom"]["big_font"] else 18
        self._label.setFont(QFont("Microsoft YaHei", size))
        self._label.setStyleSheet(
            "QLabel { background: rgba(255,255,255,245); border-radius: 16px;"
            " padding: 12px 18px; color: #333333; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        lay.addWidget(self._label)

        self._owner = None
        self._buffer = ""      # 待打字机输出的文字
        self._shown = ""       # 已显示的文字
        self._type_timer = QTimer(self)
        self._type_timer.setInterval(35)
        self._type_timer.timeout.connect(self._drain)
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(100)
        self._follow_timer.timeout.connect(self._follow_owner)
        self._follow_timer.start()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_bubble)

    # ---------- 对外接口 ----------

    def attach(self, owner):
        """跟随 owner（宠物窗口）移动"""
        self._owner = owner

    def set_enabled(self, on: bool):
        """气泡总开关：关闭时所有文字都不显示（纯语音交互），打开后恢复"""
        self.enabled = bool(on)
        if not self.enabled:
            self.hide_bubble()

    def feed_text(self, text: str):
        """追加文字，打字机逐字显示"""
        if not self.enabled:
            return
        self._buffer += text
        if not self.isVisible():
            self._show_and_locate()
        if not self._type_timer.isActive():
            self._type_timer.start()
        self._hide_timer.stop()

    def set_text(self, text: str):
        """瞬时替换显示（语音识别中间结果、提示语）"""
        if not self.enabled:
            return
        self._buffer = ""
        self._shown = text
        self._type_timer.stop()
        self._label.setText(text)
        if not self.isVisible():
            self._show_and_locate()
        else:
            self._relayout()

    def hide_bubble(self):
        self._type_timer.stop()
        self._buffer = ""
        self._shown = ""
        self._label.setText("")
        self.hide()

    def auto_hide(self, ms: int):
        self._hide_timer.start(ms)

    def show_alert(self, text: str, ms: int = 10000):
        """强制显示一条提示（气泡总开关关闭时也可见）：错误必须让老师看到"""
        self.enabled = True
        self.set_text(text)
        self.auto_hide(ms)

    # ---------- 内部 ----------

    def _drain(self):
        if not self._buffer:
            self._type_timer.stop()
            return
        take = 2
        self._shown += self._buffer[:take]
        self._buffer = self._buffer[take:]
        self._label.setText(self._shown)
        self._relayout()

    def _relayout(self):
        self._label.adjustSize()
        self.resize(self._label.width() + MARGIN * 2,
                    self._label.height() + MARGIN * 2)
        self._follow_owner()

    def _show_and_locate(self):
        self.show()
        self._relayout()

    def _follow_owner(self):
        if not self.isVisible() or self._owner is None:
            return
        if not self._owner.isVisible():
            self.hide_bubble()
            return
        r = self._owner.frameGeometry()
        x = r.center().x() - self.width() // 2
        y = r.top() - self.height() - 6
        self.move(max(0, x), max(0, y))


class ChatInputWidget(QWidget):
    """打字聊天输入框：回车或点发送提交，Esc 收起。"""

    submitted = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(400, 64)

        frame = QFrame(self)
        frame.setStyleSheet(
            "QFrame { background: rgba(255,255,255,242); border-radius: 16px; }"
        )
        frame.setGeometry(6, 6, 388, 52)

        self._edit = QLineEdit(frame)
        self._edit.setFont(QFont("Microsoft YaHei", 16))
        self._edit.setPlaceholderText("和小云宝说点什么…")
        self._edit.setStyleSheet(
            "QLineEdit { border: none; background: transparent; padding: 6px; color: #333; }"
        )
        self._edit.returnPressed.connect(self._submit)

        btn = QPushButton("发送", frame)
        btn.setFont(QFont("Microsoft YaHei", 14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background: #54A96B; color: white; border: none;"
            " border-radius: 12px; padding: 6px 14px; }"
            "QPushButton:hover { background: #4a9a60; }"
        )
        btn.clicked.connect(self._submit)

        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.addWidget(self._edit, 1)
        lay.addWidget(btn)

        QShortcut(QKeySequence("Esc"), self, activated=self.hide)

    def open_near(self, owner):
        """在 owner 上方居中弹出并聚焦"""
        if owner is None:
            return
        r = owner.frameGeometry()
        x = r.center().x() - self.width() // 2
        y = r.top() - self.height() - 10
        screen = self.screen() or owner.screen()
        if screen:
            a = screen.availableGeometry()
            x = max(a.left(), min(x, a.right() - self.width()))
            y = max(a.top(), y)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()

    def _submit(self):
        text = self._edit.text().strip()
        if not text:
            return
        self._edit.clear()
        self.hide()
        self.submitted.emit(text)

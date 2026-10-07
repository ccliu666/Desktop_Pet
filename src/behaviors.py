"""行为状态机：待机 / 散步 / 睡觉 / 进食 / 跟随鼠标。

Brain 每 50ms tick 一次，按当前状态驱动窗口移动与小云宝表情参数。
"""
import math
import random

from PySide6.QtCore import QObject, QTimer, Qt, QRectF, QVariantAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QColor, QPen, QBrush, QPainter
from PySide6.QtWidgets import QApplication, QWidget

TICK = 0.05          # 状态机步长（秒）


class FoodWidget(QWidget):
    """掉落的小苹果：从屏幕上方落下，落地弹跳，被吃时缩小消失。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(40, 50)
        self._scale = 1.0
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._fade_out)
        self._timeout.start(60000)      # 60 秒没被吃就消失

    def fall_to(self, ground_y: int):
        """从当前位置落到底部（OutBounce 弹跳落地）"""
        start = self.y()
        anim = QVariantAnimation(self)
        anim.setDuration(1400)
        anim.setStartValue(float(start))
        anim.setEndValue(float(ground_y))
        anim.setEasingCurve(QEasingCurve.Type.OutBounce)
        anim.valueChanged.connect(lambda v: self.move(self.x(), round(v)))
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def set_scale(self, s: float):
        self._scale = max(0.0, s)
        self.update()

    def _fade_out(self):
        anim = QVariantAnimation(self)
        anim.setDuration(800)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.valueChanged.connect(self.setWindowOpacity)
        anim.finished.connect(self.deleteLater)
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(self._scale, self._scale)
        p.translate(-self.width() / 2, -self.height() / 2)
        # 果柄
        p.setPen(QPen(QColor("#8A6B4A"), 3))
        p.drawLine(20, 14, 20, 5)
        # 叶子
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#6FBF73")))
        p.drawEllipse(QRectF(22, 2, 12, 8))
        # 果身
        p.setPen(QPen(QColor("#D94F4F"), 2))
        p.setBrush(QBrush(QColor("#FF6B6B")))
        p.drawEllipse(QRectF(4, 14, 32, 32))
        # 高光
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 150)))
        p.drawEllipse(QRectF(10, 19, 8, 6))


class Brain(QObject):
    """宠物行为状态机，驱动 PetWindow（本身是 MonsterWidget）。"""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.state = "idle"
        self.move_enabled = False   # 自由移动开关：默认关（上课时不乱跑；右键可开）
        self.paused = False       # 舞台模式下挂起全部行为
        self._timer = QTimer(self)
        self._timer.setInterval(int(TICK * 1000))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._t = 0.0             # 当前状态已持续秒数
        self._idle_t = 0.0        # 累计无互动秒数
        self._next_walk = random.uniform(5, 10)
        self._next_yawn = random.uniform(10, 22)
        self._walk_dir = 1
        self._walk_left = 0.0
        self._target = None       # 走向的目标点（屏幕全局坐标）
        self._follow_hold = False # 持续跟随鼠标模式
        self._food = None         # FoodWidget
        self._eating = False      # 进食阶段：走路 → 吃
        self._eat_t = 0.0
        self._zzz_t = 0.0

    # ================= 对外接口 =================

    def say_hi(self):
        self._reset_idle()
        self.win.poke()

    def on_clicked(self, global_pos: QPoint):
        self._reset_idle()
        if self.state == "sleep":
            self.wake()
            return
        if self.state == "eat":
            return
        self.win.poke()
        # 点一下 → 跑向鼠标位置（一次性跟随）；自由移动关闭时只戳不动
        if not self.move_enabled:
            return
        center = self.win.frameGeometry().center()
        if (center - global_pos).manhattanLength() > 60:
            self._target = QPoint(global_pos)
            self._set_state("follow")

    def on_drag_start(self):
        self._reset_idle()
        if self.state == "sleep":
            self.wake()
        self._set_state("idle")   # 拖拽期间暂停一切行为
        self.win.set_mood("surprised")
        self.win._animate("mouth_open", 0.3, 120)

    def on_dropped(self):
        self.win.drop_bounce()
        self.win.set_mood("normal")
        self.win._animate("mouth_open", 0.0, 200)
        self._set_state("idle")

    def feed(self):
        self._reset_idle()
        if self.state == "sleep":
            self.wake()
        a = self._area()
        self._food = FoodWidget()
        fx = self.win.x() + self.win.width() // 2 - 20
        fx = max(a.left() + 10, min(fx, a.right() - 60))
        self._food.move(fx, a.top() - 60)
        self._food.destroyed.connect(self._on_food_gone)
        self._food.show()
        self._food.fall_to(a.bottom() - self._food.height() - 2)
        self._target = QPoint(fx + 20, a.bottom() - self._food.height() // 2)
        self._eating = False
        self._eat_t = 0.0
        self._set_state("eat")

    def sleep_now(self):
        if self.state == "sleep":
            return
        self._start_sleep()

    def wake(self):
        if self.state != "sleep":
            return
        self._set_state("idle")
        self._reset_idle()
        self.win.set_mood("normal")
        self.win._animate("eye_open", 1.0, 300)
        self.win._animate("mouth_open", 0.0, 300)
        self.win.drop_bounce()    # 醒来伸个懒腰的弹跳

    def set_free_move(self, on: bool):
        """自由移动开关：关闭时取消跟随并停下散步（拖拽与喂食不受影响）"""
        self.move_enabled = bool(on)
        if not self.move_enabled:
            self._follow_hold = False
            if self.state == "follow":
                self._set_state("idle")

    def set_follow(self, on: bool):
        if on and not self.move_enabled:
            return                      # 自由移动关闭时不允许开启跟随
        self._follow_hold = on
        if on:
            self._reset_idle()
            if self.state == "sleep":
                self.wake()
            self._set_state("follow")
        elif self.state == "follow":
            self._set_state("idle")

    def build_menu(self, menu, for_tray=False):
        """往 QMenu 里填入行为菜单项"""
        menu.addAction("打个招呼", self.say_hi)
        menu.addAction("喂食", self.feed)
        menu.addAction("睡觉", self.sleep_now)
        act_move = menu.addAction("自由移动")
        act_move.setCheckable(True)
        act_move.setChecked(self.move_enabled)
        act_move.toggled.connect(self.set_free_move)
        act = menu.addAction("跟着鼠标走")
        act.setCheckable(True)
        act.setChecked(self._follow_hold)
        act.toggled.connect(self.set_follow)

    # ================= 内部 =================

    def _speed(self):
        return 2.6 * self.win.width() / 220.0

    def _area(self):
        scr = QApplication.screenAt(self.win.frameGeometry().center())
        if scr is None:
            scr = QApplication.primaryScreen()
        return scr.availableGeometry()

    def _clamp(self, x, y):
        a = self._area()
        x = max(a.left(), min(x, a.right() - self.win.width() + 1))
        y = max(a.top(), min(y, a.bottom() - self.win.height() + 1))
        return round(x), round(y)

    def _reset_idle(self):
        self._idle_t = 0.0
        self._next_walk = random.uniform(5, 10)
        self._next_yawn = random.uniform(10, 22)

    def _set_state(self, s):
        self.state = s
        self._t = 0.0
        self.win.walking = (s == "walk")

    def _on_food_gone(self):
        self._food = None

    def _tick(self):
        if self.paused:
            return
        self._t += TICK
        if self.state == "idle":
            self._tick_idle()
        elif self.state == "walk":
            self._tick_walk()
        elif self.state == "sleep":
            self._tick_sleep()
        elif self.state == "eat":
            self._tick_eat()
        elif self.state == "follow":
            self._tick_follow()

    # ---------- 待机 ----------

    def _tick_idle(self):
        if self.win.speaking:
            # 说话期间不积累"无互动"时间：不打哈欠、不散步（也不自动入睡——已取消）
            self._idle_t = 0.0
            return
        self._idle_t += TICK
        if self._idle_t >= self._next_yawn:
            self._next_yawn = self._idle_t + random.uniform(12, 25)
            self._yawn()
        if self._idle_t >= self._next_walk and self.move_enabled:
            self._start_walk()          # 自由移动关闭时不散步

    def _yawn(self):
        self.win._animate("mouth_open", 0.9, 500, QEasingCurve.Type.OutQuad)
        self.win._animate("eye_open", 0.25, 500)
        QTimer.singleShot(900, lambda: self.win._animate("mouth_open", 0.0, 400))
        QTimer.singleShot(900, lambda: self.win._animate("eye_open", 1.0, 400))

    # ---------- 散步 ----------

    def _start_walk(self):
        self._walk_dir = random.choice((-1, 1))
        self._walk_left = random.uniform(3, 8)
        self.win.facing = self._walk_dir
        self._set_state("walk")

    def _tick_walk(self):
        if self.win.speaking:
            # 开始说话了就停下散步（边说话边走路很奇怪）
            self.win.bob = 0.0
            self._set_state("idle")
            return
        if self._t >= self._walk_left:
            self.win.bob = 0.0
            self._next_walk = self._idle_t + random.uniform(5, 10)
            self._set_state("idle")
            return
        a = self._area()
        x = self.win.x() + self._walk_dir * self._speed()
        if x <= a.left() or x + self.win.width() - 1 >= a.right():
            self._walk_dir = -self._walk_dir     # 到屏幕边缘掉头
            self.win.facing = self._walk_dir
        x, y = self._clamp(x, self.win.y())
        self.win.move(x, y)
        phase = self._t * 12
        self.win.bob = -abs(math.sin(phase)) * 5 * self.win.height() / 250.0
        self.win.squash = 1.0 + 0.04 * math.sin(phase)

    # ---------- 睡觉 ----------

    def _start_sleep(self):
        self._set_state("sleep")
        self.win.set_mood("sleepy")
        self.win._animate("eye_open", 0.05, 800)
        self.win._animate("mouth_open", 0.12, 800)
        self.win._animate("squash", 0.92, 800)
        self._zzz_t = 0.0

    def _tick_sleep(self):
        self._zzz_t += TICK
        self.win.zzz_phase = self._zzz_t
        if "squash" not in self.win._active:
            # 睡梦中的深慢呼吸
            self.win.squash = 0.92 + 0.03 * math.sin(self._zzz_t * 1.2)
        self.win.update()

    # ---------- 进食 ----------

    def _tick_eat(self):
        if self._food is None:
            self._set_state("idle")
            return
        center = self.win.frameGeometry().center()
        goal = self._food.frameGeometry().center()
        dx, dy = goal.x() - center.x(), goal.y() - center.y()
        dist = math.hypot(dx, dy)
        self.win.facing = 1 if dx >= 0 else -1
        phase = self._t * 12
        self.win.bob = -abs(math.sin(phase)) * 5 * self.win.height() / 250.0
        if not self._eating:
            # 走向食物
            speed = self._speed() * 1.2
            if dist <= 50:
                self._eating = True
                self._eat_t = 0.0
                self.win.set_mood("happy")
            else:
                nx = center.x() + dx / dist * speed
                ny = center.y() + dy / dist * speed
                self.win.move(*self._clamp(nx - self.win.width() / 2,
                                           ny - self.win.height() / 2))
        else:
            # 吧唧吧唧吃
            self._eat_t += TICK
            self.win.mouth_open = 0.15 + 0.75 * abs(math.sin(self._eat_t * 6))
            self._food.set_scale(max(0.15, 1.0 - self._eat_t / 1.6))
            if self._eat_t >= 1.7:
                food = self._food
                self._food = None
                food._fade_out()
                self.win.set_mood("normal")
                self.win._animate("mouth_open", 0.0, 300)
                self._set_state("idle")

    # ---------- 跟随鼠标 ----------

    def _tick_follow(self):
        from PySide6.QtGui import QCursor
        if self._target is None and not self._follow_hold:
            self._set_state("idle")
            return
        goal = QPoint(QCursor.pos() if self._follow_hold else self._target)
        center = self.win.frameGeometry().center()
        dx, dy = goal.x() - center.x(), goal.y() - center.y()
        dist = math.hypot(dx, dy)
        self.win.facing = 1 if dx >= 0 else -1
        phase = self._t * 12
        self.win.bob = -abs(math.sin(phase)) * 5 * self.win.height() / 250.0
        if not self._follow_hold and dist < 60:
            self._set_state("idle")           # 一次性跟随到达
            return
        if self._follow_hold and dist < 60:
            return                            # 持续跟随：靠近了就守着
        speed = self._speed() * 1.4
        nx = center.x() + dx / dist * speed
        ny = center.y() + dy / dist * speed
        self.win.move(*self._clamp(nx - self.win.width() / 2,
                                   ny - self.win.height() / 2))

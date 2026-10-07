"""小云宝的绘制与表情动画。

纯 QPainter 矢量绘制，无图片素材：一朵圆滚滚的小白云（海云幼儿园吉祥物）。
所有表情参数都是 0~1 的连续量：
    eye_open    1 全睁 / 0 闭眼（眨眼动画）
    mouth_open  0 微笑闭嘴 / 1 张大嘴（打哈欠、进食、说话口型共用）
    squash      身体压扁/拉伸系数（呼吸、被戳、落地弹跳）
    bob         走路上下颠簸（后续步骤使用）
    facing      朝向：1 右 / -1 左
后续步骤的口型同步只需连续驱动 mouth_open 即可。
"""
import math
import random

from PySide6.QtCore import Qt, QRectF, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QFont, QImage
from PySide6.QtWidgets import QWidget

# ---------- 配色 ----------
C_BODY    = QColor("#FFFFFF")            # 云朵白
C_BODY_DK = QColor("#A9CBE8")            # 云朵描边（天蓝）
C_PUPIL   = QColor("#3B4A5A")            # 眼睛
C_BLUSH   = QColor(255, 177, 194, 190)   # 腮红（半透明）
C_MOUTH   = QColor("#C97B6E")            # 微笑线/口腔
C_TONGUE  = QColor("#FF8FA3")            # 舌头
C_SHADOW  = QColor(0, 0, 0, 36)          # 地面软影

LOGICAL_W, LOGICAL_H = 200, 230          # 绘制用逻辑画布尺寸


class MonsterWidget(QWidget):
    """小云宝本体：负责绘制与表情动画，不关心窗口位置。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # --- 表情参数 ---
        self.eye_open = 1.0
        self.mouth_open = 0.0
        self.pupil_scale = 1.0
        self.squash = 1.0
        self.bob = 0.0
        self.facing = 1
        self.mood = "normal"        # normal / surprised / happy / sleepy
        self.poked = False          # 被戳中（头顶冒"!"）
        self.zzz_phase = 0.0        # 睡觉时 Zzz 动画相位
        self.walking = False        # 走路中（呼吸动画让位给步态）
        self.speaking = False       # 说话中（由 ChatSession 驱动；说话时不眨眼）
        self.avatar = None          # 图片形象 {"idle": QImage, "blink": QImage}，None=矢量小云宝

        self._active = set()        # 正在被动画驱动的参数名（呼吸避免与其打架）
        self._breath_phase = 0.0

        # 呼吸：20fps 微调 squash
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(50)
        self._breath_timer.timeout.connect(self._tick_breath)
        self._breath_timer.start()

        # 被戳表情持续时间
        self._poke_timer = QTimer(self)
        self._poke_timer.setSingleShot(True)
        self._poke_timer.timeout.connect(self._end_poke)

        self._schedule_blink()      # 随机眨眼调度

    # ================= 对外接口 =================

    def set_mood(self, mood: str):
        self.mood = mood
        self.update()

    def set_avatar(self, avatar):
        """切换形象：传 {"idle": QImage, "blink": QImage} 用图片人物，传 None 回矢量小云宝"""
        self.avatar = avatar
        self.update()

    def poke(self):
        """被戳一下：惊讶脸 + 头顶冒出感叹号气泡"""
        self.poked = True
        self.mood = "surprised"
        self._animate("pupil_scale", 0.55, 120)
        self._animate("mouth_open", 0.35, 120)
        self._animate("squash", 0.92, 120)
        self._poke_timer.start(650)

    def drop_bounce(self):
        """落地弹一下：先拉伸、再压回、最后回弹"""
        self._animate("squash", 1.12, 120, QEasingCurve.Type.OutQuad)
        QTimer.singleShot(130, lambda: self._animate("squash", 0.94, 120, QEasingCurve.Type.InQuad))
        QTimer.singleShot(260, lambda: self._animate("squash", 1.0, 160, QEasingCurve.Type.OutBack))

    def set_mouth(self, v: float):
        """直接驱动口型（说话同步用）"""
        self.mouth_open = max(0.0, min(1.0, v))
        self.update()

    def set_eye(self, v: float):
        self.eye_open = max(0.0, min(1.0, v))
        self.update()

    # ================= 动画辅助 =================

    def _animate(self, attr: str, target: float, ms: int,
                 easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic):
        """把某个表情参数平滑过渡到目标值"""
        start = getattr(self, attr)
        self._active.add(attr)
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setStartValue(float(start))
        anim.setEndValue(float(target))
        anim.setEasingCurve(easing)

        def on_val(v, a=attr):
            setattr(self, a, float(v))
            self.update()

        def on_done(a=attr):
            self._active.discard(a)

        anim.valueChanged.connect(on_val)
        anim.finished.connect(on_done)
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _schedule_blink(self):
        delay = random.randint(2000, 6000)
        QTimer.singleShot(delay, self._do_blink)

    def _do_blink(self):
        if self.speaking or self.mood == "sleepy":
            # 说话/睡觉时不眨眼（嘴型/闭眼帧已占画面，眨眼会让形象跳变），顺延到下次
            self._schedule_blink()
            return
        # 眨眼总时长（闭眼+睁眼）；两次眨眼之间的"微笑"间隔由 _schedule_blink 控制，不变
        anim = QVariantAnimation(self)
        anim.setDuration(260)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.5, 0.05)
        anim.setEndValue(1.0)
        anim.valueChanged.connect(self.set_eye)
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
        self._schedule_blink()

    def _tick_breath(self):
        if "squash" in self._active or self.walking:
            return
        self._breath_phase += 0.06
        if self.mood == "normal":
            self.squash = 1.0 + 0.015 * math.sin(self._breath_phase)
            self.update()

    def _end_poke(self):
        self.poked = False
        self.mood = "normal"
        self._animate("pupil_scale", 1.0, 200)
        self._animate("mouth_open", 0.0, 200)
        self._animate("squash", 1.0, 260)

    # ================= 绘制 =================

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        self.draw_monster(p, QRectF(self.rect()))

    def draw_monster(self, p: QPainter, rect: QRectF):
        """把 200×230 逻辑画布上的小云宝画到任意矩形（窗口与离屏截图共用）"""
        p.save()
        s = min(rect.width() / LOGICAL_W, rect.height() / LOGICAL_H)
        p.translate(rect.center())
        p.scale(s, s)
        p.translate(-LOGICAL_W / 2, -LOGICAL_H / 2)
        self._paint_body(p)
        p.restore()

    def _paint_body(self, p: QPainter):
        # 地面软影（云朵漂浮，影子比身体略宽）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(C_SHADOW))
        p.drawEllipse(QRectF(62, 210, 76, 10))

        if self.avatar:
            self._paint_avatar_sprite(p)
        else:
            # 云朵整体：以底边中点(100, 210)为轴做压扁/拉伸 + 颠簸 + 朝向翻转
            p.save()
            p.translate(100, 210)
            p.translate(0, self.bob)
            p.scale(2.0 - self.squash, self.squash)
            p.scale(self.facing, 1)
            p.translate(-100, -210)

            self._paint_cloud(p)
            self._paint_eyes(p)
            self._paint_blush(p)
            self._paint_mouth(p)
            p.restore()

        # 头顶气泡 / Zzz（不随身体翻转/挤压）
        if self.poked:
            self._paint_poke_bubble(p)
        if self.mood == "sleepy":
            self._paint_zzz(p)

    def _paint_avatar_sprite(self, p: QPainter):
        """图片形象三帧切换，沿用与矢量形象相同的压扁/颠簸/朝向变换：

        - 说话时（mouth_open ≥ 0.45）：微笑 ↔ 说话 互换，模拟嘴巴开闭
          （口型由 ChatSession 按语音节奏驱动，张合自然交替）
        - 不说话时：微笑 ↔ 眨眼 互换（随机眨眼动画与睡觉闭眼共用 blink 帧）
        """
        img = None
        if self.avatar:
            if self.mouth_open >= 0.45 and self.avatar.get("talk") is not None:
                img = self.avatar["talk"]
            elif self.avatar.get("blink") is not None and self.eye_open < 0.5:
                img = self.avatar["blink"]
            else:
                img = self.avatar.get("idle")
        if img is None or img.isNull():
            return
        p.save()
        p.translate(100, 210)
        p.translate(0, self.bob)
        p.scale(2.0 - self.squash, self.squash)
        p.scale(self.facing, 1)
        p.translate(-100, -210)
        side = min(LOGICAL_W, LOGICAL_H - 16)
        p.drawImage(QRectF((LOGICAL_W - side) / 2, 210 - side, side, side), img)
        p.restore()

    def _paint_cloud(self, p: QPainter):
        """云朵身体：几团圆滚滚的云球并成一片"""
        path = QPainterPath()
        for rect in (QRectF(35, 95, 130, 100),   # 主体
                     QRectF(35, 45, 75, 75),     # 左上云球
                     QRectF(75, 30, 85, 85),     # 顶部云球
                     QRectF(115, 55, 65, 65)):   # 右上云球
            sub = QPainterPath()
            sub.addEllipse(rect)
            path = path.united(sub)
        p.setPen(QPen(C_BODY_DK, 4))
        p.setBrush(QBrush(C_BODY))
        p.drawPath(path)

    def _paint_eyes(self, p: QPainter):
        if self.mood == "happy":
            # 开心眼：^ ^ 弧线
            p.setPen(QPen(C_PUPIL, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for ex in (78, 122):
                path = QPainterPath()
                path.moveTo(ex - 14, 122)
                path.quadTo(ex, 110, ex + 14, 122)
                p.drawPath(path)
            return
        look = 3 * self.facing      # 瞳孔随朝向偏移
        for ex in (78, 122):
            if self.eye_open > 0.12:
                # 云朵本身是白的：直接画深色眼珠 + 高光（惊讶时缩小）
                r = 10 * (0.55 + 0.45 * self.pupil_scale)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(C_PUPIL))
                p.drawEllipse(QRectF(ex + look - r, 121 - r, r * 2, r * 2))
                p.setBrush(QBrush(C_BODY))
                p.drawEllipse(QRectF(ex - 2 + look, 115, 6, 6))
            else:
                # 闭眼：一条弯弯的线
                p.setPen(QPen(C_PUPIL, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath()
                path.moveTo(ex - 11, 121)
                path.quadTo(ex, 127, ex + 11, 121)
                p.drawPath(path)

    def _paint_blush(self, p: QPainter):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(C_BLUSH))
        p.drawEllipse(QRectF(48, 138, 22, 14))
        p.drawEllipse(QRectF(130, 138, 22, 14))

    def _paint_mouth(self, p: QPainter):
        if self.mouth_open < 0.12:
            # 闭嘴：微笑弧线
            p.setPen(QPen(C_MOUTH, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(84, 143)
            path.quadTo(100, 155, 116, 143)
            p.drawPath(path)
        else:
            # 张嘴：口腔 + 舌头，高度随 mouth_open 增大
            p.setPen(QPen(C_MOUTH.darker(120), 2))
            p.setBrush(QBrush(C_MOUTH))
            p.drawRoundedRect(QRectF(86, 140, 28, 4 + 24 * self.mouth_open), 6, 6)
            if self.mouth_open > 0.3:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(C_TONGUE))
                bottom = 144 + 24 * self.mouth_open
                p.drawEllipse(QRectF(92, bottom - 9, 16, 8))

    def _paint_poke_bubble(self, p: QPainter):
        """被戳时头顶的"!"气泡"""
        rect = QRectF(84, 4, 32, 26)
        p.setPen(QPen(QColor(0, 0, 0, 120), 2))
        p.setBrush(QBrush(QColor(255, 255, 255, 235)))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(QColor("#2E3A46"))
        font = QFont("Microsoft YaHei", 15)
        font.setBold(True)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "!")

    def _paint_zzz(self, p: QPainter):
        """睡觉时飘出的 Zzz"""
        t = (self.zzz_phase % 3.0) / 3.0
        for i, (x, y, size) in enumerate(((150, 44, 14), (164, 27, 18), (180, 8, 22))):
            a = max(0.0, 1.0 - abs(t - (i + 0.5) / 3.0) * 3.0)
            if a <= 0.05:
                continue
            font = QFont("Microsoft YaHei", size)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(96, 140, 210, int(235 * a)))
            p.drawText(QRectF(x, y, 30, 30), Qt.AlignmentFlag.AlignCenter, "z")

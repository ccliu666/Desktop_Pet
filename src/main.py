"""桌面小云宝 —— 幼儿园课堂 AI 语音助教，入口。

用法：
    python main.py              # 正常运行
    python main.py --smoke      # 离屏渲染 smoke.png 自检形象后退出
    python main.py --scale 1.6  # 放大（教室大屏用）
    python selfcheck.py         # 环境与功能自检（不需要任何 API Key）
"""
import json
import os
import sys

from PySide6.QtCore import Qt, QPoint, QRectF, QTimer
from PySide6.QtGui import QPainter, QImage, QPixmap, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from behaviors import Brain
from bubble import BubbleWidget, ChatInputWidget
from chat import ChatSession
from config import load_config
from fx import SoundFx
from license import check_authorized, machine_code, should_check
from pet import MonsterWidget
from stage import StageWindow
from tts import Speaker
from voice import VoiceController

BASE_W, BASE_H = 220, 250
POS_FILE = "pet_pos.json"
AVATAR_FILES = {"idle": "img/avatar_idle.png", "blink": "img/avatar_blink.png",
                "talk": "img/avatar_talk.png"}


def _asset_path(name: str) -> str:
    """按优先级找资源文件：CWD → CWD/character（开发）→ 打包目录(_MEIPASS)
    → 脚本目录 → 项目 character/（源码兜底）。

    exe 双击启动时 CWD = exe 所在目录，所以把 img/ 文件夹放在 exe 旁边
    就能直接替换形象（无需重新打包）；找不到再退回打包内嵌的图片。
    """
    script = os.path.dirname(os.path.abspath(__file__))
    proot = os.path.dirname(script) if os.path.basename(script) == "src" else script
    candidates = [
        os.path.join(os.getcwd(), name),
        os.path.join(os.getcwd(), "character", name),
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, name))
    candidates += [
        os.path.join(script, name),
        os.path.join(proot, "character", name),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def load_avatar():
    """读取抠好的透明三帧人物图（小云宝 = img 图片形象）。

    返回 {"idle", "blink", "talk"}；必需帧缺失或损坏则返回 None，
    程序退化为矢量云朵形象。talk 帧可有可无（没有就退回双帧逻辑）。
    """
    images = {}
    for key, name in AVATAR_FILES.items():
        path = _asset_path(name)
        if key == "talk" and not os.path.exists(path):
            continue            # talk 帧可选
        if not os.path.exists(path):
            return None
        img = QImage(path)
        if img.isNull():
            return None
        images[key] = img
    return images


class PetWindow(MonsterWidget):
    """透明置顶窗口：拖拽/点击/右键菜单/滚轮缩放，行为由 Brain 驱动。"""

    SCALE_MIN = 0.5            # 最小缩放

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(BASE_W, BASE_H)
        self._scale = 1.0
        self._down = False
        self._dragging = False
        self._press_global = QPoint()
        self._press_win = QPoint()
        self.brain = Brain(self)
        # 由 main() 注入
        self.session = None
        self.voice = None
        self.stage = None
        self.fx = None
        self._stage_open = False

    # ---------- 鼠标交互 ----------

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self._dragging = False
            self._press_global = e.globalPosition().toPoint()
            self._press_win = self.pos()
        elif e.button() == Qt.MouseButton.RightButton:
            self._show_menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if not self._down:
            return
        delta = e.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() > 6:
            self._dragging = True
            self.brain.on_drag_start()
        if self._dragging:
            self.move(self._press_win + delta)

    def mouseReleaseEvent(self, e):
        if not self._down:
            return
        self._down = False
        if self._dragging:
            self._clamp_to_screen()
            self.brain.on_dropped()
        else:
            self.brain.on_clicked(e.globalPosition().toPoint())
            if self.fx:
                self.fx.play("click")

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.session:
            self.session.toggle_input()     # 双击：输入框开↔关

    def _max_scale(self):
        """缩放上限：宠物最大可放大到填满所在屏幕（可用区域），随屏幕大小动态变化。

        窗口保持 220:250 长宽比不变形，哪个方向先碰到屏幕边缘就到头了
        （宽屏白板上通常是高度先到顶）。
        """
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        a = screen.availableGeometry()
        return max(self.SCALE_MIN,
                   min(a.width() / BASE_W, a.height() / BASE_H))

    def _scale_step(self):
        """滚轮/菜单一次缩放的步长：按当前屏幕的上限等比（约 20 步走满全范围）"""
        return max(0.1, (self._max_scale() - self.SCALE_MIN) / 20)

    def wheelEvent(self, e):
        """鼠标滚轮在宠物身上滚动：放大/缩小"""
        if e.angleDelta().y() > 0:
            self.set_scale(self._scale + self._scale_step())
        elif e.angleDelta().y() < 0:
            self.set_scale(self._scale - self._scale_step())

    def set_scale(self, factor: float):
        """调整宠物大小（底边中点保持不动），最大可填满所在屏幕，退出时自动记住"""
        factor = round(max(self.SCALE_MIN, min(self._max_scale(), factor)), 2)
        if abs(factor - self._scale) < 0.005:
            return
        geo = self.frameGeometry()
        anchor_x, anchor_y = geo.center().x(), geo.bottom()
        self._scale = factor
        self.resize(int(BASE_W * factor), int(BASE_H * factor))
        self.move(anchor_x - self.width() // 2, anchor_y - self.height())
        self._clamp_to_screen()

    def _clamp_to_screen(self):
        """保证窗口落在某个屏幕可见区域内（多屏/任务栏都适用）"""
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            return
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    # ---------- 舞台模式 ----------

    def toggle_stage(self, on: bool):
        if on and not self._stage_open:
            self._stage_open = True
            self.stage.open_near(self)
            if self.session:
                self.session.set_stage_mode(True)
                self.session.set_pet_view(self.stage.monster)
            self.brain.paused = True
            self.hide()
        elif not on and self._stage_open:
            self.stage.close()          # 触发 closed → exit_stage

    def exit_stage(self):
        if not self._stage_open:
            return
        self._stage_open = False
        self.show()
        self.brain.paused = False
        if self.session:
            self.session.set_stage_mode(False)
            self.session.set_pet_view(self)

    def _set_muted(self, on: bool):
        self.session.speaker.set_muted(on)
        if self.fx:
            self.fx.set_muted(on)

    # ---------- 菜单 ----------

    def _show_menu(self, global_pos: QPoint):
        menu = QMenu()
        if self.session:
            act_chat = menu.addAction("跟我聊天（打字）")
            act_chat.setCheckable(True)
            act_chat.setChecked(self.session.input.isVisible())
            act_chat.toggled.connect(
                lambda on: self.session.open_input() if on else self.session.input.hide())
            act_bubble = menu.addAction("显示对话气泡")
            act_bubble.setCheckable(True)
            act_bubble.setChecked(self.session.bubble.enabled)
            act_bubble.toggled.connect(self.session.bubble.set_enabled)
        if self.voice and self.session:
            act_btn = menu.addAction("显示麦克风按钮")
            act_btn.setCheckable(True)
            act_btn.setChecked(self.voice.button.isVisible())
            act_btn.toggled.connect(self.voice.set_button_visible)
            act_wake = menu.addAction("唤醒词监听（喊名字）")
            act_wake.setCheckable(True)
            act_wake.setChecked(self.voice.wake_enabled)
            act_wake.toggled.connect(self.voice.set_wake_enabled)
            act_cont = menu.addAction("连续对话（免唤醒）")
            act_cont.setCheckable(True)
            act_cont.setChecked(self.voice.cont_mode)
            act_cont.toggled.connect(self.voice.set_cont_mode)
            act_mute = menu.addAction("静音")
            act_mute.setCheckable(True)
            act_mute.setChecked(self.session.speaker.muted)
            act_mute.toggled.connect(self._set_muted)
        if self.stage:
            act_stage = menu.addAction("舞台模式（全屏）")
            act_stage.setCheckable(True)
            act_stage.setChecked(self._stage_open)
            act_stage.toggled.connect(self.toggle_stage)
        menu.addSeparator()
        menu.addAction("放大", lambda: self.set_scale(self._scale + self._scale_step()))
        menu.addAction("缩小", lambda: self.set_scale(self._scale - self._scale_step()))
        menu.addSeparator()
        self.brain.build_menu(menu)
        menu.addSeparator()
        menu.addAction("隐藏", self.hide)
        menu.addAction("退出", QApplication.instance().quit)
        menu.exec(global_pos)


def make_icon(avatar=None) -> QIcon:
    """用小云宝（图片形象，缺失时退化为矢量云朵）渲染一个托盘图标"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    m = MonsterWidget()
    if avatar:
        m.set_avatar(avatar)
    m.draw_monster(p, QRectF(0, 0, 64, 64))
    p.end()
    return QIcon(pm)


def load_state():
    """读取上次位置（宠物 + 麦克风按钮）与大小、气泡/移动开关，校验必须落在某块屏幕上"""
    result = {"pet": (200, 300), "mic": None, "scale": 1.0, "bubble": None, "move": None}

    def valid(x, y):
        for scr in QApplication.screens():
            a = scr.availableGeometry()
            if a.left() <= x <= a.right() - 100 and a.top() <= y <= a.bottom() - 100:
                return True
        return False

    try:
        with open(POS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        pet = d.get("pet")
        if pet and valid(int(pet[0]), int(pet[1])):
            result["pet"] = (int(pet[0]), int(pet[1]))
        mic = d.get("mic")
        if mic and valid(int(mic[0]), int(mic[1])):
            result["mic"] = (int(mic[0]), int(mic[1]))
        try:
            # 上限随屏幕动态变化，这里只做下限保护，应用时再钳到当前屏幕
            result["scale"] = max(0.5, float(d.get("scale", 1.0)))
        except (TypeError, ValueError):
            pass
        if "bubble" in d:               # 气泡开关记忆（老文件没有则用配置默认值）
            result["bubble"] = bool(d["bubble"])
        if "move" in d:                 # 自由移动开关记忆
            result["move"] = bool(d["move"])
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return result


def save_state(win, mic_button, bubble_enabled, move_enabled):
    try:
        with open(POS_FILE, "w", encoding="utf-8") as f:
            json.dump({"pet": [win.x(), win.y()],
                       "mic": [mic_button.x(), mic_button.y()],
                       "scale": win._scale,
                       "bubble": bool(bubble_enabled),
                       "move": bool(move_enabled)}, f)
    except OSError:
        pass


def main():
    app = QApplication(sys.argv)
    # 按点位授权校验（仅打包 exe 生效；--smoke/--selftest 诊断模式跳过）
    if should_check() and not check_authorized():
        QMessageBox.warning(
            None, "未授权",
            f"本机没有使用小云宝的权限（{machine_code()}），请联系管理员。")
        return
    if "--smoke" in sys.argv:
        # 离屏渲染形象，开发/打包后自检用：矢量兜底 → smoke.png，图片形象 → smoke_avatar.png
        w = MonsterWidget()
        w.resize(BASE_W, BASE_H)
        img = QImage(BASE_W, BASE_H, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        w.draw_monster(p, QRectF(0, 0, BASE_W, BASE_H))
        p.end()
        img.save("smoke.png")
        print("smoke.png saved (矢量兜底)")
        avatar = load_avatar()
        if avatar:
            w.set_avatar(avatar)
            img2 = QImage(BASE_W, BASE_H, QImage.Format.Format_ARGB32_Premultiplied)
            img2.fill(Qt.GlobalColor.transparent)
            p2 = QPainter(img2)
            w.draw_monster(p2, QRectF(0, 0, BASE_W, BASE_H))
            p2.end()
            img2.save("smoke_avatar.png")
            print("smoke_avatar.png saved (图片形象)")
        else:
            print("图片形象缺失，仅矢量兜底")
        return

    cfg = load_config()
    scale = 1.0
    if "--scale" in sys.argv:
        try:
            scale = float(sys.argv[sys.argv.index("--scale") + 1])
        except (IndexError, ValueError):
            pass

    win = PetWindow()
    win.resize(int(BASE_W * scale), int(BASE_H * scale))

    # 操作音效：点击 / 发送 / 唤醒
    fx = SoundFx()
    # 对话链路：打字 + 气泡 + 语音合成
    session = ChatSession(cfg)
    speaker = Speaker(cfg)
    session.attach(win, BubbleWidget(cfg), speaker, ChatInputWidget(cfg))
    # 语音输入链路：大按钮 + 唤醒词
    voice = VoiceController(cfg, session, fx)
    # 全屏舞台
    stage = StageWindow(cfg)
    stage.closed.connect(win.exit_stage)
    win.session, win.voice, win.stage, win.fx = session, voice, stage, fx

    # 形象：固定用 img 图片人物（小云宝）；图片缺失时退化为矢量云朵
    avatar = load_avatar()
    if avatar:
        win.set_avatar(avatar)
        stage.monster.set_avatar(avatar)

    # 发送消息音效（打字与语音提交都会经过 ask，这里只接打字框）
    session.input.submitted.connect(lambda _text: fx.play("send"))
    # 小云宝睡觉时有人提问就自动醒来
    session.state_changed.connect(
        lambda s: win.brain.wake() if (s != "idle" and win.brain.state == "sleep") else None)
    # TTS 合成失败打控制台（文字仍会照常显示，见 chat.py 的 _on_speak_failed）
    def on_tts_failed(msg):
        print("语音合成失败:", msg)
    speaker.failed.connect(on_tts_failed)

    # 全链路自测：自动提问一句，记录 TTS 事件（带时间戳），收尾后打印结果退出
    if "--selftest" in sys.argv:
        import time as _time
        events = []
        speaker.started.connect(lambda: events.append(f"tts:started@{_time.monotonic():.1f}"))
        speaker.finished.connect(lambda: events.append(f"tts:finished@{_time.monotonic():.1f}"))
        speaker.failed.connect(lambda m: events.append("tts:failed:" + m))
        session.state_changed.connect(lambda s: events.append("state:" + s))

        testing = [False]

        def _start_test():
            print("SELFTEST 开始提问…")
            session.ask("你好呀，请说一句完整的话给我听", from_voice=False)
            testing[0] = True

        def _check_done():
            if testing[0] and not session._busy:
                print("SELFTEST events:", events)
                print("SELFTEST 气泡可见:", session.bubble.isVisible(),
                      "| 输入框可见:", session.input.isVisible())
                spoke = any(e.startswith("tts:started") for e in events)
                failed = any(e.startswith("tts:failed") for e in events)
                # 计算句与句之间的停顿
                ts = []
                for e in events:
                    if e.startswith("tts:started@") or e.startswith("tts:finished@"):
                        tag, t = e.split("@")
                        ts.append((tag.split(":")[1], float(t)))
                gaps = [round(b[1] - a[1], 2) for a, b in zip(ts, ts[1:])
                        if a[0] == "finished" and b[0] == "started"]
                print("SELFTEST 句间停顿(秒):", gaps if gaps else "单句回复无间隔")
                if failed:
                    print("SELFTEST FAIL: TTS 失败", [e for e in events if e.startswith("tts:failed")])
                else:
                    print("SELFTEST PASS" if spoke else "SELFTEST WARN: TTS 从未开始播放")
                app.quit()

        check_t = QTimer()
        check_t.timeout.connect(_check_done)
        check_t.start(500)
        QTimer.singleShot(1500, _start_test)
        QTimer.singleShot(90000, lambda: (print("SELFTEST TIMEOUT events:", events), app.quit()))

    state = load_state()
    if state["bubble"] is not None:
        session.bubble.set_enabled(state["bubble"])   # 恢复上次的气泡开关状态
    if state["move"] is not None:
        win.brain.set_free_move(state["move"])        # 恢复上次的自由移动开关
    else:
        win.brain.set_free_move(bool(cfg["classroom"].get("free_move", False)))
    win.move(*state["pet"])
    # 恢复上次的宠物大小（命令行 --scale 优先）
    if "--scale" in sys.argv:
        win._scale = scale
    else:
        win.set_scale(state["scale"])
    if state["mic"]:
        voice.button.move(*state["mic"])
    else:
        scr = QApplication.primaryScreen().availableGeometry()
        voice.button.move(scr.right() - 130, scr.bottom() - 130)
    win.show()

    # 系统托盘
    tray = QSystemTrayIcon(make_icon(avatar), app)
    tray.setToolTip(cfg["pet"]["name"])
    tray_menu = QMenu()
    tray_menu.addAction("显示/隐藏", lambda: win.setVisible(not win.isVisible()))
    tray_menu.addAction("舞台模式", lambda: win.toggle_stage(not win._stage_open))
    tray_menu.addSeparator()
    tray_menu.addAction("退出", app.quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: win.setVisible(not win.isVisible())
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    win._tray = tray      # 保持引用防止被回收

    app.aboutToQuit.connect(lambda: save_state(win, voice.button,
                                               session.bubble.enabled, win.brain.move_enabled))
    app.aboutToQuit.connect(speaker.close)     # 收起合成线程，避免退出竞态
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

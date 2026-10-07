"""把小云宝（img 图片形象，微笑状态）做成多尺寸 .ico，用作 exe 图标。

优先用 img/avatar_idle.png（抠好的透明微笑图，即用户说的"微笑图片"）；
缺失时回退到矢量云朵离屏渲染。

用法：python scripts/make_icon.py
输出：assets/小云宝.ico（16/32/48/64/128/256 六种尺寸）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PIL import Image
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from pet import MonsterWidget

OUT = os.path.join(ROOT, "character", "assets", "小云宝.ico")
AVATAR_IDLE = os.path.join(ROOT, "character", "img", "avatar_idle.png")
SIZES = (16, 32, 48, 64, 128, 256)


def render_image(size: int) -> Image.Image:
    """用抠好的微笑图片，四周留一点透明边"""
    im = Image.open(AVATAR_IDLE).convert("RGBA")
    pad = max(1, int(size * 0.04))
    inner = im.resize((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(inner, (pad, pad), inner)
    return canvas


def render_vector(size: int) -> Image.Image:
    """回退：矢量云朵离屏渲染"""
    w = MonsterWidget()
    w.resize(size, size)
    w.set_eye(1.0)
    w.set_mouth(0.0)
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.06
    w.draw_monster(p, QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    p.end()
    return Image.frombuffer("RGBA", (size, size), img.constBits(),
                            "raw", "BGRA", img.bytesPerLine(), 1)


def main():
    app = QApplication(sys.argv)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    use_image = os.path.exists(AVATAR_IDLE)
    frames = [render_image(s) if use_image else render_vector(s) for s in SIZES]
    frames[-1].save(OUT, format="ICO",
                    append_images=frames[:-1],
                    sizes=[(s, s) for s in SIZES])
    print(f"已生成 {OUT}，尺寸: {SIZES}，来源: {'img 微笑图片' if use_image else '矢量云朵'}")

    if not use_image:
        print("提示: img/avatar_idle.png 不存在，已回退矢量云朵；先跑 scripts/prepare_avatar.py 生成图片")


if __name__ == "__main__":
    main()

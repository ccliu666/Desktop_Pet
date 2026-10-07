"""把 AI 生成的图片处理成三帧透明 PNG（一次性预处理，可重复运行）。

小云宝三帧（2026-09-30 用户重新上传的 2048² PNG，文件名与内容一致）：
    idle  ← img/微笑.png  睁眼微笑（常态，白底）
    blink ← img/眨眼.png  闭眼眨眼（白底）
    talk  ← img/说话.png  张嘴说话（绿底满幅）

流程：
1. 先缩到最大边 1024（提速 + 顺带抹掉 AI 图的散布噪点）。
2. 水印清除：三张图右下角都有"豆包AI生成"字样（已定位：x≥0.80、y≥0.92
   分数区域），整块涂成背景色。
3. 背景色自动检测（四边中位数）+ 与四边连通的近背景色区域置透明
   （白底/绿底通用；Pillow 12 已移除 floodfill，用迭代生长实现）。
4. 3x3 最小滤波收缩 alpha 边缘 1px 去白边。
5. 统一归一化：裁出角色包围盒，三帧缩放到同一高度（0.86 输出边长），
   水平居中、底部对齐贴到 768×768 透明画布——保证三帧切换时角色大小不变。
6. 颜色统一：以 idle 帧为基准，其余帧按每通道直方图匹配对齐（AI 分次生成
   的图有色差，尤其身体偏灰/偏绿），最后三帧统一提升鲜艳度。
"""
import os

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

OUT_SIZE = 768              # 输出边长
CHAR_H_FRAC = 0.86          # 角色统一高度 = 输出边长的这个比例
MAX_SIDE = 1024             # 处理前缩到的最大边
TOL = 25                    # 背景色容差
WM_X_FRAC, WM_Y_FRAC = 0.80, 0.92   # 右下角水印区（分数坐标，三张图都在此位置）
VIVID = 1.22                # 鲜艳度提升倍数（颜色统一后三帧一起提鲜）

SRC = {
    "idle":  "character/img/微笑.png",
    "blink": "character/img/眨眼.png",
    "talk":  "character/img/说话.png",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def detect_bg(arr):
    """取四边像素的中位数作为背景色"""
    border = np.concatenate([arr[0, :, :], arr[-1, :, :], arr[:, 0, :], arr[:, -1, :]])
    return np.median(border, axis=0)


def remove_bg(arr, bg):
    """把与四边连通的近背景色区域标记为 True"""
    near = (np.abs(arr[:, :, 0].astype(int) - bg[0]) <= TOL) & \
           (np.abs(arr[:, :, 1].astype(int) - bg[1]) <= TOL) & \
           (np.abs(arr[:, :, 2].astype(int) - bg[2]) <= TOL)
    seed = near.copy()
    seed[1:-1, 1:-1] = False
    prev = 0
    while seed.sum() != prev:
        prev = seed.sum()
        grown = seed.copy()
        grown[:-1, :] |= seed[1:, :]
        grown[1:, :] |= seed[:-1, :]
        grown[:, :-1] |= seed[:, 1:]
        grown[:, 1:] |= seed[:, :-1]
        seed = grown & near
    return seed


def normalize(im_rgba):
    """裁出角色包围盒，统一缩放到底部居中"""
    alpha = np.asarray(im_rgba)[:, :, 3]
    ys, xs = np.where(alpha > 10)
    if len(xs) == 0:
        return im_rgba
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = im_rgba.crop((x0, y0, x1 + 1, y1 + 1))
    target_h = int(OUT_SIZE * CHAR_H_FRAC)
    scale = target_h / crop.height
    new_w = max(1, int(crop.width * scale))
    crop = crop.resize((new_w, target_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (OUT_SIZE, OUT_SIZE), (0, 0, 0, 0))
    x = (OUT_SIZE - new_w) // 2
    y = OUT_SIZE - target_h - int(OUT_SIZE * 0.03)
    canvas.paste(crop, (x, y), crop)
    return canvas


def process(rel_path):
    """预处理一帧，返回归一化后的 RGBA 图像（不落盘）"""
    src = os.path.join(ROOT, rel_path)
    if not os.path.exists(src):
        print(f"跳过（找不到原图）: {src}")
        return None
    im = Image.open(src).convert("RGB")
    # 1) 缩到最大边 1024
    w, h = im.size
    if max(w, h) > MAX_SIDE:
        scale = MAX_SIDE / max(w, h)
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    arr = np.array(im, dtype=np.uint8)

    bg = detect_bg(arr)
    print(f"  {rel_path}: 背景色 {tuple(int(v) for v in bg)}")

    # 2) 右下角水印整块涂背景色
    arr[int(arr.shape[0] * WM_Y_FRAC):, int(arr.shape[1] * WM_X_FRAC):] = bg.astype(np.uint8)

    # 3) 连通背景清除
    seed = remove_bg(arr, bg)
    alpha = np.where(seed, 0, 255).astype(np.uint8)
    im = im.convert("RGBA")
    im.putalpha(Image.fromarray(alpha, "L"))
    # 4) 收缩 alpha 1px 去白边
    alpha2 = im.getchannel("A").filter(ImageFilter.MinFilter(3))
    im.putalpha(alpha2)

    # 5) 归一化
    return normalize(im)


def hist_match(src, ref):
    """src: (N,3) uint8 像素 → 按参考像素 ref 的每通道分位数映射到相同分布"""
    out = np.empty_like(src)
    for ch in range(3):
        s_vals, s_cdf = np.unique(src[:, ch], return_counts=True)
        s_cdf = np.cumsum(s_cdf) / src.shape[0]
        r_vals, r_cdf = np.unique(ref[:, ch], return_counts=True)
        r_cdf = np.cumsum(r_cdf) / ref.shape[0]
        lut = np.interp(np.arange(256), s_vals,
                        np.interp(s_cdf, r_cdf, r_vals)).astype(np.uint8)
        out[:, ch] = lut[src[:, ch]]
    return out


def unify_colors(frames):
    """以 idle 为基准统一三帧颜色，再统一提升鲜艳度（用户要求：颜色统一、鲜亮为先）"""
    def rgb_mask(im):
        a = np.asarray(im)
        m = a[:, :, 3] > 128
        return a[:, :, :3], m

    ref_rgb, ref_m = rgb_mask(frames["idle"])
    ref_px = ref_rgb[ref_m]

    def body_mean(im):
        a = np.asarray(im)
        m = a[:, :, 3] > 128
        return a[:, :, :3][m].mean(axis=0)

    def cell_means(im):
        """6x8 网格逐格 RGB 均值（内容不足的格子为 None）"""
        a = np.asarray(im)
        m = a[:, :, 3] > 128
        H, W = a.shape[:2]
        means = []
        for cy in range(8):
            for cx in range(6):
                blk = m[cy * H // 8:(cy + 1) * H // 8, cx * W // 6:(cx + 1) * W // 6]
                if blk.sum() < 200:
                    means.append(None)
                    continue
                reg = a[cy * H // 8:(cy + 1) * H // 8, cx * W // 6:(cx + 1) * W // 6, :3][blk]
                means.append(reg.mean(axis=0))
        return means

    print("  颜色统一前 各帧整体均值 RGB:")
    for k, im in frames.items():
        print(f"    {k}: {np.round(body_mean(im), 1)}")

    out = {}
    for k, im in frames.items():
        a = np.asarray(im).copy()
        m = a[:, :, 3] > 128
        if k != "idle" and m.sum() > 0:
            # 第一步：直方图匹配（整体色调对齐）
            a[:, :, :3][m] = hist_match(a[:, :, :3][m], ref_px)
            # 第二步：用内容一致的稳定格子（差值最小的 1/3）做每通道线性回归，
            # 进一步对齐身体/衣服的偏色（避开眼睛嘴巴等内容变化区）
            base = cell_means(frames["idle"])
            fr = cell_means(Image.fromarray(a))
            pairs = [(b, f) for b, f in zip(base, fr)
                     if b is not None and f is not None]
            pairs.sort(key=lambda p: float(np.abs(np.array(p[0]) - np.array(p[1])).max()))
            sel = pairs[:max(3, len(pairs) // 3)]
            X = np.array([p[1] for p in sel])
            Y = np.array([p[0] for p in sel])
            px = a[:, :, :3][m].astype(np.float64)
            for ch in range(3):
                coef = np.polyfit(X[:, ch], Y[:, ch], 1)
                px[:, ch] = np.clip(coef[0] * px[:, ch] + coef[1], 0, 255)
            a[:, :, :3][m] = px.astype(np.uint8)
        out[k] = ImageEnhance.Color(Image.fromarray(a)).enhance(VIVID)

    print("  颜色统一后 各帧整体均值 RGB:")
    for k, im in out.items():
        print(f"    {k}: {np.round(body_mean(im), 1)}")
    return out


def local_correct(ref_im, src_im):
    """分区局部校色：AI 分次生成的着色偏差在不同区域方向不同（如下巴带偏暗/
    偏绿），全局校色拉不齐。做法：把图分成 8x6 格，内容一致的格子算出每通道
    增益（向 idle 对齐），无效格子（眼睛/嘴巴等内容变化区）由邻域插值，
    增益图平滑后逐像素应用到整帧。"""
    ref = np.asarray(ref_im).astype(np.float64)
    src = np.asarray(src_im).astype(np.float64)
    m_ref = ref[:, :, 3] > 128
    m_src = src[:, :, 3] > 128
    H, W = ref.shape[:2]
    GH, GW = 8, 6
    gains = np.ones((GH, GW, 3))
    valid = np.zeros((GH, GW), bool)
    for cy in range(GH):
        for cx in range(GW):
            br = m_ref[cy * H // GH:(cy + 1) * H // GH, cx * W // GW:(cx + 1) * W // GW]
            bs = m_src[cy * H // GH:(cy + 1) * H // GH, cx * W // GW:(cx + 1) * W // GW]
            nr, ns = int(br.sum()), int(bs.sum())
            if nr < 300 or ns < 300:
                continue
            if abs(nr - ns) / max(nr, ns) > 0.08:
                continue                    # 内容不同（眼/嘴），跳过
            r = ref[cy * H // GH:(cy + 1) * H // GH, cx * W // GW:(cx + 1) * W // GW, :3][br]
            s = src[cy * H // GH:(cy + 1) * H // GH, cx * W // GW:(cx + 1) * W // GW, :3][bs]
            g = r.mean(axis=0) / np.maximum(s.mean(axis=0), 1.0)
            if np.all(g > 0.75) and np.all(g < 1.30):
                gains[cy, cx] = np.clip(g, 0.85, 1.18)
                valid[cy, cx] = True
    if valid.sum() < GH * GW // 3:
        print("    有效格子太少，跳过局部校色")
        return src_im
    # 无效格子用全局有效均值填充，再做两轮 3x3 平滑
    fill = gains[valid].mean(axis=0)
    gains[~valid] = fill
    for _ in range(2):
        g2 = gains.copy()
        g2[1:-1, 1:-1] = (gains[:-2, 1:-1] + gains[2:, 1:-1]
                         + gains[1:-1, :-2] + gains[1:-1, 2:]
                         + 4 * gains[1:-1, 1:-1]) / 8.0
        gains = g2
    # 增益图放大到全图并应用
    gain_map = np.empty((H, W, 3))
    for ch in range(3):
        g_im = Image.fromarray((gains[:, :, ch] * 256).astype(np.uint16))
        gain_map[:, :, ch] = np.asarray(g_im.resize((W, H), Image.BILINEAR)) / 256.0
    out = src.copy()
    out[:, :, :3][m_src] = np.clip(src[:, :, :3][m_src] * gain_map[m_src], 0, 255)
    return Image.fromarray(out.astype(np.uint8))


def main():
    frames = {}
    for key, rel in SRC.items():
        im = process(rel)
        if im is not None:
            frames[key] = im
    if "idle" not in frames:
        print("缺少 idle 帧，无法做颜色基准，退出")
        return
    frames = unify_colors(frames)
    # 局部校色（第 7 步）：进一步消除区域性偏色
    for key in ("blink", "talk"):
        if key in frames:
            frames[key] = local_correct(frames["idle"], frames[key])
    for key, im in frames.items():
        out = os.path.join(ROOT, "character", "img", f"avatar_{key}.png")
        im.save(out)
        corners = [im.getpixel(p) for p in [(1, 1), (OUT_SIZE - 2, 1),
                                            (1, OUT_SIZE - 2), (OUT_SIZE - 2, OUT_SIZE - 2)]]
        print(f"  -> {os.path.basename(out)}  四角 alpha: {[c[3] for c in corners]}")


if __name__ == "__main__":
    main()

"""生成操作音效 wav（一次性，可重复运行）：点击 / 发送 / 唤醒。"""
import math
import os
import struct
import wave

SR = 22050
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "character", "fx")

# 每段：(起始频率, 结束频率, 时长秒, 幅度)
SPECS = {
    "click": [(900, 500, 0.09, 0.45)],
    "send":  [(660, 660, 0.05, 0.35), (990, 990, 0.08, 0.35)],
    "wake":  [(1318, 1318, 0.12, 0.35), (1760, 1760, 0.20, 0.30)],
}


def gen(name: str, segments):
    total = sum(d for *_ , d, _ in segments)
    n = int(SR * total)
    samples = []
    t = 0.0
    for f0, f1, dur, amp in segments:
        m = int(SR * dur)
        for i in range(m):
            k = i / m
            f = f0 + (f1 - f0) * k
            # 指数衰减包络，避免爆音
            env = amp * math.exp(-3.5 * k)
            samples.append(env * math.sin(2 * math.pi * f * t))
            t += 1.0 / SR
    # 首尾各 2ms 淡入淡出
    fade = int(SR * 0.002)
    for i in range(fade):
        samples[i] *= i / fade
        samples[-1 - i] *= i / fade
    path = os.path.join(OUT_DIR, f"{name}.wav")
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))
    print(f"{path}  {len(samples) / SR:.2f}s")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, seg in SPECS.items():
        gen(name, seg)


if __name__ == "__main__":
    main()

"""生成 PWA 图标（纯标准库，无外部依赖）。
标记：赤陶底 + 米白纸页 + 鼠尾草状态点 —— 呼应 Organic 设计系统。"""
import math, struct, zlib, os, sys

GROUND = (0xc6, 0x71, 0x39)
PAPER  = (0xf5, 0xea, 0xd8)
SAGE   = (0x7a, 0x8a, 0x5e)
INK    = (0xd6, 0x94, 0x63)

def rr(px, py, cx, cy, hw, hh, r):
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r

def circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r

def over(dst, src, a):
    return tuple(int(round(src[i] * a + dst[i] * (1 - a))) for i in range(3))

def render(size):
    s = float(size)
    sheet = (0.50 * s, 0.50 * s, 0.285 * s, 0.325 * s, 0.075 * s)
    dot   = (0.375 * s, 0.335 * s, 0.032 * s)
    lines = [
        (0.575 * s, 0.335 * s, 0.085 * s, 0.0165 * s),
        (0.500 * s, 0.470 * s, 0.160 * s, 0.0165 * s),
        (0.455 * s, 0.590 * s, 0.115 * s, 0.0165 * s),
    ]
    rows = []
    for y in range(size):
        py = y + 0.5
        row = []
        for x in range(size):
            px = x + 0.5
            c = GROUND
            a = min(max(0.5 - rr(px, py, *sheet), 0.0), 1.0)
            if a > 0:
                c = over(c, PAPER, a)
            a = min(max(0.5 - circle(px, py, *dot), 0.0), 1.0)
            if a > 0:
                c = over(c, SAGE, a)
            for lx, ly, lhw, lhh in lines:
                a = min(max(0.5 - rr(px, py, lx, ly, lhw, lhh, lhh), 0.0), 1.0)
                if a > 0:
                    c = over(c, INK, a)
            row.append((c[0], c[1], c[2], 255))
        rows.append(row)
    return rows

def write_png(path, rows):
    h = len(rows); w = len(rows[0])
    raw = b''.join(b'\x00' + bytes(v for px in r for v in px) for r in rows)
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    data = (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(data)

out = sys.argv[1] if len(sys.argv) > 1 else 'public/icons'
os.makedirs(out, exist_ok=True)
for size, name in ((192, 'icon-192.png'), (512, 'icon-512.png'), (180, 'apple-touch-icon.png')):
    write_png(os.path.join(out, name), render(size))
    print('wrote', name, size)

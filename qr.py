"""Minimal QR Code generator (byte mode, error correction M, versions 1-6).

Enough for URLs up to 106 bytes. Standard library only. Output is an SVG string.
Follows ISO/IEC 18004; structure and table values cross-checked against the
public QR reference tables. See test_qr.py for the tests.
"""
from __future__ import annotations

# (data codewords per block, number of blocks, EC codewords per block) for level M
_BLOCKS = {1: (16, 1, 10), 2: (28, 1, 16), 3: (44, 1, 26),
           4: (32, 2, 18), 5: (43, 2, 24), 6: (27, 4, 16)}
MAX_VERSION = 6


def capacity(version: int) -> int:
    """Max bytes that fit in `version` (byte mode, level M)."""
    per, blocks, _ = _BLOCKS[version]
    return (per * blocks * 8 - 12) // 8


# ------------------------------------------------------------ Reed-Solomon
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(n: int) -> list[int]:
    g = [1]
    for i in range(n):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _gmul(c, _EXP[i])
        g = ng
    return g


def rs_remainder(data: list[int], n: int) -> list[int]:
    """Reed-Solomon error-correction codewords for `data`."""
    g = _generator(n)
    rem = [0] * n
    for b in data:
        factor = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _gmul(g[i + 1], factor)
    return rem


# ---------------------------------------------------------- format info
def format_bits(mask: int) -> int:
    """15-bit format information for level M and the given mask (0-7)."""
    data = (0b00 << 3) | mask           # level M = 00
    rem = data << 10
    for i in range(14, 9, -1):
        if (rem >> i) & 1:
            rem ^= 0x537 << (i - 10)
    return ((data << 10) | rem) ^ 0x5412


def format_positions(size: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(x, y) module positions of format bits 0..14 for both copies."""
    a = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    b = [(size - 1 - i, 8) for i in range(8)] + [(8, size - 15 + i) for i in range(8, 15)]
    return a, b


# ----------------------------------------------------------- matrix build
class _Builder:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = 17 + 4 * version
        n = self.size
        self.mod = [[False] * n for _ in range(n)]
        self.func = [[False] * n for _ in range(n)]
        self._patterns()

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.mod[y][x] = dark
        self.func[y][x] = True

    def _patterns(self) -> None:
        n = self.size
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        if self.version >= 2:
            cx = cy = n - 7
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    self._set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)  # reserve the format areas

    def draw_format(self, mask: int) -> None:
        bits = format_bits(mask)
        a, b = format_positions(self.size)
        for i in range(15):
            bit = (bits >> i) & 1 == 1
            self._set(*a[i], bit)
            self._set(*b[i], bit)
        self._set(8, self.size - 8, True)  # the always-dark module

    def place(self, codewords: list[int]) -> None:
        n, i = self.size, 0
        total = len(codewords) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            for vert in range(n):
                y = n - 1 - vert if upward else vert
                for j in range(2):
                    x = right - j
                    if not self.func[y][x] and i < total:
                        self.mod[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.func[y][x] and mask_bit(mask, x, y):
                    self.mod[y][x] = not self.mod[y][x]


def mask_bit(mask: int, x: int, y: int) -> bool:
    return [
        (x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0,
        (x // 3 + y // 2) % 2 == 0, x * y % 2 + x * y % 3 == 0,
        (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0,
    ][mask]


def _penalty(m: list[list[bool]]) -> int:
    n = len(m)
    score = 0
    cols = [[m[y][x] for y in range(n)] for x in range(n)]
    for lines in (m, cols):
        for line in lines:
            run = 1
            for i in range(1, n):
                if line[i] == line[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run = 1
            if run >= 5:
                score += 3 + run - 5
            s = "".join("1" if v else "0" for v in line)
            score += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    dark = sum(v for row in m for v in row)
    total = n * n
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return score + k * 10


def encode_codewords(data: bytes, version: int) -> list[int]:
    """Data + EC codewords, interleaved, ready for placement."""
    per, blocks, ec = _BLOCKS[version]
    total_data = per * blocks
    bits = "0100" + format(len(data), "08b") + "".join(format(b, "08b") for b in data)
    bits += "0" * min(4, total_data * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    cw = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(cw) < total_data:
        cw.append(pad[(len(cw) - len(bits) // 8) % 2])
    chunks = [cw[i * per:(i + 1) * per] for i in range(blocks)]
    ecs = [rs_remainder(c, ec) for c in chunks]
    out = [c[i] for i in range(per) for c in chunks]
    out += [e[i] for i in range(ec) for e in ecs]
    return out


def function_mask(version: int) -> list[list[bool]]:
    return _Builder(version).func


def make_matrix(text: str) -> tuple[list[list[bool]], int]:
    data = text.encode("utf-8")
    version = next((v for v in range(1, MAX_VERSION + 1) if len(data) <= capacity(v)), None)
    if version is None:
        raise ValueError(f"text too long for this QR generator (max {capacity(MAX_VERSION)} bytes)")
    codewords = encode_codewords(data, version)
    best, best_score = None, None
    for mask in range(8):
        b = _Builder(version)
        b.place(codewords)
        b.apply_mask(mask)
        b.draw_format(mask)
        s = _penalty(b.mod)
        if best_score is None or s < best_score:
            best, best_score = b.mod, s
    return best, version


def to_svg(text: str, border: int = 4) -> str:
    m, _ = make_matrix(text)
    n = len(m)
    path = " ".join(f"M{x + border},{y + border}h1v1h-1z"
                    for y, row in enumerate(m) for x, d in enumerate(row) if d)
    size = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
            f'<path d="{path}" fill="#000"/></svg>')

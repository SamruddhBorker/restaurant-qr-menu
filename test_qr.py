import unittest

import qr


def decode(matrix):
    """Independent-ish decoder: reads a module matrix back into bytes, checking
    format-info BCH, both format copies, and Reed-Solomon."""
    size = len(matrix)
    version = (size - 17) // 4
    a, b = qr.format_positions(size)
    bits_a = sum(matrix[y][x] << i for i, (x, y) in enumerate(a))
    bits_b = sum(matrix[y][x] << i for i, (x, y) in enumerate(b))
    assert bits_a == bits_b, "format copies differ"
    mask = next(m for m in range(8) if qr.format_bits(m) == bits_a)
    func = qr.function_mask(version)
    # unmask a copy, then read codewords in zig-zag order
    bitsout = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vert in range(size):
            y = size - 1 - vert if upward else vert
            for j in range(2):
                x = right - j
                if not func[y][x]:
                    bitsout.append(int(matrix[y][x] ^ qr.mask_bit(mask, x, y)))
        right -= 2
    per, blocks, ec = qr._BLOCKS[version]
    total = (per + ec) * blocks
    cws = [int("".join(map(str, bitsout[i * 8:(i + 1) * 8])), 2) for i in range(total)]
    data_part = cws[:per * blocks]
    ec_part = cws[per * blocks:]
    chunks = [[data_part[i * blocks + k] for i in range(per)] for k in range(blocks)]
    ecs = [[ec_part[i * blocks + k] for i in range(ec)] for k in range(blocks)]
    for c, e in zip(chunks, ecs):
        assert qr.rs_remainder(c, ec) == e, "Reed-Solomon check failed"
    flat = [b for c in chunks for b in c]
    bits = "".join(format(b, "08b") for b in flat)
    assert bits[:4] == "0100"
    n = int(bits[4:12], 2)
    return bytes(int(bits[12 + 8 * i:20 + 8 * i], 2) for i in range(n))


class ReferenceValueTests(unittest.TestCase):
    def test_reed_solomon_known_vector(self):
        # Standard worked example: "HELLO WORLD", version 1-M
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr.rs_remainder(data, 10),
                         [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_format_info_known_values(self):
        self.assertEqual(format(qr.format_bits(0), "015b"), "101010000010010")  # M, mask 0
        self.assertEqual(format(qr.format_bits(1), "015b"), "101000100100101")  # M, mask 1

    def test_capacities_match_spec(self):
        self.assertEqual([qr.capacity(v) for v in range(1, 7)], [14, 26, 42, 62, 84, 106])


class RoundTripTests(unittest.TestCase):
    def test_roundtrip_various_lengths(self):
        samples = ["hi", "http://192.168.1.5:8000/?t=1",
                   "https://restaurant.example.com/menu?t=12",
                   "x" * 14, "y" * 26, "z" * 42, "w" * 62, "v" * 84, "u" * 106,
                   "Café ₹ 🍽"]
        for s in samples:
            m, v = qr.make_matrix(s)
            self.assertEqual(decode(m), s.encode("utf-8"), s)

    def test_version_grows_with_length(self):
        self.assertEqual(qr.make_matrix("a" * 14)[1], 1)
        self.assertEqual(qr.make_matrix("a" * 15)[1], 2)
        self.assertEqual(qr.make_matrix("a" * 106)[1], 6)

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            qr.make_matrix("a" * 107)

    def test_finder_patterns_present(self):
        m, _ = qr.make_matrix("hello")
        n = len(m)
        for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
            self.assertTrue(all(m[oy][ox + i] for i in range(7)))        # top edge dark
            self.assertTrue(all(m[oy + 6][ox + i] for i in range(7)))    # bottom edge dark
            self.assertFalse(m[oy + 1][ox + 1])                          # light ring
            self.assertTrue(m[oy + 3][ox + 3])                           # dark centre

    def test_svg_output(self):
        svg = qr.to_svg("http://x.y/")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("viewBox", svg)
        self.assertNotIn("<script", svg)


if __name__ == "__main__":
    unittest.main()

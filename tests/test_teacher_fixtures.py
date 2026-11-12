"""教师素材回归：解析器必须能吃下“可供选用的图片”里的每一张合规图。

素材目录可能不在本机（同学 clone 后可能只拿到代码），找不到就跳过，不判失败。
"""
import unittest

from bmp_lsb import BMP, BMPError
from tools.bmp_probe import find_fixtures_root, iter_bmps

try:
    FIXTURES = find_fixtures_root()
except FileNotFoundError:
    FIXTURES = None

skip_without_fixtures = unittest.skipIf(FIXTURES is None, '本机没有“可供选用的图片”素材目录')

# 实测容量，作为解析结果的独立基准，避免“解析通过但字段读错”仍被判通过。
EXPECTED_CAPACITY = {
    '256灰度/4X2.BMP': 1, '256灰度/4X4.bmp': 2, '256灰度/8X8.bmp': 8,
    '256灰度/16X16.bmp': 32, '256灰度/4X16.bmp': 8,
    '256灰度/test2.bmp': 8192, '256灰度/lake.BMP': 32768,
    '24位真彩图/LENA_COLOR.BMP': 98304, '24位真彩图/test2.bmp': 24576,
    '24位真彩图/test9.bmp': 73728, '24位真彩图/test13.bmp': 36864,
}


@skip_without_fixtures
class TeacherFixtureTests(unittest.TestCase):
    def test_all_fixtures_parse(self):
        rejected = []
        for path in iter_bmps(FIXTURES):
            rel = path.relative_to(FIXTURES).as_posix()
            try:
                BMP.open(path)
            except (BMPError, OSError) as exc:
                rejected.append((rel, str(exc)))
        # 只有超 512 的 test14 允许被拒。
        self.assertEqual([rel for rel, _ in rejected], ['24位真彩图/test14.bmp'])
        self.assertIn('512', rejected[0][1])

    def test_capacity_baseline(self):
        for rel, expected in EXPECTED_CAPACITY.items():
            with self.subTest(fixture=rel):
                self.assertEqual(BMP.open(FIXTURES / rel).capacity, expected)

    def test_missized_image_size_field_accepted(self):
        # 这五张小图的 biSizeImage 被写成 宽×高×3，过去会被判为非法。
        for rel in ('256灰度/4X2.BMP', '256灰度/4X4.bmp', '256灰度/8X8.bmp',
                    '256灰度/16X16.bmp', '256灰度/4X16.bmp'):
            with self.subTest(fixture=rel):
                bmp = BMP.open(FIXTURES / rel)
                self.assertEqual(bmp.bpp, 8)
                self.assertEqual(bmp.trailing_bytes, 0)

    def test_page27_cases_with_real_fixtures(self):
        small = FIXTURES / '256灰度'
        source = BMP.open(small / '4X2.BMP')
        self.assertEqual(source.embed(b'?').extract(1), b'?')
        source = BMP.open(small / '4X4.bmp')
        self.assertEqual(source.embed(b'?S').extract(2), b'?S')
        with self.assertRaises(BMPError):
            source.embed(b'AbCd')

    def test_trailing_bytes_kept(self):
        for name in ('test6.bmp', 'test7.bmp'):
            with self.subTest(fixture=name):
                source = BMP.open(FIXTURES / '256灰度' / name)
                self.assertEqual(source.trailing_bytes, 2)
                tail = source.data[source.pixel_end:]
                payload = '尾随字节'.encode('utf-8')
                carrier = source.embed(payload)
                self.assertEqual(carrier.data[carrier.pixel_end:], tail)
                self.assertEqual(carrier.extract(len(payload)), payload)

    def test_palette_grayscale_real_image(self):
        # 教师灰度图的调色板并非都按 0..255 顺序排列，嵌入必须走灰度映射。
        bmp = BMP.open(FIXTURES / '256灰度/test5.bmp')
        payload = '灰度调色板'.encode('utf-8')
        carrier = bmp.embed(payload)
        self.assertEqual(carrier.extract(len(payload)), payload)
        self.assertTrue(all(abs(carrier.value(q) - bmp.value(p)) <= 1
                            for p, q in zip(bmp.positions(), carrier.positions())))


if __name__ == '__main__':
    unittest.main(verbosity=2)

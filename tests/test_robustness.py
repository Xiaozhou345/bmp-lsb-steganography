"""轨道 B：JPEG 往返（附加②）与剪裁（附加③）的单元测试。

覆盖三块：

- ``robustness.crop``：像素搬运、文件头重建、8 位调色板、方向、非法参数；
- 样本流模型：整行剪裁的位移/字节对齐，以及"顶部剪裁消息仍在、底部剪裁
  从头丢"的实际提取结果；
- ``tools/jpeg_roundtrip``：基线 JPEG 编码→解码的尺寸、PSNR、标记结构、
  4:2:0/4:4:4、非 8 倍数尺寸的补齐，以及"JPEG 后 LSB 失效"的端到端流程。
"""
import struct
import unittest

from bmp_lsb import BMP, BMPError
from make_samples import make_bmp
from robustness import (compare_payload, crop, crop_layout, crop_survival,
                        embed_at_plane, extract_at_plane, jpeg_bit_plane_table,
                        jpeg_survival, payload_bits)
from tools.jpeg_roundtrip import (bmp_from_rows, decode_jpeg, encode_bmp_to_jpeg,
                                  jpeg_roundtrip, scaled_tables)


def psnr(original, carrier):
    from bmp_lsb import analyze
    return analyze(original, carrier)['psnr_db']


def smooth_image(width, height):
    """平滑彩色渐变：JPEG 编解码测试用它，避免 make_bmp 的锯齿图案干扰 PSNR。"""
    stride = ((width * 3 + 3) // 4) * 4
    pixels = bytearray()
    for y in range(height):
        line = bytearray()
        for x in range(width):
            line += bytes((40 + 180 * x // max(width - 1, 1),
                           60 + 150 * y // max(height - 1, 1), 120))
        pixels += line[:width * 3] + b'\0' * (stride - width * 3)
    header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
    dib = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels),
                      2835, 2835, 0, 0)
    return BMP.parse(header + dib + bytes(pixels))


class CropTests(unittest.TestCase):
    def test_24bit_pixels_and_header(self):
        source = make_bmp(64, 48, 24)
        piece = crop(source, 8, 4, 32, 16)
        self.assertEqual((piece.width, piece.height), (32, 16))
        self.assertEqual(piece.bpp, 24)
        self.assertEqual(piece.signed_height, 16)
        self.assertEqual(piece.stride, 96)
        self.assertEqual(piece.pixel_end, len(piece.data))
        rows = list(source.rgb_rows())
        got = list(piece.rgb_rows())
        for y in range(16):
            self.assertEqual(got[y], rows[4 + y][8 * 3:(8 + 32) * 3])

    def test_8bit_keeps_palette(self):
        source = make_bmp(32, 32, 8)
        piece = crop(source, 4, 8, 16, 16)
        self.assertEqual(piece.bpp, 8)
        self.assertEqual(piece.palette, source.palette)
        self.assertEqual(list(piece.rgb_rows())[0],
                         list(source.rgb_rows())[8][4 * 3:(4 + 16) * 3])

    def test_top_down_source_becomes_bottom_up(self):
        source = make_bmp(32, 32, 24, top_down=True)
        piece = crop(source, 0, 4, 32, 8)
        self.assertEqual(piece.signed_height, 8)      # 产物统一为正高度
        rows = list(source.rgb_rows())
        self.assertEqual(list(piece.rgb_rows()), rows[4:12])

    def test_rejects_bad_rectangles(self):
        source = make_bmp(32, 32)
        for rect in ((-4, 0, 8, 8), (0, -1, 8, 8), (0, 0, 0, 8), (30, 0, 8, 8),
                     (0, 0, 6, 8), (0, 0, 8, 40)):
            with self.subTest(rect=rect):
                with self.assertRaises(BMPError):
                    crop(source, *rect)

    def test_cropped_carrier_still_extractable_when_message_kept(self):
        source = make_bmp(64, 64, 24)
        payload = b'ABCDEFGH'
        carrier = source.embed(payload)
        # 只保留底部 56 行：剪掉的是样本流末尾，消息在开头，应当原样取回
        piece = crop(carrier, 0, 8, 64, 56)
        self.assertEqual(piece.extract(len(payload)), payload)


class StreamModelTests(unittest.TestCase):
    def test_layout_rows_only_and_alignment(self):
        source = make_bmp(8, 16, 24)                  # 每行 24 个样本，是 8 的倍数
        layout = crop_layout(source, 0, 0, 8, 15)
        self.assertEqual(layout['samples_per_row'], 24)
        self.assertEqual(layout['head_samples'], 24)  # 剪掉底部一行 = 流头少 24 个样本
        self.assertTrue(layout['rows_only'])
        self.assertTrue(layout['byte_aligned'])
        self.assertEqual(layout['capacity'], 24 * 15 // 8)

        narrow = make_bmp(4, 16, 24)                  # 每行 12 个样本，不是 8 的倍数
        layout = crop_layout(narrow, 0, 0, 4, 15)
        self.assertEqual(layout['head_samples'], 12)
        self.assertFalse(layout['byte_aligned'])

    def test_left_crop_is_not_rows_only(self):
        source = make_bmp(32, 32, 24)
        layout = crop_layout(source, 4, 0, 28, 32)
        self.assertFalse(layout['rows_only'])
        self.assertFalse(layout['byte_aligned'])
        self.assertEqual(layout['head_samples'], 0)

    def test_top_crop_removes_tail_not_head(self):
        source = make_bmp(32, 32, 24)
        layout = crop_layout(source, 0, 8, 32, 24)    # 剪掉顶部 8 行
        self.assertEqual(layout['head_samples'], 0)
        self.assertEqual(layout['tail_samples'], 8 * 96)

    def test_aligned_crop_keeps_payload_suffix(self):
        source = make_bmp(64, 64, 24)                 # 每行 192 个样本 = 24 字节
        payload = bytes(range(40))
        carrier = source.embed(payload)
        piece = crop(carrier, 0, 0, 64, 63)           # 剪掉最底下一行
        got = piece.extract(40)
        self.assertEqual(got[:16], payload[24:40])    # 消息整体前移 24 字节

    def test_misaligned_crop_destroys_everything(self):
        source = make_bmp(4, 16, 24)                  # 每行 12 个样本 = 1.5 字节
        payload = b'ABCD'
        carrier = source.embed(payload)
        piece = crop(carrier, 0, 0, 4, 15)
        result = compare_payload(payload, piece.extract(4))
        self.assertFalse(result['exact'])
        self.assertGreater(result['ber'], 0.2)


class CompareTests(unittest.TestCase):
    def test_perfect_match(self):
        payload = '中文 abc'.encode('utf-8')
        result = compare_payload(payload, payload)
        self.assertTrue(result['exact'])
        self.assertEqual(result['ber'], 0.0)
        self.assertEqual(result['prefix_bytes'], len(payload))
        self.assertEqual(result['correct_bytes'], len(payload))

    def test_single_bit_error(self):
        result = compare_payload(b'\x00', b'\x01')
        self.assertEqual(result['bit_errors'], 1)
        self.assertEqual(result['bits_compared'], 8)
        self.assertAlmostEqual(result['ber'], 0.125)
        self.assertEqual(result['correct_bytes'], 0)
        self.assertEqual(result['prefix_bytes'], 0)

    def test_shifted_payload_has_zero_prefix(self):
        payload = b'ABCD'
        self.assertEqual(compare_payload(payload, payload[2:] + b'xy')['prefix_bytes'], 0)
        self.assertEqual(payload_bits(b'A')[:8], [0, 1, 0, 0, 0, 0, 0, 1])


class PlaneTests(unittest.TestCase):
    def test_round_trip_all_planes(self):
        for bpp in (8, 24):
            for plane in range(8):
                with self.subTest(bpp=bpp, plane=plane):
                    source = make_bmp(16, 16, bpp)
                    payload = b'plane-%d' % plane
                    carrier = embed_at_plane(source, payload, plane)
                    self.assertEqual(extract_at_plane(carrier, len(payload), plane), payload)

    def test_plane_changes_only_that_bit(self):
        source = make_bmp(16, 16, 24)
        carrier = embed_at_plane(source, b'\xff', 3)
        mask = 1 << 3
        for p in source.positions():
            self.assertEqual(source.value(p) & ~mask, carrier.value(p) & ~mask)

    def test_plane_validation_and_capacity(self):
        source = make_bmp(8, 8, 8)                    # 容量 8 字节
        with self.assertRaises(BMPError):
            embed_at_plane(source, b'', 8)
        with self.assertRaises(BMPError):
            embed_at_plane(source, b'123456789')
        with self.assertRaises(BMPError):
            extract_at_plane(source, 9)


class JpegCodecTests(unittest.TestCase):
    def test_round_trip_sizes_and_quality(self):
        for width, height in ((8, 8), (12, 20), (20, 12), (64, 64), (4, 2)):
            with self.subTest(size=(width, height)):
                source = smooth_image(width, height)
                jpeg, back = jpeg_roundtrip(source, 90, '420')
                self.assertEqual(jpeg[:2], b'\xff\xd8')
                self.assertEqual(jpeg[-2:], b'\xff\xd9')
                self.assertEqual((back.width, back.height), (width, height))
                # 4×2 这种极小的彩色渐变图会被 4:2:0 的色度下采样削掉大半细节，
                # 只要求尺寸正确、PSNR 不像随机噪声
                floor = 30 if width * height >= 64 else 10
                self.assertGreater(psnr(source, back), floor)

    def test_quality_and_subsampling_change_output(self):
        source = make_bmp(32, 32, 24)
        high = encode_bmp_to_jpeg(source, 95, '420')
        low = encode_bmp_to_jpeg(source, 30, '420')
        self.assertLess(len(low), len(high))
        luma_low, _ = scaled_tables(30)
        luma_high, _ = scaled_tables(95)
        self.assertGreater(luma_low[0], luma_high[0])
        # 4:4:4 不做色度下采样，同样的质量下文件更大
        self.assertGreater(len(encode_bmp_to_jpeg(source, 90, '444')),
                           len(encode_bmp_to_jpeg(source, 90, '420')))

    def test_jpeg_uses_expected_markers(self):
        jpeg = encode_bmp_to_jpeg(make_bmp(16, 16, 24), 90, '420')
        for marker in (b'\xff\xe0', b'\xff\xdb', b'\xff\xc0', b'\xff\xc4', b'\xff\xda'):
            self.assertIn(marker, jpeg)
        decoded = decode_jpeg(jpeg)
        self.assertEqual((decoded['width'], decoded['height']), (16, 16))
        self.assertEqual(len(decoded['rows']), 16)
        self.assertEqual(len(decoded['rows'][0]), 16 * 3)

    def test_only_24bit_and_valid_arguments(self):
        with self.assertRaises(BMPError):
            encode_bmp_to_jpeg(make_bmp(16, 16, 8), 90)
        with self.assertRaises(BMPError):
            encode_bmp_to_jpeg(make_bmp(16, 16, 24), 0)
        with self.assertRaises(BMPError):
            encode_bmp_to_jpeg(make_bmp(16, 16, 24), 90, '422')
        with self.assertRaises(BMPError):
            bmp_from_rows(6, 2, [b'\0' * 18] * 2)     # 宽度不是 4 的倍数

    def test_rejects_non_baseline_streams(self):
        with self.assertRaises(BMPError):
            decode_jpeg(b'not a jpeg')
        progressive = bytearray(encode_bmp_to_jpeg(make_bmp(16, 16, 24), 90))
        index = progressive.index(b'\xff\xc0')
        progressive[index + 1] = 0xC2                  # 改成 SOF2（渐进式）
        with self.assertRaises(BMPError):
            decode_jpeg(bytes(progressive))


class RobustnessPipelineTests(unittest.TestCase):
    """端到端：嵌入 → JPEG 往返 / 剪裁 → 提取 → 比对。"""

    def test_jpeg_destroys_lsb_message(self):
        source = smooth_image(64, 64)
        payload = ('有损压缩实验' * 4).encode('utf-8')
        rows = jpeg_survival(source, payload, lambda bmp, q: jpeg_roundtrip(bmp, q)[1],
                             (95, 50))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertGreater(row['ber'], 0.2)
            self.assertFalse(row['exact'])
            self.assertGreater(row['psnr_db'], 25)

    def test_bit_plane_table_reports_tradeoff(self):
        source = make_bmp(32, 32, 24)
        payload = b'payload!'
        rows = jpeg_bit_plane_table(source, payload,
                                    lambda bmp, q: jpeg_roundtrip(bmp, q)[1],
                                    90, (0, 7))
        self.assertEqual([row['plane'] for row in rows], [0, 7])
        self.assertLess(rows[1]['carrier_psnr_db'], rows[0]['carrier_psnr_db'])
        self.assertGreater(rows[1]['max_absolute_error'], 64)

    def test_crop_survival_marks_aligned_rows(self):
        source = make_bmp(64, 64, 24)
        payload = bytes(range(24))
        rows = crop_survival(source, payload, [('keep-top', 0, 0, 64, 56),
                                               ('keep-bottom', 0, 56, 64, 8),
                                               ('left', 4, 0, 60, 64)])
        keep_top, keep_bottom, left = rows
        self.assertEqual(keep_top['layout_head_samples'], 8 * 192)
        self.assertTrue(keep_top['layout_byte_aligned'])
        self.assertEqual(keep_bottom['layout_head_samples'], 0)
        self.assertTrue(keep_bottom['exact'])
        self.assertFalse(left['layout_rows_only'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

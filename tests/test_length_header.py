"""图内长度头：容量足够时带头，小图退回外部长度。"""
import unittest
from pathlib import Path
import tempfile

from bmp_lsb import BMP, BMPError
from length_header import (HEADER_BYTES, embed_with_length, extract_with_length,
                           header_capacity, needs_external_length)
from make_samples import make_bmp


class LengthHeaderTests(unittest.TestCase):
    def test_small_image_refuses_header(self):
        tiny = make_bmp(4, 2)                      # 容量 1 字节
        self.assertEqual(tiny.capacity, 1)
        self.assertTrue(needs_external_length(tiny.capacity))
        self.assertEqual(header_capacity(tiny.capacity), 0)
        with self.assertRaises(BMPError):
            embed_with_length(tiny, b'?')

    def test_capacity_math(self):
        self.assertEqual(header_capacity(5), 1)
        self.assertEqual(header_capacity(8192), 8192 - HEADER_BYTES)
        self.assertEqual(header_capacity(4), 0)

    def test_round_trip_with_header(self):
        source = make_bmp(8, 8)                    # 容量 8 字节，带头后正文上限 4
        payload = 'LSB'.encode('utf-8')
        carrier = embed_with_length(source, payload)
        self.assertEqual(extract_with_length(carrier), payload)
        # 长度头真的写进了最前面 32 个 LSB，而不是旁路记录。
        header_bits = [carrier.value(p) & 1 for p in list(carrier.positions())[:HEADER_BYTES * 8]]
        self.assertEqual(header_bits, [int(b) for b in f'{len(payload):032b}'])
        # 原图未被就地修改。
        self.assertEqual(source.data, make_bmp(8, 8).data)

    def test_overflow_and_zero_length(self):
        source = make_bmp(8, 8)
        self.assertEqual(extract_with_length(embed_with_length(source, b'')), b'')
        with self.assertRaises(BMPError):
            embed_with_length(source, b'12345')    # 5 > 8 - 4
        self.assertEqual(extract_with_length(embed_with_length(source, b'1234')), b'1234')

    def test_large_image_chinese_text_through_disk(self):
        source = make_bmp(256, 256, 8)
        payload = ('信息安全实验·LSB信息隐藏' * 60).encode('utf-8')
        self.assertGreater(len(payload), 2000)
        carrier = embed_with_length(source, payload)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'carrier.bmp'
            path.write_bytes(carrier.data)
            self.assertEqual(extract_with_length(BMP.open(path)), payload)

    def test_carrier_without_header_reports_error(self):
        source = make_bmp(256, 256, 8)
        plain = source.embed(b'?S')                # 走满容量路径，没有长度头
        with self.assertRaises(BMPError):
            extract_with_length(plain)

    def test_tiny_carrier_extract_refused(self):
        with self.assertRaises(BMPError):
            extract_with_length(make_bmp(4, 2))


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""带密钥随机间隔 LSB：密钥正确才能提取，容量与位置流均由密钥决定。"""
import struct
import unittest
from pathlib import Path
import tempfile

from bmp_lsb import BMP, BMPError
from keyed_lsb import (HEADER_BYTES, embed_keyed, extract_keyed,
                       keyed_capacity, keyed_sample_positions)
from make_samples import make_bmp

KEY = 'team-C-key'


class KeyedLSBTests(unittest.TestCase):
    def test_round_trip_all_formats_and_directions(self):
        for bpp in (8, 24):
            for top in (False, True):
                for reverse in (False, True):
                    with self.subTest(bpp=bpp, top=top, reverse=reverse):
                        source = make_bmp(32, 32, bpp, top, reverse)
                        payload = '密钥C\n随机间隔\0🙂'.encode('utf-8')
                        carrier = embed_keyed(source, payload, KEY)
                        self.assertEqual(extract_keyed(carrier, KEY), payload)
                        self.assertEqual(source.data, make_bmp(32, 32, bpp, top, reverse).data)
                        diffs = [source.value(p) ^ carrier.value(p) for p in source.positions()]
                        self.assertTrue(all(d in (0, 1) for d in diffs))

    def test_bits_laid_out_at_keyed_positions(self):
        # 独立核对：长度头 + 正文按 MSB→LSB 写在密钥位置流的对应样本上。
        source = make_bmp(16, 16, 24)
        payload = 'OK'.encode('utf-8')
        carrier = embed_keyed(source, payload, KEY)
        stream = list(keyed_sample_positions(source, KEY))
        expected = [int(bit) for byte in struct.pack('>I', len(payload)) + payload
                    for bit in f'{byte:08b}']
        actual = [carrier.value(p) & 1 for p in stream[:len(expected)]]
        self.assertEqual(actual, expected)

    def test_wrong_key_cannot_recover(self):
        source = make_bmp(32, 32, 24)
        payload = '秘密信息'.encode('utf-8')
        carrier = embed_keyed(source, payload, KEY)
        for wrong in ('team-c-key', 'Team-C-key', KEY + ' '):
            with self.subTest(wrong=wrong):
                try:
                    out = extract_keyed(carrier, wrong)
                except BMPError:
                    continue
                self.assertNotEqual(out, payload)
        # 顺序 LSB 的载体没有随机间隔布局，同样取不出有效消息。
        try:
            out = extract_keyed(source.embed(payload), KEY)
        except BMPError:
            pass
        else:
            self.assertNotEqual(out, payload)

    def test_gap_range_must_match_between_embed_and_extract(self):
        source = make_bmp(32, 32)
        carrier = embed_keyed(source, b'gap', KEY)
        try:
            out = extract_keyed(carrier, KEY, gap_range=(2, 6))
        except BMPError:
            pass
        else:
            self.assertNotEqual(out, b'gap')

    def test_gap_range_validation_and_empty_key(self):
        source = make_bmp(8, 8)
        for gap_range in ((0, 4), (4, 1), (1.5, 3)):
            with self.subTest(gap_range=gap_range):
                with self.assertRaises(BMPError):
                    embed_keyed(source, b'?', KEY, gap_range)
        with self.assertRaises(BMPError):
            embed_keyed(source, b'?', '')
        with self.assertRaises(BMPError):
            extract_keyed(source, '')

    def test_capacity_smaller_than_sequential_and_overflow_refused(self):
        source = make_bmp(64, 64, 24)
        limit = keyed_capacity(source, KEY)
        self.assertGreater(limit, HEADER_BYTES)
        self.assertLess(limit, source.capacity)          # 随机间隔必然损失容量
        self.assertEqual(extract_keyed(embed_keyed(source, b'', KEY), KEY), b'')
        self.assertEqual(extract_keyed(
            embed_keyed(source, bytes(limit - HEADER_BYTES), KEY), KEY),
            bytes(limit - HEADER_BYTES))
        with self.assertRaises(BMPError):
            embed_keyed(source, bytes(limit - HEADER_BYTES + 1), KEY)

    def test_positions_are_random_not_sequential(self):
        source = make_bmp(32, 32, 24)
        payload = 'spread'.encode('utf-8')
        carrier = embed_keyed(source, payload, KEY)
        stream = list(keyed_sample_positions(source, KEY))
        changed = [p for p in source.positions() if source.data[p] != carrier.data[p]]
        used = (HEADER_BYTES + len(payload)) * 8     # 长度头也占位置流
        # 修改过的样本必然落在密钥位置流的前 used 个位置之内。
        self.assertLessEqual(len(changed), used)
        self.assertTrue(set(changed) <= set(stream[:used]))
        # 且不是顺序 LSB 那样占据开头一段连续样本。
        self.assertNotEqual(changed, list(source.positions())[:used])

    def test_large_image_chinese_text_through_disk(self):
        source = make_bmp(256, 256, 8)
        payload = ('信息安全实验·密钥随机间隔LSB' * 40).encode('utf-8')
        self.assertGreater(len(payload), 1000)
        carrier = embed_keyed(source, payload, KEY)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'carrier.bmp'
            path.write_bytes(carrier.data)
            self.assertEqual(extract_keyed(BMP.open(path), KEY), payload)

    def test_psnr_still_high(self):
        from bmp_lsb import analyze
        source = make_bmp(128, 128, 24)
        carrier = embed_keyed(source, b'quality check', KEY)
        result = analyze(source, carrier)
        self.assertEqual(result['max_absolute_error'], 1)
        self.assertGreater(result['psnr_db'], 50)


if __name__ == '__main__':
    unittest.main(verbosity=2)

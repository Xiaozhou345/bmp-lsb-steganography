import struct
import unittest
from bmp_lsb import BMP, BMPError, analyze
from make_samples import make_bmp


class LSBTests(unittest.TestCase):
    def test_assignment_examples(self):
        for width, height, text in [(4,2,'?'), (4,4,'?S')]:
            with self.subTest(text=text):
                original = make_bmp(width, height)
                payload = text.encode('ascii')
                carrier = original.embed(payload)
                self.assertEqual(carrier.capacity, len(payload))
                self.assertEqual(BMP.parse(carrier.data).extract(len(payload)), payload)
                # 独立核对消息字节按 MSB→LSB 的位序，而非只测回环。
                actual = [carrier.value(p)&1 for p in carrier.positions()]
                expected = [int(bit) for byte in payload for bit in f'{byte:08b}']
                self.assertEqual(actual, expected)
                with self.assertRaises(BMPError):
                    original.embed(b'AbCd')

    def test_all_formats_and_directions(self):
        for bpp in (8,24):
            for top in (False,True):
                for reverse in (False,True):
                    with self.subTest(bpp=bpp, top=top, reverse=reverse):
                        a = make_bmp(16,16,bpp,top,reverse)
                        payload = '密码学\nLSB\0🙂'.encode('utf-8')
                        b = a.embed(payload)
                        self.assertEqual(b.extract(len(payload)),payload)
                        self.assertEqual(a.data[:a.offset], b.data[:b.offset])
                        diffs = [a.value(p)^b.value(p) for p in a.positions()]
                        self.assertTrue(all(d in (0,1) for d in diffs))
                        used = len(payload)*8
                        positions = list(a.positions())
                        self.assertTrue(all(a.data[p]==b.data[p] for p in positions[used:]))
                        self.assertLessEqual(analyze(a,b)['max_absolute_error'],1)

    def test_capacity_and_empty(self):
        for bpp in (8,24):
            a = make_bmp(512,512,bpp)
            self.assertEqual(a.capacity, 32768 if bpp==8 else 98304)
            payload = bytes(i%256 for i in range(a.capacity))
            self.assertEqual(a.embed(payload).extract(a.capacity),payload)
            with self.assertRaises(BMPError): a.embed(payload+b'x')
            self.assertEqual(a.embed(b'').data,a.data)
            self.assertEqual(a.extract(0),b'')
            self.assertIsNone(analyze(a,a)['psnr_db'])
            for length in (-1, a.capacity+1, 1.5):
                with self.assertRaises(BMPError): a.extract(length)

    def test_manual_bmp_and_display_orientation(self):
        for bpp in (8,24):
            bottom = make_bmp(4,4,bpp)
            top = make_bmp(4,4,bpp,True)
            self.assertEqual(bottom.ppm(),top.ppm())
            self.assertEqual(len(bottom.ppm().split(b'\n',3)[3]),4*4*3)
        preview = make_bmp(512,512).ppm(450,300)
        self.assertTrue(preview.startswith(b'P6\n256 256\n255\n'))
        self.assertEqual(len(preview.split(b'\n',3)[3]),256*256*3)

    def test_known_pixel_example(self):
        a = make_bmp(4,2)
        data = bytearray(a.data)
        data[a.offset:a.offset+8] = bytes((200,151,73,187,200,151,73,187))
        a = BMP.parse(data)
        b = a.embed(b'\x90')  # 前四个消息位为文档示例的 1001
        self.assertEqual(list(b.data[b.offset:b.offset+4]),[201,150,72,187])

    def test_headers_gaps_and_trailing_bytes_preserved(self):
        a = make_bmp(4,4)
        raw = bytearray(a.data[:a.offset]+b'GAP!'+a.data[a.offset:]+b'TAIL')
        struct.pack_into('<I',raw,2,len(raw))
        struct.pack_into('<I',raw,10,a.offset+4)
        a = BMP.parse(raw)
        b = a.embed(b'?S')
        self.assertEqual(a.data[:a.offset],b.data[:b.offset])
        self.assertEqual(b.data[-4:],b'TAIL')

    def test_invalid_inputs(self):
        a = make_bmp(4,4)
        for offset, fmt, value in [(0,'2s',b'XX'),(18,'i',3),(22,'i',0),
                                   (18,'i',516),(26,'H',2),(28,'H',32),
                                   (30,'I',1),(10,'I',20),(2,'I',1),(46,'I',2)]:
            with self.subTest(offset=offset,value=value):
                raw=bytearray(a.data)
                struct.pack_into('<'+fmt,raw,offset,value)
                with self.assertRaises(BMPError): BMP.parse(raw)
        for raw in (b'',a.data[:-1]):
            with self.assertRaises(BMPError): BMP.parse(raw)
        raw=bytearray(a.data); raw[54]=100
        with self.assertRaises(BMPError): BMP.parse(raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)

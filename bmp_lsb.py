"""手工解析 BMP 的单比特 LSB 隐写。仅使用 Python 标准库。

校验策略针对教师素材做了两处放宽，理由见 docs/接口约定.md：

1. ``biSizeImage``（DIB 头偏移 34）在 BI_RGB 下不是必需字段，实测教师提供的
   8 位灰度小图统一写成 ``宽 × 高 × 3``（按每像素 3 字节误算），因此接受
   ``0``、``stride × 高``、``宽 × 高 × 3`` 三种取值，像素区实际边界一律以
   ``bfOffBits + stride × 高`` 为准。
2. ``bfSize``（文件头偏移 2）允许比文件长度少若干填充字节，实测教师素材最多
   少 2 字节；尾随字节原样保留，不参与嵌入也不参与提取。
"""
from dataclasses import dataclass
import math
from pathlib import Path
import struct


class BMPError(ValueError):
    """输入文件或操作不满足作业约束。"""


@dataclass(frozen=True)
class BMP:
    data: bytes
    width: int
    signed_height: int
    bpp: int
    offset: int
    stride: int
    palette: tuple

    @classmethod
    def parse(cls, data):
        data = bytes(data)
        if len(data) < 54 or data[:2] != b'BM':
            raise BMPError('不是完整的 Windows BMP 文件。')
        size, = struct.unpack_from('<I', data, 2)
        offset, dib = struct.unpack_from('<II', data, 10)
        if dib not in (40, 52, 56, 108, 124) or len(data) < 14 + dib:
            raise BMPError('不支持或不完整的 DIB 信息头。')
        width, height, planes, bpp, compression, image_size = struct.unpack_from('<iiHHII', data, 18)
        if not (0 < width <= 512 and 0 < abs(height) <= 512) or width % 4:
            raise BMPError('尺寸须不超过 512×512，宽度须为 4 的倍数。')
        if planes != 1 or bpp not in (8, 24) or compression != 0:
            raise BMPError('只支持未压缩 BI_RGB 的 8 位 256 灰度图或 24 位真彩图。')
        stride = ((width * bpp + 31) // 32) * 4
        needed = stride * abs(height)
        if offset < 14 + dib or offset + needed > len(data):
            raise BMPError('像素偏移非法或像素数据被截断。')
        # bfSize 允许比实际文件短（写入器补的尾部填充），但不得短于像素区末端。
        if not offset + needed <= size <= len(data):
            raise BMPError('BMP 文件大小或像素数据大小字段不正确。')
        # biSizeImage 接受 0、真实像素区大小，以及被写成“每像素 3 字节”的情况。
        if image_size not in (0, needed, width * height * 3):
            raise BMPError('BMP 文件大小或像素数据大小字段不正确。')
        palette = ()
        if bpp == 8:
            colors, = struct.unpack_from('<I', data, 46)
            start = 14 + dib
            if colors not in (0, 256) or offset < start + 1024:
                raise BMPError('8 位图必须具有完整的 256 色灰度调色板。')
            values = []
            for i in range(256):
                b, g, r, _ = data[start + 4*i:start + 4*i + 4]
                if b != g or g != r:
                    raise BMPError('8 位索引彩色图不是 256 灰度图。')
                values.append(r)
            if len(set(values)) != 256:
                raise BMPError('调色板必须包含 0～255 全部 256 个灰度值。')
            palette = tuple(values)
        return cls(data, width, height, bpp, offset, stride, palette)

    @classmethod
    def open(cls, path):
        return cls.parse(Path(path).read_bytes())

    @property
    def height(self):
        return abs(self.signed_height)

    @property
    def sample_count(self):
        return self.width * self.height * (self.bpp // 8)

    @property
    def capacity(self):
        return self.sample_count // 8

    @property
    def pixel_end(self):
        """像素区最后一个字节之后的位置，由 bfOffBits 与行距推算。"""
        return self.offset + self.stride * self.height

    @property
    def trailing_bytes(self):
        """文件尾部不参与像素读取的多余字节数（教师素材最多 2 字节）。"""
        return len(self.data) - self.pixel_end

    def positions(self):
        """按文件存储顺序逐行遍历；24 位图为 B、G、R；不使用行填充。"""
        for row in range(self.height):
            start = self.offset + row * self.stride
            yield from range(start, start + self.width * (self.bpp // 8))

    def value(self, position):
        sample = self.data[position]
        return self.palette[sample] if self.bpp == 8 else sample

    def embed(self, payload):
        payload = bytes(payload)
        if len(payload) > self.capacity:
            raise BMPError(f'信息为 {len(payload)} 字节，超过最大容量 {self.capacity} 字节。')
        result = bytearray(self.data)
        inverse = {v: i for i, v in enumerate(self.palette)}
        positions = iter(self.positions())
        for byte in payload:
            for shift in range(7, -1, -1):
                pos = next(positions)
                value = (self.value(pos) & 0xFE) | ((byte >> shift) & 1)
                result[pos] = inverse[value] if self.bpp == 8 else value
        return BMP.parse(result)

    def extract(self, length):
        if not isinstance(length, int) or not 0 <= length <= self.capacity:
            raise BMPError(f'提取长度须为 0～{self.capacity} 的整数字节数。')
        positions = iter(self.positions())
        result = bytearray()
        for _ in range(length):
            byte = 0
            for _ in range(8):
                byte = (byte << 1) | (self.value(next(positions)) & 1)
            result.append(byte)
        return bytes(result)

    def rgb_rows(self):
        """手工解码，返回从上到下的 RGB 行，用于显示及质量分析。"""
        for y in range(self.height):
            row = y if self.signed_height < 0 else self.height - 1 - y
            start = self.offset + row * self.stride
            result = bytearray()
            for x in range(self.width):
                if self.bpp == 8:
                    v = self.palette[self.data[start + x]]
                    result.extend((v, v, v))
                else:
                    p = start + 3*x
                    b, g, r = self.data[p:p+3]
                    result.extend((r, g, b))
            yield bytes(result)

    def ppm(self, max_width=None, max_height=None):
        # PPM 只是自行生成的显示数据；未使用任何图片解码/处理库。
        step = max(1, math.ceil(self.width / max_width) if max_width else 1,
                   math.ceil(self.height / max_height) if max_height else 1)
        width = (self.width + step - 1) // step
        height = (self.height + step - 1) // step
        pixels = bytearray()
        for y, row in enumerate(self.rgb_rows()):
            if y % step == 0:
                for x in range(0, self.width, step):
                    pixels.extend(row[3*x:3*x+3])
        return f'P6\n{width} {height}\n255\n'.encode('ascii') + pixels

    def info(self):
        return {'width': self.width, 'height': self.height, 'bpp': self.bpp,
                'type': '256 灰度图' if self.bpp == 8 else '24 位真彩图',
                'capacity_bytes': self.capacity, 'raw_capacity_bits': self.sample_count,
                'pixel_offset': self.offset, 'row_stride': self.stride,
                'trailing_bytes': self.trailing_bytes,
                'storage': '从上到下' if self.signed_height < 0 else '从下到上'}


def analyze(original, carrier):
    if (original.width, original.signed_height, original.bpp, original.palette) != (
            carrier.width, carrier.signed_height, carrier.bpp, carrier.palette):
        raise BMPError('分析要求两幅图的尺寸、方向、位深及调色板一致。')
    diffs = [carrier.value(q) - original.value(p)
             for p, q in zip(original.positions(), carrier.positions())]
    mse = sum(d*d for d in diffs) / len(diffs)
    return {'sample_count': len(diffs), 'changed_samples': sum(d != 0 for d in diffs),
            'change_ratio': sum(d != 0 for d in diffs) / len(diffs),
            'max_absolute_error': max(map(abs, diffs)), 'mse': mse,
            'psnr_db': None if mse == 0 else 10 * math.log10(255**2 / mse)}

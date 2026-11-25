"""基线 JPEG 编解码器（纯标准库），用于复现作业第 24 页的"画图另存 JPEG"。

作业原文要求手工操作：24 位图嵌入 → 在画图中另存为 JPEG → 再另存为 24 位
BMP → 提取 → 比对。手工步骤难以批量重复，本工具用**标准库**实现基线
JPEG（SOF0、8 位量化、标准霍夫曼表、4:2:0 或 4:4:4）的编码与解码，把这一步
自动化，产物与画图另存的 BMP 等价，随时可用 ``BMP.parse`` 读回。

它**不进入**隐写路径：``bmp_lsb.py``、``robustness.py`` 都不 import 它，
只有实验脚本和测试用它。因此"不得使用图片处理库"这一条不受影响——这里
没有第三方库，DCT、量化、霍夫曼编码与解码全部是本文件里的 Python 代码。

局限（报告中如实写明）：

- 只解码**基线** JPEG；遇到渐进式（SOF2）等直接报错，不做静默降级；
- 色度上采样用最近邻，画图使用的插值略有不同，因此本工具算出的 PSNR 与
  画图结果可能差零点几 dB；这不影响"LSB 在 JPEG 后全部失效"的结论；
- 编码质量为 IJG 标准缩放（1～100），默认 90 与画图的默认质量相当。

命令行：

    python tools/jpeg_roundtrip.py --input carrier.bmp --jpeg out.jpg \\
        --bmp back.bmp --quality 90
    python tools/jpeg_roundtrip.py --decode out.jpg --bmp back.bmp
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bmp_lsb import BMP, BMPError  # noqa: E402

# 自然顺序（行优先）下标，按之字形扫描排列；值 = 该系数在 8×8 块中的自然下标
ZIGZAG = (
    0, 1, 8, 16, 9, 2, 3, 10,
    17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
)

LUMA_QUANT = (
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
)

CHROMA_QUANT = (
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
)

# 标准霍夫曼表（JPEG 规范附录 K）
DC_LUMA_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)
DC_LUMA_VALS = tuple(range(12))
DC_CHROMA_BITS = (0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)
DC_CHROMA_VALS = tuple(range(12))

AC_LUMA_BITS = (0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D)
AC_LUMA_VALS = (
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12,
    0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
    0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
    0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0,
    0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0A, 0x16,
    0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
    0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
    0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
    0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
    0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98,
    0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7,
    0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
    0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5,
    0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4,
    0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA,
    0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8,
    0xF9, 0xFA,
)

AC_CHROMA_BITS = (0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77)
AC_CHROMA_VALS = (
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21,
    0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
    0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
    0xA1, 0xB1, 0xC1, 0x09, 0x23, 0x33, 0x52, 0xF0,
    0x15, 0x62, 0x72, 0xD1, 0x0A, 0x16, 0x24, 0x34,
    0xE1, 0x25, 0xF1, 0x17, 0x18, 0x19, 0x1A, 0x26,
    0x27, 0x28, 0x29, 0x2A, 0x35, 0x36, 0x37, 0x38,
    0x39, 0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
    0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
    0x69, 0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78,
    0x79, 0x7A, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
    0x88, 0x89, 0x8A, 0x92, 0x93, 0x94, 0x95, 0x96,
    0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5,
    0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4,
    0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3,
    0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD2,
    0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA,
    0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9,
    0xEA, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8,
    0xF9, 0xFA,
)

_COS = tuple(tuple(0.5 * (1 / math.sqrt(2) if u == 0 else 1.0) *
                   math.cos((2 * x + 1) * u * math.pi / 16) for x in range(8))
             for u in range(8))


def scaled_tables(quality):
    """IJG 质量缩放。质量 50 对应标准表原值；1 最差、100 最好（全 1）。"""
    if not isinstance(quality, int) or not 1 <= quality <= 100:
        raise BMPError('JPEG 质量须为 1～100 的整数。')
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality

    def apply(base):
        return tuple(max(1, min(255, (v * scale + 50) // 100)) for v in base)

    return apply(LUMA_QUANT), apply(CHROMA_QUANT)


def _fdct(block):
    """8×8 浮点正变换，block 为自然顺序的 64 个浮点数。"""
    tmp = [[0.0] * 8 for _ in range(8)]
    for y in range(8):
        row = block[y * 8:y * 8 + 8]
        for u in range(8):
            cu = _COS[u]
            tmp[y][u] = sum(row[x] * cu[x] for x in range(8))
    out = [0.0] * 64
    for u in range(8):
        for v in range(8):
            cv = _COS[v]
            out[v * 8 + u] = sum(tmp[y][u] * cv[y] for y in range(8))
    return out


def _idct(coef):
    """8×8 浮点逆变换，返回值仍是未加 128 的浮点数。"""
    tmp = [[0.0] * 8 for _ in range(8)]
    for v in range(8):
        cv = _COS[v]
        row = coef[v * 8:v * 8 + 8]
        for x in range(8):
            tmp[v][x] = sum(row[u] * _COS[u][x] for u in range(8))
    out = [0.0] * 64
    for y in range(8):
        for x in range(8):
            out[y * 8 + x] = sum(tmp[v][x] * _COS[v][y] for v in range(8))
    return out


class _BitWriter:
    def __init__(self):
        self.buffer = bytearray()
        self.acc = 0
        self.count = 0

    def write(self, value, length):
        for shift in range(length - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> shift) & 1)
            self.count += 1
            if self.count == 8:
                self.buffer.append(self.acc)
                if self.acc == 0xFF:            # 字节填充，避免误判为标记
                    self.buffer.append(0x00)
                self.acc = 0
                self.count = 0

    def flush(self):
        if self.count:
            self.write((1 << (8 - self.count)) - 1, 8 - self.count)
        return bytes(self.buffer)


def _huffman_codes(bits, values):
    """按 JPEG 规范由码长分布生成 (值 -> (码字, 码长)) 表。"""
    table = {}
    code = 0
    index = 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            table[values[index]] = (code, length)
            code += 1
            index += 1
        code <<= 1
    return table


def _category(value):
    return abs(value).bit_length()


def _amplitude_bits(value, size):
    return value if value >= 0 else value + (1 << size) - 1


def _write_block(writer, block, qtable, dc_table, ac_table, previous_dc):
    """量化 + 之字形 + 霍夫曼编码一个块，返回新的 DC 预测值。"""
    quantized = [int(round(block[ZIGZAG[i]] / qtable[ZIGZAG[i]])) for i in range(64)]
    quantized = [max(-1023, min(1023, value)) for value in quantized]
    diff = quantized[0] - previous_dc
    diff = max(-2047, min(2047, diff))
    size = _category(diff)
    code, length = dc_table[size]
    writer.write(code, length)
    if size:
        writer.write(_amplitude_bits(diff, size), size)
    run = 0
    for k in range(1, 64):
        value = quantized[k]
        if value == 0:
            run += 1
            continue
        while run > 15:
            code, length = ac_table[0xF0]
            writer.write(code, length)
            run -= 16
        size = _category(value)
        code, length = ac_table[(run << 4) | size]
        writer.write(code, length)
        writer.write(_amplitude_bits(value, size), size)
        run = 0
    if run:
        code, length = ac_table[0x00]
        writer.write(code, length)
    return quantized[0]


def _marker(code, payload=b''):
    return bytes((0xFF, code)) + struct.pack('>H', len(payload) + 2) + payload


def _to_ycbcr(rows, width, height):
    y_plane = [[0.0] * width for _ in range(height)]
    cb_plane = [[0.0] * width for _ in range(height)]
    cr_plane = [[0.0] * width for _ in range(height)]
    for row in range(height):
        line = rows[row]
        for x in range(width):
            r, g, b = line[3 * x], line[3 * x + 1], line[3 * x + 2]
            y_plane[row][x] = 0.299 * r + 0.587 * g + 0.114 * b
            cb_plane[row][x] = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
            cr_plane[row][x] = 0.5 * r - 0.418688 * g - 0.081312 * b + 128
    return y_plane, cb_plane, cr_plane


def _downsample(plane, width, height):
    """2×2 盒式平均，边缘用复制补齐；返回 (ceil(w/2), ceil(h/2)) 的平面。"""
    out_w, out_h = (width + 1) // 2, (height + 1) // 2
    out = [[0.0] * out_w for _ in range(out_h)]
    for y in range(out_h):
        y0, y1 = 2 * y, min(2 * y + 1, height - 1)
        for x in range(out_w):
            x0, x1 = 2 * x, min(2 * x + 1, width - 1)
            out[y][x] = (plane[y0][x0] + plane[y0][x1] +
                         plane[y1][x0] + plane[y1][x1]) / 4
    return out


def _pad(plane, width, height):
    out = [row + [row[-1]] * (width - len(row)) for row in plane]
    while len(out) < height:
        out.append(list(out[-1]))
    return out


def _block(plane, width, bx, by):
    block = []
    for y in range(8):
        row = plane[by * 8 + y]
        for x in range(8):
            block.append(row[bx * 8 + x] - 128)
    return block


def encode_bmp_to_jpeg(bmp, quality=90, subsampling='420'):
    """把 24 位 BMP 编码为基线 JPEG，返回 JPEG 字节串。"""
    if bmp.bpp != 24:
        raise BMPError('JPEG 往返实验要求 24 位真彩图。')
    if subsampling not in ('420', '444'):
        raise BMPError("色度采样只支持 '420' 或 '444'。")
    luma_q, chroma_q = scaled_tables(quality)
    width, height = bmp.width, bmp.height
    rows = list(bmp.rgb_rows())
    y_plane, cb_plane, cr_plane = _to_ycbcr(rows, width, height)

    if subsampling == '420':
        comps = [('Y', 2, 2, y_plane, width, height, 0),
                 ('Cb', 1, 1, _downsample(cb_plane, width, height),
                  (width + 1) // 2, (height + 1) // 2, 1),
                 ('Cr', 1, 1, _downsample(cr_plane, width, height),
                  (width + 1) // 2, (height + 1) // 2, 1)]
        max_h = max_v = 2
    else:
        comps = [('Y', 1, 1, y_plane, width, height, 0),
                 ('Cb', 1, 1, cb_plane, width, height, 1),
                 ('Cr', 1, 1, cr_plane, width, height, 1)]
        max_h = max_v = 1

    mcu_w, mcu_h = 8 * max_h, 8 * max_v
    mcus_x = (width + mcu_w - 1) // mcu_w
    mcus_y = (height + mcu_h - 1) // mcu_h
    padded = []
    for name, hs, vs, plane, pw, ph, table in comps:
        padded.append((plane, _pad(plane, mcus_x * hs * 8, mcus_y * vs * 8),
                       hs, vs, table))

    dc_luma = _huffman_codes(DC_LUMA_BITS, DC_LUMA_VALS)
    ac_luma = _huffman_codes(AC_LUMA_BITS, AC_LUMA_VALS)
    dc_chroma = _huffman_codes(DC_CHROMA_BITS, DC_CHROMA_VALS)
    ac_chroma = _huffman_codes(AC_CHROMA_BITS, AC_CHROMA_VALS)

    writer = _BitWriter()
    predictors = [0, 0, 0]
    for my in range(mcus_y):
        for mx in range(mcus_x):
            for index, (_, plane, hs, vs, table) in enumerate(padded):
                if table == 0:
                    dc_table, ac_table, qtable = dc_luma, ac_luma, luma_q
                else:
                    dc_table, ac_table, qtable = dc_chroma, ac_chroma, chroma_q
                for dy in range(vs):
                    for dx in range(hs):
                        block = _block(plane, mcus_x * hs * 8, mx * hs + dx, my * vs + dy)
                        predictors[index] = _write_block(
                            writer, _fdct(block), qtable, dc_table, ac_table,
                            predictors[index])

    header = bytearray(b'\xFF\xD8')                                    # SOI
    header += _marker(0xE0, b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')  # APP0
    header += _marker(0xDB, bytes([0x00]) + bytes(luma_q[i] for i in ZIGZAG) +
                      bytes([0x01]) + bytes(chroma_q[i] for i in ZIGZAG))     # DQT
    frame = struct.pack('>BHHB', 8, height, width, len(comps))
    for index, (name, hs, vs, _, _, _, table) in enumerate(comps):
        frame += bytes((index + 1, (hs << 4) | vs, table))
    header += _marker(0xC0, frame)                                      # SOF0
    dht = bytearray()
    for table_class, table_id, bits, values in (
            (0, 0, DC_LUMA_BITS, DC_LUMA_VALS), (1, 0, AC_LUMA_BITS, AC_LUMA_VALS),
            (0, 1, DC_CHROMA_BITS, DC_CHROMA_VALS), (1, 1, AC_CHROMA_BITS, AC_CHROMA_VALS)):
        dht += bytes([(table_class << 4) | table_id]) + bytes(bits) + bytes(values)
    header += _marker(0xC4, bytes(dht))                                 # DHT
    scan = struct.pack('>B', len(comps))
    for index in range(len(comps)):
        scan += bytes((index + 1, 0x00 if index == 0 else 0x11))
    scan += bytes((0, 63, 0))                                           # Ss, Se, Ah/Al
    header += _marker(0xDA, scan)                                       # SOS
    return bytes(header) + writer.flush() + b'\xFF\xD9'                 # EOI


class _BitReader:
    """熵编码段读取器：处理 0xFF00 填充，遇到真标记即停止。"""

    def __init__(self, data, pos):
        self.data = data
        self.pos = pos
        self.acc = 0
        self.count = 0
        self.finished = False

    def _byte(self):
        if self.pos >= len(self.data):
            self.finished = True
            return 0
        value = self.data[self.pos]
        self.pos += 1
        if value == 0xFF:
            following = self.data[self.pos] if self.pos < len(self.data) else 0
            if following == 0x00:
                self.pos += 1
            elif 0xD0 <= following <= 0xD7:      # 重启标记不属于熵编码数据
                self.pos += 1
                self.finished = True
                return 0
            else:
                self.finished = True
                return 0
        return value

    def bit(self):
        if self.count == 0:
            self.acc = self._byte()
            self.count = 8
        self.count -= 1
        return (self.acc >> self.count) & 1

    def bits(self, length):
        value = 0
        for _ in range(length):
            value = (value << 1) | self.bit()
        return value

    def receive_extend(self, size):
        if size == 0:
            return 0
        value = self.bits(size)
        return value if value >= (1 << (size - 1)) else value - ((1 << size) - 1)

    def reset(self):
        self.acc = 0
        self.count = 0
        self.finished = False

    def align(self):
        self.count = 0


def _build_decode_table(bits, values):
    table = {}
    code = 0
    index = 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            table[(length, code)] = values[index]
            code += 1
            index += 1
        code <<= 1
    return table


def _decode_symbol(reader, table):
    code = 0
    for length in range(1, 17):
        code = (code << 1) | reader.bit()
        value = table.get((length, code))
        if value is not None:
            return value
    raise BMPError('JPEG 霍夫曼码无效或数据被截断。')


def _decode_block(reader, dc_table, ac_table, qtable, previous_dc):
    size = _decode_symbol(reader, dc_table)
    diff = reader.receive_extend(size)
    dc = previous_dc + diff
    coef = [0.0] * 64
    coef[0] = dc * qtable[0]
    k = 1
    while k < 64:
        symbol = _decode_symbol(reader, ac_table)
        run, size = symbol >> 4, symbol & 0x0F
        if size == 0:
            if run == 15:
                k += 16
                continue
            break
        k += run
        if k >= 64:
            break
        value = reader.receive_extend(size)
        position = ZIGZAG[k]
        coef[position] = value * qtable[position]
        k += 1
    return _idct(coef), dc


def decode_jpeg(jpeg):
    """解码基线 JPEG，返回 {'width','height','rows'}，rows 为自上而下的 RGB 行。"""
    data = bytes(jpeg)
    if len(data) < 4 or data[:2] != b'\xFF\xD8':
        raise BMPError('不是 JPEG 文件（缺少 SOI）。')
    pos = 2
    quant = {}
    huffman = {}
    frame = None
    restart_interval = 0
    while pos < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        while pos + 1 < len(data) and data[pos + 1] == 0xFF:
            pos += 1
        if pos + 1 >= len(data):
            break
        marker = data[pos + 1]
        pos += 2
        if marker == 0xD9:
            break
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(data):
            raise BMPError('JPEG 段被截断。')
        length = struct.unpack_from('>H', data, pos)[0]
        if length < 2 or pos + length > len(data):
            raise BMPError('JPEG 段长度非法。')
        segment = data[pos + 2:pos + length]
        pos += length
        if marker == 0xDB:
            offset = 0
            while offset < len(segment):
                info = segment[offset]
                precision, table_id = info >> 4, info & 0x0F
                offset += 1
                count = 64 * (2 if precision else 1)
                raw = segment[offset:offset + count]
                offset += count
                values = struct.unpack(f'>{64}H', raw) if precision else tuple(raw)
                table = [0] * 64
                for i in range(64):
                    table[ZIGZAG[i]] = values[i]
                quant[table_id] = table
        elif marker == 0xC4:
            offset = 0
            while offset < len(segment):
                info = segment[offset]
                table_class, table_id = info >> 4, info & 0x0F
                bits = tuple(segment[offset + 1:offset + 17])
                count = sum(bits)
                values = tuple(segment[offset + 17:offset + 17 + count])
                offset += 17 + count
                huffman[(table_class, table_id)] = _build_decode_table(bits, values)
        elif marker == 0xC0:
            precision, height, width, count = struct.unpack_from('>BHHB', segment, 0)
            if precision != 8:
                raise BMPError('只支持 8 位样本的 JPEG。')
            comps = []
            offset = 6
            for _ in range(count):
                comp_id, sampling, table_id = segment[offset:offset + 3]
                comps.append({'id': comp_id, 'h': sampling >> 4, 'v': sampling & 0x0F,
                              'tq': table_id})
                offset += 3
            frame = {'width': width, 'height': height, 'comps': comps}
        elif marker == 0xC2:
            raise BMPError('只支持基线 JPEG（SOF0），遇到渐进式 JPEG（SOF2）。')
        elif marker == 0xC1:
            raise BMPError('只支持基线 JPEG（SOF0），遇到扩展顺序 JPEG（SOF1）。')
        elif marker == 0xC3:
            raise BMPError('不支持无损 JPEG（SOF3）。')
        elif marker == 0xDD:
            restart_interval = struct.unpack('>H', segment[:2])[0]
        elif marker == 0xDA:
            if frame is None:
                raise BMPError('JPEG 缺少 SOF 帧头。')
            count = segment[0]
            mapping = {}
            offset = 1
            for _ in range(count):
                comp_id, tables = segment[offset], segment[offset + 1]
                mapping[comp_id] = (tables >> 4, tables & 0x0F)
                offset += 2
            return _decode_scan(frame, mapping, quant, huffman, restart_interval, data, pos)
        elif marker in (0x01,):
            continue
    raise BMPError('JPEG 中未找到扫描数据。')


def _decode_scan(frame, mapping, quant, huffman, restart_interval, data, pos):
    width, height = frame['width'], frame['height']
    comps = frame['comps']
    max_h = max(comp['h'] for comp in comps)
    max_v = max(comp['v'] for comp in comps)
    mcu_w, mcu_h = 8 * max_h, 8 * max_v
    mcus_x = (width + mcu_w - 1) // mcu_w
    mcus_y = (height + mcu_h - 1) // mcu_h
    planes = []
    for comp in comps:
        pw, ph = mcus_x * comp['h'] * 8, mcus_y * comp['v'] * 8
        planes.append([[0.0] * pw for _ in range(ph)])
    predictors = [0] * len(comps)
    reader = _BitReader(data, pos)
    for my in range(mcus_y):
        for mx in range(mcus_x):
            if restart_interval and (my * mcus_x + mx) % restart_interval == 0:
                reader.align()
                reader.reset()
                predictors = [0] * len(comps)
            for index, comp in enumerate(comps):
                dc_id, ac_id = mapping[comp['id']]
                dc_table = huffman[(0, dc_id)]
                ac_table = huffman[(1, ac_id)]
                qtable = quant[comp['tq']]
                for dy in range(comp['v']):
                    for dx in range(comp['h']):
                        block, predictors[index] = _decode_block(
                            reader, dc_table, ac_table, qtable, predictors[index])
                        base_y = (my * comp['v'] + dy) * 8
                        base_x = (mx * comp['h'] + dx) * 8
                        plane = planes[index]
                        for y in range(8):
                            row = plane[base_y + y]
                            for x in range(8):
                                row[base_x + x] = block[y * 8 + x] + 128
    if len(comps) != 3:
        raise BMPError('只支持 3 分量（YCbCr）JPEG。')
    full = [_upsample(planes[i], width, height,
                      max_h // comps[i]['h'], max_v // comps[i]['v'])
            for i in range(3)]
    rows = []
    for y in range(height):
        line = bytearray()
        luma_row, cb_row, cr_row = full[0][y], full[1][y], full[2][y]
        for x in range(width):
            yy = luma_row[x]
            cb, cr = cb_row[x] - 128, cr_row[x] - 128
            r = yy + 1.402 * cr
            g = yy - 0.344136 * cb - 0.714136 * cr
            b = yy + 1.772 * cb
            for channel in (r, g, b):
                line.append(max(0, min(255, int(round(channel)))))
        rows.append(bytes(line))
    return {'width': width, 'height': height, 'rows': rows}


def _upsample(plane, width, height, h_factor, v_factor):
    """色度上采样：2× 用 libjpeg 同款的 3:1 三角插值，其余按最近邻。

    2× 情形下每个色度样本覆盖 2×2 像素、中心落在四个像素的中心点，因此
    像素与样本中心相距 0.5 / 1.5 个像素，权重为 3/4 与 1/4；边缘复制。
    """
    plane_h, plane_w = len(plane), len(plane[0])
    if v_factor == 2:
        vertical = []
        for y in range(height):
            j = y // 2
            neighbour = max(j - 1, 0) if y % 2 == 0 else min(j + 1, plane_h - 1)
            row, other = plane[j], plane[neighbour]
            vertical.append([0.75 * row[x] + 0.25 * other[x] for x in range(plane_w)])
    else:
        vertical = [row[:plane_w] for row in plane[:height]]
    if h_factor == 2:
        out = []
        for row in vertical:
            line = []
            for x in range(width):
                i = x // 2
                neighbour = max(i - 1, 0) if x % 2 == 0 else min(i + 1, plane_w - 1)
                line.append(0.75 * row[i] + 0.25 * row[neighbour])
            out.append(line)
        return out
    return [row[:width] for row in vertical]


def bmp_from_rows(width, height, rows):
    """把自上而下的 RGB 行写成 24 位 BMP 字节串（正高度，自下而上存储）。"""
    if width % 4 or width > 512 or height > 512:
        raise BMPError('JPEG 解码结果须满足宽度 4 倍数且不超过 512×512。')
    stride = (width * 3 + 3) // 4 * 4
    pixels = bytearray()
    for row in reversed(rows):
        line = bytes(row)
        if len(line) != width * 3:
            raise BMPError('解码行长度与宽度不符。')
        # BMP 像素区按 B、G、R 存放，解码结果是 R、G、B
        swapped = bytearray(len(line))
        swapped[0::3] = line[2::3]
        swapped[1::3] = line[1::3]
        swapped[2::3] = line[0::3]
        pixels += bytes(swapped) + b'\0' * (stride - len(line))
    header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
    dib = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels),
                      2835, 2835, 0, 0)
    return header + dib + bytes(pixels)


def jpeg_roundtrip(bmp, quality=90, subsampling='420'):
    """完整往返：BMP → JPEG → 解码 → 新 BMP 对象；返回 (jpeg 字节, BMP)。"""
    jpeg = encode_bmp_to_jpeg(bmp, quality, subsampling)
    decoded = decode_jpeg(jpeg)
    return jpeg, BMP.parse(bmp_from_rows(decoded['width'], decoded['height'],
                                         decoded['rows']))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='纯标准库 JPEG 往返（复现画图另存步骤）')
    parser.add_argument('--input', help='输入的 24 位 BMP')
    parser.add_argument('--decode', help='输入的 JPEG（解码为 BMP）')
    parser.add_argument('--jpeg', help='输出 JPEG 路径')
    parser.add_argument('--bmp', help='输出 BMP 路径')
    parser.add_argument('--quality', type=int, default=90)
    parser.add_argument('--subsampling', choices=('420', '444'), default='420')
    args = parser.parse_args(argv)
    if args.input:
        source = BMP.open(args.input)
        jpeg = encode_bmp_to_jpeg(source, args.quality, args.subsampling)
        if args.jpeg:
            Path(args.jpeg).write_bytes(jpeg)
            print(f'已写出 JPEG：{args.jpeg}（{len(jpeg)} 字节，质量 {args.quality}，'
                  f'{args.subsampling}）')
        if args.bmp:
            decoded = decode_jpeg(jpeg)
            Path(args.bmp).write_bytes(bmp_from_rows(
                decoded['width'], decoded['height'], decoded['rows']))
            print(f'已写出解码后的 BMP：{args.bmp}')
        return 0
    if args.decode:
        decoded = decode_jpeg(Path(args.decode).read_bytes())
        target = args.bmp or 'decoded.bmp'
        Path(target).write_bytes(bmp_from_rows(decoded['width'], decoded['height'],
                                               decoded['rows']))
        print(f'已解码 {args.decode} → {target}（{decoded["width"]}×{decoded["height"]}）')
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())

"""带密钥的随机间隔 LSB 嵌入（附加④，PDF 第 25 页）。仅使用 Python 标准库。

设计（供报告第 7 章引用）：

1. 密钥派生：任意非空字符串密钥经 SHA-256 摘要转成大整数，作为 Mersenne
   Twister 伪随机数生成器（``random.Random``）的种子。教学场景足够；报告可
   指出真实方案应改用 CSPRNG/HMAC 派生。
2. 随机间隔位置流：以种子初始化生成器后，从图首出发，每次以 ``randint(lo, hi)``
   的随机步长跳到下一个嵌入位置（首个位置本身也由第一步长决定）。步长序列由
   密钥唯一决定，因此嵌入方与提取方用同一密钥即得到同一条位置流；密钥错误则
   位置流完全不同，无法定位真正的嵌入位。默认间隔 (1, 4)，平均 2.5 个样本
   承载 1 bit，容量约为顺序 LSB 的 40%，且随密钥略有波动。
3. 图内长度头：与 ``length_header.py`` 一致，消息前写 4 字节大端 uint32 长度，
   但这 32 bit 同样写进**随机位置**而非图首，长度信息本身也被隐藏。
4. 容量：随机间隔必然跳过部分样本，容量低于顺序 LSB。``keyed_capacity``
   沿位置流数一遍即可精确得出（流是确定性的），含长度头。
5. 写入复用 ``BMP`` 的语义：逐样本用 ``positions()``/``value(pos)`` 遍历与
   读值，8 位图按调色板灰度值反查索引写入（与 ``bmp_lsb.embed`` 的 inverse
   映射一致），不改 ``bmp_lsb.py``，只读公开字段 ``data``/``palette``。
"""
import hashlib
import random
import struct

from bmp_lsb import BMP, BMPError

HEADER_BYTES = 4
HEADER_BITS = HEADER_BYTES * 8
DEFAULT_GAP_RANGE = (1, 4)


def derive_seed(key):
    """把字符串密钥派生为 PRNG 种子；空密钥拒绝。"""
    if not isinstance(key, str) or not key:
        raise BMPError('密钥须为非空字符串。')
    return int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest(), 'big')


def _check_gap_range(gap_range):
    lo, hi = gap_range
    if not (isinstance(lo, int) and isinstance(hi, int)) or lo < 1 or hi < lo:
        raise BMPError('间隔范围须为 1 ≤ 最小间隔 ≤ 最大间隔 的整数对。')
    return lo, hi


def keyed_sample_positions(bmp, key, gap_range=DEFAULT_GAP_RANGE):
    """按密钥产出随机间隔的嵌入位置（文件存储顺序中的样本绝对下标）。

    同一 (bmp 尺寸, key, gap_range) 永远得到同一条流；这正是提取的依据。
    """
    lo, hi = _check_gap_range(gap_range)
    samples = list(bmp.positions())
    count = len(samples)
    if count == 0:
        return
    rng = random.Random(derive_seed(key))
    index = 0
    while True:
        index += rng.randint(lo, hi)
        if index >= count:
            return
        yield samples[index]


def keyed_capacity(bmp, key, gap_range=DEFAULT_GAP_RANGE):
    """随机间隔方案下本图可嵌入的总字节数（含 4 字节长度头）。

    位置流是确定性的，数一遍流长即可精确得出容量；必小于顺序 LSB 容量。
    """
    return sum(1 for _ in keyed_sample_positions(bmp, key, gap_range)) // 8


def embed_keyed(source, payload, key, gap_range=DEFAULT_GAP_RANGE):
    """用密钥把 UTF-8/字节消息以随机间隔 LSB 写入，返回新的 BMP 对象。"""
    payload = bytes(payload)
    limit = keyed_capacity(source, key, gap_range)
    if len(payload) + HEADER_BYTES > limit:
        raise BMPError(f'信息 {len(payload)} 字节加 {HEADER_BYTES} 字节长度头，'
                       f'超过随机间隔容量 {limit} 字节。')
    stream = keyed_sample_positions(source, key, gap_range)
    result = bytearray(source.data)
    inverse = {v: i for i, v in enumerate(source.palette)} if source.bpp == 8 else None
    try:
        for byte in struct.pack('>I', len(payload)) + payload:
            for shift in range(7, -1, -1):
                bit = (byte >> shift) & 1
                pos = next(stream)
                value = source.value(pos)
                if value & 1 == bit:
                    continue                    # 该样本已满足，保持不动
                target = (value & 0xFE) | bit
                result[pos] = inverse[target] if source.bpp == 8 else target
    except StopIteration:
        raise BMPError('随机间隔位置流提前用尽，嵌入中止。') from None
    return BMP.parse(bytes(result))


def extract_keyed(carrier, key, gap_range=DEFAULT_GAP_RANGE):
    """用同一密钥沿随机间隔位置流读出 4 字节长度头，再自动提取消息正文。"""
    stream = keyed_sample_positions(carrier, key, gap_range)

    def read_byte():
        byte = 0
        for _ in range(8):
            pos = next(stream)                  # 流用尽会抛 StopIteration
            byte = (byte << 1) | (carrier.value(pos) & 1)
        return byte

    try:
        header = bytes(read_byte() for _ in range(HEADER_BYTES))
    except StopIteration:
        raise BMPError('随机间隔位置流提前用尽，密钥或载体可能不匹配。') from None
    length = struct.unpack('>I', header)[0]
    if length + HEADER_BYTES > carrier.capacity:
        raise BMPError(f'图内长度头声明 {length} 字节，超过本图顺序容量上限；'
                       f'密钥可能错误或载体损坏。')
    try:
        return bytes(read_byte() for _ in range(length))
    except StopIteration:
        raise BMPError('随机间隔位置流提前用尽，密钥或载体可能不匹配。') from None

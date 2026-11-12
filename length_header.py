"""图内长度头：把消息字节数写进载体最前面的 32 个 LSB。

背景：``bmp_lsb.BMP.embed`` 本身不写入任何长度信息，为的是让 4×2 灰度图那 8 个
LSB 刚好装下一个 ``?``（作业第 27 页用例），多 1 bit 都放不下。但报告第 26 页
要求回答“如何在嵌入信息的图片中存储嵌入的信息的长度”，只靠同目录的
``.bmp.lsb.json`` 记录不算把长度存进了图片。

折中方案：**容量 ≥ 5 字节时启用图内长度头，容量 ≤ 4 字节的小图退回外部给定长度**。

布局（按嵌入顺序，即文件存储顺序）：

    前 32 个样本 LSB  = 消息字节数（大端 uint32）
    其后 8 × n 个样本 LSB = 消息正文（UTF-8，逐字节高位在前）

长度头占用 4 字节容量，所以真正可嵌入的正文上限是 ``capacity - 4``。4×2（容量 1）、
4×4（容量 2）这类图无法带头，仍走 ``BMP.embed`` 的满容量路径，作业用例不受影响。
"""
import struct

from bmp_lsb import BMP, BMPError

HEADER_BYTES = 4
HEADER_BITS = HEADER_BYTES * 8
MIN_CAPACITY_WITH_HEADER = HEADER_BYTES + 1


def header_capacity(capacity):
    """给定总容量，返回启用长度头后能装入的正文最大字节数。"""
    if capacity < MIN_CAPACITY_WITH_HEADER:
        return 0
    return capacity - HEADER_BYTES


def needs_external_length(capacity):
    """容量小到装不下长度头时返回 True，调用方需另行保存消息长度。"""
    return capacity < MIN_CAPACITY_WITH_HEADER


def embed_with_length(source, payload):
    """嵌入消息并把字节数写进图内长度头，返回新的 BMP 对象。"""
    payload = bytes(payload)
    capacity = source.capacity
    if needs_external_length(capacity):
        raise BMPError(f'容量仅 {capacity} 字节，装不下 {HEADER_BYTES} 字节长度头；'
                       f'该图请改用 BMP.embed 并由外部保存消息长度。')
    if len(payload) > capacity - HEADER_BYTES:
        raise BMPError(f'信息 {len(payload)} 字节，超过带长度头时的上限 '
                       f'{capacity - HEADER_BYTES} 字节。')
    return source.embed(struct.pack('>I', len(payload)) + payload)


def extract_with_length(carrier):
    """按图内长度头自动提取消息，不需要外部给定字节数。"""
    capacity = carrier.capacity
    if needs_external_length(capacity):
        raise BMPError(f'容量仅 {capacity} 字节，不可能带有长度头。')
    header = carrier.extract(HEADER_BYTES)
    length = struct.unpack('>I', header)[0]
    if length > capacity - HEADER_BYTES:
        raise BMPError(f'图内长度头声明 {length} 字节，超过本图带头的上限 '
                       f'{capacity - HEADER_BYTES} 字节；该载体可能未使用长度头或已损坏。')
    return carrier.extract(HEADER_BYTES + length)[HEADER_BYTES:]

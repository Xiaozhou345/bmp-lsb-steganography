"""轨道 B：有损压缩（JPEG 往返）与剪裁的鲁棒性分析。仅使用 Python 标准库。

对应作业第 24、25 页的两项附加实验：

- 附加②：24 位图嵌入 → 画图另存 JPEG → 再另存 24 位 BMP → 提取 → 比对，
  分析 LSB 的抗有损压缩能力；
- 附加③：分析并实践验证 LSB 的抗剪裁能力。

本模块只负责"怎么量"：剪出仍可解析的 BMP、把提取结果与原消息做比特级
比对、把消息写到任意比特平面、按固定矩阵跑质量/剪裁实验。真正做 JPEG
编解码的是 ``tools/jpeg_roundtrip.py``，本模块不 import 它，只接收一个
``roundtrip(BMP, quality) -> BMP`` 回调——单元测试可以传入"不做压缩"的
假函数，也可以换成别的编解码器。

两条来自 ``docs/接口约定.md`` 的约束在此体现：

1. 不修改 ``bmp_lsb.py``；逐样本遍历一律用 ``BMP.positions()`` 与
   ``BMP.value()``，8 位图写回时按调色板反查索引（``BMP.embed`` 的语义）。
2. 剪裁宽度必须是 4 的倍数：冻结的解析器只接受宽度为 4 倍数的 BMP，剪成
   190 像素宽以后连本程序都打不开。裁剪实验因此只取 4 的倍数宽度，这条
   限制本身是第 6 章要如实写出的实验约束。
"""
import struct

from bmp_lsb import BMP, BMPError


# --------------------------------------------------------------------------
# 1. 剪裁：只动像素区，重建文件头，产物仍是本程序可解析的 BMP
# --------------------------------------------------------------------------
def _check_rect(source, left, top, width, height):
    if not all(isinstance(v, int) for v in (left, top, width, height)):
        raise BMPError('裁剪参数须为整数。')
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise BMPError('裁剪区域须落在图内，宽高须为正。')
    if left + width > source.width or top + height > source.height:
        raise BMPError(f'裁剪区域 {width}×{height} 超出 {source.width}×{source.height}。')
    if width % 4:
        raise BMPError('裁剪宽度须为 4 的倍数，冻结的解析器不接受其它宽度。')


def crop(source, left, top, width, height):
    """按图像坐标（左上角为原点）剪出一块，返回新的 BMP 对象。

    像素按原图存储顺序逐行搬运；8 位图连同调色板一起保留；行距按新宽度
    重新计算，文件头中的 bfSize / 宽 / 高 / biSizeImage 一并改写，因此产物
    与画图另存出来的 BMP 一样能被 ``BMP.parse`` 打开。
    """
    _check_rect(source, left, top, width, height)
    bytes_per_pixel = source.bpp // 8
    new_stride = ((width * source.bpp + 31) // 32) * 4
    pixels = bytearray()
    for out_row in range(height):
        # 产物统一写成正高度（自下而上），等价于画图另存 BMP 的方向
        image_row = top + height - 1 - out_row
        file_row = image_row if source.signed_height < 0 else source.height - 1 - image_row
        start = source.offset + file_row * source.stride + left * bytes_per_pixel
        line = source.data[start:start + width * bytes_per_pixel]
        pixels += line
        pixels += b'\0' * (new_stride - len(line))
    header = bytearray(source.data[:source.offset])
    struct.pack_into('<I', header, 2, source.offset + len(pixels))       # bfSize
    struct.pack_into('<i', header, 18, width)                            # biWidth
    struct.pack_into('<i', header, 22, height)                           # biHeight
    struct.pack_into('<I', header, 34, len(pixels))                      # biSizeImage
    return BMP.parse(bytes(header) + bytes(pixels))


def crop_layout(source, left, top, width, height):
    """用"样本流"语言描述一次剪裁（不含像素操作），供分析/测试核对。

    返回字段：

    ``samples_per_row``  一整行的样本数（24 位图 = 宽×3，8 位图 = 宽）
    ``head_samples``     被剪掉的、位于样本流开头之前的样本数
    ``tail_samples``     被剪掉的、位于样本流末尾之后的样本数
    ``rows_only``        是否只裁掉整行（左右边界未动）
    ``byte_aligned``     保留段起点是否落在原消息的字节边界上
    ``capacity``         剪裁后图的嵌入容量（字节）

    单比特 LSB 的样本流从文件里第一行像素开始，正高度 BMP 的第一行是图像
    最底下一行。所以"从图像底部剪掉 b 行"砍掉的是消息**开头** b×行样本数
    个比特，"从图像顶部剪掉 t 行"砍掉的是**末尾**。只有 ``rows_only`` 且
    起点是 8 的倍数时，幸存部分才保持字节对齐；否则整条流移位，后续每个
    字节都会被相邻比特重新拼装。
    """
    _check_rect(source, left, top, width, height)
    per_row = source.width * (source.bpp // 8)
    kept_per_row = width * (source.bpp // 8)
    first_file_row = top if source.signed_height < 0 else source.height - (top + height)
    last_file_row = first_file_row + height - 1
    head_samples = first_file_row * per_row
    tail_samples = (source.height - 1 - last_file_row) * per_row
    rows_only = left == 0 and width == source.width
    return {
        'samples_per_row': per_row,
        'kept_samples_per_row': kept_per_row,
        'first_file_row': first_file_row,
        'last_file_row': last_file_row,
        'head_samples': head_samples,
        'tail_samples': tail_samples,
        'rows_only': rows_only,
        'byte_aligned': rows_only and head_samples % 8 == 0,
        'contiguous': rows_only,
        'kept_samples': kept_per_row * height,
        'capacity': kept_per_row * height // 8,
    }


# --------------------------------------------------------------------------
# 2. 比对：消息字节 → 比特，统计比特误差与"有多少字节完全正确"
# --------------------------------------------------------------------------
def payload_bits(payload):
    """把字节串展开成 MSB→LSB 的比特列表，与 ``BMP.embed`` 的写入顺序一致。"""
    return [(byte >> shift) & 1 for byte in bytes(payload) for shift in range(7, -1, -1)]


def compare_payload(expected, actual):
    """比对"原消息"与"提取结果"。

    返回：

    ``bits_compared`` / ``bit_errors`` / ``ber``  逐比特错误率（0 最好，0.5 即完全随机）
    ``correct_bytes``                              逐字节完全正确的个数
    ``prefix_bytes`` / ``suffix_bytes``            与原消息相同的最长前缀/后缀字节数
    ``exact``                                      是否逐字节完全一致
    """
    expected, actual = bytes(expected), bytes(actual)
    bits_e, bits_a = payload_bits(expected), payload_bits(actual)
    compared = min(len(bits_e), len(bits_a))
    errors = sum(1 for i in range(compared) if bits_e[i] != bits_a[i])
    prefix = 0
    while prefix < min(len(expected), len(actual)) and expected[prefix] == actual[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(expected), len(actual)) - prefix
           and expected[len(expected) - 1 - suffix] == actual[len(actual) - 1 - suffix]):
        suffix += 1
    return {
        'bits_compared': compared,
        'bit_errors': errors,
        'ber': errors / compared if compared else 0.0,
        'correct_bytes': sum(1 for a, b in zip(expected, actual) if a == b),
        'prefix_bytes': prefix,
        'suffix_bytes': suffix,
        'exact': expected == actual,
        'expected_bytes': len(expected),
        'actual_bytes': len(actual),
    }


# --------------------------------------------------------------------------
# 3. 位平面：把消息写到第 n 位，用来说明"鲁棒性来自比特位置，而不是来自
#    某个实现细节"
# --------------------------------------------------------------------------
def embed_at_plane(source, payload, plane=0):
    """把消息以 MSB→LSB 顺序写到每个样本的第 ``plane`` 位（0 即普通 LSB）。

    容量与 ``BMP.embed`` 相同（样本数 // 8）；8 位图按调色板灰度值改写后
    反查索引写回。``plane`` 越大，像素改动越大、肉眼越容易察觉，这是报告
    里"容量/隐蔽性/鲁棒性三者互斥"的量化依据。
    """
    if not 0 <= plane <= 7:
        raise BMPError('比特平面须为 0～7 的整数。')
    payload = bytes(payload)
    if len(payload) > source.capacity:
        raise BMPError(f'信息为 {len(payload)} 字节，超过最大容量 {source.capacity} 字节。')
    mask = 1 << plane
    inverse = {v: i for i, v in enumerate(source.palette)} if source.bpp == 8 else None
    result = bytearray(source.data)
    stream = iter(source.positions())
    for byte in payload:
        for shift in range(7, -1, -1):
            pos = next(stream)
            value = source.value(pos)
            target = (value & ~mask) | (((byte >> shift) & 1) << plane)
            result[pos] = inverse[target] if source.bpp == 8 else target
    return BMP.parse(bytes(result))


def extract_at_plane(carrier, length, plane=0):
    """从第 ``plane`` 位读回 ``length`` 字节，读取顺序与 ``embed_at_plane`` 相同。"""
    if not 0 <= plane <= 7:
        raise BMPError('比特平面须为 0～7 的整数。')
    if not isinstance(length, int) or not 0 <= length <= carrier.capacity:
        raise BMPError(f'提取长度须为 0～{carrier.capacity} 的整数字节数。')
    mask = 1 << plane
    stream = iter(carrier.positions())
    result = bytearray()
    for _ in range(length):
        byte = 0
        for _ in range(8):
            byte = (byte << 1) | (1 if carrier.value(next(stream)) & mask else 0)
        result.append(byte)
    return bytes(result)


# --------------------------------------------------------------------------
# 4. 实验矩阵
# --------------------------------------------------------------------------
def jpeg_survival(image, payload, roundtrip, qualities=(95, 90, 75, 50, 25)):
    """附加②：对每个 JPEG 质量做一次"嵌入—往返—提取—比对"。

    ``roundtrip(bmp, quality) -> BMP`` 由调用方提供（画图手工做，或用
    ``tools/jpeg_roundtrip.py`` 的编码器）。除比特误差外还记录往返图的
    PSNR：PSNR 越高说明"看起来越无损"，而已有实验结果会显示 LSB 早已
    全部失效——这正是本章要打的对比。
    """
    from bmp_lsb import analyze
    payload = bytes(payload)
    carrier = image.embed(payload)
    rows = []
    for quality in qualities:
        back = roundtrip(carrier, quality)
        verdict = compare_payload(payload, back.extract(len(payload)))
        diff = analyze(carrier, back)
        rows.append({
            'quality': quality,
            'psnr_db': diff['psnr_db'],
            'mse': diff['mse'],
            'changed_ratio': diff['change_ratio'],
            'ber': verdict['ber'],
            'correct_bytes': verdict['correct_bytes'],
            'prefix_bytes': verdict['prefix_bytes'],
            'exact': verdict['exact'],
            'preview': back.extract(min(12, len(payload))).hex(' '),
        })
    return rows


def jpeg_bit_plane_table(image, payload, roundtrip, quality=90, planes=range(8)):
    """附加②补充实验：同一质量下把消息放在不同比特平面，看哪一层能活下来。

    这是"鲁棒性是以像素改动为代价换来的"最直观的一张表：平面 0（普通 LSB）
    在 JPEG 后基本全错，平面越高越可能幸存，但肉眼可见的失真同时增大。
    """
    from bmp_lsb import analyze
    payload = bytes(payload)
    rows = []
    for plane in planes:
        carrier = embed_at_plane(image, payload, plane)
        back = roundtrip(carrier, quality)
        verdict = compare_payload(payload, extract_at_plane(back, len(payload), plane))
        diff = analyze(image, carrier)
        rows.append({
            'plane': plane,
            'ber': verdict['ber'],
            'exact': verdict['exact'],
            'carrier_psnr_db': diff['psnr_db'],
            'max_absolute_error': diff['max_absolute_error'],
        })
    return rows


def crop_survival(image, payload, crops, describe_crop=True):
    """附加③：对每个剪裁矩形做一次"嵌入—剪裁—提取—比对"。

    ``crops`` 为 ``(标签, left, top, width, height)`` 序列。返回每项的
    布局参数（见 ``crop_layout``）、容量、比特误差与正确前缀/后缀，用来
    验证"只有整行剪裁才保得住字节对齐"这条结论。
    """
    payload = bytes(payload)
    carrier = image.embed(payload)
    rows = []
    for label, left, top, width, height in crops:
        layout = crop_layout(image, left, top, width, height)
        cropped = crop(carrier, left, top, width, height)
        length = min(len(payload), cropped.capacity)
        verdict = compare_payload(payload, cropped.extract(length))
        row = {'label': label, 'rect': (left, top, width, height),
               'capacity': cropped.capacity, 'extracted_bytes': length,
               'ber': verdict['ber'], 'correct_bytes': verdict['correct_bytes'],
               'prefix_bytes': verdict['prefix_bytes'],
               'suffix_bytes': verdict['suffix_bytes'],
               'exact': verdict['exact']}
        if describe_crop:
            row.update({f'layout_{k}': v for k, v in layout.items()})
        rows.append(row)
    return rows

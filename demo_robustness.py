"""第 6 章实验演示脚本（B 负责）：JPEG 往返（附加②）与剪裁（附加③）。

用法（在项目根目录下）：

    python -X utf8 demo_robustness.py

实验图：脚本按固定种子生成的 512×512 彩色场景图（低频彩色渐变 + ±3 灰度
颗粒），因为教师素材目录不在本机，合成图的可复现性比"随便找一张照片"更好；
``samples/color256.bmp`` 作为第二张对照图出现在质量表的最后一行。

产物（outputs/B/）：

    carrier_scene.bmp        原始测试图
    carrier_hidden.bmp       嵌入消息后的载体
    jpeg_q90_420.jpg         画图等价步骤产出的 JPEG（质量 90、4:2:0）
    jpeg_back_q90.bmp        由该 JPEG 另存的 24 位 BMP（提取用）
    jpeg_quality_curve.png   BER 与 PSNR 随质量变化的对照图（截图点 2）
    bit_plane_ladder.png     比特平面阶梯图（截图点 3）
    jpeg_view.png            原图 / 载体 / 往返图肉眼对比（截图点 4）
    crop_view.png            剪裁示意与剪裁后图像（截图点 5）
    results.json             本章全部表格数据
"""
import json
import math
import random
import struct
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')                          # 不弹窗口，仅出图文件
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import numpy as np

from bmp_lsb import BMP, analyze
from robustness import (compare_payload, crop, crop_layout, embed_at_plane,
                        extract_at_plane, jpeg_bit_plane_table, jpeg_survival)
from tools.jpeg_roundtrip import jpeg_roundtrip

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'outputs' / 'B'
OUT.mkdir(parents=True, exist_ok=True)

PAYLOAD_TEXT = ('轨道B：24 位图 → JPEG 往返 → BMP → 提取，用来检验 LSB 的抗有损压缩能力；'
                '同时用整行剪裁与左右剪裁检验抗剪裁能力。')
PAYLOAD = (PAYLOAD_TEXT * 6).encode('utf-8')      # 约 1 KB，跨越多行像素
QUALITIES = (100, 95, 90, 75, 50, 25)


def make_scene(width=512, height=512, seed=2026, grain=3.0):
    """固定种子的彩色场景图：低频渐变（像天空/远山）+ 每像素独立颗粒。

    颗粒的作用是让整幅图的 LSB 接近随机——否则大片平滑区域的 LSB 全是 0，
    统计会失真。生成过程不使用任何图像库。
    """
    rng = random.Random(seed)
    stride = ((width * 3 + 3) // 4) * 4
    pixels = bytearray()
    for y in range(height - 1, -1, -1):        # BMP 自下而上存储
        line = bytearray()
        for x in range(width):
            r = 118 + 52 * math.sin(x / 61.0) * math.cos(y / 87.0) + 16 * math.sin((x + y) / 29.0)
            g = 116 + 46 * math.cos((x - y) / 73.0) + 14 * math.sin(y / 17.0)
            b = 148 + 58 * math.sin((x + y) / 101.0) * math.cos(x / 43.0)
            line += bytes((max(0, min(255, int(b + rng.uniform(-grain, grain)))),
                           max(0, min(255, int(g + rng.uniform(-grain, grain)))),
                           max(0, min(255, int(r + rng.uniform(-grain, grain))))))
        pixels += line + b'\0' * (stride - len(line))
    header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
    dib = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels),
                      2835, 2835, 0, 0)
    return BMP.parse(header + dib + bytes(pixels))


def to_array(image):
    rows = list(image.rgb_rows())
    return np.stack([np.frombuffer(r, dtype=np.uint8).reshape(image.width, 3)
                     for r in rows])


def roundtrip(bmp, quality):
    """robustness 需要的回调：BMP → JPEG → 解码 → BMP。"""
    return jpeg_roundtrip(bmp, quality, '420')[1]


def print_table(header, rows, widths):
    line = '  '.join(str(h).ljust(w) for h, w in zip(header, widths))
    print(line)
    print('-' * len(line))
    for row in rows:
        print('  '.join(str(v).ljust(w) for v, w in zip(row, widths)))


def main():
    scene = make_scene(512, 512)
    (OUT / 'carrier_scene.bmp').write_bytes(scene.data)
    carrier = scene.embed(PAYLOAD)
    (OUT / 'carrier_hidden.bmp').write_bytes(carrier.data)
    carrier_diff = analyze(scene, carrier)

    print(f'实验图：合成彩色场景 512×512（种子 2026），容量 {scene.capacity} 字节')
    print(f'载荷：{len(PAYLOAD)} 字节 UTF-8；嵌入后载体 PSNR '
          f'{carrier_diff["psnr_db"]:.2f} dB，修改样本比例 {carrier_diff["change_ratio"]:.3f}')

    # ---------------- 附加②：JPEG 往返 ----------------
    print('\n========== 截图点 1：附加② JPEG 往返（质量 90、4:2:0） ==========')
    jpeg, back = jpeg_roundtrip(carrier, 90, '420')
    (OUT / 'jpeg_q90_420.jpg').write_bytes(jpeg)
    (OUT / 'jpeg_back_q90.bmp').write_bytes(back.data)
    verdict = compare_payload(PAYLOAD, back.extract(len(PAYLOAD)))
    diff = analyze(carrier, back)
    print(f'往返 JPEG {len(jpeg)} 字节（载体的 {len(jpeg)/len(carrier.data):.1%}），'
          f'往返图 PSNR {diff["psnr_db"]:.2f} dB')
    print(f'提取结果：BER {verdict["ber"]:.4f}，逐字节正确 {verdict["correct_bytes"]}/'
          f'{len(PAYLOAD)}，最长正确前缀 {verdict["prefix_bytes"]} 字节，'
          f'完整还原：{"是" if verdict["exact"] else "否"}')
    print(f'提取文本（前 40 字符）：{back.extract(len(PAYLOAD))[:40].decode("utf-8", "replace")!r}')
    print('========== ↑ 此整段终端输出截图 ==========')

    quality_rows = jpeg_survival(scene, PAYLOAD, roundtrip, QUALITIES)
    color = BMP.open(ROOT / 'samples' / 'color256.bmp')
    color_row = jpeg_survival(color, PAYLOAD, roundtrip, (90,))[0]
    print('\n各质量下的比特误差（BER）与图像质量（PSNR）')
    table = [(row['quality'], f'{row["psnr_db"]:.2f}', f'{row["ber"]:.4f}',
              f'{row["correct_bytes"]}/{len(PAYLOAD)}',
              '是' if row['exact'] else '否') for row in quality_rows]
    print_table(('质量', 'PSNR/dB', 'BER', '字节正确', '完整提取'), table,
                (12, 9, 8, 10, 8))
    print(f'换一张图对照（samples/color256.bmp 彩虹渐变，质量 90）：PSNR '
          f'{color_row["psnr_db"]:.2f} dB，BER {color_row["ber"]:.4f}，'
          f'完整提取：{"是" if color_row["exact"] else "否"}')

    # 4:4:4 对照：不做色度下采样，只看量化误差
    jpeg444, back444 = jpeg_roundtrip(carrier, 90, '444')
    verdict444 = compare_payload(PAYLOAD, back444.extract(len(PAYLOAD)))
    print(f'对照：质量 90 但 4:4:4（不降采样色度）→ BER {verdict444["ber"]:.4f}，'
          f'完整还原：{"是" if verdict444["exact"] else "否"}')

    print('\n========== 截图点 2：BER 与 PSNR 随质量变化（图） ==========')
    fig, ax1 = plt.subplots(figsize=(7.6, 4.2))
    qualities = [row['quality'] for row in quality_rows]
    ax1.plot(qualities, [row['ber'] for row in quality_rows], 'o-', color='#d62728',
             label='比特误差率 BER')
    ax1.axhline(0.5, color='#999999', linestyle='--', linewidth=1,
                label='完全随机（0.5）')
    ax1.set_xlabel('JPEG 质量')
    ax1.set_ylabel('比特误差率 BER', color='#d62728')
    ax1.set_ylim(0, 0.65)
    ax1.invert_xaxis()
    ax2 = ax1.twinx()
    ax2.plot(qualities, [row['psnr_db'] for row in quality_rows], 's--', color='#1f77b4',
             label='往返图 PSNR')
    ax2.set_ylabel('PSNR / dB', color='#1f77b4')
    ax2.set_ylim(20, 55)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], loc='center right', fontsize=9)
    ax1.set_title('质量越高 PSNR 越好，但 LSB 的 BER 始终贴着 0.5', fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / 'jpeg_quality_curve.png', dpi=150)

    print('\n========== 截图点 3：比特平面阶梯（质量 90） ==========')
    small = crop(scene, 0, 0, 256, 256)
    plane_rows = jpeg_bit_plane_table(small, PAYLOAD, roundtrip, 90, range(8))
    print_table(('比特平面', 'BER', '完整提取', '载体 PSNR/dB', '最大误差'),
                [(row['plane'], f'{row["ber"]:.4f}', '是' if row['exact'] else '否',
                  f'{row["carrier_psnr_db"]:.2f}', row['max_absolute_error'])
                 for row in plane_rows], (10, 8, 10, 12, 8))
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.bar([row['plane'] for row in plane_rows],
           [row['ber'] for row in plane_rows], color='#3a6ea5', width=0.6,
           label='BER')
    ax.axhline(0.5, color='#999999', linestyle='--', linewidth=1)
    ax.set_xlabel('嵌入比特平面（0 = 最低位，7 = 最高位）')
    ax.set_ylabel('比特误差率 BER', color='#3a6ea5')
    ax.set_ylim(0, 0.65)
    axes2 = ax.twinx()
    axes2.plot([row['plane'] for row in plane_rows],
               [row['carrier_psnr_db'] for row in plane_rows], 'o-', color='#d62728')
    axes2.set_ylabel('载体 PSNR / dB', color='#d62728')
    ax.set_title('比特平面越高越抗 JPEG，但像素改动越大（PSNR 越低）', fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / 'bit_plane_ladder.png', dpi=150)

    print('\n========== 截图点 4：原图 / 载体 / JPEG 往返图对比（图） ==========')
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    for ax, image, title in zip(axes, (scene, carrier, back),
                                ('原始场景图',
                                 f'LSB 载体（{len(PAYLOAD)} 字节，PSNR {carrier_diff["psnr_db"]:.1f} dB）',
                                 f'JPEG 往返（质量 90，PSNR {diff["psnr_db"]:.1f} dB）')):
        ax.imshow(to_array(image))
        ax.set_title(title, fontsize=10)
        ax.axis('off')
    fig.tight_layout()
    fig.savefig(OUT / 'jpeg_view.png', dpi=150)
    print(f'图片已写出：{OUT / "jpeg_view.png"}')

    # ---------------- 附加③：剪裁 ----------------
    print('\n========== 截图点 5：附加③ 剪裁 ==========')
    crops = [
        ('原图对照', 0, 0, 512, 512),
        ('剪掉底部 16 行', 0, 0, 512, 496),
        ('剪掉顶部 16 行', 0, 16, 512, 496),
        ('剪掉底部 1 行', 0, 0, 512, 511),
        ('剪掉左侧 4 列', 4, 0, 508, 512),
        ('剪掉右侧 4 列', 0, 0, 508, 512),
        ('中心裁剪 256×256', 128, 128, 256, 256),
        ('只留底部 16 行', 0, 496, 512, 16),
    ]
    crop_rows = []
    for label, left, top, width, height in crops:
        layout = crop_layout(scene, left, top, width, height)
        piece = crop(carrier, left, top, width, height)
        length = min(len(PAYLOAD), piece.capacity)
        got = piece.extract(length)
        verdict = compare_payload(PAYLOAD, got)
        shift = layout['head_samples'] // 8 if layout['byte_aligned'] else None
        if shift is None:
            model_bytes, measured = None, None
        else:
            model_bytes = min(max(len(PAYLOAD) - shift, 0), length)
            measured = 0
            if shift < len(PAYLOAD):
                measured = sum(1 for i in range(min(length, len(PAYLOAD) - shift))
                               if got[i] == PAYLOAD[shift + i])
        crop_rows.append({
            'label': label, 'rect': [left, top, width, height],
            'capacity': piece.capacity, 'head_bytes': None if shift is None else shift,
            'byte_aligned': layout['byte_aligned'], 'rows_only': layout['rows_only'],
            'ber': verdict['ber'], 'correct_bytes': verdict['correct_bytes'],
            'prefix_bytes': verdict['prefix_bytes'],
            'model_bytes': model_bytes, 'measured_bytes': measured,
            'exact': verdict['exact'],
        })
    print_table(('剪裁方式', '容量', '流头位移', 'BER', '正确前缀', '偏移恢复', '完整提取'),
                [(row['label'], row['capacity'],
                  '—' if row['head_bytes'] is None else f'{row["head_bytes"]} B',
                  f'{row["ber"]:.4f}',
                  f'{row["prefix_bytes"]}/{len(PAYLOAD)}',
                  '—' if row['measured_bytes'] is None
                  else f'{row["measured_bytes"]}/{len(PAYLOAD)}',
                  '是' if row['exact'] else '否') for row in crop_rows],
                (18, 7, 10, 8, 12, 12, 8))
    checked = [row for row in crop_rows if row['model_bytes'] is not None]
    consistent = all(row['model_bytes'] == row['measured_bytes'] for row in checked)
    print(f'模型核对：整行剪裁时"偏移处可恢复字节数"的预测与实测'
          f'{"完全一致" if consistent else "不一致，需检查"}'
          f'（{len(checked)} 个用例）')

    # 每行样本数（3W）是不是 8 的倍数，决定整行剪裁后还能不能保持字节对齐
    tiny_rows = []
    for width in (4, 8, 12):
        image = _tiny_image(width, 16)
        payload = b'ABCD'
        piece_carrier = image.embed(payload)
        kept = crop(piece_carrier, 0, 0, width, 15)     # 只剪掉最底下一行
        layout = crop_layout(image, 0, 0, width, 15)
        got = kept.extract(min(4, kept.capacity))
        shift = layout['head_samples']
        measured = 0
        if layout['byte_aligned'] and shift // 8 < 4:
            measured = sum(1 for i in range(min(4 - shift // 8, kept.capacity))
                           if got[i] == payload[shift // 8 + i])
        tiny_rows.append({'width': width, 'samples_per_row': width * (image.bpp // 8),
                          'byte_aligned': layout['byte_aligned'],
                          'head_samples': shift, 'recovered_bytes': measured,
                          'ber': compare_payload(payload, got)['ber']})
    print('\n整行剪裁是否保住字节对齐：每行样本数 3W 是否为 8 的倍数')
    print_table(('宽度', '每行样本数', '8 的倍数', '剪 1 行位移', '可恢复字节', 'BER'),
                [(row['width'], row['samples_per_row'], '是' if row['byte_aligned'] else '否',
                  f'{row["head_samples"]} 样本', f'{row["recovered_bytes"]}/4',
                  f'{row["ber"]:.4f}') for row in tiny_rows],
                (6, 10, 8, 12, 12, 8))

    # 剪裁示意图：原图 / 剪掉底部 / 剪掉顶部 / 中心裁剪
    fig, axes = plt.subplots(2, 2, figsize=(9, 8.4))
    previews = (('载体（原图）', carrier, (0, 0, 512, 512)),
                ('剪掉底部 16 行', carrier, (0, 0, 512, 496)),
                ('剪掉顶部 16 行', carrier, (0, 16, 512, 496)),
                ('中心裁剪 256×256', carrier, (128, 128, 256, 256)))
    for ax, (title, image, rect) in zip(axes.flat, previews):
        piece = crop(image, *rect)
        ax.imshow(to_array(piece))
        ax.set_title(f'{title}（{piece.width}×{piece.height}）', fontsize=10)
        ax.axis('off')
    fig.tight_layout()
    fig.savefig(OUT / 'crop_view.png', dpi=150)
    print(f'剪裁示意图：{OUT / "crop_view.png"}')

    (OUT / 'results.json').write_text(json.dumps({
        'carrier': {'width': scene.width, 'height': scene.height,
                    'capacity': scene.capacity, 'psnr_db': carrier_diff['psnr_db'],
                    'payload_bytes': len(PAYLOAD)},
        'quality': quality_rows, 'color256_q90': color_row,
        'subsampling_444_q90': {'ber': verdict444['ber'], 'exact': verdict444['exact'],
                                'jpeg_bytes': len(jpeg444)},
        'planes': plane_rows, 'crops': crop_rows, 'tiny': tiny_rows,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n数据：{OUT / "results.json"}')

    print('\n========== 画图手工操作步骤（报告"操作方法"一节用） ==========')
    print('1. 画图打开 outputs/B/carrier_hidden.bmp → 另存为 JPEG（默认质量）')
    print('2. 关闭并重新打开该 JPEG → 另存为 24 位 BMP')
    print('3. 按原长度提取并看十六进制（main.py extract 会按 UTF-8 解码，乱码会直接报错）：')
    print('   python -X utf8 -c "from bmp_lsb import BMP; '
          'print(BMP.open(r\'outputs/B/另存的.bmp\').extract(%d)[:24].hex(\' \'))"' % len(PAYLOAD))
    print('   对照本脚本的自动结果：BER ≈ 0.5，文字不可读，即"LSB 被有损压缩摧毁"')
    print('4. 剪裁：画图选中任意区域 → 裁剪 → 另存 BMP → 按同一长度提取')


def _tiny_image(width, height):
    """生成宽 width（4 的倍数）的 24 位小图，用于"每行样本数"对齐规则实验。"""
    stride = ((width * 3 + 3) // 4) * 4
    pixels = bytearray()
    for row in range(height):
        line = bytearray()
        for x in range(width):
            line += bytes(((x * 17 + row * 29) % 256, (x * 11 + row * 13) % 256,
                           (x * 7 + row * 19) % 256))
        pixels += line + b'\0' * (stride - len(line))
    header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
    dib = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels),
                      2835, 2835, 0, 0)
    return BMP.parse(header + dib + bytes(pixels))


if __name__ == '__main__':
    main()

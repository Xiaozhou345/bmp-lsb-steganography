"""第 7 章实验演示脚本（C 负责）。跑一遍，按打印的【截图点】提示截图。

用法（在 lsp 目录下）：
    python -X utf8 demo_keyed.py

实验图：教师素材 24位真彩图/LENA_COLOR.BMP（512x512）；
载荷取"本密钥随机间隔容量 - 4 字节长度头"的近满容量。

产物（outputs/C/）：
    keyed_carrier_lena.bmp  随机间隔载体
    seq_carrier_lena.bmp    顺序 LSB 对照载体
    hist_compare.png        三联直方图（截图点 4）
    lsb_prefix_curve.png    修改位置累积曲线（截图点 4）
    image_view.png          原图/载体并排肉眼对比（截图点 3）
终端输出对应截图点 1、2。
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')                          # 不弹窗口，仅出图文件
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import numpy as np

from bmp_lsb import BMP, analyze
from keyed_lsb import embed_keyed, extract_keyed, keyed_capacity

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'outputs' / 'C'
OUT.mkdir(parents=True, exist_ok=True)
KEY = 'team-C-key-2026'

# 自动定位教师素材的 LENA_COLOR.BMP（素材目录比仓库根多套一层同名文件夹）
for candidate in (ROOT.parent / '可供选用的图片' / '可供选用的图片' / '24位真彩图' / 'LENA_COLOR.BMP',
                  ROOT / 'samples' / 'color256.bmp'):
    if candidate.exists():
        img = BMP.open(candidate)
        img_name = candidate.name
        break
else:
    raise SystemExit('未找到素材图，请确认 可供选用的图片/ 目录位置')

limit = keyed_capacity(img, KEY)
raw = '信息安全实验·附加四·带密钥随机间隔LSB·LENA512载体。'.encode('utf-8')
payload = (raw * (limit // len(raw) + 1))[:limit - 4]      # 近满容量
print(f'实验图：{img_name}（{img.width}x{img.height} 24位真彩图）')
print(f'顺序 LSB 容量 {img.capacity} 字节 | 本密钥随机间隔容量 {limit} 字节 '
      f'（损失 {1 - limit / img.capacity:.0%}）| 实际嵌入 {len(payload)} 字节')

print('\n========== 截图点 1：嵌入 + 正确密钥提取 ==========')
carrier = embed_keyed(img, payload, KEY)
print(f'[嵌入成功] 密钥="{KEY}"，载体已生成')
back = extract_keyed(carrier, KEY)
print(f'[提取成功] 提取文本（前 60 字符）= {back[:60].decode("utf-8")}...')
print(f'[比对一致] {back == payload}')
a = analyze(img, carrier)
print(f'[失真分析] 修改样本比例 {a["change_ratio"]:.4f}，最大绝对误差 '
      f'{a["max_absolute_error"]}，PSNR = {a["psnr_db"]:.2f} dB')
print('========== ↑ 此整段终端输出截图 ==========')

(OUT / 'keyed_carrier_lena.bmp').write_bytes(carrier.data)
(OUT / 'original_lena.bmp').write_bytes(img.data)

print('\n========== 截图点 2：错误密钥被拒绝 ==========')
try:
    wrong = extract_keyed(carrier, 'wrong-key')
    print(f'[异常] 错误密钥竟提取成功（不应发生）')
except Exception as exc:
    print('[错误密钥提取] key="wrong-key"')
    print(f'程序拒绝并报错：{exc}')
print('========== ↑ 此整段终端输出截图 ==========')

print('\n========== 截图点 3、4：图片文件已生成 ==========')
seq = img.embed(payload)                                   # 顺序 LSB 对照
(OUT / 'seq_carrier_lena.bmp').write_bytes(seq.data)
seq_a = analyze(img, seq)

def to_array(image):
    rows = list(image.rgb_rows())
    return np.stack([np.frombuffer(r, dtype=np.uint8).reshape(image.width, 3)
                     for r in rows])

# 截图点 3：原图与载体并排肉眼对比（人眼不可分辨）
arr_o, arr_c = to_array(img), to_array(carrier)
fig3, axes = plt.subplots(1, 2, figsize=(9, 5.2))
axes[0].imshow(arr_o); axes[0].set_title('原图 LENA_COLOR.BMP')
axes[1].imshow(arr_c)
axes[1].set_title(f'密钥随机间隔载体（嵌入 {len(payload)} 字节，PSNR {a["psnr_db"]:.2f} dB）')
for ax in axes:
    ax.axis('off')
fig3.tight_layout()
fig3.savefig(OUT / 'image_view.png', dpi=150)

# 截图点 4a：三联字节值直方图
fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
for ax, image, title in zip(axes, (img, seq, carrier),
                            (f'原图（{img_name}）',
                             f'顺序LSB载体（PSNR {seq_a["psnr_db"]:.1f} dB）',
                             f'密钥随机间隔载体（PSNR {a["psnr_db"]:.1f} dB）')):
    pixels = np.frombuffer(image.data[image.offset:image.pixel_end], dtype=np.uint8)
    ax.hist(pixels, bins=256, range=(0, 256), color='#3a6ea5')
    ax.set_title(title, fontsize=10)
    ax.set_xlabel('字节值')
axes[0].set_ylabel('频数')
fig.tight_layout()
fig.savefig(OUT / 'hist_compare.png', dpi=150)

# 截图点 4b：LSB 修改位置累积曲线（对照原图逐样本比较）
fig2, ax = plt.subplots(figsize=(13, 3.4))
orig_lsb = [img.value(p) & 1 for p in img.positions()]
n = len(orig_lsb)
for image, label, color in ((seq, '顺序LSB', '#d62728'), (carrier, '随机间隔', '#2ca02c')):
    lsb = [image.value(p) & 1 for p in image.positions()]
    changed = np.cumsum([o != b for o, b in zip(orig_lsb, lsb)]) / np.arange(1, n + 1)
    ax.plot(changed, label=f'{label}：前缀修改比例', color=color, linewidth=0.9)
ax.set_xlabel('按文件顺序的样本序号')
ax.set_ylabel('前缀中被修改样本占比')
ax.set_title('顺序 LSB 的修改集中在图首约 10% 区域，随机间隔铺满全图', fontsize=11)
ax.legend(loc='upper right', fontsize=9)
fig2.tight_layout()
fig2.savefig(OUT / 'lsb_prefix_curve.png', dpi=150)
print(f'肉眼对比图（截图点 3）：{OUT / "image_view.png"}')
print(f'直方图与修改曲线（截图点 4）：{OUT / "hist_compare.png"}、{OUT / "lsb_prefix_curve.png"}')
print(f'载体 BMP：{OUT / "keyed_carrier_lena.bmp"}、{OUT / "seq_carrier_lena.bmp"}')

"""素材探测：定位教师提供的“可供选用的图片”，逐张打印 BMP 头部关键字段。

只读前 54 字节，不依赖 bmp_lsb，因此即使解析器拒绝某张图也能看清它为什么被拒。

用法：

    python tools/bmp_probe.py              # 打印表格
    python tools/bmp_probe.py --fail-only   # 只打印 bmp_lsb 拒绝的图
"""
import os
import struct
import sys
from pathlib import Path

FIXTURES_NAME = '可供选用的图片'
FIXTURE_SUBDIRS = ('256灰度', '24位真彩图')


def find_fixtures_root(start=None):
    """定位素材目录；教师压缩包解开后会多套一层同名文件夹，这里两种都试。"""
    roots = []
    if start:
        roots.append(Path(start))
    here = Path(__file__).resolve()
    roots += [here.parents[1], Path(r'D:\信息安全实验')]
    for root in roots:
        for candidate in (root / FIXTURES_NAME, root / FIXTURES_NAME / FIXTURES_NAME):
            if any((candidate / name).is_dir() for name in FIXTURE_SUBDIRS):
                return candidate
    raise FileNotFoundError(f'未找到“{FIXTURES_NAME}”素材目录，请用 --root 指定。')


def iter_bmps(root):
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            if name.lower().endswith('.bmp'):
                yield Path(dirpath) / name


def probe(path):
    """返回该 BMP 的头部字段与合规判定，不抛异常（格式错误也作为结果返回）。"""
    path = Path(path)
    size_on_disk = path.stat().st_size
    with path.open('rb') as handle:
        head = handle.read(54)
    if len(head) < 54 or head[:2] != b'BM':
        return {'path': path, 'error': '不是完整的 BMP 文件', 'size_on_disk': size_on_disk}
    bf_size, = struct.unpack_from('<I', head, 2)
    offset, dib = struct.unpack_from('<II', head, 10)
    width, height, planes, bpp, compression, image_size = struct.unpack_from('<iiHHII', head, 18)
    stride = ((width * bpp + 31) // 32) * 4 if bpp else 0
    pixel_end = offset + stride * abs(height)
    compliant = (bpp in (8, 24) and compression == 0 and planes == 1
                 and 0 < width <= 512 and 0 < abs(height) <= 512 and width % 4 == 0)
    capacity = (width * abs(height) * (bpp // 8)) // 8 if bpp in (8, 24) else 0
    return {'path': path, 'width': width, 'height': height, 'bpp': bpp,
            'compression': compression, 'image_size': image_size, 'bf_size': bf_size,
            'pixel_offset': offset, 'stride': stride, 'pixel_end': pixel_end,
            'trailing': size_on_disk - pixel_end, 'size_on_disk': size_on_disk,
            'compliant': compliant, 'capacity': capacity}


def _verdict(row):
    if 'error' in row:
        return row['error']
    if not row['compliant']:
        return '超 512 或宽度非 4 倍数'
    notes = []
    if row['bf_size'] != row['size_on_disk']:
        notes.append(f'bfSize 少 {row["size_on_disk"] - row["bf_size"]} 字节')
    if row['image_size'] not in (0, row['stride'] * abs(row['height']), row['width'] * abs(row['height']) * 3):
        notes.append(f'biSizeImage={row["image_size"]}')
    return '；'.join(notes) if notes else '正常'


def main(argv):
    fail_only = '--fail-only' in argv
    root = None
    if '--root' in argv:
        root = Path(argv[argv.index('--root') + 1])
    base = find_fixtures_root(root)
    rows = [probe(path) for path in iter_bmps(base)]
    print(f'素材目录：{base}（共 {len(rows)} 张）')
    print('| 相对路径 | 宽×高 | 位深 | 容量字节 | bfSize差 | biSizeImage | 合规 | 备注 |')
    print('| --- | --- | ---: | ---: | ---: | ---: | --- | --- |')
    for row in rows:
        if fail_only and row.get('compliant', False) and 'error' not in row \
                and row.get('bf_size') == row.get('size_on_disk'):
            continue
        rel = row['path'].relative_to(base) if 'error' not in row else row['path'].name
        if 'error' in row:
            print(f'| {rel} | — | — | — | — | — | 否 | {row["error"]} |')
            continue
        diff = row['bf_size'] - row['size_on_disk']
        print(f'| {rel} | {row["width"]}×{row["height"]} | {row["bpp"]} | {row["capacity"]} | '
              f'{diff} | {row["image_size"]} | {"是" if row["compliant"] else "否"} | {_verdict(row)} |')


if __name__ == '__main__':
    main(sys.argv[1:])

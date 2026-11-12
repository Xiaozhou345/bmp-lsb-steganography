"""任务 0 回归：教师素材全量解析 + 作业第 27 页三个用例 + 尾随字节保留。

输出写入 outputs/A/，并在 docs/素材核查.md 里生成一张可直接进报告的表格。

    python tools/verify_fixtures.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bmp_lsb import BMP, BMPError, analyze  # noqa: E402
from tools.bmp_probe import find_fixtures_root, iter_bmps  # noqa: E402


def parse_all(base):
    """逐张解析，返回 (通过行, 被拒行)。"""
    passed, rejected = [], []
    for path in iter_bmps(base):
        rel = path.relative_to(base)
        try:
            bmp = BMP.open(path)
        except (BMPError, OSError) as exc:
            rejected.append((rel, str(exc)))
            continue
        passed.append((rel, bmp))
    return passed, rejected


def page27_cases(base, outdir):
    """作业第 27 页要求的三个用例，全部使用教师提供的真实小图。"""
    rows = []
    small = base / '256灰度'

    source = BMP.open(small / '4X2.BMP')
    carrier = source.embed(b'?')
    (outdir / '4X2_hidden.bmp').write_bytes(carrier.data)
    restored = BMP.open(outdir / '4X2_hidden.bmp').extract(1)
    rows.append({'file': '4X2.BMP', 'capacity': source.capacity, 'payload': '?',
                 'payload_bytes': 1, 'extracted': restored.decode('utf-8', 'replace'),
                 'ok': restored == b'?', 'note': '满容量，8 个 LSB 恰好 1 字节'})

    source = BMP.open(small / '4X4.bmp')
    carrier = source.embed(b'?S')
    (outdir / '4X4_hidden.bmp').write_bytes(carrier.data)
    restored = BMP.open(outdir / '4X4_hidden.bmp').extract(2)
    rows.append({'file': '4X4.bmp', 'capacity': source.capacity, 'payload': '?S',
                 'payload_bytes': 2, 'extracted': restored.decode('utf-8', 'replace'),
                 'ok': restored == b'?S', 'note': '满容量，16 个 LSB 恰好 2 字节'})

    source = BMP.open(small / '4X4.bmp')
    try:
        source.embed(b'AbCd')
    except BMPError as exc:
        rows.append({'file': '4X4.bmp', 'capacity': source.capacity, 'payload': 'AbCd',
                     'payload_bytes': 4, 'extracted': '（已拒绝）',
                     'ok': True, 'note': f'超长被拒：{exc}'})
    else:
        rows.append({'file': '4X4.bmp', 'capacity': source.capacity, 'payload': 'AbCd',
                     'payload_bytes': 4, 'extracted': '（未拒绝）', 'ok': False,
                     'note': '超容量却嵌入成功，不符合要求'})
    return rows


def trailing_cases(base):
    """test6/test7 尾部多 2 字节：嵌入后必须原样保留，且提取正确。"""
    rows = []
    for name in ('test6.bmp', 'test7.bmp'):
        source = BMP.open(base / '256灰度' / name)
        tail = source.data[source.pixel_end:]
        payload = '尾随字节保留验证'.encode('utf-8')
        carrier = source.embed(payload)
        rows.append({'file': name, 'trailing_bytes': source.trailing_bytes,
                     'tail_before': tail.hex(), 'tail_after': carrier.data[carrier.pixel_end:].hex(),
                     'extract_ok': carrier.extract(len(payload)) == payload,
                     'ok': carrier.data[carrier.pixel_end:] == tail
                     and carrier.extract(len(payload)) == payload})
    return rows


def main():
    base = find_fixtures_root()
    outdir = Path(__file__).resolve().parents[1] / 'outputs' / 'A'
    outdir.mkdir(parents=True, exist_ok=True)

    passed, rejected = parse_all(base)
    cases = page27_cases(base, outdir)
    trails = trailing_cases(base)

    print(f'素材目录：{base}')
    print(f'解析通过 {len(passed)} 张，被拒 {len(rejected)} 张')
    for rel, reason in rejected:
        print(f'  被拒 {rel} -> {reason}')

    md = ['| 序号 | 文件 | 宽×高 | 位深 | 容量/字节 | 尾随字节 | 结果 |',
          '| --- | --- | --- | ---: | ---: | ---: | --- |']
    for index, (rel, bmp) in enumerate(passed, 1):
        md.append(f'| {index} | {rel} | {bmp.width}×{bmp.height} | {bmp.bpp} | '
                  f'{bmp.capacity} | {bmp.trailing_bytes} | 通过 |')
    for rel, reason in rejected:
        md.append(f'| {len(passed) + len(rejected)} | {rel} | — | — | — | — | 拒收：{reason} |')

    print('\n第 27 页用例：')
    for row in cases:
        print(f"  {row['file']} 嵌「{row['payload']}」-> 提取「{row['extracted']}」 "
              f"{'OK' if row['ok'] else 'FAIL'}（{row['note']}）")
    print('\n尾随字节：')
    for row in trails:
        print(f"  {row['file']} 尾随 {row['trailing_bytes']} 字节，"
              f"嵌入后 {'保留一致' if row['tail_after'] == row['tail_before'] else '被改写'}，"
              f"提取 {'一致' if row['extract_ok'] else '不一致'}")

    report = ['# 教师素材核查（任务 0 回归）', '',
              f'素材目录：`{base}`', '',
              f'共 {len(passed) + len(rejected)} 张 BMP：解析通过 {len(passed)} 张，'
              f'被拒 {len(rejected)} 张。', '',
              '## 全量解析结果', ''] + md + [
              '', '## 作业第 27 页用例（真实素材）', '',
              '| 序号 | 文件 | 容量/字节 | 嵌入 | 字节数 | 提取结果 | 结论 | 说明 |',
              '| --- | --- | ---: | --- | ---: | --- | --- | --- |']
    for index, row in enumerate(cases, 1):
        report.append(f"| {index} | {row['file']} | {row['capacity']} | `{row['payload']}` | "
                      f"{row['payload_bytes']} | `{row['extracted']}` | "
                      f"{'通过' if row['ok'] else '失败'} | {row['note']} |")
    report += ['', '## 尾随字节保留', '',
               '| 序号 | 文件 | 尾随字节 | 嵌入前 | 嵌入后 | 提取 | 结论 |',
               '| --- | --- | ---: | --- | --- | --- | --- |']
    for index, row in enumerate(trails, 1):
        report.append(f"| {index} | {row['file']} | {row['trailing_bytes']} | "
                      f"`{row['tail_before']}` | `{row['tail_after']}` | "
                      f"{'一致' if row['extract_ok'] else '不一致'} | "
                      f"{'通过' if row['ok'] else '失败'} |")
    report += ['', '被拒图像的原因见上表；`test14.bmp` 为 600×400，超出作业简化条件'
               '（≤512×512），实验中直接弃用，不作为解析器缺陷。', '']
    docs = Path(__file__).resolve().parents[1] / 'docs'
    docs.mkdir(exist_ok=True)
    (docs / '素材核查.md').write_text('\n'.join(report), encoding='utf-8')

    summary = {'fixtures': len(passed) + len(rejected), 'passed': len(passed),
               'rejected': [str(rel) for rel, _ in rejected],
               'page27_ok': all(row['ok'] for row in cases),
               'trailing_ok': all(row['ok'] for row in trails)}
    print('\n' + json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['page27_ok'] and summary['trailing_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

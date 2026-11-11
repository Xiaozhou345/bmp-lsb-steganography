"""运行 python main.py 打开 GUI；--help 查看命令行。"""
import argparse
import json
from pathlib import Path
import sys
from bmp_lsb import BMP, BMPError, analyze


def save_new(path, data, source=None):
    target = Path(path)
    if source and target.resolve() == Path(source).resolve():
        raise BMPError('请另存为新文件，保留原始载体。')
    # 防止命令行静默覆盖文件；GUI 保存对话框另行处理确认。
    with target.open('xb') as output:
        output.write(data)


def main():
    # Windows 重定向输出也统一采用 UTF-8，保证中文提示可读。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='BMP LSB 信息隐藏（纯 Python 标准库）')
    sub = parser.add_subparsers(dest='command')
    p = sub.add_parser('info', help='识别 BMP 并计算容量')
    p.add_argument('input')
    p = sub.add_parser('embed', help='嵌入 UTF-8 文本并另存为 BMP')
    p.add_argument('input'); p.add_argument('output'); p.add_argument('text')
    p = sub.add_parser('extract', help='按给定字节数提取 UTF-8 文本')
    p.add_argument('input'); p.add_argument('length', type=int)
    p = sub.add_parser('analyze', help='比较原图和载体')
    p.add_argument('original'); p.add_argument('carrier')
    args = parser.parse_args()
    try:
        if not args.command:
            from gui import run
            run()
        elif args.command == 'info':
            print(json.dumps(BMP.open(args.input).info(), ensure_ascii=False, indent=2))
        elif args.command == 'embed':
            original = BMP.open(args.input)
            payload = args.text.encode('utf-8')
            carrier = original.embed(payload)
            save_new(args.output, carrier.data, args.input)
            print(f'嵌入成功：{len(payload)} 字节。提取时请指定相同字节数。')
            print(json.dumps(analyze(original, carrier), ensure_ascii=False, indent=2))
        elif args.command == 'extract':
            print(BMP.open(args.input).extract(args.length).decode('utf-8'))
        else:
            print(json.dumps(analyze(BMP.open(args.original), BMP.open(args.carrier)), indent=2))
    except (ValueError, OSError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

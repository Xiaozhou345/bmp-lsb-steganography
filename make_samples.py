"""不依赖图片库，构造可复现实验用 BMP。"""
from pathlib import Path
import struct
from bmp_lsb import BMP


def make_bmp(width, height, bpp=8, top_down=False, reverse_palette=False):
    stride = ((width*bpp + 31)//32)*4
    palette = b''
    if bpp == 8:
        values = range(255, -1, -1) if reverse_palette else range(256)
        palette = b''.join(bytes((v, v, v, 0)) for v in values)
    offset = 54 + len(palette)
    pixels = bytearray()
    for row in range(height):
        y = row if top_down else height-1-row
        line = bytearray()
        for x in range(width):
            if bpp == 8:
                v = (x*17 + y*29) % 256
                line.append(255-v if reverse_palette else v)
            else:
                line.extend(((x*11+y*3)%256, (y*13+x*5)%256, (x*7+y*19)%256))
        line.extend(b'\0'*(stride-len(line)))
        pixels.extend(line)
    header = struct.pack('<2sIHHI', b'BM', offset+len(pixels), 0, 0, offset)
    dib = struct.pack('<IiiHHIIiiII', 40, width, -height if top_down else height,
                      1, bpp, 0, len(pixels), 2835, 2835, 256 if bpp == 8 else 0, 0)
    return BMP.parse(header+dib+palette+pixels)


def generate(directory=None):
    directory = Path(directory) if directory else Path(__file__).resolve().parent / 'samples'
    directory.mkdir(parents=True, exist_ok=True)
    for name, w, h, bpp in [('4X2',4,2,8), ('4X4',4,4,8),
                            ('gray256',256,256,8), ('color256',256,256,24)]:
        (directory / f'{name}.bmp').write_bytes(make_bmp(w,h,bpp).data)


if __name__ == '__main__':
    generate()

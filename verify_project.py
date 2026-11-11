"""执行 GUI 自检、磁盘回环和实测分析；运行后自动关闭自检窗口。"""
import json
from pathlib import Path
import tkinter as tk
from unittest.mock import patch
from bmp_lsb import BMP, BMPError, analyze
from gui import App
from make_samples import generate


def verify():
    base = Path(__file__).resolve().parent
    folder = base / 'samples'
    output = base / 'outputs'
    output.mkdir(exist_ok=True)
    generate(folder)
    cases = [('4X2', '?'), ('4X4', '?S'),
             ('gray256', '密码学大作业：LSB 信息隐藏与提取。'),
             ('color256', '密码学大作业：LSB 信息隐藏与提取。')]
    rows = []
    for name, text in cases:
        source = BMP.open(folder/f'{name}.bmp')
        payload = text.encode('utf-8')
        carrier = source.embed(payload)
        path = output/f'{name}_hidden.bmp'
        path.write_bytes(carrier.data)
        restored = BMP.open(path).extract(len(payload))
        assert restored == payload
        rows.append((name, source.capacity, len(payload), analyze(source, carrier)))
    try:
        BMP.open(folder/'4X4.bmp').embed(b'AbCd')
    except BMPError:
        pass
    else:
        raise AssertionError('超长信息未被拒绝')

    root = tk.Tk()
    root.withdraw()
    try:
        app = App(root)
        with patch('gui.messagebox.showerror') as error, patch('gui.messagebox.showinfo') as info:
            assert str(app.buttons['embed']['state']) == 'disabled'
            assert str(app.buttons['save']['state']) == 'disabled'
            assert str(app.buttons['extract']['state']) == 'disabled'
            with patch('gui.filedialog.askopenfilename', return_value=str(folder/'4X4.bmp')):
                app.open_original()
            assert app.original.capacity == 2
            assert str(app.buttons['embed']['state']) == 'disabled'
            app.text.insert('1.0', '?S')
            root.update()
            assert str(app.buttons['embed']['state']) == 'normal'
            def confirm_embed(title, message, **kwargs):
                assert title == '嵌入成功'
                # 确认前仍保留输入，确认后才清空。
                assert app.text.get('1.0', 'end-1c') == '?S'
            info.side_effect = confirm_embed
            app.embed()
            info.assert_called_once()
            info.side_effect = None
            assert app.text.get('1.0', 'end-1c') == ''
            assert app.length.get() == '2'
            assert app.carrier.extract(2) == b'?S'
            assert str(app.buttons['embed']['state']) == 'disabled'
            assert str(app.buttons['save']['state']) == 'normal'
            assert str(app.buttons['extract']['state']) == 'disabled'
            with patch('gui.filedialog.asksaveasfilename', return_value=str(output/'gui_hidden.bmp')):
                app.save()
            assert BMP.open(output/'gui_hidden.bmp').extract(2) == b'?S'
            assert app.original is None and app.carrier is None
            assert app.photos == {}
            assert str(app.buttons['save']['state']) == 'disabled'
            # 验证独立打开载体，不依赖原图或嵌入时的对象。
            app.original = app.carrier = None
            with patch('gui.filedialog.askopenfilename', return_value=str(output/'gui_hidden.bmp')):
                app.open_carrier()
            assert app.length.get() == '2'  # 自动读取，不再手填
            assert str(app.length_entry['state']) == 'readonly'
            assert str(app.buttons['extract']['state']) == 'normal'
            app.extract()
            assert app.result.get('1.0','end-1c') == '?S'
            # 旧载体没有长度记录时，清空旧输入、旧结果、旧长度。
            with patch('gui.filedialog.askopenfilename', return_value=str(folder/'4X4.bmp')):
                app.open_original()
            app.text.insert('1.0', '旧文字')
            with patch('gui.filedialog.askopenfilename', return_value=str(output/'4X4_hidden.bmp')):
                app.open_carrier()
            assert app.original is None
            assert app.text.get('1.0', 'end-1c') == ''
            assert app.result.get('1.0', 'end-1c') == ''
            assert app.length.get() == ''
            assert str(app.length_entry['state']) == 'normal'
            assert str(app.buttons['extract']['state']) == 'disabled'
            app.length.set('3')
            assert str(app.buttons['extract']['state']) == 'disabled'
            app.length.set('2')
            app.extract()
            assert app.result.get('1.0','end-1c') == '?S'
            # 24 位图以及 256×256 预览的 PhotoImage 路径也需实际运行。
            app.show(BMP.open(folder/'color256.bmp'),0)
            app.show(BMP.open(folder/'gray256.bmp'),1)
            root.update()
            assert not error.called, error.call_args_list
    finally:
        root.destroy()

    lines = ['# LSB 隐写实验结果', '',
             '以下为本机运行 `python verify_project.py` 的实测结果。载体由标准库手工生成，非教师提供图片。', '',
             '| 原图 | 最大容量/字节 | 消息/字节 | 修改样本 | 最大误差 | MSE | PSNR/dB | 磁盘重读提取 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for name, capacity, size, a in rows:
        psnr = '∞' if a['psnr_db'] is None else f'{a["psnr_db"]:.6f}'
        lines.append(f'| {name} | {capacity} | {size} | {a["changed_samples"]}/{a["sample_count"]} | '
                     f'{a["max_absolute_error"]} | {a["mse"]:.8f} | {psnr} | 一致 |')
    lines += ['', '4×2 灰度图的 8 个 LSB 恰好容纳 `?`（ASCII 0x3F，位序 00111111）；'
              '4×4 灰度图的 16 个 LSB 恰好容纳 `?S`（0x3F 0x53，位序 00111111 01010011）。'
              '`AbCd` 为 4 字节，在容量 2 字节的 4×4 灰度图中被拒绝。', '',
              '所有实验最大样本误差为 1 或 0，符合只修改最低位的性质。较大图中相同短消息只占很小比例，'
              '故全图 MSE 更低，PSNR 更高。这些指标说明本次实验的数值失真很小；不能据此断言无法检测隐写。', '',
              '已执行 Tkinter 窗口控件自检：初始按钮禁用、有效输入后解锁、嵌入成功弹窗及确认后清空、'
              '保存后清空预览、重新打开载体自动读取长度并提取、切换载体清空旧输入与旧结果、'
              '没有长度记录时手动填写，以及两种格式像素显示。对话框用预设路径替代，测试窗口自动关闭。'
              '此项验证控件流程及图像数据加载，未进行人工窗口外观验收。', '']
    docs = base / 'docs'
    docs.mkdir(exist_ok=True)
    (docs/'实验结果.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'gui_check': 'passed', 'disk_round_trip': 'passed',
                      'cases': len(cases)},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    verify()

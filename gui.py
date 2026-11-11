"""Tkinter 负责窗口与显示；像素操作由本项目手工实现。"""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from bmp_lsb import BMP, analyze
from carrier_metadata import read_length, write_length


class App:
    def __init__(self, root):
        self.root = root
        self.original = self.carrier = None
        self.source_path = None
        self.known_length = None
        self.photos = {}
        root.title('BMP LSB Steganography')
        root.geometry('1180x850')
        root.minsize(960, 780)
        toolbar = ttk.Frame(root, padding=12)
        toolbar.pack(fill='x')
        groups = []
        for title in ('隐藏信息：①打开 → ②输入并嵌入 → ③保存', '读取信息：④打开载体 → ⑤提取'):
            group = ttk.LabelFrame(toolbar, text=title, padding=8)
            group.pack(side='left', padx=(0, 12))
            groups.append(group)
        self.buttons = {}
        for group, key, label, command in [
                (0,'open','① 打开原图',self.open_original),
                (0,'embed','② 嵌入信息',self.embed),
                (0,'save','③ 保存载体',self.save),
                (1,'carrier','④ 打开载体',self.open_carrier),
                (1,'extract','⑤ 提取信息',self.extract)]:
            button = ttk.Button(groups[group], text=label, command=command)
            button.pack(side='left', padx=3)
            self.buttons[key] = button
        self.step = tk.StringVar(value='下一步：点击①打开原图；如果已有载体，可以直接点击④。')
        ttk.Label(root, textvariable=self.step, padding=(16,6), wraplength=1100).pack(fill='x')
        self.info = tk.StringVar(value='支持 8 位 256 灰度 BMP 和 24 位真彩 BMP。')
        ttk.Label(root, textvariable=self.info, padding=(16,4), wraplength=1100).pack(fill='x')
        images = ttk.Frame(root, padding=(12,4))
        images.pack(fill='both', expand=True)
        images.columnconfigure((0,1), weight=1)
        images.rowconfigure(0, weight=1)
        self.views = []
        for col, title in enumerate(('原图', '载体预览')):
            frame = ttk.LabelFrame(images, text=title, padding=8)
            frame.grid(row=0, column=col, sticky='nsew', padx=4)
            label = ttk.Label(frame, anchor='center', text='尚未打开图片')
            label.pack(fill='both', expand=True)
            self.views.append(label)
        panel = ttk.Frame(root, padding=16)
        panel.pack(fill='x')
        ttk.Label(panel, text='待嵌入信息（UTF-8；嵌入成功并确认后自动清空）').pack(anchor='w')
        self.text = tk.Text(panel, height=3, wrap='word', undo=True)
        self.text.pack(fill='x', pady=5)
        self.text.bind('<<Modified>>', self.on_modified)
        self.count = tk.StringVar()
        ttk.Label(panel, textvariable=self.count).pack(anchor='w')
        line = ttk.Frame(panel)
        line.pack(fill='x', pady=6)
        ttk.Label(line, text='提取字节数：').pack(side='left')
        self.length = tk.StringVar(value='')
        self.length_entry = ttk.Entry(line, textvariable=self.length, width=10)
        self.length_entry.pack(side='left')
        self.length_hint = tk.StringVar(value='打开载体后自动读取长度；缺少记录时才需要填写。')
        ttk.Label(line, textvariable=self.length_hint, wraplength=760).pack(side='left', padx=8)
        self.length.trace_add('write', lambda *_: self.update_buttons())
        ttk.Label(panel, text='提取结果').pack(anchor='w')
        self.result = tk.Text(panel, height=3, wrap='word', state='disabled')
        self.result.pack(fill='x', pady=5)
        self.stats = tk.StringVar(value='分析：嵌入后显示像素变化、MSE 与 PSNR。')
        ttk.Label(root, textvariable=self.stats, padding=(16,8), wraplength=1100).pack(fill='x')
        self.refresh()

    def guard(self, action):
        try:
            action()
        except (ValueError, OSError, tk.TclError) as exc:
            messagebox.showerror('操作失败', str(exc), parent=self.root)

    def show(self, bmp, index):
        photo = tk.PhotoImage(data=bmp.ppm(450,300), format='PPM')
        self.photos[index] = photo
        self.views[index].configure(image=photo, text='')

    def clear_view(self, index, text):
        self.views[index].configure(image='', text=text)
        self.photos.pop(index, None)

    def clear_text(self):
        self.text.configure(state='normal')
        self.text.delete('1.0','end')
        self.text.edit_reset()
        self.text.edit_modified(False)

    def clear_result(self):
        self.result.configure(state='normal')
        self.result.delete('1.0','end')
        self.result.configure(state='disabled')

    def describe(self, bmp, path):
        self.info.set(f'{Path(path).name} ｜ {bmp.info()["type"]} ｜ {bmp.width}×{bmp.height} ｜ '
                      f'最大信息长度 {bmp.capacity} 字节 ｜ 像素偏移 {bmp.offset} ｜ 每行 {bmp.stride} 字节')

    def can_replace(self):
        if self.original is not None and self.carrier is not None:
            return messagebox.askyesno('载体尚未保存', '当前嵌入结果尚未保存。是否放弃并打开其他图片？', parent=self.root)
        return True

    def open_original(self):
        if not self.can_replace():
            return
        path = filedialog.askopenfilename(filetypes=[('BMP 图片','*.bmp')])
        if not path:
            return
        def action():
            bmp = BMP.open(path)
            self.show(bmp,0)
            self.original, self.source_path = bmp, path
            self.carrier = None
            self.known_length = None
            self.clear_view(1,'输入文字并点击②后，在这里显示载体')
            self.clear_text()
            self.clear_result()
            self.length.set('')
            self.describe(bmp,path)
            self.step.set('下一步：在“待嵌入信息”中输入文字，再点击②嵌入信息。')
            self.stats.set('分析：等待嵌入信息。')
            self.length_hint.set('嵌入后自动记录长度，无需填写。')
            self.refresh()
        self.guard(action)

    def open_carrier(self):
        if not self.can_replace():
            return
        path = filedialog.askopenfilename(filetypes=[('BMP 图片','*.bmp')])
        if not path:
            return
        def action():
            bmp = BMP.open(path)
            self.show(bmp,1)
            self.original, self.source_path = None, None
            self.carrier = bmp
            self.known_length = read_length(path,bmp)
            self.clear_view(0,'提取信息无需打开原图')
            self.clear_text()
            self.clear_result()
            self.length.set('' if self.known_length is None else str(self.known_length))
            self.describe(bmp,path)
            if self.known_length is None:
                self.step.set('下一步：未找到有效长度记录，请填写原消息的 UTF-8 字节数，再点击⑤提取。')
                self.length_hint.set('没有匹配的长度记录；需手填，程序不能从裸 LSB 准确推断长度。')
            else:
                self.step.set('下一步：消息长度已自动读取，直接点击⑤提取信息。')
                self.length_hint.set('已自动读取配套长度记录，无需填写。')
            self.stats.set('载体已打开，等待提取。')
            self.refresh()
        self.guard(action)

    def on_modified(self, event=None):
        if self.text.edit_modified():
            self.refresh()
            self.text.edit_modified(False)

    def update_buttons(self):
        size = len(self.text.get('1.0','end-1c').encode('utf-8'))
        can_embed = (self.original is not None and self.carrier is None
                     and 0 < size <= self.original.capacity)
        self.buttons['embed'].configure(state='normal' if can_embed else 'disabled')
        self.buttons['save'].configure(state='normal' if self.original is not None and self.carrier is not None else 'disabled')
        try:
            length = int(self.length.get())
            can_extract = (self.original is None and self.carrier is not None
                           and 0 < length <= self.carrier.capacity)
        except ValueError:
            can_extract = False
        self.buttons['extract'].configure(state='normal' if can_extract else 'disabled')

    def refresh(self):
        size = len(self.text.get('1.0','end-1c').encode('utf-8'))
        if self.original is not None and self.carrier is None:
            cap = self.original.capacity
            self.text.configure(state='normal')
            self.count.set(f'当前 {size} 字节 / 最大 {cap} 字节；' +
                           (f'超出 {size-cap} 字节，无法嵌入' if size > cap else f'剩余 {cap-size} 字节'))
        else:
            self.text.configure(state='disabled')
            self.count.set('待嵌入信息已清空；再次嵌入请先打开原图。' if self.carrier else '请先打开原图，再输入文字。')
        self.length_entry.configure(state=('disabled' if self.carrier is None
                                          else 'readonly' if self.known_length is not None else 'normal'))
        self.update_buttons()

    def embed(self):
        def action():
            if self.original is None or self.carrier is not None:
                raise ValueError('请先打开原图；上一份嵌入结果请先保存。')
            payload = self.text.get('1.0','end-1c').encode('utf-8')
            if not payload:
                raise ValueError('请输入要嵌入的文字。')
            bmp = self.original.embed(payload)
            self.show(bmp,1)
            self.carrier = bmp
            self.known_length = len(payload)
            self.length.set(str(len(payload)))
            a = analyze(self.original,bmp)
            psnr = '∞' if a['psnr_db'] is None else f'{a["psnr_db"]:.4f} dB'
            self.stats.set(f'已嵌入 {len(payload)} 字节；修改样本 {a["changed_samples"]}/{a["sample_count"]} '
                           f'（{a["change_ratio"]:.2%}）；最大误差 {a["max_absolute_error"]}；'
                           f'MSE={a["mse"]:.6f}；PSNR={psnr}。')
            self.step.set('下一步：点击③保存载体。图片预览保留到保存完成，便于对比确认。')
            self.length_hint.set('已记住本次嵌入长度，无需填写。')
            self.update_buttons()
            messagebox.showinfo('嵌入成功', f'已成功嵌入 {len(payload)} 字节！\n'
                                '点击确定后清空待嵌入信息。\n接下来请点击③保存载体。', parent=self.root)
            self.clear_text()
            self.clear_result()
            self.refresh()
        self.guard(action)

    def save(self):
        if self.original is None or self.carrier is None:
            return
        path = filedialog.asksaveasfilename(defaultextension='.bmp',initialfile='carrier.bmp',
                                          filetypes=[('BMP 图片','*.bmp')])
        if not path:
            return
        def action():
            if self.source_path and Path(path).resolve() == Path(self.source_path).resolve():
                raise ValueError('请另存为新文件，保留原图用于分析。')
            Path(path).write_bytes(self.carrier.data)
            try:
                write_length(path,self.carrier,self.known_length)
            except OSError as exc:
                raise OSError(f'BMP 已保存，但长度记录保存失败：{exc}。请重试保存；'
                              f'也可手动按 {self.known_length} 字节提取。') from exc
            messagebox.showinfo('保存成功', '载体 BMP 和配套长度记录已保存。\n'
                                '下一步点击④打开载体，然后点击⑤提取，无需填写字节数。\n'
                                '移动或发送载体时，请同时带上同名 .bmp.lsb.json 文件。', parent=self.root)
            self.original = self.carrier = None
            self.source_path = None
            self.known_length = None
            self.length.set('')
            self.clear_text()
            self.clear_result()
            self.clear_view(0,'本次嵌入已保存')
            self.clear_view(1,'点击④打开已保存的载体')
            self.info.set(f'已保存：{Path(path).name}')
            self.step.set('下一步：点击④打开刚保存的载体，再点击⑤提取信息。也可点击①开始新的嵌入。')
            self.length_hint.set('打开载体后自动读取配套长度记录。')
            self.refresh()
        self.guard(action)

    def extract(self):
        def action():
            if self.carrier is None or self.original is not None:
                raise ValueError('请先点击④打开载体。')
            try:
                length = int(self.length.get())
            except ValueError:
                raise ValueError('未找到自动长度记录，请填写原消息的 UTF-8 字节数。') from None
            if length <= 0:
                raise ValueError('请输入大于零的消息字节数。')
            payload = self.carrier.extract(length)
            try:
                text = payload.decode('utf-8')
            except UnicodeDecodeError:
                raise ValueError('提取结果不是有效 UTF-8 文本，请检查载体和消息字节数。') from None
            self.clear_result()
            self.result.configure(state='normal')
            self.result.insert('1.0',text)
            self.result.configure(state='disabled')
            self.step.set('提取完成：结果显示在下方。点击④读取其他载体，点击①开始新的嵌入。')
            self.stats.set(f'提取完成：{len(payload)} 字节，{len(text)} 个字符；十六进制 {payload.hex(" ")}')
        self.guard(action)


def run():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    run()

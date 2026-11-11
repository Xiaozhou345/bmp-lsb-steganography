# BMP LSB 信息隐藏

在 BMP 图像最低有效位中嵌入文本，再从保存的载体中提取文本。支持 8 位 256 灰度 BMP 和 24 位真彩 BMP，提供图形界面、命令行、容量检查和图像失真分析。

BMP 文件解析、像素解码、预览抽样及 LSB 修改均由 Python 字节操作实现，不使用 Pillow、OpenCV 或其他图片处理库。Tkinter 仅负责窗口和像素显示。

## 在 IDE 中运行

需要 **Python 3.10 或更高版本，且带 Tkinter**。无第三方依赖，无须安装额外的 Python 包。

### PyCharm

1. 用“打开项目”选择本项目文件夹。
2. 为项目选择 Python 3.10+ 解释器，可使用现有解释器或新建虚拟环境。
3. 打开根目录的 `main.py`，右键选择“运行 main”。启动参数留空即可进入图形界面。

### VS Code

1. 使用“打开文件夹”打开项目根目录，安装 Python 和 Python Debugger 扩展。
2. 通过“Python: Select Interpreter”选择 Python 3.10+ 解释器。
3. 打开“运行和调试”，选择 **运行 LSB 图形界面**，按 F5。

已提供 `.vscode/launch.json` 和测试发现配置；VS Code 测试面板可运行 `tests/` 中的 unittest 测试。

### 其他 Python IDE 或终端

直接运行根目录的 `main.py`。它通过同目录模块导入运行，不要求把当前工作目录设置为某个固定位置。

```bash
python main.py
```

Windows 也可以双击 `run.bat`。如果提示缺少 `_tkinter`，请在 Python 安装程序中补装 Tcl/Tk；它不是需要通过 pip 安装的第三方依赖。

## 使用流程

1. **打开原图**：自动识别类型，显示宽高和最大容量。
2. 输入文本，查看 UTF-8 字节计数；超长内容会拒绝嵌入。
3. **嵌入信息**：弹出“嵌入成功”提示，点击确定后清空输入；保留图片用于对比，并提示保存。
4. **保存载体**：另存为 BMP，同时生成 `.bmp.lsb.json` 长度记录；保存完成后清空图片，开始下一步。
5. **打开载体**：自动读取配套长度记录，直接点击 **提取信息**。切换图片会清空旧输入与旧结果。

按钮按①至⑤分组排列，窗口始终提示下一步。未打开原图、输入为空或超长时，不能点击嵌入；嵌入后才能保存，打开载体后才能提取。

**消息长度约定：** 为满足 4×2 灰度图存储一个字符的要求，图内不额外存储长度头或终止符。GUI 保存时在 BMP 旁记录长度，记录文件不保存消息明文。重新打开时会核对图片摘要并自动填写长度。移动或发送载体时，请同时带上 `图片名.bmp.lsb.json`；旧载体、仅有 BMP 或长度记录损坏/不匹配时，才需手动填写原消息的 UTF-8 字节数。不能仅根据裸 LSB 准确推断消息长度。中文通常占多个字节，以嵌入时的界面计数为准。命令行操作仍使用显式长度参数。

## 项目结构

```text
bmp-lsb-steganography/
├── main.py                  # IDE 运行入口及命令行
├── gui.py                   # Tkinter 图形界面
├── bmp_lsb.py               # BMP 解析与 LSB 算法
├── carrier_metadata.py      # 配套长度记录的保存与校验
├── make_samples.py          # 手工生成样例 BMP
├── verify_project.py        # GUI 流程与磁盘读写自检
├── run.bat                  # Windows 启动脚本
├── tests/
│   ├── __init__.py
│   ├── test_lsb.py          # unittest 核心测试
│   └── test_metadata.py     # 长度记录测试
├── samples/                 # 四幅可直接使用的原始示例 BMP
├── docs/
│   ├── 作业要求与算法说明.md
│   └── 实验结果.md
├── .vscode/                 # 可共享的运行与测试配置
├── .github/workflows/       # GitHub Actions 核心测试
├── .gitattributes
└── .gitignore
```

运行产生的载体默认由自检程序写入 `outputs/`，该目录被 Git 忽略。GUI 保存时可自行选择位置。BMP 文件及配套 `.lsb.json` 长度记录默认不提交，仅明确保留 `samples/` 中的四幅原始示例图；需要新增原始样例时，应在 `.gitignore` 中增加对应例外。原文档图片及旧压缩包保存在本地 `.local/` 中，也由忽略规则排除。

## 命令行与测试

以下命令从项目根目录执行。嵌入命令的目标文件应尚不存在，避免覆盖已有文件。

```bash
python main.py info samples/4X2.bmp
python main.py embed samples/4X2.bmp demo_question.bmp "?"
python main.py extract demo_question.bmp 1
python main.py embed samples/4X4.bmp demo_two_chars.bmp "?S"
python main.py extract demo_two_chars.bmp 2
python main.py analyze samples/4X4.bmp demo_two_chars.bmp
python -m unittest discover -s tests -v
```

`python make_samples.py` 可重新生成四幅原始示例图。`python verify_project.py` 会启动自动关闭的测试窗口，验证界面流程、保存后重新读取提取，并更新 `docs/实验结果.md`。

测试覆盖小图指定用例、超长拒绝、UTF-8、两种位深、两种扫描方向、灰度调色板映射、满容量、文件头和异常输入。GitHub Actions 在推送或创建拉取请求后运行核心测试；GUI 自检在带 Tkinter 的桌面环境中手动运行。

## 上传 GitHub

上传的是这套源码目录中的文件，**不需要压缩，也不需要解压步骤**。保留 `.github`、`.vscode`、`.gitignore` 和 `.gitattributes` 等以点开头的项目配置。

使用 GitHub Desktop 或 Git 从项目根目录创建仓库时，忽略规则会排除 `.local/`、`outputs/`、Python 缓存、虚拟环境、压缩包和 IDE 私有配置。若用网页手动上传，请按上述项目结构选择文件；网页上传不会自动应用本地 `.gitignore`，不要选择 `.local/`、`outputs/`、`__pycache__/` 或虚拟环境。

本项目不含账号、访问令牌或个人机器的绝对路径配置。上传和仓库可见性由使用者自行设置。

## 要求与分析

见 [作业要求与算法说明](docs/作业要求与算法说明.md) 和 [实测结果](docs/实验结果.md)。

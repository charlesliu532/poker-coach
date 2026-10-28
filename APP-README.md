# 扑克复盘台 · 桌面版

## 打包

```bash
pip install pyinstaller numpy
python build_app.py          # Mac/Linux
```
Windows 上双击 `build_windows.bat`。

产物：
- Mac/Linux：`dist/扑克复盘台`（约 25 MB，单文件）
- Windows：`dist\扑克复盘台.exe`

**必须在目标平台上各打一次**——PyInstaller 不能交叉编译。

## 运行

双击可执行文件。它会：
1. 在用户目录建数据文件夹
   - macOS `~/Library/Application Support/扑克复盘台/`
   - Windows `%APPDATA%\扑克复盘台\`
2. 第一次启动建知识库索引（约 30 秒），之后秒开
3. 自动打开浏览器

**数据存在用户目录**，升级 app 不会丢进度。

## 体积构成

| 部分 | 大小 |
| :--- | ---: |
| Python 运行时 + numpy | ~20 MB |
| 策略树 + 笔记 + 转写 | ~4 MB |
| 知识库索引（首次运行生成） | ~35 MB（用户目录） |

## 为什么不是一个真正的 .app

现在的形态是「单文件可执行 + 浏览器界面」。要变成 macOS `.app` 或
Windows 安装包，需要再做一层封装：

- macOS：`py2app` 或手动建 `.app` 目录结构
- Windows：`Inno Setup` 或 `NSIS`

功能上完全一样，只是图标和启动方式不同。

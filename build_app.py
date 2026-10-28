"""把复盘台打包成单文件桌面 app（Mac / Windows 通用脚本）。

用法：
    python build_app.py            # 在当前平台打一个可执行文件
产物在 dist/ 下。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEP = ";" if sys.platform == "win32" else ":"

args = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--onefile",
    "--name", "扑克复盘台",
    # 数据文件全部打进去
    "--add-data", f"{ROOT/'pokercoach/web'}{SEP}pokercoach/web",
    "--add-data", f"{ROOT/'data/tree'}{SEP}data/tree",
    "--add-data", f"{ROOT/'data/notes'}{SEP}data/notes",
    "--add-data", f"{ROOT/'data/transcripts'}{SEP}data/transcripts",
    # 只用到这些第三方包
    "--hidden-import", "numpy",
    "--collect-submodules", "pokercoach",
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "--exclude-module", "pandas",
    "--exclude-module", "scipy",
    str(ROOT / "app_entry.py"),
]
print("运行：", " ".join(str(a) for a in args[:6]), "…")
subprocess.run(args, cwd=str(ROOT), check=True)
print("\n完成，产物在 dist/")

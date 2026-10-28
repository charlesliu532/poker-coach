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

# 数据目录：存在才打包（云端仓库不含私密笔记，缺目录不能报错）
DATA_DIRS = [
    ("pokercoach/web", "pokercoach/web"),
    ("data/tree", "data/tree"),
    ("data/notes", "data/notes"),
    ("data/transcripts", "data/transcripts"),
]

args = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--onefile",
    "--name", "扑克复盘台",
] + [
    a for src, dst in DATA_DIRS
    if (ROOT / src).exists()
    for a in ("--add-data", f"{ROOT/src}{SEP}{dst}")
] + [
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

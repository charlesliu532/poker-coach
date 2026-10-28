"""把复盘台打包成单文件桌面 app（Mac / Windows 通用脚本）。

用法：
    python build_app.py            # 在当前平台打一个可执行文件
产物在 dist/ 下。
"""
import os
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认不是 UTF-8，打印中文会 UnicodeEncodeError
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    # Windows 对中文可执行名敏感，统一先用 ASCII 名，构建完再改名
    "--name", "pokercoach" if sys.platform == "win32" else "扑克复盘台",
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
print("[build] PyInstaller ...", flush=True)
subprocess.run(args, cwd=str(ROOT), check=True)
# Windows：把 pokercoach.exe 改名成「扑克复盘台.exe」
if sys.platform == "win32":
    src = ROOT / "dist" / "pokercoach.exe"
    dst = ROOT / "dist" / "扑克复盘台.exe"
    try:
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)
            print("[build] renamed ->", dst.name, flush=True)
    except Exception as e:
        print("[build] rename failed:", e, flush=True)

print("[build] done -> dist/", flush=True)

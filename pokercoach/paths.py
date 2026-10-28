"""统一数据根目录。

打包后 __file__ 指向 PyInstaller 的临时解包目录（_MEIxxxx），
用它定位数据 → 用户写的东西全落在临时目录，进程一退就没了。

所以：所有模块只认 POKER_DATA_ROOT，启动时由 app_entry 注入。
"""
import os
from pathlib import Path


def data_root() -> Path:
    env = os.environ.get("POKER_DATA_ROOT")
    if env:
        p = Path(env)
        if not p.name == "data":
            p = p / "data"
        return p
    # 开发态：项目根/data
    return Path(__file__).resolve().parent.parent / "data"


def data_path(*parts) -> Path:
    return data_root().joinpath(*parts)

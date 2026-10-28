"""桌面 app 入口：启动本地服务并自动打开浏览器。

数据放在用户目录（不在临时解包目录），这样关掉后进度不会丢：
  macOS   ~/Library/Application Support/扑克复盘台/
  Windows %APPDATA%/扑克复盘台/
"""
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE))


def user_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    d = root / "扑克复盘台" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 版本戳文件：记录上次铺入的数据版本，只在新版本时才覆盖
_SEED_STAMP = ".seed_version"


def _pkg_version() -> str:
    """随包数据的版本标识（用 tree/buckets.csv 的大小+mtime 做指纹）。"""
    try:
        f = BASE / "data" / "tree" / "buckets.csv"
        st = f.stat()
        return f"{int(st.st_size)}-{int(st.st_mtime)}"
    except Exception:
        return "0"


def seed_data(target: Path):
    """把随包数据铺到用户目录。

    重要：**绝不无条件删除用户目录**。
    - 用户改过的文件（策略树、桶表、笔记）必须保住
    - 只在「随包数据版本变了」时铺一次，且只补缺失的文件
    """
    stamp_file = target / _SEED_STAMP
    pkg_ver = _pkg_version()
    try:
        old_ver = stamp_file.read_text(encoding="utf-8").strip()
    except Exception:
        old_ver = ""

    if old_ver == pkg_ver:
        return                      # 同一版本，什么都不做

    for sub in ("tree", "notes", "transcripts"):
        src = BASE / "data" / sub
        dst = target / sub
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        # 逐文件补齐：已有的不覆盖，缺的才拷
        for item in src.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(src)
            out = dst / rel
            if out.exists():
                continue            # ← 用户可能改过，保留
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(item, out)
            except Exception:
                pass

    try:
        stamp_file.write_text(pkg_ver, encoding="utf-8")
    except Exception:
        pass


def ensure_index(root: Path):
    """首次运行建检索索引（大约 30 秒），之后直接复用。"""
    db = root / "coach.sqlite"
    need = not db.exists() or db.stat().st_size < 1024 * 1024
    if not need:
        return
    print("第一次启动，正在建知识库索引（约 30 秒）…")
    try:
        from pokercoach.ingest import ingest
        from pokercoach.store import Store
        st = Store(db)
        ingest(root, st, transcribe_media=False, log=print)
        print("索引建好了。")
    except Exception as e:
        print("建索引失败（不影响策略树）：", e)


def find_port(start=8770, tries=60):
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _port_of(root):
    try:
        return int((root / ".port").read_text().strip())
    except Exception:
        return None


def _running_port(root):
    """已有实例在跑就返回它的端口，否则 None。"""
    try:
        pid = int((root / ".lock").read_text().strip() or "0")
    except Exception:
        return None
    if not pid or not _alive(pid):
        return None
    p = _port_of(root)
    if not p:
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=2) as r:
            if r.status == 200:
                return p
    except Exception:
        return None
    return None


def main():
    root = user_data_dir()

    # ── 单实例锁 ──────────────────────────────────────────
    # 连点图标时，第二个进程检测到已有实例就直接开浏览器，不再起一个服务。
    running = _running_port(root)
    if running:
        print(f"已经有实例在跑（端口 {running}），直接打开浏览器。")
        open_browser(f"http://127.0.0.1:{running}")
        return

    lock = root / ".lock"
    try:
        lock.write_text(str(os.getpid()))
    except Exception:
        pass
    import atexit
    atexit.register(lambda: lock.exists() and lock.unlink())

    # 注入统一数据根：打包后 __file__ 在临时目录，不能用来定位数据
    os.environ["POKER_DATA_ROOT"] = str(root)
    seed_data(root)
    ensure_index(root)

    port = find_port()
    url = f"http://127.0.0.1:{port}"
    from pokercoach.server import serve
    from pokercoach.store import Store
    from pokercoach.coach import Coach

    os.chdir(str(root))
    store = Store(root / "coach.sqlite")
    coach = Coach(store)
    # 端口可能被抢：绑定失败就往后试
    httpd = None
    for try_port in range(port, port + 30):
        try:
            httpd = serve(store, coach, port=try_port)
            port = try_port
            url = f"http://127.0.0.1:{port}"
            break
        except OSError:
            continue
    if httpd is None:
        print("找不到可用端口（8770–8800 全被占用）")
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(1.0)
    try:
        (root / ".port").write_text(str(port))
    except Exception:
        pass
    print(f"\n扑克复盘台已启动：{url}")
    print(f"数据目录：{root}")
    print("关掉这个窗口就停止服务。\n")
    open_browser(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def open_browser(url: str):
    """尽量可靠地打开浏览器；失败就弹通知 + 复制到剪贴板。"""
    import subprocess
    ok = False
    try:
        if sys.platform == "darwin":
            # macOS 原生 open，比 webbrowser 可靠
            ok = subprocess.run(["open", url], capture_output=True).returncode == 0
        else:
            ok = webbrowser.open(url)
    except Exception:
        ok = False
    if not ok:
        try:
            webbrowser.open(url)
            ok = True
        except Exception:
            pass
    # 不管成功与否，都把地址放剪贴板
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=url.encode()).returncode
    except Exception:
        pass
    if not ok:
        try:
            subprocess.run(["osascript", "-e",
                            f'display alert "扑克复盘台" message "浏览器没能自动打开。\\n请手动访问：{url}\\n（地址已复制到剪贴板）"'],
                           capture_output=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()

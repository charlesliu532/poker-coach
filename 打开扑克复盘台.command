#!/bin/bash
# 双击这个文件就能启动扑克复盘台（macOS 会自动用终端打开它）
cd "$(dirname "$0")" || exit 1

pick_python() {
  for cand in \
    ".venv/bin/python" \
    "$HOME/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3"
  do
    [ -x "$cand" ] || continue
    if "$cand" -c "import numpy" >/dev/null 2>&1; then
      echo "$cand"
      return 0
    fi
  done
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import numpy" >/dev/null 2>&1; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

PY=$(pick_python)
if [ -z "$PY" ]; then
  echo "❌ 找不到带 numpy 的 Python。"
  echo "   在终端里运行这一句装一下：python3 -m pip install numpy"
  read -r -p "按回车关闭窗口…" _
  exit 1
fi

clear
echo "♠ 扑克复盘台"
echo "──────────────────────────────"
echo "正在启动（后台常驻，这个窗口会自动关闭）。"
echo

echo "（服务在后台常驻，关掉这个窗口也不会停）"
echo
if pgrep -f serve_guard.sh >/dev/null 2>&1; then
  echo "守护进程已在运行。"
else
  nohup ./serve_guard.sh > /tmp/guard.log 2>&1 &
  echo "守护进程已启动。"
fi

# 等服务就绪再开浏览器
for i in $(seq 1 40); do
  sleep 0.5
  if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:8770/health"; then
    open "http://127.0.0.1:8770/"
    echo "✅ 已打开浏览器：http://127.0.0.1:8770/"
    break
  fi
done
echo
echo "后台已就绪。这个窗口会自动关闭。"
exit 0

#!/bin/bash
# 守护进程：服务挂了自动拉起。
# 关键：服务启动要 5–10 秒才绑定端口，不能每 3 秒查端口就重启，
# 否则会连开多个实例互相抢端口，全部崩溃。用「进程在不在」判断。
cd "$(dirname "$0")" || exit 1
LOCK=/tmp/pokercoach-guard.lock
PY="$HOME/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3"
LOG=/tmp/pokercoach_serve.log

if [ -f "$LOCK" ]; then
  old=$(cat "$LOCK" 2>/dev/null)
  [ -n "$old" ] && kill -0 "$old" 2>/dev/null && exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

started=0
while true; do
  # 已经在跑（进程存在）就不动，只等服务自己就绪
  if pgrep -f "run.py serve --port 8770" >/dev/null 2>&1; then
    sleep 3
    continue
  fi
  # 进程不在：起一个新的，并给足 15 秒启动时间，期间不再重复启动
  echo "[guard $(date '+%H:%M:%S')] 启动服务" >> "$LOG"
  "$PY" run.py serve --port 8770 >> "$LOG" 2>&1 &
  sleep 15
done

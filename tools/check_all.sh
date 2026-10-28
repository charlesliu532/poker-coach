#!/bin/bash
# 一键跑完所有检查：逻辑审计 + 全量回归 + 规则验证
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"
echo "════ 1/3 逻辑审计 ════"
"$PY" tools/audit.py
echo
echo "════ 2/3 全量回归 ════"
"$PY" tools/fullreg.py
echo
echo "════ 3/3 规则验证 ════"
"$PY" -m pokercoach.validate data/tree

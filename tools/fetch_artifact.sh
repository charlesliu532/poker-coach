#!/bin/bash
# 用 GitHub API 下载 Actions 构建产物（绕过打不开的网页）
# 用法：GH_TOKEN=ghp_xxx ./tools/fetch_artifact.sh
set -e
OWNER="charlesliu532"; REPO="poker-coach"; DEST="$HOME/Desktop"
TOKEN="${GH_TOKEN:?请先设置 GH_TOKEN 环境变量}"
API="https://api.github.com/repos/$OWNER/$REPO"
H=(-H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json")

echo "① 查最近一次构建"
RUN=$(curl -s "${H[@]}" "$API/actions/runs?per_page=1")
echo "$RUN" | python3 -c "
import json,sys
r=json.load(sys.stdin)['workflow_runs'][0]
print(f\"   #{r['run_number']} {r['head_branch']} · {r['status']} · {r['conclusion']}\")
print(f\"   id={r['id']}\")"
RUN_ID=$(echo "$RUN" | python3 -c "import json,sys;print(json.load(sys.stdin)['workflow_runs'][0]['id'])")

echo "② 列出该次构建的产物"
ARTS=$(curl -s "${H[@]}" "$API/actions/runs/$RUN_ID/artifacts")
echo "$ARTS" | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('artifacts',[]):
    print(f\"   {a['name']}  {a['size_in_bytes']//1024//1024} MB  id={a['id']}\")"

echo "③ 下载到桌面"
mkdir -p "$DEST/github-artifacts"
echo "$ARTS" | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('artifacts',[]): print(a['id'], a['name'])" | while read -r aid name; do
  out="$DEST/github-artifacts/${name}.zip"
  printf '   %s … ' "$name"
  curl -sL "${H[@]}" "$API/actions/artifacts/$aid/zip" -o "$out"
  echo "完成 ($(du -h "$out" | cut -f1))"
done

echo
echo "④ 解压"
cd "$DEST/github-artifacts"
for z in *.zip; do
  [ -f "$z" ] || continue
  unzip -oq "$z" -d "${z%.zip}" 2>/dev/null && echo "   解压 ${z%.zip}"
done
echo
echo "产物在：$DEST/github-artifacts/"
find "$DEST/github-artifacts" -type f \( -name "*.exe" -o -name "*.zip" -o -name "*.app" \) | head -10

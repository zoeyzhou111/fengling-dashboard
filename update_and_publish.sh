#!/usr/bin/env bash
set -euo pipefail

# One-command daily pipeline:
# 1) Auto-detect latest 4 source Excel files from Downloads
# 2) Regenerate daily Excel outputs
# 3) Regenerate web dashboard pages
# 4) Git add/commit/push for GitHub Pages auto-deploy

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/config.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/config.env"
fi

ROOT_DIR="${ROOT_DIR:-$SCRIPT_DIR}"
DOWNLOADS_DIR="${DOWNLOADS_DIR:-$HOME/Downloads}"
OUTPUT_ROOT="$ROOT_DIR/每日输出"
STYLE_AUTH_TEMPLATE="${STYLE_AUTH_TEMPLATE:-$ROOT_DIR/templates/样式表2.xlsx}"
STYLE_SALES_TEMPLATE="${STYLE_SALES_TEMPLATE:-$ROOT_DIR/templates/样式表.xlsx}"
PAGES_URL="${PAGES_URL:-https://你的用户名.github.io/你的仓库名/}"

DRY_RUN="${DRY_RUN:-0}"

latest_file_by_prefix() {
  local directory="$1"
  local prefix="$2"
  python3 - "$directory" "$prefix" <<'PY'
import sys
from pathlib import Path

directory = Path(sys.argv[1]).expanduser()
prefix = sys.argv[2]
candidates = sorted(
    [p for p in directory.glob(f"{prefix}*.xlsx") if p.is_file()],
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)
if not candidates:
    sys.exit(2)
print(str(candidates[0]))
PY
}

run_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY_RUN] $*"
  else
    eval "$@"
  fi
}

echo "== Step 0: resolve latest source files =="
SALES_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "销售风灵在线率明细数据_")"
AUTH_HIGH_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "爱芯个微授权数据_")"
AUTH_AIXUE_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "爱芯个微授权数据_爱学_")"
WECHAT_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "风灵个微在线数据_")"

if [[ "$AUTH_HIGH_FILE" == *"爱学"* ]]; then
  AUTH_HIGH_FILE="$(python3 - "$DOWNLOADS_DIR" <<'PY'
import sys
from pathlib import Path
d = Path(sys.argv[1]).expanduser()
files = [p for p in d.glob("爱芯个微授权数据_*.xlsx") if p.is_file() and "爱学" not in p.name]
files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    sys.exit(2)
print(str(files[0]))
PY
)"
fi

echo "销售源文件: $SALES_FILE"
echo "授权(高中)源文件: $AUTH_HIGH_FILE"
echo "授权(爱学)源文件: $AUTH_AIXUE_FILE"
echo "个微在线源文件: $WECHAT_FILE"

echo "== Preflight: git working tree check =="
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY_RUN] cd \"$ROOT_DIR\" && git status -sb"
else
  cd "$ROOT_DIR"
  git status -sb
fi

echo "== Step 1: regenerate daily excel reports =="
run_cmd "cd \"$ROOT_DIR\" && python3 \"generate_daily_reports.py\" \
  --sales \"$SALES_FILE\" \
  --auth-high \"$AUTH_HIGH_FILE\" \
  --wechat \"$WECHAT_FILE\" \
  --auth-aixue \"$AUTH_AIXUE_FILE\" \
  --output-root \"$OUTPUT_ROOT\" \
  --style-auth-template \"$STYLE_AUTH_TEMPLATE\" \
  --style-sales-template \"$STYLE_SALES_TEMPLATE\""

echo "== Step 2: regenerate web dashboard =="
run_cmd "cd \"$ROOT_DIR\" && python3 \"build_daily_web_dashboard.py\""

echo "== Step 3: git add/commit/push =="
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY_RUN] git commit/push skipped in dry run"
else
  cd "$ROOT_DIR"
  git add ".gitignore" ".nojekyll" ".github/workflows/deploy-pages.yml" "build_daily_web_dashboard.py" "generate_daily_reports.py" "update_and_publish.sh" "config.env.example" "每日三表汇总看板.html" "周维度在线率看板.html" "访问统计看板.html" "dashboard_history.csv" "每日三表汇总看板_详情" "index.html"
  if git diff --cached --quiet; then
    echo "没有检测到需要提交的更新，跳过 commit/push。"
    exit 0
  fi
  git commit -m "update daily dashboard $(date +%F)"
  git -c http.version=HTTP/1.1 push
fi

echo "== Done =="
echo "固定链接: $PAGES_URL"

if [[ "$DRY_RUN" != "1" ]]; then
  cd "$ROOT_DIR"
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "[提醒] 仍有未提交改动："
    git status -sb
  else
    echo "[OK] 本地工作区干净，线上与本次提交保持一致。"
  fi
fi

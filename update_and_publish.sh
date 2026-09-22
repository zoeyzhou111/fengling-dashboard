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
SALES_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "销售风灵在线率明细数据_" 2>/dev/null || true)"
if [[ -z "${SALES_FILE:-}" ]]; then
  SALES_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "学习规划师风灵在线率明细数据_")"
fi
AUTH_HIGH_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "爱芯个微授权数据_")"
AUTH_AIXUE_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "爱芯个微授权数据_爱学_")"
WECHAT_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "风灵个微在线数据_")"

MERGE_CACHE_DIR="$ROOT_DIR/.merge_cache"
mkdir -p "$MERGE_CACHE_DIR"
WECHAT_FILE="$(python3 - "$DOWNLOADS_DIR" "$MERGE_CACHE_DIR" "$WECHAT_FILE" <<'PY'
import sys
from pathlib import Path
import pandas as pd

downloads = Path(sys.argv[1]).expanduser()
cache = Path(sys.argv[2])
fallback = Path(sys.argv[3])

def is_tezhan_only(path: Path) -> bool:
    try:
        df = pd.read_excel(path, sheet_name="风灵个微在线率明细数据", usecols=["运营中心"])
    except Exception:
        return False
    oc = df["运营中心"].astype(str)
    if oc.empty:
        return False
    return oc.str.contains("特战", na=False).mean() > 0.95

def merge_wechat(full: Path, patch: Path, out: Path) -> None:
    detail_sheet = "风灵个微在线率明细数据"
    df_f = pd.read_excel(full, sheet_name=detail_sheet)
    df_p = pd.read_excel(patch, sheet_name=detail_sheet)
    oc = df_f.get("运营中心", pd.Series("", index=df_f.index)).astype(str)
    merged = pd.concat([df_f.loc[~oc.str.contains("特战", na=False)], df_p], ignore_index=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        merged.to_excel(w, sheet_name=detail_sheet, index=False)
        xfull = pd.ExcelFile(full)
        if "风灵微信在线率汇总数据" in xfull.sheet_names:
            sumdf = pd.read_excel(full, sheet_name="风灵微信在线率汇总数据")
            oc2 = sumdf.get("运营中心", pd.Series("", index=sumdf.index)).astype(str)
            sumdf = sumdf.loc[~oc2.str.contains("特战", na=False)]
            xpatch = pd.ExcelFile(patch)
            if "风灵微信在线率汇总数据" in xpatch.sheet_names:
                sum_p = pd.read_excel(patch, sheet_name="风灵微信在线率汇总数据")
                sumdf = pd.concat([sumdf, sum_p], ignore_index=True)
            sumdf.to_excel(w, sheet_name="风灵微信在线率汇总数据", index=False)

files = sorted(downloads.glob("风灵个微在线数据_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    print(fallback)
    raise SystemExit(0)
latest = files[0]
if not is_tezhan_only(latest):
    print(latest)
    raise SystemExit(0)
full = next((p for p in files[1:] if not is_tezhan_only(p)), None)
if full is None:
    print(latest)
    raise SystemExit(0)
out = cache / "merged_wechat.xlsx"
merge_wechat(full, latest, out)
print(out)
PY
)"

AUTH_AIXUE_FILE="$(python3 - "$DOWNLOADS_DIR" "$MERGE_CACHE_DIR" "$AUTH_AIXUE_FILE" <<'PY'
import sys
from pathlib import Path
import pandas as pd

downloads = Path(sys.argv[1]).expanduser()
cache = Path(sys.argv[2])
fallback = Path(sys.argv[3])

def is_tezhan_only(path: Path) -> bool:
    try:
        df = pd.read_excel(path, sheet_name="个微授权明细数据", usecols=["运营中心"])
    except Exception:
        return False
    oc = df["运营中心"].astype(str)
    if oc.empty:
        return False
    return oc.str.contains("特战", na=False).mean() > 0.95

def merge_auth(full: Path, patch: Path, out: Path) -> None:
    sheet = "个微授权明细数据"
    df_f = pd.read_excel(full, sheet_name=sheet)
    df_p = pd.read_excel(patch, sheet_name=sheet)
    oc = df_f.get("运营中心", pd.Series("", index=df_f.index)).astype(str)
    merged = pd.concat([df_f.loc[~oc.str.contains("特战", na=False)], df_p], ignore_index=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        merged.to_excel(w, sheet_name=sheet, index=False)

files = sorted(downloads.glob("爱芯个微授权数据_爱学_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    print(fallback)
    raise SystemExit(0)
latest = files[0]
if not is_tezhan_only(latest):
    print(latest)
    raise SystemExit(0)
full = next((p for p in files[1:] if not is_tezhan_only(p)), None)
if full is None:
    print(latest)
    raise SystemExit(0)
out = cache / "merged_auth_aixue.xlsx"
merge_auth(full, latest, out)
print(out)
PY
)"

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

echo "== Step 2b: regenerate long-term class dashboard =="
CHANGQI_FILE="$(latest_file_by_prefix "$DOWNLOADS_DIR" "长期班辅导风灵在线明细数据_")"
echo "长期班源文件: $CHANGQI_FILE"
run_cmd "cd \"$ROOT_DIR\" && python3 \"build_changqi_dashboard.py\" --source \"$CHANGQI_FILE\""

echo "== Step 3: git add/commit/push =="
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY_RUN] git commit/push skipped in dry run"
else
  cd "$ROOT_DIR"
  git add ".gitignore" ".nojekyll" ".github/workflows/deploy-pages.yml" "build_daily_web_dashboard.py" "build_changqi_dashboard.py" "generate_daily_reports.py" "update_and_publish.sh" "config.env.example" "每日三表汇总看板.html" "每日三表汇总看板-初中.html" "每日三表汇总看板-高中.html" "周维度在线率看板.html" "周维度在线率看板-初中.html" "周维度在线率看板-高中.html" "长期班风灵在线看板.html" "长期班周维度在线率看板.html" "长期班风灵在线看板_详情" "changqi_history.csv" "changqi_detail_history.csv" "访问统计看板.html" "dashboard_history.csv" "每日三表汇总看板_详情" "index.html"
  if git diff --cached --quiet; then
    echo "没有检测到需要提交的看板更新，跳过 commit。"
  else
    git commit -m "update daily dashboard $(date +%F)"
  fi

  ahead_count="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"
  if [[ "$ahead_count" -gt 0 ]]; then
    echo "检测到本地有 ${ahead_count} 个未推送提交，开始 push..."
    push_ok=0
    for attempt in 1 2 3; do
      echo "git push 尝试 ${attempt}/3 ..."
      if git -c http.version=HTTP/1.1 push; then
        push_ok=1
        break
      fi
      if [[ "$attempt" -lt 3 ]]; then
        echo "push 失败，5 秒后重试..."
        sleep 5
      fi
    done
    if [[ "$push_ok" -ne 1 ]]; then
      echo "ERROR: git push 连续 3 次失败。数据已在本地生成，可稍后手动执行："
      echo "  cd \"$ROOT_DIR\" && git -c http.version=HTTP/1.1 push"
      exit 1
    fi
  else
    echo "本地与远程已同步，无需 push。"
  fi
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

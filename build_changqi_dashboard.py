from __future__ import annotations

import argparse
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from build_daily_web_dashboard import analytics_head_html, base_styles


ROOT = Path(__file__).resolve().parent
CHANGQI_HTML = ROOT / "长期班风灵在线看板.html"
CHANGQI_DETAIL_DIR = ROOT / "长期班风灵在线看板_详情"
CHANGQI_HISTORY_CSV = ROOT / "changqi_history.csv"
CHANGQI_DETAIL_CSV = ROOT / "changqi_detail_history.csv"

SUBJECT_ORDER = ["英语", "语文", "数学", "物理", "化学"]
XUEBU_ORDER = ["初中", "高中", "小学"]
MAX_DATE_COLUMNS = 14


def find_latest_source(downloads_dir: Path) -> Optional[Path]:
    candidates = sorted(
        downloads_dir.glob("长期班辅导风灵在线明细数据_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_source(path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    df = pd.read_excel(path, sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {
        "风灵app在线率": "app_rate",
        "风灵pc在线率": "pc_rate",
        "学习管理师姓名": "姓名",
        "学习管理师邮箱": "邮箱",
        "学段": "学部",
        "阶段": "年级",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ("运营中心", "学部", "学科", "年级", "姓名", "邮箱"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    df["app_rate"] = pd.to_numeric(df.get("app_rate"), errors="coerce")
    df["pc_rate"] = pd.to_numeric(df.get("pc_rate"), errors="coerce")
    return df.dropna(subset=["日期"]).copy()


def aggregate_history(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = ["日期", "运营中心", "学部", "学科"]
    for group_keys, gdf in df.groupby(keys, dropna=False):
        if isinstance(group_keys, tuple):
            row = dict(zip(keys, group_keys))
        else:
            row = {keys[0]: group_keys}
        row["app_rate"] = gdf["app_rate"].mean()
        row["pc_rate"] = gdf["pc_rate"].mean()
        row["headcount"] = len(gdf)
        rows.append(row)

    for (dt, oc, xuebu), gdf in df.groupby(["日期", "运营中心", "学部"], dropna=False):
        rows.append(
            {
                "日期": dt,
                "运营中心": oc,
                "学部": xuebu,
                "学科": f"{xuebu} 汇总",
                "app_rate": gdf["app_rate"].mean(),
                "pc_rate": gdf["pc_rate"].mean(),
                "headcount": len(gdf),
            }
        )
    out = pd.DataFrame(rows)
    out["app_rate"] = pd.to_numeric(out["app_rate"], errors="coerce")
    out["pc_rate"] = pd.to_numeric(out["pc_rate"], errors="coerce")
    return out


def merge_history(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        combined = new_rows.copy()
    else:
        combined = pd.concat([existing, new_rows], ignore_index=True)
    key_cols = ["日期", "运营中心", "学部", "学科"]
    combined = combined.drop_duplicates(subset=key_cols, keep="last")
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.sort_values(["日期", "运营中心", "学部", "学科"]).reset_index(drop=True)
    combined["日期"] = combined["日期"].dt.strftime("%Y-%m-%d")
    return combined


def merge_detail(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    detail_cols = [
        "日期",
        "运营中心",
        "学部",
        "学科",
        "年级",
        "姓名",
        "邮箱",
        "app_rate",
        "pc_rate",
        "app不在线时间段",
        "pc不在线时间段",
        "风灵不在线时间段",
    ]
    for col in detail_cols:
        if col not in new_rows.columns:
            new_rows[col] = ""
    new_rows = new_rows[detail_cols].copy()
    if existing.empty:
        combined = new_rows
    else:
        combined = pd.concat([existing, new_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["日期", "邮箱"], keep="last")
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.sort_values(["日期", "学部", "学科", "年级", "姓名"]).reset_index(drop=True)
    combined["日期"] = combined["日期"].dt.strftime("%Y-%m-%d")
    return combined


def pct_text(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "#N/A"
    return f"{value * 100:.2f}%"


def rate_class(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return ""
    if value < 0.5:
        return " rate-low"
    if value > 0.8:
        return " rate-high"
    return ""


def subject_sort_key(subject: str) -> Tuple[int, str]:
    if subject.endswith("汇总"):
        return (99, subject)
    if subject in SUBJECT_ORDER:
        return (SUBJECT_ORDER.index(subject), subject)
    return (50, subject)


def latest_dates(history: pd.DataFrame, limit: int = MAX_DATE_COLUMNS) -> List[str]:
    dates = sorted(history["日期"].dropna().unique(), reverse=True)
    return dates[:limit]


def lookup_rate(
    history: pd.DataFrame,
    dt: str,
    oc: str,
    xuebu: str,
    subject: str,
    metric: str,
) -> Optional[float]:
    mask = (
        (history["日期"] == dt)
        & (history["运营中心"] == oc)
        & (history["学部"] == xuebu)
        & (history["学科"] == subject)
    )
    rows = history.loc[mask]
    if rows.empty:
        return None
    val = rows.iloc[-1][metric]
    return float(val) if pd.notna(val) else None


def build_pivot_table(history: pd.DataFrame, dates: List[str]) -> str:
    if history.empty or not dates:
        return '<p class="dashboard-sub">暂无历史数据</p>'

    centers = sorted(history["运营中心"].dropna().unique())
    date_headers = []
    sub_headers = []
    for dt in dates:
        label = dt.replace("-", "/")
        date_headers.append(f"<th colspan='2'>{escape(label)}</th>")
        sub_headers.append("<th>风灵app在线率</th><th>风灵pc在线率</th>")

    body_rows: List[str] = []
    for oc in centers:
        oc_rows: List[str] = []
        xuebus = [x for x in XUEBU_ORDER if x in set(history.loc[history["运营中心"] == oc, "学部"])]
        extra = sorted(set(history.loc[history["运营中心"] == oc, "学部"]) - set(xuebus))
        xuebus.extend(extra)

        for xuebu in xuebus:
            subjects = sorted(
                {
                    s
                    for s in history.loc[
                        (history["运营中心"] == oc) & (history["学部"] == xuebu), "学科"
                    ].astype(str)
                    if not str(s).endswith("汇总")
                },
                key=subject_sort_key,
            )
            subjects.append(f"{xuebu} 汇总")
            for idx, subject in enumerate(subjects):
                cells = []
                if idx == 0:
                    cells.append(f'<td rowspan="{len(subjects)}" class="left-group">{escape(xuebu)}</td>')
                cls = "summary-row" if subject.endswith("汇总") else ""
                cells.append(f'<td class="{cls}">{escape(subject)}</td>')
                for dt in dates:
                    app = lookup_rate(history, dt, oc, xuebu, subject, "app_rate")
                    pc = lookup_rate(history, dt, oc, xuebu, subject, "pc_rate")
                    cells.append(
                        f'<td class="rate-blue{rate_class(app)}">{pct_text(app)}</td>'
                        f'<td class="rate-blue{rate_class(pc)}">{pct_text(pc)}</td>'
                    )
                oc_rows.append("<tr>" + "".join(cells) + "</tr>")

        if not oc_rows:
            continue
        oc_rows[0] = oc_rows[0].replace("<tr>", f'<tr><td rowspan="{len(oc_rows)}" class="left-group">{escape(oc)}</td>', 1)
        body_rows.extend(oc_rows)

    return f"""
<table class="sheet-table changqi-table">
  <thead>
    <tr>
      <th rowspan="2">运营中心</th>
      <th rowspan="2">学部</th>
      <th rowspan="2">学科</th>
      {''.join(date_headers)}
    </tr>
    <tr>{''.join(sub_headers)}</tr>
  </thead>
  <tbody>
    {''.join(body_rows)}
  </tbody>
</table>
"""


def build_detail_page(detail: pd.DataFrame, latest_date: str) -> str:
    day_df = detail[detail["日期"] == latest_date].copy()
    if day_df.empty:
        return "<p class='dashboard-sub'>暂无明细数据</p>"

    sections: List[str] = []
    for xuebu in [x for x in XUEBU_ORDER if x in set(day_df["学部"])]:
        xdf = day_df[day_df["学部"] == xuebu]
        subjects = sorted(xdf["学科"].unique(), key=subject_sort_key)
        for subject in subjects:
            sdf = xdf[xdf["学科"] == subject].sort_values(["年级", "姓名"])
            rows = []
            for i, row in enumerate(sdf.itertuples(index=False), 1):
                app_cls = rate_class(row.app_rate)
                pc_cls = rate_class(row.pc_rate)
                rows.append(
                    "<tr>"
                    f"<td>{i}</td>"
                    f"<td>{escape(str(row.年级))}</td>"
                    f"<td>{escape(str(row.姓名))}</td>"
                    f'<td class="rate-yellow{app_cls}">{pct_text(row.app_rate)}</td>'
                    f'<td class="rate-yellow{pc_cls}">{pct_text(row.pc_rate)}</td>'
                    f"<td>{escape(str(getattr(row, 'app不在线时间段', '') or ''))}</td>"
                    f"<td>{escape(str(getattr(row, 'pc不在线时间段', '') or ''))}</td>"
                    "</tr>"
                )
            sections.append(
                f"""
<section class="detail-block">
  <h2 class="section-title">{escape(xuebu)} · {escape(subject)}</h2>
  <table class="sheet-table mini-table">
    <thead>
      <tr>
        <th>序号</th><th>年级</th><th>姓名</th>
        <th>风灵app在线率</th><th>风灵pc在线率</th>
        <th>app不在线时段</th><th>pc不在线时段</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
"""
            )

    title = f"长期班风灵在线明细（{latest_date}）"
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
{base_styles(scale=0.55)}
.detail-block {{ margin-bottom: 22px; }}
.changqi-table th, .changqi-table td {{ font-size: 22px; }}
  </style>
  {analytics_head_html(title)}
</head>
<body>
  <div class="page">
    <a class="nav-link" href="../长期班风灵在线看板.html">← 返回长期班看板</a>
    <h1 class="main-title">{title}</h1>
    {''.join(sections)}
  </div>
</body>
</html>
"""


def build_main_page(history: pd.DataFrame, latest_date: str) -> str:
    dates = latest_dates(history)
    build_stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = "长期班风灵在线看板（郑州）"
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
{base_styles(scale=0.7)}
.changqi-table th, .changqi-table td {{ font-size: 24px; }}
.changqi-entry {{ background: linear-gradient(135deg, #fef3c7 0%, #ffffff 100%); border-left: 8px solid #f59e0b; }}
  </style>
  {analytics_head_html(title)}
</head>
<body>
  <div class="page">
    <a class="nav-link" href="每日三表汇总看板.html">← 返回每日看板</a>
    <h1 class="dashboard-title">{title}</h1>
    <div class="dashboard-sub">最新数据日期：{escape(latest_date or '暂无')}｜页面版本：{build_stamp}</div>
    <div class="weekly-inline-link-wrap">
      <a class="weekly-inline-link" href="长期班风灵在线看板_详情/detail.html">学习管理师在线明细（点击进入）</a>
    </div>
    {build_pivot_table(history, dates)}
  </div>
</body>
</html>
"""


def main(source_path: str = "", downloads_dir: str = "") -> None:
    src = Path(source_path) if source_path else find_latest_source(Path(downloads_dir or Path.home() / "Downloads"))
    if src is None or not src.exists():
        raise FileNotFoundError("未找到长期班源文件：长期班辅导风灵在线明细数据_*.xlsx")

    raw = load_source(src)
    history_new = aggregate_history(raw)

    history_existing = pd.read_csv(CHANGQI_HISTORY_CSV) if CHANGQI_HISTORY_CSV.exists() else pd.DataFrame()
    history = merge_history(history_existing, history_new)
    CHANGQI_HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(CHANGQI_HISTORY_CSV, index=False, encoding="utf-8-sig")

    detail_existing = pd.read_csv(CHANGQI_DETAIL_CSV) if CHANGQI_DETAIL_CSV.exists() else pd.DataFrame()
    detail = merge_detail(detail_existing, raw)
    detail.to_csv(CHANGQI_DETAIL_CSV, index=False, encoding="utf-8-sig")

    latest_date = sorted(raw["日期"].unique())[-1]
    CHANGQI_DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    (CHANGQI_DETAIL_DIR / "detail.html").write_text(build_detail_page(detail, latest_date), encoding="utf-8")
    CHANGQI_HTML.write_text(build_main_page(history, latest_date), encoding="utf-8")

    print(f"Source: {src}")
    print(f"Generated: {CHANGQI_HTML}")
    print(f"Generated: {CHANGQI_DETAIL_DIR / 'detail.html'}")
    print(f"History: {CHANGQI_HISTORY_CSV} ({len(history)} rows)")
    print(f"Latest date: {latest_date}, people: {len(raw[raw['日期'] == latest_date])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成长期班风灵在线看板")
    parser.add_argument("--source", default="", help="长期班源 Excel 路径")
    parser.add_argument("--downloads-dir", default="", help="Downloads 目录，用于自动查找最新源文件")
    args = parser.parse_args()
    main(source_path=args.source, downloads_dir=args.downloads_dir)

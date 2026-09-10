from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from build_daily_web_dashboard import analytics_head_html, base_styles


ROOT = Path(__file__).resolve().parent
CHANGQI_HTML = ROOT / "长期班风灵在线看板.html"
CHANGQI_WEEKLY_HTML = ROOT / "长期班周维度在线率看板.html"
CHANGQI_DETAIL_DIR = ROOT / "长期班风灵在线看板_详情"
CHANGQI_HISTORY_CSV = ROOT / "changqi_history.csv"
CHANGQI_DETAIL_CSV = ROOT / "changqi_detail_history.csv"

SUBJECT_ORDER = ["英语", "语文", "数学", "物理", "化学"]
UNKNOWN_SUBJECT = "未分学科"
XUEBU_ORDER = ["初中", "高中", "小学"]
MAX_DATE_COLUMNS = 14
COMPLIANCE_THRESHOLD = 0.999
XUEBU_STYLES = {
    "初中": ("segment-chuduan", "#3b82f6"),
    "高中": ("segment-gaoduan", "#f97316"),
    "小学": ("segment-xiaoduan", "#22c55e"),
}
CHANGQI_WEEKDAY_NAMES = ["周四", "周五", "周六", "周日", "周一"]


def find_latest_source(downloads_dir: Path) -> Optional[Path]:
    candidates = sorted(
        downloads_dir.glob("长期班辅导风灵在线明细数据_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def normalize_subject(value) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text if text in SUBJECT_ORDER else ""


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
    for col in ("运营中心", "学部", "年级", "姓名", "邮箱"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
            df.loc[df[col].str.lower().eq("nan"), col] = ""
    if "学科" in df.columns:
        df["学科"] = df["学科"].map(normalize_subject)
    df["app_rate"] = pd.to_numeric(df.get("app_rate"), errors="coerce")
    df["pc_rate"] = pd.to_numeric(df.get("pc_rate"), errors="coerce")
    return df.dropna(subset=["日期"]).copy()


def aggregate_history(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = ["日期", "运营中心", "学部", "学科"]
    subject_df = df[df["学科"].astype(str).str.strip().ne("")].copy()
    for group_keys, gdf in subject_df.groupby(keys, dropna=False):
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
    combined["学科"] = combined["学科"].fillna("").astype(str).str.strip()
    combined.loc[combined["学科"].str.lower().eq("nan"), "学科"] = ""
    combined = combined[~((combined["学科"] == "") & ~combined["学科"].str.endswith("汇总"))]
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


def is_rate_compliant(value: Optional[float]) -> bool:
    return pd.notna(value) and float(value) >= COMPLIANCE_THRESHOLD


def is_non_compliant(app_rate: Optional[float], pc_rate: Optional[float]) -> bool:
    return not (is_rate_compliant(app_rate) and is_rate_compliant(pc_rate))


def has_offline_slot(value) -> bool:
    text = "" if pd.isna(value) else str(value).strip()
    return bool(text) and text != ":-:"


def has_any_offline_slot(app_slot, pc_slot) -> bool:
    return has_offline_slot(app_slot) or has_offline_slot(pc_slot)


def _time_to_minutes(hhmm: str) -> int:
    hour, minute = map(int, hhmm.split(":"))
    return hour * 60 + minute


def _minutes_to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _parse_offline_slot(slot: str) -> Optional[Tuple[int, int]]:
    piece = slot.strip()
    if not piece or "-" not in piece:
        return None
    start_text, end_text = piece.split("-", 1)
    try:
        return _time_to_minutes(start_text.strip()), _time_to_minutes(end_text.strip())
    except ValueError:
        return None


def summarize_offline_slots(value) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if not text or text == ":-:":
        return ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    intervals: List[Tuple[int, int]] = []
    for part in parts:
        parsed = _parse_offline_slot(part)
        if parsed is not None:
            intervals.append(parsed)
    if not intervals:
        return text
    intervals.sort(key=lambda item: item[0])
    merged: List[Tuple[int, int]] = []
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    return ",".join(f"{_minutes_to_hhmm(start)}-{_minutes_to_hhmm(end)}" for start, end in merged)


def format_offline_slot_display(value) -> str:
    raw = "" if pd.isna(value) else str(value).strip()
    if not raw or raw == ":-:":
        return "-"
    summarized = summarize_offline_slots(raw)
    if not summarized:
        return "-"
    ranges = [part.strip() for part in summarized.split(",") if part.strip()]
    body = ",<br>".join(escape(part) for part in ranges)
    raw_count = len([part for part in raw.split(",") if part.strip()])
    if len(ranges) > 1 or raw_count > len(ranges):
        return f'<span class="slot-summary">共{len(ranges)}段（原{raw_count}个时段）</span><br>{body}'
    return body


def detail_page_styles() -> str:
    return """
body { margin: 0; padding: 16px; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f7f8fc; color: #111827; }
.page { max-width: 1100px; margin: 0 auto; }
.nav-link { display: inline-block; margin-bottom: 12px; color: #1d4ed8; text-decoration: none; font-weight: 700; }
.main-title { text-align: center; color: #7e22ce; font-size: 28px; margin: 0 0 16px; }
.dashboard-sub { text-align: center; color: #64748b; margin-bottom: 16px; }
.segment-block { background: #fff; border: 1px solid #dbe2ef; border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; }
.segment-name { margin: 0 0 10px; font-size: 22px; color: #0f172a; }
.section-title { margin: 14px 0 8px; font-size: 18px; color: #334155; }
.table-wrap { overflow-x: auto; }
.detail-table { width: 100%; border-collapse: collapse; background: #fff; table-layout: fixed; }
.detail-table th, .detail-table td { border: 2px solid #111827; padding: 6px 8px; text-align: center; font-size: 16px; line-height: 1.35; }
.detail-table thead th { background: #0c6cb3; color: #fff; font-weight: 800; white-space: nowrap; }
.detail-table .col-name { text-align: center; white-space: nowrap; }
.detail-table .col-slot { text-align: left; white-space: normal; word-break: break-word; font-size: 14px; vertical-align: top; }
.slot-summary { display: inline-block; margin-bottom: 4px; font-size: 12px; color: #64748b; font-weight: 700; }
.detail-table .col-rate { white-space: nowrap; }
.rate-yellow { background: linear-gradient(90deg, #fde89f 0%, #fff9ea 100%); font-weight: 800; }
.rate-low { color: #b91c1c !important; background: #fee2e2 !important; font-weight: 800; }
"""


def subject_sort_key(subject) -> Tuple[int, str]:
    subject = str(subject).strip() if pd.notna(subject) else UNKNOWN_SUBJECT
    if subject in ("", "nan"):
        subject = UNKNOWN_SUBJECT
    if subject.endswith("汇总"):
        return (99, subject)
    if subject == UNKNOWN_SUBJECT:
        return (98, subject)
    if subject in SUBJECT_ORDER:
        return (SUBJECT_ORDER.index(subject), subject)
    return (50, subject)


def display_subjects(history: pd.DataFrame, oc: str, xuebu: str) -> List[str]:
    available = set(
        history.loc[
            (history["运营中心"] == oc) & (history["学部"] == xuebu), "学科"
        ].astype(str)
    )
    return [s for s in SUBJECT_ORDER if s in available]


def latest_dates(history: pd.DataFrame, limit: int = MAX_DATE_COLUMNS) -> List[str]:
    dates = sorted(history["日期"].dropna().unique(), reverse=True)
    return dates[:limit]


def changqi_week_start(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 3) % 7)


def changqi_week_days(week_start: date) -> List[str]:
    return [(week_start + timedelta(days=i)).isoformat() for i in range(5)]


def is_changqi_report_day(d: date) -> bool:
    return d.weekday() in (0, 3, 4, 5, 6)


def filter_weekly_history(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    df = history.copy()
    dt = pd.to_datetime(df["日期"], errors="coerce")
    mask = dt.apply(lambda value: is_changqi_report_day(value.date()) if pd.notna(value) else False)
    return df.loc[mask].copy()


def prepare_changqi_history_records(history: pd.DataFrame) -> List[dict]:
    records: List[dict] = []
    for _, row in history.iterrows():
        records.append(
            {
                "date": str(row["日期"]),
                "oc": str(row["运营中心"]),
                "xuebu": str(row["学部"]),
                "subject": str(row["学科"]),
                "app_rate": float(row["app_rate"]) if pd.notna(row.get("app_rate")) else None,
                "pc_rate": float(row["pc_rate"]) if pd.notna(row.get("pc_rate")) else None,
                "headcount": int(row["headcount"]) if pd.notna(row.get("headcount")) else None,
            }
        )
    return records


def available_changqi_week_starts(history: pd.DataFrame, today: date) -> List[str]:
    weekly = filter_weekly_history(history)
    if weekly.empty:
        return [changqi_week_start(today).isoformat()]
    dt = pd.to_datetime(weekly["日期"], errors="coerce").dropna()
    week_starts = {changqi_week_start(value.date()).isoformat() for value in dt}
    week_starts.add(changqi_week_start(today).isoformat())
    return sorted(week_starts, reverse=True)


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


def build_pivot_table_for_xuebu(history: pd.DataFrame, dates: List[str], xuebu: str) -> str:
    part = history[history["学部"] == xuebu].copy()
    if part.empty or not dates:
        return f'<p class="dashboard-sub">{escape(xuebu)}暂无历史数据</p>'

    centers = sorted(part["运营中心"].dropna().unique())
    date_headers = []
    sub_headers = []
    for dt in dates:
        label = dt.replace("-", "/")
        date_headers.append(f"<th colspan='2'>{escape(label)}</th>")
        sub_headers.append("<th>风灵app在线率</th><th>风灵pc在线率</th>")

    body_rows: List[str] = []
    for oc in centers:
        subjects = display_subjects(part, oc, xuebu)
        subjects.append(f"{xuebu} 汇总")
        oc_rows: List[str] = []
        for idx, subject in enumerate(subjects):
            cls = "summary-row" if subject.endswith("汇总") else ""
            cells = [f'<td class="{cls}">{escape(subject)}</td>']
            for dt in dates:
                app = lookup_rate(part, dt, oc, xuebu, subject, "app_rate")
                pc = lookup_rate(part, dt, oc, xuebu, subject, "pc_rate")
                cells.append(
                    f'<td class="rate-blue{rate_class(app)}">{pct_text(app)}</td>'
                    f'<td class="rate-blue{rate_class(pc)}">{pct_text(pc)}</td>'
                )
            oc_rows.append("<tr>" + "".join(cells) + "</tr>")
        oc_rows[0] = oc_rows[0].replace(
            "<tr>",
            f'<tr><td rowspan="{len(oc_rows)}" class="left-group">{escape(oc)}</td>',
            1,
        )
        body_rows.extend(oc_rows)

    return f"""
<table class="sheet-table changqi-table">
  <thead>
    <tr>
      <th rowspan="2">运营中心</th>
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


def build_pivot_sections(history: pd.DataFrame, dates: List[str]) -> str:
    if history.empty or not dates:
        return '<p class="dashboard-sub">暂无历史数据</p>'

    sections: List[str] = []
    for xuebu in XUEBU_ORDER:
        if xuebu not in set(history["学部"].astype(str)):
            continue
        style_cls, border_color = XUEBU_STYLES.get(xuebu, ("segment-block", "#6d28d9"))
        sections.append(
            f"""
<section class="segment-block {style_cls}" style="border-left:8px solid {border_color}">
  <h2 class="segment-name">{escape(xuebu)}</h2>
  {build_pivot_table_for_xuebu(history, dates, xuebu)}
</section>
"""
        )
    return "".join(sections) if sections else '<p class="dashboard-sub">暂无历史数据</p>'


def build_detail_page(detail: pd.DataFrame, latest_date: str) -> str:
    day_df = detail[detail["日期"] == latest_date].copy()
    if day_df.empty:
        return "<p class='dashboard-sub'>暂无明细数据</p>"

    day_df = day_df[
        day_df.apply(
            lambda r: has_any_offline_slot(r.get("app不在线时间段"), r.get("pc不在线时间段")),
            axis=1,
        )
    ].copy()
    if day_df.empty:
        body = "<p class='dashboard-sub'>当日无不在线时段记录。</p>"
        title = f"长期班不在线时段明细（{latest_date}）"
        return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{detail_page_styles()}</style>
  {analytics_head_html(title)}
</head>
<body>
  <div class="page">
    <a class="nav-link" href="../长期班风灵在线看板.html">← 返回长期班看板</a>
    <h1 class="main-title">{title}</h1>
    {body}
  </div>
</body>
</html>
"""

    sections: List[str] = []
    for xuebu in [x for x in XUEBU_ORDER if x in set(day_df["学部"])]:
        xdf = day_df[day_df["学部"] == xuebu]
        style_cls, border_color = XUEBU_STYLES.get(xuebu, ("segment-block", "#6d28d9"))
        subject_sections: List[str] = []
        xdf = xdf.copy()
        xdf["展示学科"] = (
            xdf["学科"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace({"": UNKNOWN_SUBJECT, "nan": UNKNOWN_SUBJECT})
        )
        subjects = sorted(xdf["展示学科"].unique(), key=subject_sort_key)
        for subject in subjects:
            sdf = xdf[xdf["展示学科"] == subject].sort_values(["年级", "姓名"])
            if sdf.empty:
                continue
            rows = []
            seq = 0
            for row in sdf.itertuples(index=False):
                if not has_any_offline_slot(
                    getattr(row, "app不在线时间段", ""),
                    getattr(row, "pc不在线时间段", ""),
                ):
                    continue
                seq += 1
                app_cls = "col-rate rate-yellow" + (" rate-low" if not is_rate_compliant(row.app_rate) else "")
                pc_cls = "col-rate rate-yellow" + (" rate-low" if not is_rate_compliant(row.pc_rate) else "")
                app_slot = format_offline_slot_display(getattr(row, "app不在线时间段", ""))
                pc_slot = format_offline_slot_display(getattr(row, "pc不在线时间段", ""))
                rows.append(
                    "<tr>"
                    f"<td>{seq}</td>"
                    f"<td>{escape(str(row.年级) or '')}</td>"
                    f'<td class="col-name">{escape(str(row.姓名))}</td>'
                    f'<td class="{app_cls}">{pct_text(row.app_rate)}</td>'
                    f'<td class="{pc_cls}">{pct_text(row.pc_rate)}</td>'
                    f'<td class="col-slot">{app_slot}</td>'
                    f'<td class="col-slot">{pc_slot}</td>'
                    "</tr>"
                )
            if not rows:
                continue
            subject_sections.append(
                f"""
  <h3 class="section-title">{escape(subject)}</h3>
  <div class="table-wrap">
  <table class="detail-table">
    <thead>
      <tr>
        <th style="width:52px">序号</th>
        <th style="width:64px">年级</th>
        <th style="width:88px">姓名</th>
        <th style="width:10%">风灵app在线率</th>
        <th style="width:10%">风灵pc在线率</th>
        <th style="width:28%">app不在线时段</th>
        <th style="width:28%">pc不在线时段</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
"""
            )
        if subject_sections:
            sections.append(
                f"""
<section class="segment-block {style_cls} detail-block" style="border-left:8px solid {border_color}">
  <h2 class="segment-name">{escape(xuebu)}（不在线 {len(xdf)} 人）</h2>
  {''.join(subject_sections)}
</section>
"""
            )

    title = f"长期班不在线时段明细（{latest_date}）"
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{detail_page_styles()}</style>
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


def build_weekly_page(history: pd.DataFrame, latest_date: str) -> str:
    weekly_history = filter_weekly_history(history)
    today = datetime.strptime(latest_date, "%Y-%m-%d").date() if latest_date else date.today()
    week_options = available_changqi_week_starts(weekly_history, today)
    default_week = changqi_week_start(today).isoformat()
    history_records = prepare_changqi_history_records(weekly_history)
    build_stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = "长期班周维度在线率看板（郑州）"
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
{base_styles(scale=0.7)}
.changqi-table th, .changqi-table td {{ font-size: 22px; }}
.segment-block {{ margin-bottom: 18px; }}
.segment-chuduan {{ background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%); }}
.segment-gaoduan {{ background: linear-gradient(135deg, #fff7ed 0%, #ffffff 100%); }}
.segment-xiaoduan {{ background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%); }}
.segment-name {{ margin: 0 0 12px; font-size: 28px; color: #0f172a; }}
.weekly-query-bar {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 10px; margin: 0 0 14px; padding: 12px 14px; background: #fff; border: 1px solid #dbe2ef; border-radius: 10px; }}
.weekly-query-bar label {{ font-size: 16px; font-weight: 700; color: #334155; }}
.weekly-query-bar select {{ min-width: 320px; font-size: 15px; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; }}
.weekly-query-btn {{ font-size: 14px; font-weight: 700; padding: 8px 14px; border: 1px solid #cbd5e1; border-radius: 8px; background: #f8fafc; color: #1d4ed8; cursor: pointer; }}
.section-title {{ font-size: 20px; margin: 12px 0 8px; color: #334155; font-weight: 700; }}
.subject-summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 14px; }}
.subject-summary-card {{ border: 1px solid #dbe2ef; border-radius: 10px; background: #fff; padding: 10px 12px; }}
.subject-summary-name {{ font-size: 16px; font-weight: 800; color: #0f172a; margin-bottom: 6px; }}
.subject-chart-grid {{ margin-bottom: 12px; }}
  </style>
  {analytics_head_html(title)}
</head>
<body>
  <div class="page">
    <a class="nav-link" href="长期班风灵在线看板.html">← 返回长期班每日看板</a>
    <h1 class="dashboard-title">{title}</h1>
    <div class="weekly-query-bar">
      <label for="weekSelect">历史周查询（周四至周一）</label>
      <select id="weekSelect" aria-label="选择历史周"></select>
      <button type="button" class="weekly-query-btn" id="prevWeekBtn">上一周</button>
      <button type="button" class="weekly-query-btn" id="nextWeekBtn">下一周</button>
    </div>
    <div class="dashboard-sub" id="weekSubtitle"></div>
    <div class="dashboard-sub">页面版本：{build_stamp}｜不含周二、周三</div>
    <section class="weekly-grid" id="weeklyCards"></section>
    <section class="chart-grid">
      <div class="chart-card">
        <h3 class="chart-title">风灵app在线率趋势（%）</h3>
        <canvas id="appTrend"></canvas>
      </div>
      <div class="chart-card">
        <h3 class="chart-title">风灵pc在线率趋势（%）</h3>
        <canvas id="pcTrend"></canvas>
      </div>
    </section>
    <div id="weeklySections"></div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    const HISTORY = {json.dumps(history_records, ensure_ascii=False)};
    const WEEK_OPTIONS = {json.dumps(week_options, ensure_ascii=False)};
    const DEFAULT_WEEK = {json.dumps(default_week, ensure_ascii=False)};
    const TODAY_WEEK = {json.dumps(default_week, ensure_ascii=False)};
    const XUEBU_ORDER = {json.dumps(XUEBU_ORDER, ensure_ascii=False)};
    const SUBJECT_ORDER = {json.dumps(SUBJECT_ORDER, ensure_ascii=False)};
    const WEEKDAY_NAMES = {json.dumps(CHANGQI_WEEKDAY_NAMES, ensure_ascii=False)};
    const XUEBU_COLORS = {{ "初中": "#3b82f6", "高中": "#f97316", "小学": "#22c55e" }};
    const SUBJECT_COLORS = {{ "英语": "#3b82f6", "语文": "#8b5cf6", "数学": "#f97316", "物理": "#22c55e", "化学": "#e11d48" }};
    const XUEBU_CARD_CLS = {{ "初中": "weekly-chuduan1", "高中": "weekly-gaoduan", "小学": "weekly-xiaoduan" }};

    const charts = {{}};
    const weekSelect = document.getElementById("weekSelect");
    const prevWeekBtn = document.getElementById("prevWeekBtn");
    const nextWeekBtn = document.getElementById("nextWeekBtn");
    const weeklySections = document.getElementById("weeklySections");

    function addDays(iso, days) {{
      const parts = iso.split("-").map(Number);
      const dt = new Date(parts[0], parts[1] - 1, parts[2]);
      dt.setDate(dt.getDate() + days);
      const y = dt.getFullYear();
      const m = String(dt.getMonth() + 1).padStart(2, "0");
      const d = String(dt.getDate()).padStart(2, "0");
      return `${{y}}-${{m}}-${{d}}`;
    }}

    function weekDays(weekStart) {{
      return Array.from({{ length: 5 }}, (_, i) => addDays(weekStart, i));
    }}

    function dayLabels(days) {{
      return days.map((dt, idx) => `${{WEEKDAY_NAMES[idx]}}\\n${{dt.slice(5).replace("-", "/")}}`);
    }}

    function weekLabel(weekStart) {{
      const days = weekDays(weekStart);
      let suffix = "";
      if (weekStart === TODAY_WEEK) suffix = "（本周）";
      else if (weekStart === addDays(TODAY_WEEK, -7)) suffix = "（上周）";
      return `${{weekStart}} ~ ${{days[4]}}（周四至周一）${{suffix}}`;
    }}

    function pct(v) {{
      if (v === null || v === undefined || Number.isNaN(v)) return "#N/A";
      return (v * 100).toFixed(2) + "%";
    }}

    function avg(values) {{
      const nums = values.filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
      if (!nums.length) return null;
      return nums.reduce((a, b) => a + b, 0) / nums.length;
    }}

    function kpiClass(v) {{
      if (v === null || v === undefined || Number.isNaN(v)) return "";
      if (v < 0.5) return " kpi-low";
      if (v > 0.8) return " kpi-high";
      return "";
    }}

    function rateClass(v) {{
      if (v === null || v === undefined || Number.isNaN(v)) return "";
      if (v < 0.5) return " rate-low";
      if (v > 0.8) return " rate-high";
      return "";
    }}

    function lookupRate(rows, dt, oc, xuebu, subject, metric) {{
      const row = rows.find((item) => item.date === dt && item.oc === oc && item.xuebu === xuebu && item.subject === subject);
      if (!row) return null;
      return row[metric];
    }}

    function subjectsFor(rows, oc, xuebu) {{
      const available = new Set(rows.filter((item) => item.oc === oc && item.xuebu === xuebu && !item.subject.endsWith("汇总")).map((item) => item.subject));
      const subjects = SUBJECT_ORDER.filter((subject) => available.has(subject));
      subjects.push(`${{xuebu}} 汇总`);
      return subjects;
    }}

    function summaryRows(rows, xuebu) {{
      const summarySubject = `${{xuebu}} 汇总`;
      return rows.filter((item) => item.xuebu === xuebu && item.subject === summarySubject);
    }}

    function subjectRows(rows, xuebu, subject) {{
      return rows.filter((item) => item.xuebu === xuebu && item.subject === subject);
    }}

    function makeLineDatasets(rows, days, metric, seriesKey, seriesLabel, colorMap) {{
      const seriesNames = [...new Set(rows.map((item) => item[seriesKey]))].sort();
      return seriesNames.map((name) => {{
        const seriesRows = rows.filter((item) => item[seriesKey] === name);
        const rateMap = Object.fromEntries(seriesRows.map((row) => [row.date, row[metric]]));
        const headMap = Object.fromEntries(seriesRows.map((row) => [row.date, row.headcount]));
        return {{
          label: seriesLabel(name),
          data: days.map((dt) => {{
            const val = rateMap[dt];
            return val === null || val === undefined ? null : Math.round(val * 10000) / 100;
          }}),
          headcounts: days.map((dt) => headMap[dt] ?? null),
          borderColor: colorMap[name] || "#334155",
          backgroundColor: colorMap[name] || "#334155",
          tension: 0.25,
          spanGaps: true,
        }};
      }});
    }}

    const tooltipCb = {{
      callbacks: {{
        label: function(ctx) {{
          const ds = ctx.dataset;
          const i = ctx.dataIndex;
          const head = ds.headcounts ? ds.headcounts[i] : null;
          if (head === null || head === undefined) {{
            return `${{ds.label}}: ${{ctx.formattedValue}}%`;
          }}
          return `${{ds.label}}: ${{ctx.formattedValue}}% (${{head}}人)`;
        }}
      }}
    }};

    const commonOptions = {{
      responsive: true,
      plugins: Object.assign({{ legend: {{ position: "bottom" }} }}, tooltipCb),
      scales: {{ y: {{ min: 0, max: 100 }} }}
    }};

    function ensureChart(id, labels, datasets) {{
      if (charts[id]) {{
        charts[id].data.labels = labels;
        charts[id].data.datasets = datasets;
        charts[id].update();
        return;
      }}
      charts[id] = new Chart(document.getElementById(id), {{
        type: "line",
        data: {{ labels, datasets }},
        options: commonOptions
      }});
    }}

    function renderXuebuCards(rows) {{
      const container = document.getElementById("weeklyCards");
      container.innerHTML = XUEBU_ORDER.map((xuebu) => {{
        const segRows = summaryRows(rows, xuebu);
        const cardCls = XUEBU_CARD_CLS[xuebu] || "";
        if (!segRows.length) {{
          return `<div class="weekly-card ${{cardCls}}"><div class="weekly-seg">${{xuebu}}</div><div class="weekly-kpi">该周暂无数据</div></div>`;
        }}
        const appAvg = avg(segRows.map((row) => row.app_rate));
        const pcAvg = avg(segRows.map((row) => row.pc_rate));
        return `<div class="weekly-card ${{cardCls}}">
          <div class="weekly-seg">${{xuebu}} 汇总</div>
          <div class="weekly-kpi">风灵app周均值：<span class="kpi-value${{kpiClass(appAvg)}}">${{pct(appAvg)}}</span></div>
          <div class="weekly-kpi">风灵pc周均值：<span class="kpi-value${{kpiClass(pcAvg)}}">${{pct(pcAvg)}}</span></div>
        </div>`;
      }}).join("");
    }}

    function renderSubjectSummary(rows, xuebu) {{
      const subjects = SUBJECT_ORDER.filter((subject) => subjectRows(rows, xuebu, subject).length);
      if (!subjects.length) return "";
      const cards = subjects.map((subject) => {{
        const srows = subjectRows(rows, xuebu, subject);
        const appAvg = avg(srows.map((row) => row.app_rate));
        const pcAvg = avg(srows.map((row) => row.pc_rate));
        return `<div class="subject-summary-card">
          <div class="subject-summary-name">${{subject}}</div>
          <div class="weekly-kpi">app周均值：<span class="kpi-value${{kpiClass(appAvg)}}">${{pct(appAvg)}}</span></div>
          <div class="weekly-kpi">pc周均值：<span class="kpi-value${{kpiClass(pcAvg)}}">${{pct(pcAvg)}}</span></div>
        </div>`;
      }}).join("");
      return `<div class="subject-summary-grid">${{cards}}</div>`;
    }}

    function destroySubjectCharts() {{
      Object.keys(charts).forEach((id) => {{
        if (id === "appTrend" || id === "pcTrend") return;
        charts[id].destroy();
        delete charts[id];
      }});
    }}

    function buildXuebuSection(rows, days, xuebu) {{
      const tableHtml = buildXuebuTable(rows, days, xuebu);
      if (!tableHtml) return "";
      const appChartId = `appSubject_${{xuebu}}`;
      const pcChartId = `pcSubject_${{xuebu}}`;
      const styleMap = {{ "初中": "segment-chuduan", "高中": "segment-gaoduan", "小学": "segment-xiaoduan" }};
      const colorMap = {{ "初中": "#3b82f6", "高中": "#f97316", "小学": "#22c55e" }};
      return `
<section class="segment-block ${{styleMap[xuebu] || ""}}" style="border-left:8px solid ${{colorMap[xuebu] || "#6d28d9"}}">
  <h2 class="segment-name">${{xuebu}}</h2>
  <h3 class="section-title">分学科周汇总</h3>
  ${{renderSubjectSummary(rows, xuebu)}}
  <div class="chart-grid subject-chart-grid">
    <div class="chart-card">
      <h3 class="chart-title">${{xuebu}} · 风灵app在线率（分学科）</h3>
      <canvas id="${{appChartId}}"></canvas>
    </div>
    <div class="chart-card">
      <h3 class="chart-title">${{xuebu}} · 风灵pc在线率（分学科）</h3>
      <canvas id="${{pcChartId}}"></canvas>
    </div>
  </div>
  <h3 class="section-title">分学科每日明细</h3>
  ${{tableHtml}}
</section>`;
    }}

    function renderSubjectCharts(rows, days) {{
      const labels = dayLabels(days);
      XUEBU_ORDER.forEach((xuebu) => {{
        if (!rows.some((item) => item.xuebu === xuebu)) return;
        const subjectChartRows = rows.filter((item) => item.xuebu === xuebu && !item.subject.endsWith("汇总"));
        ensureChart(`appSubject_${{xuebu}}`, labels, makeLineDatasets(subjectChartRows, days, "app_rate", "subject", (name) => name, SUBJECT_COLORS));
        ensureChart(`pcSubject_${{xuebu}}`, labels, makeLineDatasets(subjectChartRows, days, "pc_rate", "subject", (name) => name, SUBJECT_COLORS));
      }});
    }}

    function buildXuebuTable(rows, days, xuebu) {{
      const ocs = [...new Set(rows.filter((item) => item.xuebu === xuebu).map((item) => item.oc))].sort();
      if (!ocs.length) return "";
      const dateHeaders = days.map((dt, idx) => `<th colspan="2">${{WEEKDAY_NAMES[idx]}}<br>${{dt.replaceAll("-", "/")}}</th>`).join("");
      const subHeaders = days.map(() => "<th>风灵app在线率</th><th>风灵pc在线率</th>").join("");
      const bodyRows = [];
      for (const oc of ocs) {{
        const subjects = subjectsFor(rows, oc, xuebu);
        const ocRows = subjects.map((subject, idx) => {{
          const cls = subject.endsWith("汇总") ? "summary-row" : "";
          const cells = [`<td class="${{cls}}">${{subject}}</td>`];
          for (const dt of days) {{
            const app = lookupRate(rows, dt, oc, xuebu, subject, "app_rate");
            const pc = lookupRate(rows, dt, oc, xuebu, subject, "pc_rate");
            cells.push(`<td class="rate-blue${{rateClass(app)}}">${{pct(app)}}</td><td class="rate-blue${{rateClass(pc)}}">${{pct(pc)}}</td>`);
          }}
          const row = `<tr>${{cells.join("")}}</tr>`;
          if (idx === 0) {{
            return row.replace("<tr>", `<tr><td rowspan="${{subjects.length}}" class="left-group">${{oc}}</td>`);
          }}
          return row;
        }});
        bodyRows.push(...ocRows);
      }}
      return `
  <table class="sheet-table changqi-table">
    <thead>
      <tr><th rowspan="2">运营中心</th><th rowspan="2">学科</th>${{dateHeaders}}</tr>
      <tr>${{subHeaders}}</tr>
    </thead>
    <tbody>${{bodyRows.join("")}}</tbody>
  </table>`;
    }}

    function renderWeek(weekStart) {{
      const days = weekDays(weekStart);
      const rows = HISTORY.filter((item) => days.includes(item.date));
      const labels = dayLabels(days);
      const summaryChartRows = rows.filter((item) => item.subject.endsWith("汇总"));
      document.getElementById("weekSubtitle").textContent = weekLabel(weekStart);
      renderXuebuCards(rows);
      ensureChart("appTrend", labels, makeLineDatasets(summaryChartRows, days, "app_rate", "xuebu", (name) => `${{name}} 汇总`, XUEBU_COLORS));
      ensureChart("pcTrend", labels, makeLineDatasets(summaryChartRows, days, "pc_rate", "xuebu", (name) => `${{name}} 汇总`, XUEBU_COLORS));
      destroySubjectCharts();
      weeklySections.innerHTML = XUEBU_ORDER
        .filter((xuebu) => rows.some((item) => item.xuebu === xuebu))
        .map((xuebu) => buildXuebuSection(rows, days, xuebu))
        .join("") || '<p class="dashboard-sub">该周暂无周四至周一数据</p>';
      renderSubjectCharts(rows, days);
      weekSelect.value = weekStart;
      const idx = WEEK_OPTIONS.indexOf(weekStart);
      prevWeekBtn.disabled = idx < 0 || idx >= WEEK_OPTIONS.length - 1;
      nextWeekBtn.disabled = idx <= 0;
      const url = new URL(window.location.href);
      url.searchParams.set("week", weekStart);
      window.history.replaceState(null, "", url.toString());
    }}

    weekSelect.innerHTML = WEEK_OPTIONS.map((weekStart) => `<option value="${{weekStart}}">${{weekLabel(weekStart)}}</option>`).join("");
    weekSelect.addEventListener("change", () => renderWeek(weekSelect.value));
    prevWeekBtn.addEventListener("click", () => {{
      const idx = WEEK_OPTIONS.indexOf(weekSelect.value);
      if (idx >= 0 && idx < WEEK_OPTIONS.length - 1) renderWeek(WEEK_OPTIONS[idx + 1]);
    }});
    nextWeekBtn.addEventListener("click", () => {{
      const idx = WEEK_OPTIONS.indexOf(weekSelect.value);
      if (idx > 0) renderWeek(WEEK_OPTIONS[idx - 1]);
    }});
    const params = new URLSearchParams(window.location.search);
    const initialWeek = params.get("week");
    renderWeek(WEEK_OPTIONS.includes(initialWeek) ? initialWeek : DEFAULT_WEEK);
  </script>
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
.segment-block {{ margin-bottom: 18px; }}
.segment-chuduan {{ background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%); }}
.segment-gaoduan {{ background: linear-gradient(135deg, #fff7ed 0%, #ffffff 100%); }}
.segment-xiaoduan {{ background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%); }}
.segment-name {{ margin: 0 0 12px; font-size: 28px; color: #0f172a; }}
  </style>
  {analytics_head_html(title)}
</head>
<body>
  <div class="page">
    <a class="nav-link" href="每日三表汇总看板.html">← 返回每日看板</a>
    <h1 class="dashboard-title">{title}</h1>
    <div class="dashboard-sub">最新数据日期：{escape(latest_date or '暂无')}｜页面版本：{build_stamp}</div>
    <div class="weekly-inline-link-wrap">
      <a class="weekly-inline-link" href="长期班周维度在线率看板.html">长期班周维度在线率看板（点击进入）</a>
      <span class="weekly-inline-sep">｜</span>
      <a class="weekly-inline-link" href="长期班风灵在线看板_详情/detail.html">不在线时段明细（点击进入）</a>
    </div>
    {build_pivot_sections(history, dates)}
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

    latest_date = sorted(history["日期"].unique())[-1]
    CHANGQI_DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    (CHANGQI_DETAIL_DIR / "detail.html").write_text(build_detail_page(detail, latest_date), encoding="utf-8")
    CHANGQI_HTML.write_text(build_main_page(history, latest_date), encoding="utf-8")
    CHANGQI_WEEKLY_HTML.write_text(build_weekly_page(history, latest_date), encoding="utf-8")

    print(f"Source: {src}")
    print(f"Generated: {CHANGQI_HTML}")
    print(f"Generated: {CHANGQI_WEEKLY_HTML}")
    print(f"Generated: {CHANGQI_DETAIL_DIR / 'detail.html'}")
    print(f"History: {CHANGQI_HISTORY_CSV} ({len(history)} rows)")
    print(f"Latest date: {latest_date}, people: {len(raw[raw['日期'] == latest_date])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成长期班风灵在线看板")
    parser.add_argument("--source", default="", help="长期班源 Excel 路径")
    parser.add_argument("--downloads-dir", default="", help="Downloads 目录，用于自动查找最新源文件")
    args = parser.parse_args()
    main(source_path=args.source, downloads_dir=args.downloads_dir)

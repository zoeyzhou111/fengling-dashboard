from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Tuple
from html import escape

import pandas as pd


ROOT = Path("/Users/zoeyzhou/Desktop/工作/风灵数据")
OUTPUT_ROOT = ROOT / "每日输出"
INDEX_HTML = ROOT / "每日三表汇总看板.html"
DETAIL_DIR = ROOT / "每日三表汇总看板_详情"
TEAM_DETAIL_DIR = DETAIL_DIR / "team"

SEGMENTS = ["初短一部", "初短二部", "小短", "高短"]
SEGMENT_KEYS = {
    "初短一部": "chuduan1",
    "初短二部": "chuduan2",
    "小短": "xiaoduan",
    "高短": "gaoduan",
}


def _grade_order_key(grade_value: object) -> int:
    grade = str(grade_value or "").strip().replace(" ", "")
    base = grade.replace("汇总", "")
    order_map = {
        "新兵营": 1,
        "高一": 2,
        "高二": 3,
        "高三": 4,
        "高中": 5,
    }
    return order_map.get(base, 99)


def sort_gaoduan_auth_sales(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy().reset_index(drop=True)
    rows = []
    current_grade = ""
    for idx, row in data.iterrows():
        grade_raw = str(row.get("年级", "") or "").strip()
        team_raw = str(row.get("战队", "") or "").strip()
        if grade_raw and grade_raw.lower() != "nan" and "汇总" not in grade_raw:
            current_grade = grade_raw
        is_summary = ("汇总" in grade_raw) or ("汇总" in team_raw)
        if is_summary:
            grade_base = grade_raw.replace("汇总", "").strip() if grade_raw else current_grade
            kind = "overall_summary" if grade_base == "高短" else "grade_summary"
            logical_grade = grade_base
        else:
            logical_grade = grade_raw if (grade_raw and grade_raw.lower() != "nan") else current_grade
            kind = "detail"

        if team_raw == "溯川向上-刘炎鹤":
            logical_grade = "高二"
            if kind == "detail":
                row["年级"] = "高二"

        rows.append(
            {
                "__idx": idx,
                "__kind": kind,
                "__grade": logical_grade,
                "__row": row,
            }
        )

    kind_order = {"detail": 0, "grade_summary": 1, "overall_summary": 2}
    rows.sort(
        key=lambda x: (
            _grade_order_key(x["__grade"]),
            kind_order.get(x["__kind"], 9),
            x["__idx"],
        )
    )

    out = []
    for item in rows:
        row = item["__row"].copy()
        if item["__kind"] == "grade_summary":
            row["年级"] = f'{item["__grade"]} 汇总'
        elif item["__kind"] == "overall_summary":
            row["年级"] = "高短 汇总"
        out.append(row)
    return pd.DataFrame(out, columns=df.columns)


def sort_gaoduan_bad(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["__grade_order"] = data["年级"].apply(_grade_order_key)
    data["__team_text"] = data["战队"].fillna("").astype(str)
    data["__name_text"] = data["辅导姓名"].fillna("").astype(str)
    data = data.sort_values(
        by=["__grade_order", "__team_text", "__name_text"],
        ascending=[True, True, True],
        kind="mergesort",
    )
    return data.drop(columns=["__grade_order", "__team_text", "__name_text"])


def safe_pct(v: object) -> str:
    if pd.isna(v) or v == "":
        return "#N/A"
    try:
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return str(v)


def safe_int(v: object) -> str:
    if pd.isna(v) or v == "":
        return "#N/A"
    try:
        return str(int(float(v)))
    except Exception:
        return str(v)


def safe_text(v: object) -> str:
    if pd.isna(v) or v == "":
        return ""
    s = str(v).strip()
    if s.upper() == "#N/A":
        return ""
    return s


def team_page_name(segment_key: str, team_name: str) -> str:
    digest = hashlib.md5(f"{segment_key}|{team_name}".encode("utf-8")).hexdigest()[:12]
    return f"{segment_key}_{digest}.html"


def link_team(segment_key: str, team_name: object, href_prefix: str = "team/") -> str:
    team_text = safe_text(team_name)
    if not team_text:
        return ""
    file_name = team_page_name(segment_key, team_text)
    return f'<a class="team-link" href="{href_prefix}{file_name}">{escape(team_text)}</a>'


def is_summary_row(series: pd.Series) -> bool:
    grade = str(series.get("年级", "") or "")
    team = str(series.get("战队", "") or "")
    return ("汇总" in grade) or ("汇总" in team)


def pick_overall_summary_row(df: pd.DataFrame, total_col: str) -> pd.Series | None:
    if df.empty:
        return None
    s = df.copy()
    s = s[s["年级"].astype(str).str.contains("汇总", na=False)]
    if s.empty:
        return None
    s[total_col] = pd.to_numeric(s[total_col], errors="coerce").fillna(0)
    s = s.sort_values(total_col, ascending=False)
    return s.iloc[0]


def fill_group_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    fixed = df.copy()
    for col in cols:
        if col in fixed.columns:
            fixed[col] = fixed[col].replace("", pd.NA).ffill()
    return fixed


def group_rowspans(df: pd.DataFrame, group_cols: List[str]) -> Dict[Tuple[int, str], int]:
    spans: Dict[Tuple[int, str], int] = {}
    n = len(df)
    for col in group_cols:
        i = 0
        while i < n:
            v = df.iloc[i][col]
            j = i + 1
            while j < n and df.iloc[j][col] == v:
                j += 1
            spans[(i, col)] = j - i
            i = j
    return spans


def auth_table_html(df: pd.DataFrame, title: str, date_text: str, segment_key: str) -> str:
    cols = [
        "学部",
        "年级",
        "战队",
        "低价课带班",
        "全天在线",
        "个微全天在线率",
        "接流",
        "授权人数",
        "正常人数",
        "爱芯个微授权率",
        "个微功能正常率",
    ]
    data = df[cols].copy()
    data = fill_group_cols(data, ["学部", "年级"])
    spans = group_rowspans(data, ["学部", "年级"])
    rows = []
    for i in range(len(data)):
        row = data.iloc[i]
        summary = is_summary_row(row)
        cls = "summary-row" if summary else ""
        tds = []
        for c in cols:
            if c in {"学部", "年级"}:
                start = (i, c) in spans
                if start:
                    rs = spans[(i, c)]
                    tds.append(f'<td rowspan="{rs}" class="left-group {cls}">{safe_text(row[c])}</td>')
                else:
                    continue
            else:
                val = row[c]
                if "率" in c:
                    txt = safe_pct(val)
                    rate_cls = "rate-blue" if c == "个微全天在线率" else ("rate-green" if c == "爱芯个微授权率" else "rate-mint")
                    low_cls = ""
                    try:
                        low_cls = " rate-low" if float(val) < 0.6 else ""
                    except Exception:
                        pass
                    tds.append(f'<td class="{rate_cls}{low_cls} {cls}">{txt}</td>')
                elif c == "战队":
                    if summary:
                        tds.append(f'<td class="{cls}">{safe_text(val)}</td>')
                    else:
                        tds.append(f'<td class="{cls}">{link_team(segment_key, val)}</td>')
                else:
                    tds.append(f'<td class="{cls}">{safe_int(val)}</td>')
        rows.append(f"<tr>{''.join(tds)}</tr>")

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{base_styles(scale=0.5)}</style>
</head>
<body>
  <div class="page">
    <a class="back-link" href="../每日三表汇总看板.html">← 返回总看板</a>
    <h1 class="main-title">个微-风灵全天在线率及爱芯授权功能正常率（郑州） {date_text}</h1>
    <table class="sheet-table auth-table">
      <thead>
        <tr>
          <th>学部</th><th>年级</th><th>战队</th><th>低价课带班</th><th>全天在线</th>
          <th>个微全天在线率</th><th>接流</th><th>授权人数</th><th>正常人数</th><th>爱芯个微授权率</th><th>个微功能正常率</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def sales_table_html(df: pd.DataFrame, title: str, date_text: str, segment_key: str) -> str:
    cols = ["学部", "年级", "战队", "接流人数", "电脑端全天在线人数", "电脑端全天在线率", "手机端全天在线人数", "手机端全天在线率"]
    data = df[cols].copy()
    data = fill_group_cols(data, ["学部", "年级"])
    spans = group_rowspans(data, ["学部", "年级"])
    rows = []
    for i in range(len(data)):
        row = data.iloc[i]
        summary = is_summary_row(row)
        cls = "summary-row" if summary else ""
        tds = []
        for c in cols:
            if c in {"学部", "年级"}:
                if (i, c) in spans:
                    tds.append(f'<td rowspan="{spans[(i, c)]}" class="left-group {cls}">{safe_text(row[c])}</td>')
                else:
                    continue
            elif "率" in c:
                txt = safe_pct(row[c])
                low_cls = ""
                try:
                    low_cls = " rate-low" if float(row[c]) < 0.6 else ""
                except Exception:
                    pass
                rate_cls = "rate-blue" if "电脑" in c else "rate-yellow"
                tds.append(f'<td class="{rate_cls}{low_cls} {cls}">{txt}</td>')
            elif c == "战队":
                if summary:
                    tds.append(f'<td class="{cls}">{safe_text(row[c])}</td>')
                else:
                    tds.append(f'<td class="{cls}">{link_team(segment_key, row[c])}</td>')
            else:
                tds.append(f'<td class="{cls}">{safe_int(row[c])}</td>')
        rows.append(f"<tr>{''.join(tds)}</tr>")

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{base_styles(scale=0.5)}</style>
</head>
<body>
  <div class="page">
    <a class="back-link" href="../每日三表汇总看板.html">← 返回总看板</a>
    <h1 class="main-title">企微风灵全天在线情况通晒（郑州） {date_text}</h1>
    <table class="sheet-table sales-table">
      <thead>
        <tr>
          <th rowspan="2">学部</th>
          <th rowspan="2">年级</th>
          <th rowspan="2">战队</th>
          <th rowspan="2">接流人数</th>
          <th colspan="2" class="header-blue">电脑端全天在线情况</th>
          <th colspan="2" class="header-orange">手机端全天在线情况</th>
        </tr>
        <tr>
          <th class="header-blue">人数</th>
          <th class="header-blue">全天在线率</th>
          <th class="header-orange">人数</th>
          <th class="header-orange">全天在线率</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def bad_table_html(df: pd.DataFrame, title: str, date_text: str, segment_key: str) -> str:
    cols = ["学部", "年级", "战队", "辅导姓名", "企微-手机在线率", "企微-电脑在线率", "个微在线率"]
    data = df[cols].copy()
    data = fill_group_cols(data, ["学部", "年级", "战队"])
    spans = group_rowspans(data, ["学部", "年级", "战队"])
    rows = []
    for i in range(len(data)):
        row = data.iloc[i]
        tds = []
        for c in cols:
            if c in {"学部", "年级", "战队"}:
                if (i, c) in spans:
                    if c == "战队":
                        team_html = link_team(segment_key, row[c])
                        tds.append(f'<td rowspan="{spans[(i, c)]}" class="left-group">{team_html}</td>')
                    else:
                        tds.append(f'<td rowspan="{spans[(i, c)]}" class="left-group">{safe_text(row[c])}</td>')
                else:
                    continue
            elif "率" in c:
                val = row[c]
                if pd.isna(val) or val == "":
                    val = 0
                txt = safe_pct(val)
                warn_cls = ""
                try:
                    warn_cls = " rate-warn" if float(val) < 1 else ""
                except Exception:
                    warn_cls = " rate-warn"
                tds.append(f'<td class="{warn_cls}">{txt}</td>')
            else:
                tds.append(f"<td>{row[c]}</td>")
        rows.append(f"<tr>{''.join(tds)}</tr>")

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{base_styles(scale=0.5)}</style>
</head>
<body>
  <div class="page">
    <a class="back-link" href="../每日三表汇总看板.html">← 返回总看板</a>
    <h1 class="main-title">风灵在线未达标名单（郑州） {date_text}</h1>
    <table class="sheet-table bad-table">
      <thead>
        <tr>
          <th>学部</th><th>年级</th><th>战队</th><th>辅导姓名</th><th>企微-手机在线率</th><th>企微-电脑在线率</th><th>个微在线率</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def base_styles(scale: float = 1.0) -> str:
    css = """
* { box-sizing: border-box; }
body { margin: 0; padding: 18px; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f7f8fc; color: #111827; }
.page { max-width: 1700px; margin: 0 auto; zoom: __SCALE__; }
.back-link { text-decoration: none; color: #1d4ed8; font-weight: 700; display: inline-block; margin-bottom: 10px; }
.main-title { text-align: center; color: #7e22ce; font-size: 40px; margin: 0 0 12px; line-height: 1.2; }
.sheet-table { width: 100%; border-collapse: collapse; background: #fff; }
.sheet-table th, .sheet-table td { border: 2px solid #111827; padding: 6px 10px; text-align: center; font-size: 34px; line-height: 1.25; white-space: nowrap; }
.sheet-table thead th { background: #0c6cb3; color: #fff; font-weight: 800; }
.sheet-table .header-blue { background: #0c6cb3; color: #fff; }
.sheet-table .header-orange { background: #f59e0b; color: #fff; }
.left-group { background: #fbe7cf; font-weight: 800; }
.summary-row { background: #d9e7f7; font-weight: 800; }
.rate-blue { background: linear-gradient(90deg, #dbe5ff 0%, #f9fbff 100%); font-weight: 800; color: #1f8a3d; }
.rate-yellow { background: linear-gradient(90deg, #fde89f 0%, #fff9ea 100%); font-weight: 800; }
.rate-green { background: linear-gradient(90deg, #dcfce7 0%, #f8fff9 100%); font-weight: 800; color: #0f9d58; }
.rate-mint { background: linear-gradient(90deg, #b7f0df 0%, #f5fffb 100%); font-weight: 800; }
.rate-low { color: #b91c1c !important; }
.rate-warn { background: #f8c9d2; color: #b91c1c; font-weight: 800; }
.dashboard-title { text-align: center; color: #6d28d9; font-size: 34px; margin: 8px 0 18px; }
.dashboard-sub { text-align: center; color: #6b7280; margin-bottom: 18px; font-size: 18px; }
.segment-block { background: #fff; border: 1px solid #dbe2ef; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
.segment-name { margin: 0 0 12px; font-size: 26px; color: #0f172a; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.card-link { text-decoration: none; color: inherit; display: block; border: 1px solid #e5e7eb; border-radius: 10px; background: #f9fafb; padding: 12px; transition: .2s; min-height: 134px; }
.card-link:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(15,23,42,0.09); border-color: #c7d2fe; }
.card-auth { background: linear-gradient(135deg, #ecfeff 0%, #f8fafc 100%); border-left: 8px solid #06b6d4; }
.card-online { background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%); border-left: 8px solid #3b82f6; }
.card-bad { background: linear-gradient(135deg, #fff1f2 0%, #f8fafc 100%); border-left: 8px solid #ef4444; }
.card-label { color: #334155; font-size: 18px; font-weight: 700; margin-bottom: 8px; }
.card-value { color: #111827; font-size: 34px; font-weight: 800; line-height: 1.2; }
.card-sub { color: #64748b; font-size: 15px; margin-top: 6px; min-height: 22px; }
.team-link { color: inherit; text-decoration: none; font-weight: inherit; }
.team-link:hover { text-decoration: underline; color: #1d4ed8; }
.section-title { font-size: 24px; margin: 18px 0 8px; color: #0f172a; }
.mini-table th, .mini-table td { font-size: 28px; }
@media (max-width: 1200px) {
  .cards { grid-template-columns: 1fr; }
  .main-title { font-size: 30px; }
  .sheet-table th, .sheet-table td { font-size: 20px; }
  .page { zoom: 1; }
}
"""
    return css.replace("__SCALE__", str(scale))


def render_team_table(df: pd.DataFrame, cols: List[str], rate_cols: List[str], title: str) -> str:
    if df.empty:
        return f"""
<h2 class="section-title">{title}</h2>
<table class="sheet-table mini-table">
  <thead><tr>{''.join(f'<th>{escape(c)}</th>' for c in cols)}</tr></thead>
  <tbody><tr><td colspan="{len(cols)}">无数据</td></tr></tbody>
</table>
"""
    rows = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            v = row[c] if c in row else ""
            if c in rate_cols:
                txt = safe_pct(v if not (pd.isna(v) or v == "") else 0)
                cls = "rate-blue"
                if "手机" in c:
                    cls = "rate-yellow"
                if "授权" in c:
                    cls = "rate-green"
                if "功能" in c:
                    cls = "rate-mint"
                tds.append(f'<td class="{cls}">{txt}</td>')
            elif c in {"学部", "年级", "战队", "辅导姓名", "不在线时段list", "电脑端不在线时段list"}:
                tds.append(f"<td>{escape(safe_text(v))}</td>")
            else:
                tds.append(f"<td>{safe_int(v)}</td>")
        rows.append(f"<tr>{''.join(tds)}</tr>")
    return f"""
<h2 class="section-title">{title}</h2>
<table class="sheet-table mini-table">
  <thead><tr>{''.join(f'<th>{escape(c)}</th>' for c in cols)}</tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""


def team_detail_html(
    segment: str,
    team_name: str,
    date_text: str,
    auth_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    bad_df: pd.DataFrame,
    segment_key: str,
) -> str:
    auth_cols = [
        "学部", "年级", "战队", "低价课带班", "全天在线", "个微全天在线率", "接流", "授权人数", "正常人数", "爱芯个微授权率", "个微功能正常率"
    ]
    sales_cols = ["学部", "年级", "战队", "接流人数", "电脑端全天在线人数", "电脑端全天在线率", "手机端全天在线人数", "手机端全天在线率"]
    bad_cols = ["学部", "年级", "战队", "辅导姓名", "企微-手机在线率", "企微-电脑在线率", "个微在线率", "不在线时段list", "电脑端不在线时段list"]
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{segment}-{team_name} 战队明细</title>
  <style>{base_styles(scale=0.5)}</style>
</head>
<body>
  <div class="page">
    <a class="back-link" href="../{segment_key}_auth.html">← 返回{segment}明细页</a>
    <h1 class="main-title">{escape(segment)}｜{escape(team_name)} 战队明细（{escape(date_text)}）</h1>
    {render_team_table(auth_df, auth_cols, ["个微全天在线率", "爱芯个微授权率", "个微功能正常率"], "个微&授权明细")}
    {render_team_table(sales_df, sales_cols, ["电脑端全天在线率", "手机端全天在线率"], "企微在线明细")}
    {render_team_table(bad_df, bad_cols, ["企微-手机在线率", "企微-电脑在线率", "个微在线率"], "未达标名单明细")}
  </div>
</body>
</html>
"""


def build_offline_period_map(df: pd.DataFrame) -> pd.DataFrame:
    expected = {"学部", "年级", "战队", "辅导姓名", "不在线时段list"}
    if not expected.issubset(set(df.columns)):
        return pd.DataFrame(columns=["学部", "年级", "战队", "辅导姓名", "不在线时段list"])
    d = df[["学部", "年级", "战队", "辅导姓名", "不在线时段list"]].copy()
    d = d.dropna(subset=["辅导姓名"])
    d["学部"] = d["学部"].astype(str).str.strip()
    d["年级"] = d["年级"].astype(str).str.strip()
    d["战队"] = d["战队"].astype(str).str.strip()
    d["辅导姓名"] = d["辅导姓名"].astype(str).str.strip()
    d = d[d["辅导姓名"].ne("")]
    d["不在线时段list"] = d["不在线时段list"].fillna("").astype(str).str.strip()
    return (
        d.groupby(["学部", "年级", "战队", "辅导姓名"], dropna=False)["不在线时段list"]
        .apply(lambda s: " | ".join([x for x in pd.unique(s) if x and x.lower() != "nan"]))
        .reset_index()
    )


def build_pc_offline_period_map(df: pd.DataFrame) -> pd.DataFrame:
    expected = {"学部", "年级", "战队", "老师姓名", "pc不在线时段list"}
    if not expected.issubset(set(df.columns)):
        return pd.DataFrame(columns=["学部", "年级", "战队", "辅导姓名", "电脑端不在线时段list"])
    d = df[["学部", "年级", "战队", "老师姓名", "pc不在线时段list"]].copy()
    d = d.dropna(subset=["老师姓名"])
    d["学部"] = d["学部"].astype(str).str.strip()
    d["年级"] = d["年级"].astype(str).str.strip()
    d["战队"] = d["战队"].astype(str).str.strip()
    d["辅导姓名"] = d["老师姓名"].astype(str).str.strip()
    d = d[d["辅导姓名"].ne("")]
    d["电脑端不在线时段list"] = d["pc不在线时段list"].fillna("").astype(str).str.strip()
    grouped = (
        d.groupby(["学部", "年级", "战队", "辅导姓名"], dropna=False)["电脑端不在线时段list"]
        .apply(lambda s: " | ".join([x for x in pd.unique(s) if x and x.lower() != "nan"]))
        .reset_index()
    )
    return grouped


def build_index_page(summary_rows: List[dict], date_text: str) -> str:
    segment_html = []
    for row in summary_rows:
        segment = row["segment"]
        key = SEGMENT_KEYS[segment]
        segment_html.append(
            f"""
<section class="segment-block">
  <h2 class="segment-name">{segment}</h2>
  <div class="cards">
    <a class="card-link card-auth" href="每日三表汇总看板_详情/{key}_auth.html">
      <div class="card-label">个微授权汇总率</div>
      <div class="card-value">{row["auth_rate"]}</div>
      <div class="card-sub">点击查看：个微&授权明细表（战队维度）</div>
    </a>
    <a class="card-link card-online" href="每日三表汇总看板_详情/{key}_sales.html">
      <div class="card-label">企微在线汇总率</div>
      <div class="card-value">{row["online_rate"]}</div>
      <div class="card-sub">{row["online_sub"]}</div>
    </a>
    <a class="card-link card-bad" href="每日三表汇总看板_详情/{key}_bad.html">
      <div class="card-label">每日不在线汇总人数</div>
      <div class="card-value">{row["bad_count"]}</div>
      <div class="card-sub">点击查看：风灵在线未达标名单（战队维度）</div>
    </a>
  </div>
</section>
"""
        )
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>每日三表汇总看板</title>
  <style>{base_styles(scale=1.0)}</style>
</head>
<body>
  <div class="page">
    <h1 class="dashboard-title">每日三表汇总看板（郑州）</h1>
    <div class="dashboard-sub">{date_text}｜按学部分组｜点击卡片进入对应明细页（战队维度）</div>
    {''.join(segment_html)}
  </div>
</body>
</html>
"""


def main() -> None:
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    TEAM_DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    all_dates = []
    summary_rows: List[dict] = []

    for segment in SEGMENTS:
        seg_dir = OUTPUT_ROOT / segment
        auth_file = seg_dir / f"郑州-{segment}-风灵个微全天在线率&爱芯后台授权.xlsx"
        sales_file = seg_dir / f"郑州-{segment}-销售风灵在线率明细数据.xlsx"
        bad_file = seg_dir / f"郑州-{segment}-每日风灵不在线.xlsx"

        auth = pd.read_excel(auth_file, sheet_name="数据公示表", header=1)
        sales = pd.read_excel(sales_file, sheet_name="战队汇总透视")
        bad = pd.read_excel(bad_file, sheet_name="数据透视表", header=1)
        bad_origin = pd.read_excel(bad_file, sheet_name="原表")
        bad_sheet11 = pd.read_excel(bad_file, sheet_name="Sheet11")

        auth = auth.dropna(how="all")
        sales = sales.dropna(how="all")
        bad = bad.dropna(how="all")

        bad = bad[
            [
                "学部",
                "年级",
                "战队",
                "辅导姓名",
                "企微-手机在线率",
                "企微-电脑在线率",
                "个微在线率",
            ]
        ].copy()
        bad = bad[bad["辅导姓名"].astype(str).str.strip().ne("")]
        bad = fill_group_cols(bad, ["学部", "年级", "战队"])
        offline_map = build_offline_period_map(bad_sheet11)
        pc_offline_map = build_pc_offline_period_map(bad_origin)
        if not offline_map.empty:
            bad = bad.merge(
                offline_map,
                on=["学部", "年级", "战队", "辅导姓名"],
                how="left",
            )
        else:
            bad["不在线时段list"] = ""
        bad["不在线时段list"] = bad["不在线时段list"].fillna("").astype(str)
        if not pc_offline_map.empty:
            bad = bad.merge(
                pc_offline_map,
                on=["学部", "年级", "战队", "辅导姓名"],
                how="left",
            )
        else:
            bad["电脑端不在线时段list"] = ""
        bad["电脑端不在线时段list"] = bad["电脑端不在线时段list"].fillna("").astype(str)

        # User-specified correction: keep this team under 高二 for 高短
        if segment == "高短":
            # Keep only expected grades for 高短 bad list; removes anomalies like 六年级.
            allowed_high_grades = {"新兵营", "高一", "高二", "高三"}
            bad["__grade_clean"] = (
                bad["年级"]
                .astype(str)
                .str.strip()
                .str.replace(" ", "", regex=False)
                .str.replace("汇总", "", regex=False)
            )
            before_cnt = len(bad)
            bad = bad[bad["__grade_clean"].isin(allowed_high_grades)].copy()
            removed_cnt = before_cnt - len(bad)
            bad = bad.drop(columns=["__grade_clean"])
            if removed_cnt > 0:
                print(f"[校验] 高短不在线名单已移除异常年级行: {removed_cnt}")

            # For auth/sales: only relocate this one team during render sorting.
            # For bad list: write back grade directly since all rows are detail rows.
            bad_mask = bad["战队"].astype(str).str.strip().eq("溯川向上-刘炎鹤")
            if bad_mask.any():
                bad.loc[bad_mask, "年级"] = "高二"
            auth = sort_gaoduan_auth_sales(auth)
            sales = sort_gaoduan_auth_sales(sales)
            bad = sort_gaoduan_bad(bad)

        if "日期" in bad_origin.columns:
            valid_date = bad_origin["日期"].dropna()
            if not valid_date.empty:
                all_dates.append(str(valid_date.max()))

        auth_sum = pick_overall_summary_row(auth, "接流")
        sales_sum = pick_overall_summary_row(sales, "接流人数")

        auth_rate = safe_pct(auth_sum["爱芯个微授权率"]) if auth_sum is not None else "#N/A"
        if sales_sum is not None:
            total = pd.to_numeric(sales_sum["接流人数"], errors="coerce")
            pc = pd.to_numeric(sales_sum["电脑端全天在线人数"], errors="coerce")
            mobile = pd.to_numeric(sales_sum["手机端全天在线人数"], errors="coerce")
            if pd.notna(total) and total and pd.notna(pc) and pd.notna(mobile):
                online = (float(pc) + float(mobile)) / (2 * float(total))
                online_rate = safe_pct(online)
            else:
                online_rate = "#N/A"
            online_sub = f"电脑端：{safe_pct(sales_sum['电脑端全天在线率'])}｜手机端：{safe_pct(sales_sum['手机端全天在线率'])}"
        else:
            online_rate = "#N/A"
            online_sub = "电脑端：#N/A｜手机端：#N/A"

        bad_count = str(len(bad))

        summary_rows.append(
            {
                "segment": segment,
                "auth_rate": auth_rate,
                "online_rate": online_rate,
                "online_sub": online_sub,
                "bad_count": bad_count,
            }
        )

        key = SEGMENT_KEYS[segment]
        page_date_text = all_dates[-1] if all_dates else ""

        (DETAIL_DIR / f"{key}_auth.html").write_text(
            auth_table_html(auth, f"{segment}-个微授权明细", page_date_text, key), encoding="utf-8"
        )
        (DETAIL_DIR / f"{key}_sales.html").write_text(
            sales_table_html(sales, f"{segment}-企微在线明细", page_date_text, key), encoding="utf-8"
        )
        (DETAIL_DIR / f"{key}_bad.html").write_text(
            bad_table_html(bad, f"{segment}-未达标名单", page_date_text, key), encoding="utf-8"
        )

        auth_detail = fill_group_cols(auth[["学部", "年级", "战队", "低价课带班", "全天在线", "个微全天在线率", "接流", "授权人数", "正常人数", "爱芯个微授权率", "个微功能正常率"]].copy(), ["学部", "年级"])
        sales_detail = fill_group_cols(sales[["学部", "年级", "战队", "接流人数", "电脑端全天在线人数", "电脑端全天在线率", "手机端全天在线人数", "手机端全天在线率"]].copy(), ["学部", "年级"])

        auth_detail = auth_detail[~auth_detail.apply(is_summary_row, axis=1)]
        sales_detail = sales_detail[~sales_detail.apply(is_summary_row, axis=1)]

        team_set = set()
        for frame in (auth_detail, sales_detail, bad):
            if "战队" in frame.columns:
                vals = frame["战队"].dropna().astype(str).str.strip()
                vals = vals[vals.ne("") & vals.ne("#N/A")]
                team_set.update(vals.tolist())

        for team in sorted(team_set):
            auth_team = auth_detail[auth_detail["战队"].astype(str).str.strip().eq(team)].copy()
            sales_team = sales_detail[sales_detail["战队"].astype(str).str.strip().eq(team)].copy()
            bad_team = bad[bad["战队"].astype(str).str.strip().eq(team)].copy()
            (TEAM_DETAIL_DIR / team_page_name(key, team)).write_text(
                team_detail_html(segment, team, page_date_text, auth_team, sales_team, bad_team, key),
                encoding="utf-8",
            )

    date_text = max(all_dates) if all_dates else ""
    INDEX_HTML.write_text(build_index_page(summary_rows, date_text), encoding="utf-8")
    print(f"Generated: {INDEX_HTML}")
    print(f"Detail pages: {DETAIL_DIR}")
    print("[校验] 每日检查完成：已完成各学部三表数据重建与高短年级合法性检查。")


if __name__ == "__main__":
    main()

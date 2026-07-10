"""
指定期間内の観測データを集計し、週間レポートPDFを生成するモジュール。

【出力を2種類に分けている理由】
    - 全体サマリー: 3エリア合算の集計を1枚で見たいニーズ向け（generate_weekly_summary_report）
    - エリア別レポート: 特定の1エリアだけの集計を見たいニーズ向け（generate_weekly_area_report）
どちらも別々のPDFとして出力する。

1行ごとのスコア計算は analyzer.calculate_score を再利用し、
単発レポート（generator.py）とロジックがズレないようにしている。
"""

import logging
import textwrap
from datetime import datetime

import pandas as pd
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from analyzer import calculate_score
from column_utils import (
    AREA_DEFINITIONS,
    AREA_DISPLAY_NAMES,
    AREA_SELECT_COLUMN,
    DATE_COLUMN,
    TIME_SLOT_KEYWORD,
    find_column_for_field,
    resolve_area_key,
)

logger = logging.getLogger(__name__)

FONT_NAME = "HeiseiMin-W3"
PAGE_LEFT_MARGIN = 100
LINE_HEIGHT = 20
WRAP_WIDTH = 38  # 1行あたりの目安文字数（日本語混じりの簡易折り返し）

MEDIUM_RISK_LEVEL = "中リスク（注意）"

# 曜日を丸囲み漢字で表示するためのテーブル（date.weekday(): 月=0 ... 日=6）
WEEKDAY_KANJI = ["㈪", "㈫", "㈬", "㈭", "㈮", "㈯", "㈰"]


def _format_date_with_weekday(date_value) -> str:
    """datetime.date を "2026/07/02(木)" の形式にする。"""
    weekday_glyph = WEEKDAY_KANJI[date_value.weekday()]
    return f"{date_value.strftime('%Y/%m/%d')}{weekday_glyph}"


def _parse_row_date(row):
    """行の日付列を1件だけパースして datetime.date を返す。解析できなければ None。"""
    raw_value = row.get(DATE_COLUMN)
    parsed = pd.to_datetime(raw_value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


# 「時間帯」列の自由記述（例: "□ 夕方ピーク（16:30–18:00）"）から
# 短いラベルだけを取り出すためのキーワード（長い表現を先に判定する）
TIME_PERIOD_KEYWORDS = ["早朝", "夕方", "夜間", "朝", "昼", "夜"]


def _extract_time_period_label(value):
    """"□ 夕方ピーク（16:30–18:00）" のような文字列から "夕方" のような短いラベルを取り出す。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    for keyword in TIME_PERIOD_KEYWORDS:
        if keyword in text:
            return keyword
    return None


def _get_row_time_period_label(row):
    """行のエリアを判定し、対応する「時間帯」列から短いラベルを取り出す。取れなければ None。"""
    area_key = resolve_area_key(row.get(AREA_SELECT_COLUMN))
    column_name = find_column_for_field(row.index, area_key, TIME_SLOT_KEYWORD)
    if column_name is None:
        return None
    return _extract_time_period_label(row.get(column_name))


def _format_date_entry(date_value, period_label) -> str:
    """1件分の日付を "2026/07/08㈬(夕方)" のように整形する。日付・時間帯が無ければその部分を省く。"""
    date_text = _format_date_with_weekday(date_value) if date_value is not None else "日付不明"
    if period_label:
        return f"{date_text}({period_label})"
    return date_text


def _format_date_list(entries) -> str:
    """(date, period_label) のリストを '7/7(火)(夕方)、7/8(水)' のように整形する。"""
    if not entries:
        return ""
    return "、".join(_format_date_entry(date_value, period_label) for date_value, period_label in entries)


def filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """
    DATE_COLUMN の値が [start_date, end_date]（両端含む）に収まる行だけを抽出する。
    日付が解析できない行は集計対象から除外する（例外は投げない）。

    start_date / end_date: datetime.date

    【注意】pandasのpd.to_datetime()は、Series全体をまとめて渡すと
    「最初の値の書式」から日付フォーマットを推測し、以降の行がそのフォーマットと
    異なる場合（例: 1行目が "2026/07/08"、5行目が "2026-07-07"）に、
    本来パース可能な日付でも NaT（欠損）にしてしまうことがある。
    これを避けるため、1件ずつ個別にパースする。
    """
    if DATE_COLUMN not in df.columns:
        logger.warning("日付列 '%s' がCSVに存在しません。空の結果を返します。", DATE_COLUMN)
        return df.iloc[0:0]

    parsed_dates = df[DATE_COLUMN].apply(lambda value: pd.to_datetime(value, errors="coerce"))
    mask = (parsed_dates.dt.date >= start_date) & (parsed_dates.dt.date <= end_date)
    return df[mask]


def _summarize(rows):
    """
    観測データ（行のリスト）から件数・平均スコア・最大スコア・中リスク以上件数を計算する。
    あわせて、観測日の一覧・最大スコアが出た日の一覧・危険レベルだった日の一覧を
    (日付, 時間帯ラベル) のペアで返す（レポートに曜日・時間帯付きで表示するため）。
    スコア計算に失敗した行は集計から除外するが、件数（count）には含める。
    """
    count = len(rows)
    scores = []
    danger_count = 0
    observation_entries = []
    danger_entries = []
    score_entry_pairs = []

    for row in rows:
        row_date = _parse_row_date(row)
        period_label = _get_row_time_period_label(row)
        observation_entries.append((row_date, period_label))

        try:
            score, level, _flags = calculate_score(row)
        except Exception:
            logger.exception("週間レポート集計中にスコア計算でエラーが発生しました。この行のスコアはスキップします。")
            continue

        scores.append(score)
        score_entry_pairs.append((score, row_date, period_label))
        if level == MEDIUM_RISK_LEVEL:
            danger_count += 1
            danger_entries.append((row_date, period_label))

    max_score = max(scores) if scores else None
    max_score_entries = (
        [(d, p) for s, d, p in score_entry_pairs if s == max_score] if max_score is not None else []
    )

    return {
        "count": count,
        "avg_score": (sum(scores) / len(scores)) if scores else None,
        "max_score": max_score,
        "danger_count": danger_count,
        "observation_entries": observation_entries,
        "max_score_entries": max_score_entries,
        "danger_entries": danger_entries,
    }


def _format_avg(value) -> str:
    return f"{value:.1f}" if value is not None else "―"


def _format_max(value) -> str:
    return str(value) if value is not None else "―"


def _draw_header(c, line, title):
    """タイトル行を描画する共通処理（見た目を2種類のレポートで揃える）。"""
    line(title, size=16, gap=24)


def _make_line_writer(c):
    """
    y座標を自動的に繰り下げながら1行ずつ描画する関数（折り返し対応）を作る。
    """
    state = {"y": 820}

    def line(text, x=PAGE_LEFT_MARGIN, size=12, gap=LINE_HEIGHT):
        c.setFont(FONT_NAME, size)
        c.drawString(x, state["y"], text)
        state["y"] -= gap

    def wrapped_line(text, x=PAGE_LEFT_MARGIN, size=12, gap=LINE_HEIGHT, width=WRAP_WIDTH):
        """1行が長すぎる場合に複数行へ折り返して描画する。"""
        for chunk in (textwrap.wrap(text, width=width, break_long_words=True) or [""]):
            line(chunk, x=x, size=size, gap=gap)

    return line, wrapped_line


def generate_weekly_summary_report(filename, df: pd.DataFrame, start_date, end_date):
    """
    指定期間の観測データについて、3エリア合算の「全体サマリー」だけを1枚のPDFにまとめる。

    filename: 出力先PDFパス
    df: 元のCSV全体（アップロードされたもの。フィルタ前でよい）
    start_date / end_date: datetime.date（両端を含む期間として扱う）
    """
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    c = canvas.Canvas(filename)
    line, wrapped_line = _make_line_writer(c)

    _draw_header(c, line, "週間観測レポート（全体サマリー）")
    line(
        f"集計期間： {_format_date_with_weekday(start_date)} 〜 {_format_date_with_weekday(end_date)}",
        size=11,
    )
    line(f"発行日： {datetime.now().strftime('%Y年%m月%d日')}", size=11, gap=28)

    filtered = filter_by_date_range(df, start_date, end_date)

    if filtered.empty:
        line("対象期間内に観測データがありません。", size=12)
        c.setFont(FONT_NAME, 9)
        c.drawString(PAGE_LEFT_MARGIN, 40, "©mizubedx")
        c.save()
        return

    all_rows = [filtered.iloc[i] for i in range(len(filtered))]
    overall = _summarize(all_rows)

    line("■ 全体サマリー（全エリア合算）", size=13, gap=LINE_HEIGHT)
    wrapped_line(f"観測回数： {overall['count']}件（{_format_date_list(overall['observation_entries'])}）")
    line(f"平均スコア： {_format_avg(overall['avg_score'])}")
    if overall["max_score"] is not None:
        wrapped_line(
            f"最大スコア： {_format_max(overall['max_score'])}（{_format_date_list(overall['max_score_entries'])}）"
        )
    else:
        line(f"最大スコア： {_format_max(overall['max_score'])}")
    if overall["danger_count"] > 0:
        wrapped_line(
            f"中リスク以上の件数： {overall['danger_count']}件（{_format_date_list(overall['danger_entries'])}）"
        )
    else:
        line(f"中リスク以上の件数： {overall['danger_count']}件")

    c.setFont(FONT_NAME, 9)
    c.drawString(PAGE_LEFT_MARGIN, 40, "©mizubedx")
    c.save()


def generate_weekly_area_report(filename, df: pd.DataFrame, start_date, end_date, area_key: str):
    """
    指定期間・指定エリアの観測データだけを集計してPDFにまとめる。

    filename: 出力先PDFパス
    df: 元のCSV全体（アップロードされたもの。フィルタ前でよい）
    start_date / end_date: datetime.date（両端を含む期間として扱う）
    area_key: "BBQ場" / "兵庫島1" / "兵庫島2" のいずれか（column_utils.AREA_DEFINITIONS のキー）
    """
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    c = canvas.Canvas(filename)
    line, wrapped_line = _make_line_writer(c)

    area_name = AREA_DISPLAY_NAMES.get(area_key, area_key)

    _draw_header(c, line, f"週間観測レポート（{area_name}）")
    line(
        f"集計期間： {_format_date_with_weekday(start_date)} 〜 {_format_date_with_weekday(end_date)}",
        size=11,
    )
    line(f"発行日： {datetime.now().strftime('%Y年%m月%d日')}", size=11, gap=28)

    filtered = filter_by_date_range(df, start_date, end_date)
    all_rows = [filtered.iloc[i] for i in range(len(filtered))]
    area_rows = [row for row in all_rows if resolve_area_key(row.get(AREA_SELECT_COLUMN)) == area_key]

    stats = _summarize(area_rows)

    line(f"■ {area_name}", size=13, gap=LINE_HEIGHT)
    if stats["count"] == 0:
        line("対象期間内にこのエリアの観測データがありません。", size=12)
    else:
        wrapped_line(f"観測回数： {stats['count']}件（{_format_date_list(stats['observation_entries'])}）")
        line(f"平均スコア： {_format_avg(stats['avg_score'])}")
        if stats["max_score"] is not None:
            wrapped_line(
                f"最大スコア： {_format_max(stats['max_score'])}（{_format_date_list(stats['max_score_entries'])}）"
            )
        else:
            line(f"最大スコア： {_format_max(stats['max_score'])}")
        if stats["danger_count"] > 0:
            wrapped_line(
                f"中リスク以上の件数： {stats['danger_count']}件（{_format_date_list(stats['danger_entries'])}）"
            )
        else:
            line(f"中リスク以上の件数： {stats['danger_count']}件")

    c.setFont(FONT_NAME, 9)
    c.drawString(PAGE_LEFT_MARGIN, 40, "©mizubedx")
    c.save()
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
    resolve_area_key,
)

logger = logging.getLogger(__name__)

FONT_NAME = "HeiseiMin-W3"
PAGE_LEFT_MARGIN = 100
LINE_HEIGHT = 20

MEDIUM_RISK_LEVEL = "中リスク（注意）"


def filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """
    DATE_COLUMN の値が [start_date, end_date]（両端含む）に収まる行だけを抽出する。
    日付が解析できない行は集計対象から除外する（例外は投げない）。

    start_date / end_date: datetime.date
    """
    if DATE_COLUMN not in df.columns:
        logger.warning("日付列 '%s' がCSVに存在しません。空の結果を返します。", DATE_COLUMN)
        return df.iloc[0:0]

    parsed_dates = pd.to_datetime(df[DATE_COLUMN], errors="coerce")
    mask = (parsed_dates.dt.date >= start_date) & (parsed_dates.dt.date <= end_date)
    return df[mask]


def _summarize(rows):
    """
    観測データ（行のリスト）から件数・平均スコア・最大スコア・中リスク以上件数を計算する。
    スコア計算に失敗した行は集計から除外するが、件数（count）には含める。
    """
    count = len(rows)
    scores = []
    danger_count = 0

    for row in rows:
        try:
            score, level, _flags = calculate_score(row)
        except Exception:
            logger.exception("週間レポート集計中にスコア計算でエラーが発生しました。この行のスコアはスキップします。")
            continue
        scores.append(score)
        if level == MEDIUM_RISK_LEVEL:
            danger_count += 1

    return {
        "count": count,
        "avg_score": (sum(scores) / len(scores)) if scores else None,
        "max_score": max(scores) if scores else None,
        "danger_count": danger_count,
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
    y座標を自動的に繰り下げながら1行ずつ描画する関数を作る。
    戻り値は (line関数, yを取得する関数) のタプル。
    """
    state = {"y": 820}

    def line(text, x=PAGE_LEFT_MARGIN, size=12, gap=LINE_HEIGHT):
        c.setFont(FONT_NAME, size)
        c.drawString(x, state["y"], text)
        state["y"] -= gap

    return line


def generate_weekly_summary_report(filename, df: pd.DataFrame, start_date, end_date):
    """
    指定期間の観測データについて、3エリア合算の「全体サマリー」だけを1枚のPDFにまとめる。

    filename: 出力先PDFパス
    df: 元のCSV全体（アップロードされたもの。フィルタ前でよい）
    start_date / end_date: datetime.date（両端を含む期間として扱う）
    """
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    c = canvas.Canvas(filename)
    line = _make_line_writer(c)

    _draw_header(c, line, "週間観測レポート（全体サマリー）")
    line(
        f"集計期間： {start_date.strftime('%Y/%m/%d')} 〜 {end_date.strftime('%Y/%m/%d')}",
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
    line(f"観測回数： {overall['count']}件")
    line(f"平均スコア： {_format_avg(overall['avg_score'])}")
    line(f"最大スコア： {_format_max(overall['max_score'])}")
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
    line = _make_line_writer(c)

    area_name = AREA_DISPLAY_NAMES.get(area_key, area_key)

    _draw_header(c, line, f"週間観測レポート（{area_name}）")
    line(
        f"集計期間： {start_date.strftime('%Y/%m/%d')} 〜 {end_date.strftime('%Y/%m/%d')}",
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
        line(f"観測回数： {stats['count']}件")
        line(f"平均スコア： {_format_avg(stats['avg_score'])}")
        line(f"最大スコア： {_format_max(stats['max_score'])}")
        line(f"中リスク以上の件数： {stats['danger_count']}件")

    c.setFont(FONT_NAME, 9)
    c.drawString(PAGE_LEFT_MARGIN, 40, "©mizubedx")
    c.save()
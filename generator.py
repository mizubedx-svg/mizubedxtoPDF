"""
観測データからPDFレポートを生成するモジュール。

改善点:
    1. 列名を固定文字列で直書きせず column_utils.find_column_for_field() で自動解決する。
       （全角/半角の揺れや空白の違いで値が取れない問題を解消）
    2. 該当エリアの列が見つからない場合も "不明" 等のデフォルト値で継続し、サーバーを落とさない。
    3. dataの型が dict でも pandas.Series でも同様に扱えるよう .get() を徹底する。
"""

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from column_utils import AREA_SELECT_COLUMN, find_column_for_field, resolve_area_key

# CSVの日付列の実際の列名（日本語）
DATE_COLUMN = "日付"

# PDFに表示する河川状況の項目（キーワードは正規化後の列名に対して部分一致で検索する）
RIVER_CONDITION_FIELDS = [
    ("水位", "水位"),
    ("流速", "流速"),
    ("濁り", "濁り"),
]
SUMMARY_KEYWORD = "一言サマリー"


def _get_area_field_values(row, area_key):
    """
    指定エリアの「水位・流速・濁り・一言サマリー」を安全に取得する。
    列が見つからない場合は "不明" / "特記事項なし" にフォールバックする。
    """
    values = {}
    for label, keyword in RIVER_CONDITION_FIELDS:
        column_name = find_column_for_field(row.index, area_key, keyword)
        values[label] = row.get(column_name, "不明") if column_name else "不明"

    summary_column = find_column_for_field(row.index, area_key, SUMMARY_KEYWORD)
    summary_value = row.get(summary_column) if summary_column else None
    values["サマリー"] = summary_value if summary_value and str(summary_value).strip() else "特記事項なし"

    return values


def generate_pdf(filename, data, api_data, score_info):
    """
    水辺リスクレポートのPDFを生成する。

    data: 観測データ1行分（dict または pandas.Series）。
          列が欠けていても "不明" 等のデフォルト値で継続する。
    api_data: 天気APIの結果（fetcher.get_api_data の戻り値、または同等の辞書）。
    score_info: analyzer.calculate_score の結果を詰めた dict（score, level, flags を持つ）。
    """
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    c = canvas.Canvas(filename)
    c.setFont("HeiseiMin-W3", 12)

    # --- ヘッダー情報 ---------------------------------------------------------
    date_value = data.get(DATE_COLUMN, "不明")
    c.drawString(100, 820, f"水辺リスクレポート: {date_value}")

    selected_area_raw = data.get(AREA_SELECT_COLUMN, "")
    c.drawString(100, 800, f"エリア: {selected_area_raw or '不明'}")

    # --- エリア別データの取得（自動列名解決） -------------------------------------
    area_key = resolve_area_key(selected_area_raw)
    field_values = _get_area_field_values(data, area_key)

    # --- 自動取得情報エリア（天気API） ------------------------------------------
    temp = api_data.get("temp", 0)
    humidity = api_data.get("humidity", 0)
    alerts = api_data.get("alerts", "N/A")
    c.drawString(100, 770, f"【気温】{temp}℃ 【湿度】{humidity}%")
    c.drawString(300, 770, f"【警報・注意報】{alerts}")

    # --- 河川状況エリア ---------------------------------------------------------
    c.drawString(100, 750, f"■ 河川状況（{selected_area_raw or '不明'}）")
    c.drawString(120, 730, f"水位: {field_values['水位']}")
    c.drawString(120, 710, f"流速: {field_values['流速']}")
    c.drawString(120, 690, f"濁り: {field_values['濁り']}")
    c.drawString(100, 665, f"■ サマリー: {field_values['サマリー']}")

    # --- スコア・分析エリア -----------------------------------------------------
    score = score_info.get("score", 0)
    flags = score_info.get("flags", "なし")
    level = score_info.get("level", "不明")
    c.drawString(100, 630, f"■ 総合スコア: {score}")
    c.drawString(100, 610, f"■ 危険フラグ: {flags}")
    c.drawString(100, 590, f"■ 危険レベル: {level}")

    c.save()

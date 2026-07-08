"""
観測データからPDFレポートを生成するモジュール。

改善点:
    1. CSVの列名が英語 'date' ではなく日本語 '日付' であるため row['date'] を修正
       （KeyError: 'date' の直接原因）
    2. dataの型が dict でも pandas.Series でも同様に扱えるよう .get() を徹底し、
       キー欠損時にサーバーが落ちずに "不明" 等のデフォルト値を表示するようにする
"""

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# CSVの日付列の実際の列名（日本語）
DATE_COLUMN = "日付"


def generate_pdf(filename, data, api_data, score_info):
    """
    水辺リスクレポートのPDFを生成する。

    data: 観測データ1行分（dict または pandas.Series）。
          列が欠けていても "不明" 等のデフォルト値で継続する。
    api_data: 天気APIの結果（fetcher.get_api_data の戻り値）。
              is_available=False の場合もデフォルト値が入っているためそのまま表示できる。
    score_info: analyzer.calculate_score の結果を詰めた dict
                （score, level, flags を持つ）。
    """
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    c = canvas.Canvas(filename)
    c.setFont("HeiseiMin-W3", 12)

    # --- ヘッダー情報 ---------------------------------------------------------
    # 列名は 'date' ではなく '日付'。存在しない場合は "不明" にフォールバック。
    date_value = data.get(DATE_COLUMN, "不明")
    c.drawString(100, 800, f"水辺リスクレポート: {date_value}")

    # --- 自動取得情報エリア（天気API） ------------------------------------------
    # api_data は fetcher.get_api_data が必ずキー付きの dict を返す設計だが、
    # 念のため .get() でデフォルト値を用意し、想定外の呼び出し元からの入力にも耐える。
    temp = api_data.get("temp", 0)
    humidity = api_data.get("humidity", 0)
    alerts = api_data.get("alerts", "N/A")
    c.drawString(100, 750, f"【気温】{temp}℃ 【湿度】{humidity}%")
    c.drawString(300, 750, f"【警報・注意報】{alerts}")

    # --- スコア・分析エリア -----------------------------------------------------
    score = score_info.get("score", 0)
    flags = score_info.get("flags", "なし")
    level = score_info.get("level", "不明")
    c.drawString(100, 700, f"■ 総合スコア: {score}")
    c.drawString(100, 680, f"■ 危険フラグ: {flags}")
    c.drawString(100, 660, f"■ 危険レベル: {level}")

    c.save()
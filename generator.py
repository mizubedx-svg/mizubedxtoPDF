from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def generate_pdf(filename, data, api_data, score_info):
    """
    CSVの行データ(data)からPDFを生成するモジュール。
    data: pandas.Series (CSVの1行分)
    """
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    c = canvas.Canvas(filename)
    c.setFont("HeiseiMin-W3", 12)

    # --- ヘッダー・基本情報 ---
    date_val = data.get("日付", "不明")
    time_val = data.get("時間", "不明")
    c.drawString(100, 820, f"水辺リスクレポート: {date_val} {time_val}")
    c.drawString(100, 800, f"観測員ID: {data.get('観測員ID', '不明')}")

    # --- 天気情報（API連携用エリア） ---
    temp = api_data.get("temp", "データなし")
    humidity = api_data.get("humidity", "データなし")
    c.drawString(100, 760, f"【気温】{temp}℃  【湿度】{humidity}%")

    # --- 河川状況（CSVの列名に正確に合わせる） ---
    # ※CSVの列名（例: '(BBQ場 ) 水位 (0-3)  '）をそのままコピーしています
    c.drawString(100, 720, "■ 河川状況（BBQ場）")
    c.drawString(120, 700, f"水位: {data.get('(BBQ場 ) 水位 (0-3)  ', '0')}")
    c.drawString(120, 680, f"流速: {data.get('(BBQ場 )流速 (0-3)  ', '0')}")
    c.drawString(120, 660, f"濁り: {data.get('(BBQ場 )濁り (0-3)  ', '0')}")
    c.drawString(120, 640, f"人の多さ: {data.get('(BBQ場）人の多さ', '0')}")

    # --- 分析結果 ---
    c.drawString(100, 600, "■ 分析結果")
    c.drawString(120, 580, f"総合スコア: {score_info.get('score', 0)}")
    c.drawString(120, 560, f"危険レベル: {score_info.get('level', '不明')}")
    c.drawString(120, 540, f"危険フラグ: {score_info.get('flags', 'なし')}")

    # --- サマリー ---
    summary = data.get('  【BBQ場】一言サマリー   （任意）', '特記事項なし')
    c.drawString(100, 500, f"■ サマリー: {summary}")

    c.save()
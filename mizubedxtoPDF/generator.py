from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def generate_pdf(filename, data, api_data, score_info):
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiMin-W3'))
    c = canvas.Canvas(filename)
    c.setFont('HeiseiMin-W3', 12)
    
    # ヘッダー情報
    c.drawString(100, 800, f"水辺リスクレポート: {data['date']}")
    
    # 自動取得情報エリア
    c.drawString(100, 750, f"【気温】{api_data['temp']}℃ 【湿度】{api_data['humidity']}%")
    c.drawString(300, 750, f"【警報・注意報】{api_data['alerts']}")
    
    # スコア・分析エリア
    c.drawString(100, 700, f"■ 総合スコア: {score_info['score']}")
    c.drawString(100, 680, f"■ 危険フラグ: {score_info['flags']}")
    c.drawString(100, 660, f"■ 危険レベル: {score_info['level']}")
    
    c.save()
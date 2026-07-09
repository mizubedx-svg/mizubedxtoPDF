from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def generate_pdf(filename, data, api_data, score_info):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    c = canvas.Canvas(filename)
    c.setFont("HeiseiMin-W3", 12)

    # --- ヘッダー情報 ---
    c.drawString(100, 820, f"水辺リスクレポート: {data.get('日付', '不明')}")
    selected_area = data.get("【最重要】観測エリアを選択してください", "")
    c.drawString(100, 800, f"エリア: {selected_area}")

    # --- エリア別のデータ取得ロジック ---
    if "BBQ場" in selected_area:
        水位 = data.get("(BBQ場 ) 水位 (0-3)  ", "0")
        流速 = data.get("(BBQ場 )流速 (0-3)  ", "0")
        濁り = data.get("(BBQ場 )濁り (0-3)  ", "0")
        サマリー = data.get("  【BBQ場】一言サマリー   （任意）", "特記事項なし")
        
    elif "兵庫島公園1" in selected_area:
        水位 = data.get("  【兵庫島公園1】水位（人工水路・ひょうたん池） (0-3)  ", "0")
        流速 = data.get("  【兵庫島公園1】流速（野川・合流部手前） (0-3)  ", "0")
        濁り = data.get("【兵庫島公園1】  濁り （野川・合流部手前） (0-3)  ", "0")
        サマリー = data.get("  【兵庫島公園1】一言サマリー（任意） ", "特記事項なし")

    elif "兵庫島公園2" in selected_area or "兵庫島2" in selected_area:
        # ※ここに兵庫島公園2の正確な列名を指定してください
        水位 = data.get("【兵庫島公園2】水位 (0-3)  ", "0")
        流速 = data.get("【兵庫島公園2】流速 (0-3)  ", "0")
        濁り = data.get("【兵庫島公園2】濁り (0-3)  ", "0")
        サマリー = data.get("【兵庫島公園2】一言サマリー ", "特記事項なし")
    else:
        水位, 流速, 濁り, サマリー = "不明", "不明", "不明", "データなし"

    # --- PDF書き出し ---
    c.drawString(100, 750, f"■ 河川状況（{selected_area}）")
    c.drawString(120, 730, f"水位: {水位}")
    c.drawString(120, 710, f"流速: {流速}")
    c.drawString(120, 690, f"濁り: {濁り}")
    c.drawString(100, 650, f"■ サマリー: {サマリー}")

    c.save()
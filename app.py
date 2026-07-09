import pandas as pd
from flask import Flask, render_template, request, send_file
from generator import generate_pdf  # 先ほど作成した generator.py をインポート

app = Flask(__name__)

# CSVデータの読み込み（アップロードされたファイルパスを指定してください）
CSV_FILE = "水辺リスク観測 mizubedx - フォームの回答 1 (2).csv"

@app.route('/', methods=['GET', 'POST'])
def index():
    df = pd.read_csv(CSV_FILE)
    if request.method == 'POST':
        # フォームで選択された行番号を取得
        row_index = int(request.form.get('row_index'))
        data = df.iloc[row_index]
        
        # PDFの生成
        output_filename = f"report_{row_index}.pdf"
        # api_dataとscore_infoは一旦ダミーで渡します（必要に応じて実装してください）
        api_data = {"temp": 25, "humidity": 60} 
        score_info = {"score": 10, "level": "低リスク", "flags": "なし"}
        
        generate_pdf(output_filename, data, api_data, score_info)
        return send_file(output_filename, as_attachment=True)
        
    return render_template('index.html', df=df)
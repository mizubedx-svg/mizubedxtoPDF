from flask import Flask, render_template, request, send_file
import pandas as pd
import os
from fetcher import get_api_data
from analyzer import calculate_score
from generator import generate_pdf

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # CSVがアップロードされたか確認
        if 'file' not in request.files: return "ファイルがありません"
        file = request.files['file']
        df = pd.read_csv(file)
        
        idx = int(request.form['row_index'])
        row = df.iloc[idx]
        
        # ロジック実行
        api_data = get_api_data(35.61, 139.62)
        score, level = calculate_score(row)
        
        generate_pdf("report.pdf", row, api_data, {'score': score, 'flags': row.get('危険フラグ', 'なし'), 'level': level})
        return send_file("report.pdf", as_attachment=True)
        
    return render_template('index.html')
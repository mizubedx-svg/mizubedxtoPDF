from flask import Flask, render_template, request, send_file
import pandas as pd
from fetcher import get_api_data
from analyzer import calculate_score
from generator import generate_pdf

app = Flask(__name__)

# CSVの中身を一時保持する変数
temp_df = None

@app.route('/', methods=['GET', 'POST'])
def index():
    global temp_df
    if request.method == 'POST':
        # 1. CSVアップロード時
        if 'file' in request.files and request.files['file'].filename != '':
            file = request.files['file']
            temp_df = pd.read_csv(file)
            print(f"CSV Columns: {temp_df.columns}") # ここに配置
            
            # 1列目と2列目を結合して選択肢にする
            options = []
            for i in range(len(temp_df)):
                options.append(f"{temp_df.iloc[i, 0]} - {temp_df.iloc[i, 1]}")
            
            return render_template('index.html', options=options)
        
        # 2. PDF生成時
        elif 'selected_idx' in request.form and temp_df is not None:
            idx = int(request.form['selected_idx'])
            row = temp_df.iloc[idx]
            api_data = get_api_data(35.61, 139.62)
            score, level = calculate_score(row)
            
            generate_pdf("report.pdf", row, api_data, {'score': score, 'flags': row.get('危険フラグ', 'なし'), 'level': level})
            return send_file("report.pdf", as_attachment=True)
            
    return render_template('index.html')
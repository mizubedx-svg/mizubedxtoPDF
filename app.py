from flask import Flask, render_template, request, send_file
import pandas as pd
from fetcher import get_api_data
from analyzer import calculate_score
from generator import generate_pdf

app = Flask(__name__)
df = pd.read_csv('data.csv')
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        idx = int(request.form['row_index'])
        row = df.iloc[idx]
        
        # ロジック実行
        api_data = get_api_data(35.61, 139.62) # 二子玉川の座標
        score, level = calculate_score(row)
        
        generate_pdf("report.pdf", row, api_data, {'score': score, 'flags': row['危険フラグ'], 'level': level})
        return send_file("report.pdf", as_attachment=True)
        
    return render_template('index.html', rows=df.index.tolist())

if __name__ == '__main__':
    app.run(debug=True)

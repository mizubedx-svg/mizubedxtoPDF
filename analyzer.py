import google.generativeai as genai
import os

def calculate_score(row):
    # スコア計算（各項目0-3）
    score = sum([int(row[col]) for col in ['水位', '流速', '濁り', '人の多さ', '水際接近', '滞留密度'] if col in row])
    
    # フラグ判定
    is_danger = "チェックあり" in str(row.get('危険フラグ', ''))
    level = "中リスク（注意）" if (is_danger or score >= 12) else "低リスク"
    
    return score, level

def get_ai_summary(context):
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(f"以下の水辺観測データに基づき、現場へのアドバイスとサマリーを簡潔に書いて: {context}")
    return response.text
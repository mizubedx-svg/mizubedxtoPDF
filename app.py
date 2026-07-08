"""
CSVアップロード -> 選択 -> PDFレポート生成 を行うFlaskアプリ。

改善点:
    1. CSVの列名・列数が想定と異なっていても落ちないよう row.get() / 範囲チェックを徹底
    2. temp_df が None の場合に PDF 生成ボタンを押してもエラーにならないようガード
    3. 処理を関数に分割し、コメントを整理して可読性を向上
    4. Flask のベストプラクティス（ロギング、設定の外出し、例外の種類ごとの分岐など）に沿って整理
"""

import logging

from flask import Flask, render_template, request, send_file
import pandas as pd

from fetcher import get_api_data
from analyzer import calculate_score
from generator import generate_pdf

# ------------------------------------------------------------------
# アプリ設定
# ------------------------------------------------------------------
app = Flask(__name__)
app.config["DEFAULT_LAT"] = 35.61
app.config["DEFAULT_LON"] = 139.62
app.config["PDF_OUTPUT_PATH"] = "report.pdf"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 一時的なデータ保持用（本来は本番運用ではセッションやDBに置き換えるべき）
temp_df = None


# ------------------------------------------------------------------
# ヘルパー関数
# ------------------------------------------------------------------
def build_options_from_df(df: pd.DataFrame) -> list[str]:
    """
    アップロードされたCSVから選択肢の文字列リストを作る。
    列名が不明・列数が足りない場合でも "不明" で埋めて処理を継続する。
    """
    options = []
    n_cols = df.shape[1]

    for i in range(len(df)):
        row = df.iloc[i]
        date_val = row.iloc[0] if n_cols > 0 else "不明"
        area_val = row.iloc[1] if n_cols > 1 else "不明"
        options.append(f"{date_val} - {area_val}")

    return options


def get_selected_row(df: pd.DataFrame, idx: int) -> pd.Series | None:
    """
    指定インデックスの行を安全に取得する。
    範囲外の場合は None を返す。
    """
    if idx < 0 or idx >= len(df):
        return None
    return df.iloc[idx]


# ------------------------------------------------------------------
# ルーティング
# ------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    global temp_df

    if request.method != "POST":
        return render_template("index.html")

    # --- 1. CSVアップロード処理 -------------------------------------------------
    uploaded_file = request.files.get("file")
    if uploaded_file and uploaded_file.filename != "":
        return handle_csv_upload(uploaded_file)

    # --- 2. PDF生成処理 ----------------------------------------------------------
    if "selected_idx" in request.form:
        return handle_pdf_generation(request.form.get("selected_idx"))

    # どちらの条件にも当てはまらない場合はそのままフォームを再表示
    return render_template("index.html")


def handle_csv_upload(uploaded_file):
    """CSVファイルを読み込み、選択肢を生成してフォームに渡す。"""
    global temp_df

    try:
        temp_df = pd.read_csv(uploaded_file)
    except Exception as e:
        logger.exception("CSVの読み込みに失敗しました")
        return f"CSVの読み込みエラー: {e}", 400

    if temp_df.empty:
        return render_template("index.html", options=[], error="CSVにデータがありません。")

    options = build_options_from_df(temp_df)
    return render_template("index.html", options=options)


def handle_pdf_generation(selected_idx_raw):
    """選択された行からPDFレポートを生成して返す。"""
    global temp_df

    # temp_df が存在しない（＝CSV未アップロード、またはサーバー再起動等）場合のガード
    if temp_df is None:
        return render_template(
            "index.html",
            error="CSVがアップロードされていません。先にCSVをアップロードしてください。",
        )

    # インデックスの妥当性チェック
    try:
        idx = int(selected_idx_raw)
    except (TypeError, ValueError):
        return render_template("index.html", error="選択内容が不正です。")

    row = get_selected_row(temp_df, idx)
    if row is None:
        return render_template("index.html", error="指定されたデータが見つかりません。")

    try:
        # 外部APIからのデータ取得
        api_data = get_api_data(
            app.config["DEFAULT_LAT"], app.config["DEFAULT_LON"]
        )

        # スコア計算
        score, level = calculate_score(row)

        # PDF生成用データ（row.get()で列が無くてもデフォルト値にフォールバック）
        report_data = {
            "score": score,
            "flags": row.get("危険フラグ", "なし"),
            "level": level,
        }

        generate_pdf(app.config["PDF_OUTPUT_PATH"], row, api_data, report_data)

        return send_file(app.config["PDF_OUTPUT_PATH"], as_attachment=True)

    except Exception as e:
        logger.exception("PDF生成中にエラーが発生しました")
        return f"PDF生成エラー: {e}", 500


if __name__ == "__main__":
    app.run(debug=True)
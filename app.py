"""
CSVアップロード -> 選択 -> PDFレポート生成 を行うFlaskアプリ。

改善点:
    1. CSVの列名・列数が想定と異なっていても落ちないよう row.get() / 範囲チェックを徹底
    2. temp_df が None の場合に PDF 生成ボタンを押してもエラーにならないようガード
    3. 処理を関数に分割し、コメントを整理して可読性を向上
    4. Flask のベストプラクティス（ロギング、設定の外出し、例外の種類ごとの分岐など）に沿って整理
    5. 天気APIが失敗・'current'欠損しても、デフォルト値でPDF生成処理を続行できるようにする
    6. Render等の本番環境を想定した設定（PORT環境変数、host=0.0.0.0、DEBUGの環境変数化）
"""

import logging
import os

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
# SECRET_KEY はセッション等を使う場合に必須。本番では環境変数で必ず上書きする。
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

# 本番(Render)ではログをstdoutに出し、PaaS側のログ収集に任せる
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 一時的なデータ保持用（本来は本番運用ではセッションやDBに置き換えるべき）
temp_df = None


# ------------------------------------------------------------------
# ヘルパー関数
# ------------------------------------------------------------------
def build_options_from_df(df: pd.DataFrame) -> list[str]:
    """
    アップロードされたCSVから選択肢の文字列リストを作る。

    「日付」「観測エリア」列を名前で探して表示する。
    列名が変わっている・存在しない場合は先頭2列 → "不明" の順にフォールバックする。
    """
    date_col = _find_first_matching_column(df, ["日付"])
    area_col = _find_first_matching_column(df, ["観測エリア", "エリア"])

    options = []
    n_cols = df.shape[1]

    for i in range(len(df)):
        row = df.iloc[i]

        if date_col is not None:
            date_val = row.get(date_col, "不明")
        else:
            date_val = row.iloc[0] if n_cols > 0 else "不明"

        if area_col is not None:
            area_val = row.get(area_col, "不明")
        else:
            area_val = row.iloc[1] if n_cols > 1 else "不明"

        options.append(f"{date_val} - {area_val}")

    return options


def _find_first_matching_column(df: pd.DataFrame, keywords: list[str]):
    """列名に指定キーワードのいずれかを含む最初の列名を返す。見つからなければ None。"""
    for column_name in df.columns:
        if any(keyword in str(column_name) for keyword in keywords):
            return column_name
    return None


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

    # 外部APIからのデータ取得
    # get_api_data は内部で例外を握りつぶし、失敗時はデフォルト値(is_available=False)を返す。
    # そのため、ここでAPI取得に失敗してもPDF生成処理自体は続行できる。
    api_data = get_api_data(app.config["DEFAULT_LAT"], app.config["DEFAULT_LON"])
    if not api_data.get("is_available", False):
        logger.warning("天気APIのデータが取得できなかったため、デフォルト値でPDFを生成します。")

    # スコア計算（score, level, flags の3つを返す仕様に対応）
    try:
        score, level, flags = calculate_score(row)
    except Exception:
        logger.exception("スコア計算中にエラーが発生しました。デフォルト値を使用します。")
        score, level, flags = 0, "算出不可", "なし"

    # PDF生成用データ
    report_data = {
        "score": score,
        "flags": flags,
        "level": level,
    }

    try:
        generate_pdf(app.config["PDF_OUTPUT_PATH"], row, api_data, report_data)
        return send_file(app.config["PDF_OUTPUT_PATH"], as_attachment=True)
    except Exception as e:
        logger.exception("PDF生成中にエラーが発生しました")
        return f"PDF生成エラー: {e}", 500


if __name__ == "__main__":
    # Render等のPaaSでは PORT 環境変数でリッスンポートが指定される。
    # また debug=True は本番で使わない（環境変数 FLASK_DEBUG で制御）。
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)

# 本番運用では `python app.py` ではなく、Renderの起動コマンドを
# 例: `gunicorn app:app --bind 0.0.0.0:$PORT` のようにWSGIサーバー経由にすることを推奨。
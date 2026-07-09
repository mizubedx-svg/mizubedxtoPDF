"""
CSVアップロード -> 選択 -> PDFレポート生成 を行うFlaskアプリ。

【設計方針】
Render等のPaaSでは gunicorn がリクエストごとに複数ワーカープロセスを起動することがあり、
Pythonのグローバル変数（メモリ上の値）はワーカー間で共有されない。
そのため、アップロードされたCSVは「メモリ上の変数」ではなく
「一時ディレクトリ配下のファイル」として保存し、どのワーカーからでも同じデータを読めるようにする。
（本番でワーカー数を1に固定するなら従来のグローバル変数方式でも動くが、
  ワーカー数の設定に依存しない、より安全な作り方を採用している）

改善点:
    1. CSVアップロード時にファイルが無い/壊れている場合でも Internal Server Error にしない
    2. 未アップロード状態でPDF生成ボタンを押してもエラーにならないようガード
    3. row_index が未送信・数値でない・範囲外でも例外にしない
    4. 天気API・スコア計算が失敗してもデフォルト値でPDF生成を継続する
    5. Render等の本番環境を想定した設定（PORT環境変数、host=0.0.0.0、DEBUGの環境変数化）
"""

import logging
import os
import tempfile

import pandas as pd
from flask import Flask, render_template, request, send_file

from analyzer import calculate_score
from fetcher import get_api_data
from generator import generate_pdf

app = Flask(__name__)
app.config["DEFAULT_LAT"] = 35.61
app.config["DEFAULT_LON"] = 139.62
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

# アップロードされたCSVの保存先（ワーカープロセス間で共有できるよう一時ディレクトリ配下に置く）
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", tempfile.gettempdir())
CURRENT_CSV_PATH = os.path.join(UPLOAD_DIR, "mizube_current_upload.csv")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_current_csv():
    """
    直近にアップロードされたCSVを読み込む。
    未アップロード・壊れている場合は None を返す（例外は投げない）。
    """
    if not os.path.exists(CURRENT_CSV_PATH):
        return None
    try:
        return pd.read_csv(CURRENT_CSV_PATH)
    except Exception:
        logger.exception("保存済みCSVの読み込みに失敗しました: %s", CURRENT_CSV_PATH)
        return None


def build_options(df: pd.DataFrame) -> list[dict]:
    """
    プルダウンに表示する選択肢を作る。存在しない列は "不明" にフォールバックする。
    """
    options = []
    for i in range(len(df)):
        row = df.iloc[i]
        date_val = row.get("日付", "不明")
        observer_val = row.get("観測員ID", "不明")
        area_val = row.get("【最重要】観測エリアを選択してください", "不明")
        label = f"{date_val} - {observer_val}（{area_val}）"
        options.append({"index": i, "label": label})
    return options


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # --- 1. CSVアップロード -------------------------------------------------
        uploaded_file = request.files.get("file")
        if uploaded_file and uploaded_file.filename != "":
            return handle_csv_upload(uploaded_file)

        # --- 2. PDF生成 ----------------------------------------------------------
        if "row_index" in request.form:
            return handle_pdf_generation()

    # --- GET（または上記どちらにも該当しないPOST）: 既存アップロード分があれば選択肢を表示 ---
    df = load_current_csv()
    options = build_options(df) if df is not None else []
    return render_template("index.html", options=options)


def handle_csv_upload(uploaded_file):
    """アップロードされたCSVを検証してから保存し、選択肢を表示する。"""
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        logger.exception("CSVの読み込みに失敗しました")
        return render_template(
            "index.html", options=[], error=f"CSVの読み込みエラー: {e}"
        )

    if df.empty:
        return render_template(
            "index.html", options=[], error="CSVにデータがありません。"
        )

    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        df.to_csv(CURRENT_CSV_PATH, index=False)
    except Exception:
        logger.exception("CSVの保存に失敗しました: %s", CURRENT_CSV_PATH)
        return render_template(
            "index.html", options=[], error="CSVの保存に失敗しました。時間をおいて再度お試しください。"
        )

    return render_template("index.html", options=build_options(df))


def handle_pdf_generation():
    """選択された行番号からPDFレポートを生成して返す。"""
    df = load_current_csv()
    if df is None:
        return render_template(
            "index.html",
            options=[],
            error="CSVがアップロードされていません。先にCSVをアップロードしてください。",
        )

    # --- row_index の妥当性チェック -------------------------------------------
    try:
        row_index = int(request.form.get("row_index"))
    except (TypeError, ValueError):
        return render_template(
            "index.html", options=build_options(df), error="選択内容が不正です。"
        )

    if row_index < 0 or row_index >= len(df):
        return render_template(
            "index.html",
            options=build_options(df),
            error="指定されたデータが見つかりません。",
        )

    row = df.iloc[row_index]

    # --- 天気データ取得（失敗してもデフォルト値で続行） ----------------------------
    api_data = get_api_data(app.config["DEFAULT_LAT"], app.config["DEFAULT_LON"])
    if not api_data.get("is_available", False):
        logger.warning("天気APIのデータが取得できなかったため、デフォルト値でPDFを生成します。")

    # --- スコア計算（失敗してもデフォルト値で続行） --------------------------------
    try:
        score, level, flags = calculate_score(row)
    except Exception:
        logger.exception("スコア計算中にエラーが発生しました。デフォルト値を使用します。")
        score, level, flags = 0, "算出不可", "なし"

    score_info = {"score": score, "level": level, "flags": flags}

    # --- PDF生成 ---------------------------------------------------------------
    output_filename = os.path.join(tempfile.gettempdir(), f"report_{row_index}.pdf")
    try:
        generate_pdf(output_filename, row, api_data, score_info)
        return send_file(output_filename, as_attachment=True, download_name="report.pdf")
    except Exception as e:
        logger.exception("PDF生成中にエラーが発生しました")
        return render_template(
            "index.html", options=build_options(df), error=f"PDF生成エラー: {e}"
        )


if __name__ == "__main__":
    # Render等のPaaSでは PORT 環境変数でリッスンポートが指定される。
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)

# 本番運用では `python app.py` ではなく、Renderの起動コマンドを
# 例: `gunicorn app:app --bind 0.0.0.0:$PORT` のようにWSGIサーバー経由にすることを推奨。
# gunicornを複数ワーカーで動かす場合も、CSVは一時ファイル経由で共有しているため問題なく動作する。

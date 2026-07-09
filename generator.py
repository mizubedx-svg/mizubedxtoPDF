"""
観測データからPDFレポートを生成するモジュール（サンプルレイアウト準拠）。

レイアウト方針:
    - 気象庁等の外部気象情報欄は表示しない（CSVの観測値のみで完結させる）
    - 河川状況（水位・流速・濁り）と、人的リスク（人の多さ・水際接近・滞留密度＋エリア固有項目）を
      それぞれセクションとして表示する
    - エリアごとに列名・項目ラベルが異なる問題は column_utils.py の自動解決に任せる
    - 総合スコア・危険レベルは analyzer.calculate_score の結果をそのまま使う（二重計算しない）

改善点:
    1. 列名を固定文字列で直書きせず column_utils で自動解決する
    2. 該当エリアの列が見つからない場合も "不明" 等のデフォルト値で継続し、サーバーを落とさない
    3. 長いテキスト（サマリー・発生状況・危険フラグ）は簡易的に折り返して複数行で描画する
    4. dataの型が dict でも pandas.Series でも同様に扱えるよう .get() を徹底する
"""

import io
import textwrap
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

import pandas as pd

from column_utils import (
    AREA_EXTRA_RISK_FIELD,
    AREA_SELECT_COLUMN,
    COMMON_HUMAN_SCORE_FIELDS,
    EVENT_KEYWORD,
    PHOTO_KEYWORD,
    RIVER_SCORE_FIELDS,
    SUMMARY_KEYWORD,
    TIME_SLOT_KEYWORD,
    WEATHER_KEYWORD,
    find_column_for_field,
    get_area_display_name,
    resolve_area_key,
)
from photo_utils import fetch_and_resize_image
from reportlab.lib.utils import ImageReader

DATE_COLUMN = "日付"
TIME_COLUMN = "時間"

# 曜日を丸囲み漢字で表示するためのテーブル（datetime.weekday(): 月=0 ... 日=6）
WEEKDAY_KANJI = ["㈪", "㈫", "㈬", "㈭", "㈮", "㈯", "㈰"]

FONT_NAME = "HeiseiMin-W3"
PAGE_LEFT_MARGIN = 100
LINE_HEIGHT = 20
WRAP_WIDTH = 38  # 1行あたりの目安文字数（日本語混じりの簡易折り返し）

# 写真ページのレイアウト設定
PHOTO_MAX_WIDTH_PT = 400
PHOTO_MAX_HEIGHT_PT = 500
PHOTO_TOP_Y = 780


def _draw_footer(c):
    c.setFont(FONT_NAME, 9)
    c.drawString(PAGE_LEFT_MARGIN, 40, "©mizubedx")


def _format_date_with_weekday(date_value) -> str:
    """"2026-04-19" 等の日付文字列を "2026/04/19㈰" の形式にする。解析できなければ元の値を返す。"""
    if date_value is None:
        return "不明"
    parsed = pd.to_datetime(str(date_value), errors="coerce")
    if pd.isna(parsed):
        return str(date_value)
    weekday_glyph = WEEKDAY_KANJI[parsed.weekday()]
    return f"{parsed.strftime('%Y/%m/%d')}{weekday_glyph}"


def _format_issue_date() -> str:
    """レポート発行日（PDF生成日）を「2026年4月20日」の形式で返す。"""
    now = datetime.now()
    return f"{now.year}年{now.month}月{now.day}日"


def _build_report_id(date_value) -> str:
    """観測日から "20260419" のようなレポートIDを作る。解析できなければ "不明"。"""
    parsed = pd.to_datetime(str(date_value), errors="coerce")
    if pd.isna(parsed):
        return "不明"
    return parsed.strftime("%Y%m%d")


def _clean_text(value, fallback="不明") -> str:
    """NaN/None/空文字を fallback に統一する。"""
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return fallback
    return text


def _bullet_lines(value, empty_label="なし") -> list[str]:
    """
    "A, B" のようなカンマ区切りの値を "・A" "・B" の箇条書き行に分割する。
    値が無い場合は ["・{empty_label}"] を返す。
    """
    text = _clean_text(value, fallback="")
    if not text:
        return [f"・{empty_label}"]

    items = [item.strip() for item in text.replace("、", ",").split(",") if item.strip()]
    if not items:
        return [f"・{empty_label}"]
    return [f"・{item}" for item in items]


def _wrap_text(text: str, width: int = WRAP_WIDTH) -> list[str]:
    """長いテキストをおおよその文字数で複数行に分割する（日本語は等幅ではないため簡易対応）。"""
    if not text:
        return [""]
    return textwrap.wrap(text, width=width, break_long_words=True) or [""]


def _get_area_score_fields(row, area_key):
    """
    人的リスクセクションに表示する項目（共通3項目＋エリア固有1項目）の
    ラベルと値（"1：普通" のような説明文つきの生の値）のペアのリストを返す。
    """
    fields = []
    for keyword in COMMON_HUMAN_SCORE_FIELDS:
        column_name = find_column_for_field(row.index, area_key, keyword)
        value = _clean_text(row.get(column_name) if column_name else None)
        fields.append((keyword, value))

    extra = AREA_EXTRA_RISK_FIELD.get(area_key)
    if extra:
        column_name = find_column_for_field(row.index, area_key, extra["keyword"])
        value = _clean_text(row.get(column_name) if column_name else None)
        fields.append((extra["label"], value))

    return fields


def _get_river_condition_fields(row, area_key):
    """
    「河川状況」セクションに表示する水位・流速・濁りのラベルと値
    （"1：普通" のような説明文つきの生の値）のペアのリストを返す。
    """
    fields = []
    for keyword in RIVER_SCORE_FIELDS:
        column_name = find_column_for_field(row.index, area_key, keyword)
        value = _clean_text(row.get(column_name) if column_name else None)
        fields.append((keyword, value))
    return fields


def generate_pdf(filename, data, score_info):
    """
    水辺リスクレポートのPDFを生成する。

    data: 観測データ1行分（dict または pandas.Series）。列が欠けていても継続する。
    score_info: analyzer.calculate_score の結果を詰めた dict（score, level, flags を持つ）。
    """
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    c = canvas.Canvas(filename)

    selected_area_raw = data.get(AREA_SELECT_COLUMN, "")
    area_key = resolve_area_key(selected_area_raw)
    area_display_name = get_area_display_name(area_key, selected_area_raw)

    date_raw = data.get(DATE_COLUMN)
    time_raw = _clean_text(data.get(TIME_COLUMN), fallback="")

    time_slot_col = find_column_for_field(data.index, area_key, TIME_SLOT_KEYWORD)
    time_slot_value = _clean_text(data.get(time_slot_col) if time_slot_col else None)

    weather_col = find_column_for_field(data.index, area_key, WEATHER_KEYWORD)
    weather_value = _clean_text(data.get(weather_col) if weather_col else None)

    event_col = find_column_for_field(data.index, area_key, EVENT_KEYWORD)
    event_lines = _bullet_lines(data.get(event_col) if event_col else None)

    summary_col = find_column_for_field(data.index, area_key, SUMMARY_KEYWORD)
    summary_value = _clean_text(
        data.get(summary_col) if summary_col else None, fallback="特記事項なし"
    )

    score = score_info.get("score", 0)
    level = score_info.get("level", "不明")
    flags = score_info.get("flags", "なし")

    y = 820

    def line(text, x=PAGE_LEFT_MARGIN, size=12, gap=LINE_HEIGHT):
        nonlocal y
        c.setFont(FONT_NAME, size)
        c.drawString(x, y, text)
        y -= gap

    # --- ヘッダー ---------------------------------------------------------------
    line("水辺リスクレポート", size=16, gap=24)
    line(_build_report_id(date_raw), size=10, gap=20)
    line(
        f"発行日 {_format_issue_date()}",
        size=10,
        gap=24,
    )

    # --- 基本情報 ---------------------------------------------------------------
    line(f"エリア： {area_display_name}")
    line(f"日時： {_format_date_with_weekday(date_raw)} {time_raw}")
    line(f"時間帯 {time_slot_value}")
    line(f"天候 {weather_value}", gap=24)

    # --- スコア・危険度 -----------------------------------------------------------
    line(f"総合スコア {score}")
    line(f"危険フラグ {flags}")
    line(f"危険レベル {level}", gap=24)

    # --- 河川状況 ----------------------------------------------------------------
    line("■ 河川状況", size=12, gap=LINE_HEIGHT)
    for label, value in _get_river_condition_fields(data, area_key):
        line(f"{label}： {value}")
    y -= 4

    # --- 人的リスク --------------------------------------------------------------
    line("■ 人的リスク", size=12, gap=LINE_HEIGHT)
    for label, value in _get_area_score_fields(data, area_key):
        line(f"{label}： {value}")
    y -= 4

    # --- 事件・事故・トラブル・救助・等発生状況 -------------------------------------
    line("■ 事件・事故・トラブル・救助・等発生状況", size=12, gap=LINE_HEIGHT)
    for event_line in event_lines:
        line(event_line)
    y -= 4

    # --- サマリー -----------------------------------------------------------------
    line("■ サマリー", size=12, gap=LINE_HEIGHT)
    for summary_line in _wrap_text(summary_value):
        line(summary_line)

    # --- フッター（1ページ目） -----------------------------------------------------
    _draw_footer(c)

    # --- 写真（2ページ目、取得できた場合のみ画像を表示） ----------------------------
    photo_col = find_column_for_field(data.index, area_key, PHOTO_KEYWORD)
    photo_url = _clean_text(data.get(photo_col) if photo_col else None, fallback="")

    c.showPage()
    c.setFont(FONT_NAME, 12)
    c.drawString(PAGE_LEFT_MARGIN, PHOTO_TOP_Y, "■ 現場の写真")

    if not photo_url:
        c.setFont(FONT_NAME, 11)
        c.drawString(PAGE_LEFT_MARGIN, PHOTO_TOP_Y - 30, "写真の登録はありません")
    else:
        result = fetch_and_resize_image(photo_url, PHOTO_MAX_WIDTH_PT, PHOTO_MAX_HEIGHT_PT)
        if result is None:
            c.setFont(FONT_NAME, 11)
            c.drawString(
                PAGE_LEFT_MARGIN, PHOTO_TOP_Y - 30, "写真を取得できませんでした（共有設定をご確認ください）"
            )
        else:
            image_bytes, width_px, height_px = result
            image_reader = ImageReader(io.BytesIO(image_bytes))
            # ピクセル寸法をそのままポイント寸法として描画（thumbnail()で既にPHOTO_MAX_*以内に収めてある）
            image_y = PHOTO_TOP_Y - 30 - height_px
            c.drawImage(
                image_reader,
                PAGE_LEFT_MARGIN,
                image_y,
                width=width_px,
                height=height_px,
                preserveAspectRatio=True,
            )

    _draw_footer(c)

    c.save()

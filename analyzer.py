"""
観測データからリスクスコアを計算し、必要に応じてAIによるサマリーを生成するモジュール。

エリアごとに列名が異なる問題への対処は column_utils.py に切り出してある。
本モジュールはそれを使って、
    1. エリアを判定し、スコア項目（水位・流速・濁り・人の多さ・水際接近・滞留密度）を合算
    2. 危険フラグの内容を取得（未入力なら「なし」）
    3. リスクレベルを判定
する。

改善点:
    1. エリア自動判定＋列名の自動マッチングにより、実際のCSV構造でも正しくスコアを計算
    2. 数値変換できない値・列欠損があっても落ちないようにする（すべて0/デフォルト値にフォールバック）
    3. 危険フラグは「チェックあり」ではなく「値が入っているかどうか」で判定する
    4. get_ai_summary はAPIキー未設定・呼び出し失敗時にサーバーを落とさず、フォールバック文言を返す
"""

import logging
import os

import google.generativeai as genai

from column_utils import (
    AREA_SELECT_COLUMN,
    extract_leading_int,
    find_column_for_field,
    resolve_area_key,
)

logger = logging.getLogger(__name__)

# スコアとして合算する項目（0〜3点の設問）
SCORE_FIELD_KEYWORDS = ["水位", "流速", "濁り", "人の多さ", "水際接近", "滞留密度"]
DANGER_FLAG_KEYWORD = "危険フラグ"

HIGH_SCORE_THRESHOLD = 12
FALLBACK_AI_SUMMARY = "AIサマリーは現在生成できませんでした。手動でご確認ください。"


def calculate_score(row):
    """
    観測データ(row)からリスクスコア・リスクレベル・危険フラグの内容を計算する。

    row は dict または pandas.Series（1回答分）を想定。
    エリア列の値に応じて実際の列名を自動判定するため、
    エリアごとに列名が異なるCSVでも正しく集計できる。

    戻り値: (score, level, flags)
        score: 0〜3点の項目を合算した点数（列が見つからない場合はその項目を0点として扱う）
        level: "中リスク（注意）" または "低リスク"
        flags: 危険フラグの内容（未チェックの場合は "なし"）
    """
    area_key = resolve_area_key(row.get(AREA_SELECT_COLUMN))
    if area_key is None:
        logger.warning("観測エリアが判定できないため、スコアは0として扱います。")

    # --- スコア項目の合算 --------------------------------------------------------
    score = 0
    for field_keyword in SCORE_FIELD_KEYWORDS:
        column_name = find_column_for_field(row.index, area_key, field_keyword)
        if column_name is None:
            logger.warning(
                "項目 '%s' に対応する列が見つかりませんでした（area=%s）。0点として扱います。",
                field_keyword,
                area_key,
            )
            continue
        score += extract_leading_int(row.get(column_name))

    # --- 危険フラグの取得 ----------------------------------------------------------
    flag_column = find_column_for_field(row.index, area_key, DANGER_FLAG_KEYWORD)
    flag_value = row.get(flag_column) if flag_column else None
    flag_text = (
        str(flag_value).strip()
        if flag_value is not None and str(flag_value).strip().lower() != "nan"
        else ""
    )
    is_danger = bool(flag_text)
    flags = flag_text if flag_text else "なし"

    # --- リスクレベルの判定 --------------------------------------------------------
    level = "中リスク（注意）" if (is_danger or score >= HIGH_SCORE_THRESHOLD) else "低リスク"

    return score, level, flags


def get_ai_summary(context: str) -> str:
    """
    観測データのコンテキストを元にAIサマリーを生成する。

    APIキー未設定や呼び出し失敗時は例外を投げず、フォールバック文言を返す。
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY が設定されていません。フォールバック文言を返します。")
        return FALLBACK_AI_SUMMARY

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(
            f"以下の水辺観測データに基づき、現場へのアドバイスとサマリーを簡潔に書いて: {context}"
        )
        return getattr(response, "text", None) or FALLBACK_AI_SUMMARY
    except Exception:
        logger.exception("AIサマリーの生成に失敗しました。")
        return FALLBACK_AI_SUMMARY

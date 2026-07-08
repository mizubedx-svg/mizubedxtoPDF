"""
観測データからリスクスコアを計算し、必要に応じてAIによるサマリーを生成するモジュール。

改善点:
    1. スコア計算時、数値変換できない値やキー欠損があっても落ちないようにする
    2. get_ai_summary はAPIキー未設定・呼び出し失敗時にサーバーを落とさず、フォールバック文言を返す
    3. ログ出力を追加し、原因究明をしやすくする
"""

import logging
import os

import google.generativeai as genai

logger = logging.getLogger(__name__)

SCORE_COLUMNS = ["水位", "流速", "濁り", "人の多さ", "水際接近", "滞留密度"]
HIGH_SCORE_THRESHOLD = 12

FALLBACK_AI_SUMMARY = "AIサマリーは現在生成できませんでした。手動でご確認ください。"


def _safe_int(value, default: int = 0) -> int:
    """値を安全にintへ変換する。変換できない場合はdefaultを返す。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def calculate_score(row) -> tuple[int, str]:
    """
    観測データ(row)からリスクスコアとリスクレベルを計算する。

    row は dict または pandas.Series を想定。
    列が欠けていたり、数値に変換できない値が入っていても例外を出さず 0 として扱う。
    """
    score = sum(_safe_int(row.get(col)) for col in SCORE_COLUMNS if col in row)

    is_danger = "チェックあり" in str(row.get("危険フラグ", ""))
    level = "中リスク（注意）" if (is_danger or score >= HIGH_SCORE_THRESHOLD) else "低リスク"

    return score, level


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
        # レスポンスにtextが無いケースも考慮
        return getattr(response, "text", None) or FALLBACK_AI_SUMMARY
    except Exception:
        logger.exception("AIサマリーの生成に失敗しました。")
        return FALLBACK_AI_SUMMARY
"""
観測データからリスクスコアを計算し、必要に応じてAIによるサマリーを生成するモジュール。

【重要な背景】
このアプリで扱うCSV（Googleフォームの回答）は、「BBQ場」「兵庫島公園1」「兵庫島2」の
3エリア分の質問がすべて横並びの列として存在し、実際に値が入るのは
回答者が選んだエリアの列だけ、という構造になっている。
（例: 水位を尋ねる列が "（BBQ場 ） 水位 (0-3)" "【兵庫島公園1】水位（人工水路・ひょうたん池） (0-3)"
      "【兵庫島2】水位（多摩川本流） (0-3)" のように3種類存在する）

そのため、単純に row['水位'] のような固定の列名では値を取得できない
（＝常にスコア0になってしまう）。本モジュールでは、
    1. 「【最重要】観測エリアを選択してください」列の値からエリアを判定
    2. そのエリアに対応する列名を、列名に含まれるキーワードから自動的に探す
という2段階でこの問題を解決している。

また、回答の値自体も "2：速い（子どもが足を取られる）" のように
「数値＋説明文」の文字列になっているため、先頭の数値だけを取り出して使う。

改善点:
    1. エリア自動判定＋列名の自動マッチングにより、実際のCSV構造でも正しくスコアを計算
    2. 数値変換できない値・列欠損があっても落ちないようにする（すべて0/デフォルト値にフォールバック）
    3. 危険フラグは「チェックあり」ではなく「値が入っているかどうか」で判定するよう修正
    4. get_ai_summary はAPIキー未設定・呼び出し失敗時にサーバーを落とさず、フォールバック文言を返す
"""

import logging
import os
import re
import unicodedata

import google.generativeai as genai

logger = logging.getLogger(__name__)

# CSV上でエリアを選択している列の名前
AREA_SELECT_COLUMN = "【最重要】観測エリアを選択してください"

# エリア判定用キーワード（正規化後の文字列に対して判定する）
# 値の並び順は判定の優先順位（例: "兵庫島公園2" は "兵庫島2" を含まないため両方登録している）
AREA_DEFINITIONS = {
    "BBQ場": ["BBQ場"],
    "兵庫島1": ["兵庫島公園1", "兵庫島1"],
    "兵庫島2": ["兵庫島公園2", "兵庫島2"],
}

# スコアとして合算する項目（0〜3点の設問）
SCORE_FIELD_KEYWORDS = ["水位", "流速", "濁り", "人の多さ", "水際接近", "滞留密度"]
DANGER_FLAG_KEYWORD = "危険フラグ"

HIGH_SCORE_THRESHOLD = 12
FALLBACK_AI_SUMMARY = "AIサマリーは現在生成できませんでした。手動でご確認ください。"


def _normalize(text) -> str:
    """
    全角/半角の表記ゆれ（１ vs 1 など）と、列名に含まれる余分な空白を吸収するための正規化。
    """
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", "", normalized)


def resolve_area_key(area_raw):
    """
    「観測エリアを選択してください」列の値から、内部的なエリアキー
    （'BBQ場' / '兵庫島1' / '兵庫島2'）を判定する。
    未知の値や欠損の場合は None を返す。
    """
    normalized = _normalize(area_raw)
    if not normalized:
        return None

    for area_key, markers in AREA_DEFINITIONS.items():
        if any(marker in normalized for marker in markers):
            return area_key

    logger.warning("未知の観測エリア値のため判定できませんでした: %r", area_raw)
    return None


def _find_column_for_field(row, area_key, field_keyword):
    """
    row の列名の中から、指定エリア＋指定項目に対応する列名を1つ探す。
    見つからない場合は None を返す。
    """
    if area_key is None:
        return None

    markers = AREA_DEFINITIONS.get(area_key, [])
    for column_name in row.index:
        normalized_col = _normalize(column_name)
        if field_keyword in normalized_col and any(m in normalized_col for m in markers):
            return column_name
    return None


def _extract_leading_int(value, default: int = 0) -> int:
    """
    "2：速い（子どもが足を取られる）" のような文字列から先頭の数値だけを取り出す。
    数値が見つからない・NaNの場合は default を返す。
    """
    if value is None:
        return default

    text = str(value).strip()
    match = re.match(r"^(-?\d+)", text)
    if not match:
        return default
    return int(match.group(1))


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
        column_name = _find_column_for_field(row, area_key, field_keyword)
        if column_name is None:
            logger.warning(
                "項目 '%s' に対応する列が見つかりませんでした（area=%s）。0点として扱います。",
                field_keyword,
                area_key,
            )
            continue
        score += _extract_leading_int(row.get(column_name))

    # --- 危険フラグの取得 ----------------------------------------------------------
    flag_column = _find_column_for_field(row, area_key, DANGER_FLAG_KEYWORD)
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
"""
CSV（Googleフォームの回答）の列名を扱うための共通ユーティリティ。

【背景】
このアプリで扱うCSVは、「BBQ場」「兵庫島公園1」「兵庫島2」の3エリア分の質問が
すべて横並びの列として存在し、実際に値が入るのは回答者が選んだエリアの列だけ、
という構造になっている。
（例: 水位を尋ねる列が "（BBQ場 ） 水位 (0-3)" "【兵庫島公園1】水位（人工水路・ひょうたん池） (0-3)"
      "【兵庫島2】水位（多摩川本流） (0-3)" のように3種類存在する）

さらに列名には全角/半角の揺れ（（）と()、１と1）や余分な空白が含まれているため、
固定の列名文字列で直接アクセスするのは壊れやすい。
本モジュールでは、
    1. 「【最重要】観測エリアを選択してください」列の値からエリアを判定
    2. そのエリアに対応する列名を、正規化した列名に含まれるキーワードから自動的に探す
という2段階でこの問題を解決する。analyzer.py と generator.py の両方から利用する。
"""

import logging
import re
import unicodedata

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


def normalize(text) -> str:
    """
    全角/半角の表記ゆれ（１ vs 1、（）vs () など）と、列名に含まれる余分な空白を吸収する。
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
    normalized = normalize(area_raw)
    if not normalized:
        return None

    for area_key, markers in AREA_DEFINITIONS.items():
        if any(marker in normalized for marker in markers):
            return area_key

    logger.warning("未知の観測エリア値のため判定できませんでした: %r", area_raw)
    return None


def find_column_for_field(row_index, area_key, field_keyword):
    """
    row_index（列名の一覧。pandas.Series.index や dict.keys() を想定）の中から、
    指定エリア＋指定項目に対応する列名を1つ探す。
    見つからない場合は None を返す。
    """
    if area_key is None:
        return None

    markers = AREA_DEFINITIONS.get(area_key, [])
    for column_name in row_index:
        normalized_col = normalize(column_name)
        if field_keyword in normalized_col and any(m in normalized_col for m in markers):
            return column_name
    return None


def extract_leading_int(value, default: int = 0) -> int:
    """
    "2：速い（子どもが足を取られる）" のような文字列から先頭の数値だけを取り出す。
    数値が見つからない・NaNの場合は default を返す。
    """
    if value is None:
        return default

    text = unicodedata.normalize("NFKC", str(value)).strip()
    match = re.match(r"^(-?\d+)", text)
    if not match:
        return default
    return int(match.group(1))

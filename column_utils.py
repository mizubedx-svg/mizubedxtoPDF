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

# レポートに表示するエリアの正式名称
AREA_DISPLAY_NAMES = {
    "BBQ場": "二子玉川バーベキュー場",
    "兵庫島1": "兵庫島公園（人工水路・ひょうたん池）",
    "兵庫島2": "兵庫島公園（多摩川本流）",
}

# --- スコア項目（0〜3点）の定義 ------------------------------------------------
# 「河川状況」セクションに表示する項目（3エリア共通）
RIVER_SCORE_FIELDS = ["水位", "流速", "濁り"]

# 「人的リスク」セクションのうち、3エリア共通の項目
COMMON_HUMAN_SCORE_FIELDS = ["人の多さ", "水際接近", "滞留密度"]

# 「人的リスク」セクションのうち、エリア固有の追加項目
# （BBQ場=飲酒レベル／兵庫島1=保護者の監視レベル／兵庫島2=対岸の状況影響、で列名が異なる）
AREA_EXTRA_RISK_FIELD = {
    "BBQ場": {"keyword": "飲酒", "label": "飲酒レベル"},
    "兵庫島1": {"keyword": "監視レベル", "label": "保護者の監視レベル"},
    "兵庫島2": {"keyword": "対岸", "label": "対岸（BBQ場側）の状況影響"},
}

# スコアに合算する全項目（河川状況＋人的リスク共通＋エリア固有）を返すヘルパーは
# analyzer.py 側で AREA_EXTRA_RISK_FIELD と組み合わせて使う。

# その他の項目キーワード
TIME_SLOT_KEYWORD = "時間帯"
WEATHER_KEYWORD = "天候"
EVENT_KEYWORD = "イベント発生"
SUMMARY_KEYWORD = "一言サマリー"
DANGER_FLAG_KEYWORD = "危険フラグ"
PHOTO_KEYWORD = "写真"


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


def get_area_display_name(area_key, area_raw) -> str:
    """
    レポートに表示するエリア名を返す。
    既知のエリアなら正式名称、未知の場合はCSVの生の値、それも無ければ "不明"。
    """
    if area_key and area_key in AREA_DISPLAY_NAMES:
        return AREA_DISPLAY_NAMES[area_key]
    if area_raw:
        return str(area_raw)
    return "不明"


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

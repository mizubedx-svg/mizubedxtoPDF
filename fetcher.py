"""
外部の天気API（OpenWeatherMap One Call API）からデータを取得するモジュール。

改善点:
    1. ネットワークエラー・タイムアウト・不正なJSON・HTTPエラーステータスを個別にハンドリング
    2. レスポンスに 'current' キーが無い場合でも例外を出さず、デフォルト値＋ログ出力で継続
    3. 呼び出し元が「APIデータが正常に取れたかどうか」を判定できるよう is_available フラグを追加
    4. 本番運用（Render等）を想定し、タイムアウト設定・ロギングをstdoutに統一
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

# Render等のPaaSでリクエストが無限に詰まらないよう、明示的にタイムアウトを設定
REQUEST_TIMEOUT_SECONDS = 10

# APIが取得できなかった場合に返すデフォルト値
DEFAULT_WEATHER_DATA = {
    "temp": 0,
    "humidity": 0,
    "alerts": "N/A",
    "is_available": False,
}


def get_api_data(lat: float, lon: float) -> dict:
    """
    指定した緯度経度の天気データを取得する。

    どのような失敗が起きても例外を外に投げず、必ず dict を返す。
    失敗時は DEFAULT_WEATHER_DATA をベースにした値を返し、ログに原因を記録する。
    """
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        logger.warning("OPENWEATHER_API_KEY が設定されていません。デフォルト値を返します。")
        return dict(DEFAULT_WEATHER_DATA)

    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "lang": "ja",
    }

    # --- APIリクエスト ---------------------------------------------------------
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        res.raise_for_status()  # 4xx/5xx を例外として検知
    except requests.exceptions.Timeout:
        logger.error("天気APIがタイムアウトしました (lat=%s, lon=%s)", lat, lon)
        return dict(DEFAULT_WEATHER_DATA)
    except requests.exceptions.HTTPError as e:
        logger.error("天気APIがエラーステータスを返しました: %s", e)
        return dict(DEFAULT_WEATHER_DATA)
    except requests.exceptions.RequestException as e:
        logger.error("天気APIへの接続に失敗しました: %s", e)
        return dict(DEFAULT_WEATHER_DATA)

    # --- レスポンスのJSONパース --------------------------------------------------
    try:
        data = res.json()
    except ValueError:
        logger.error("天気APIのレスポンスがJSONとして解析できませんでした。")
        return dict(DEFAULT_WEATHER_DATA)

    # --- 'current' キーの存在チェック ---------------------------------------------
    current = data.get("current")
    if not current:
        logger.warning(
            "天気APIのレスポンスに 'current' が含まれていません。デフォルト値を使用します。 response=%s",
            data,
        )
        return dict(DEFAULT_WEATHER_DATA)

    # --- alerts の安全な取得 ------------------------------------------------------
    alerts = data.get("alerts", [])
    try:
        alert_text = "、".join(a.get("event", "不明なアラート") for a in alerts) if alerts else "なし"
    except (TypeError, AttributeError):
        logger.warning("alerts の形式が想定と異なるため 'なし' として扱います。 alerts=%s", alerts)
        alert_text = "なし"

    return {
        "temp": current.get("temp", DEFAULT_WEATHER_DATA["temp"]),
        "humidity": current.get("humidity", DEFAULT_WEATHER_DATA["humidity"]),
        "alerts": alert_text,
        "is_available": True,
    }

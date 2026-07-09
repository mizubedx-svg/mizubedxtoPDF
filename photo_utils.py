"""
CSVに記録されたGoogleドライブの写真URLから画像を取得し、PDF埋め込み用にリサイズするモジュール。

【背景】
Googleフォームの「ファイルを送信」質問は、回答時にアップロードされた画像を
Googleドライブに保存し、CSVには "https://drive.google.com/open?id=XXXX" のような
共有リンクだけが記録される。画像本体はこのリンク経由で別途ダウンロードする必要がある。

【制約・注意点】
    - 共有設定が「リンクを知っている全員が閲覧可」になっていないとダウンロードできない
    - ある程度サイズが大きいファイルは、Googleが「ウイルススキャン確認」ページを
      挟むことがあり、素朴なダウンロードでは失敗する（本モジュールでは確認トークンを
      拾って再リクエストすることである程度対応している）
    - 上記いずれの理由でも取得できない場合、例外を投げずに None を返す
      （呼び出し側は「写真を取得できませんでした」等の表示にフォールバックする）
"""

import io
import logging
import re

import requests
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20MB（暴走ダウンロード防止の安全弁）

DRIVE_FILE_ID_PATTERN = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")


def _extract_drive_file_id(url: str):
    """Googleドライブの共有URLからファイルIDを取り出す。取れなければ None。"""
    if not url:
        return None
    match = DRIVE_FILE_ID_PATTERN.search(url)
    return match.group(1) if match else None


def _download_drive_file(file_id: str, session: requests.Session):
    """
    Googleドライブのファイルをダウンロードする。
    大きいファイルで挟まる「ウイルススキャン確認」ページにもある程度対応する。
    成功時はバイト列、失敗時は None を返す。
    """
    base_url = "https://drive.google.com/uc?export=download"

    try:
        response = session.get(
            base_url, params={"id": file_id}, timeout=REQUEST_TIMEOUT_SECONDS, stream=True
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning("Googleドライブへの接続に失敗しました (id=%s): %s", file_id, e)
        return None

    # 大きいファイルの場合、確認ページ（HTML）が返ってくることがある。
    # その場合はCookieに埋め込まれた確認トークンを使って再リクエストする。
    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        confirm_token = None
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                confirm_token = value
                break

        if not confirm_token:
            logger.warning(
                "Googleドライブから画像以外のレスポンスが返され、確認トークンも取得できませんでした (id=%s)",
                file_id,
            )
            return None

        try:
            response = session.get(
                base_url,
                params={"id": file_id, "confirm": confirm_token},
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=True,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.warning("確認トークン付き再リクエストに失敗しました (id=%s): %s", file_id, e)
            return None

    # サイズ上限を超えないよう、チャンクごとに読みながらチェックする
    chunks = []
    total_size = 0
    for chunk in response.iter_content(chunk_size=65536):
        total_size += len(chunk)
        if total_size > MAX_DOWNLOAD_BYTES:
            logger.warning("画像サイズが上限を超えたためダウンロードを中止しました (id=%s)", file_id)
            return None
        chunks.append(chunk)

    return b"".join(chunks)


def fetch_and_resize_image(url: str, max_width: int, max_height: int):
    """
    Googleドライブの共有URLから画像を取得し、指定サイズ以内に収まるようリサイズする。

    戻り値: (image_bytes, width, height) のタプル、または取得できなければ None。
    image_bytes はPNG形式。width/height はリサイズ後の実ピクセルサイズ
    （reportlabでの描画サイズ計算に使う）。
    """
    file_id = _extract_drive_file_id(url)
    if file_id is None:
        logger.warning("URLからGoogleドライブのファイルIDを取り出せませんでした: %r", url)
        return None

    session = requests.Session()
    raw_bytes = _download_drive_file(file_id, session)
    if raw_bytes is None:
        return None

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()
    except UnidentifiedImageError:
        logger.warning("ダウンロードした内容を画像として認識できませんでした (id=%s)", file_id)
        return None
    except Exception:
        logger.exception("画像の読み込み中にエラーが発生しました (id=%s)", file_id)
        return None

    # EXIFの回転情報があれば正しい向きに補正する
    try:
        from PIL import ImageOps

        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    image.thumbnail((max_width, max_height), Image.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), image.width, image.height

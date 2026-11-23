"""Google Cloud TTS クライアント (tech-news ナレーション生成モジュール)。

eng-listening tools/content/cloud_tts.py (実績あり) を本チャンネル用に適応したもの。設計:

- 音声設定は voice_config.json 一元管理 (単一構成固定)。
- ja-JP-Neural2 系の声のみ許可 (ゼロコスト制約: Neural2 無料枠 月100万文字)。
  Gemini TTS は意図的にサポートしない (muse-gemini の50件/日枠をアニメ側と共有するため)。
- TTS 呼び出しにウォッチドッグ (タイムアウトでハングを自動切断) と上限付きリトライ。
- 月間文字数カウンタ: 送信前に予約、成功時に確定、失敗時に解放 (原子的更新)。
  monthlyStopChars 到達で UsageLimitExceeded。
- 別エンジン・別声へのフォールバックは実装しない (単一構成固定、障害時は待って再開)。

認証はこの Mac の既存 gcloud ユーザー認証を使い、アクセストークンの値は
決してログ・標準出力・ファイルに出さない。ユーザー認証トークンで呼ぶ際は
X-Goog-User-Project ヘッダ (クォータプロジェクト) が必須 (無いと 403)。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "voice_config.json"
USAGE_DIR = HERE / "usage"
VOICE_PREFIX = "ja-JP-Neural2"


class TTSError(RuntimeError):
    """TTS 呼び出しがリトライ上限に達するなどして失敗した。"""


class UsageLimitExceeded(TTSError):
    """月間文字数カウンタが停止上限 (monthlyStopChars) に達した。"""


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def config_hash(cfg: dict) -> str:
    """voice_config.json の SHA-256 (先頭16文字)。

    生成物の manifest に記録し、異なるハッシュの既存音声と混在しないようにする。
    """
    blob = json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 月間文字数カウンタ (ゼロコスト制約)
# ---------------------------------------------------------------------------

def current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def usage_path(month: str | None = None) -> Path:
    return USAGE_DIR / f"monthly-{month or current_month()}.json"


def read_usage(month: str | None = None) -> dict:
    path = usage_path(month)
    if not path.exists():
        return {"month": month or current_month(), "chars": 0, "requests": 0,
                "pendingChars": 0, "jobs": {}}
    usage = json.loads(path.read_text(encoding="utf-8"))
    usage.setdefault("pendingChars", 0)
    for per in usage.setdefault("jobs", {}).values():
        per.setdefault("pendingChars", 0)
    return usage


def _write_usage_atomic(usage: dict) -> None:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = usage_path(usage["month"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(usage, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def reserve_usage(cfg: dict, chars: int, job_id: str) -> dict:
    """TTS 送信前に文字数を永続的に予約する (原子的更新)。

    確定済み + 予約中 + 予約分が monthlyStopChars を超えるなら UsageLimitExceeded。
    プロセスが finalize 前に死んでも pendingChars はカウンタに残り、
    成功分が未計上のまま無料枠を超過することがない。
    """
    if chars <= 0:
        return read_usage()
    usage = read_usage()
    stop = int(cfg["limits"]["monthlyStopChars"])
    if usage["chars"] + usage["pendingChars"] + chars > stop:
        raise UsageLimitExceeded(
            f"月間文字数カウンタが停止上限に達します: 使用 {usage['chars']} + "
            f"予約中 {usage['pendingChars']} + 追加分 {chars} > 上限 {stop} 文字。"
            "生成を停止します。無料枠 (月1,000,000文字) 超過による課金を防ぐため、"
            "当月はこれ以上生成しないこと。"
        )
    usage["pendingChars"] += chars
    per = usage.setdefault("jobs", {}).setdefault(job_id, {"chars": 0, "requests": 0, "pendingChars": 0})
    per["pendingChars"] += chars
    _write_usage_atomic(usage)
    return usage


def finalize_usage(chars: int, job_id: str) -> dict:
    """成功したリクエストの予約を実績へ確定する (原子的更新)。"""
    if chars <= 0:
        return read_usage()
    usage = read_usage()
    usage["pendingChars"] -= chars
    usage["chars"] += chars
    usage["requests"] += 1
    per = usage.setdefault("jobs", {}).setdefault(job_id, {"chars": 0, "requests": 0, "pendingChars": 0})
    per["pendingChars"] -= chars
    per["chars"] += chars
    per["requests"] += 1
    _write_usage_atomic(usage)
    return usage


def release_usage(chars: int, job_id: str) -> dict:
    """失敗したリクエストの予約を解放する (実績には計上しない)。"""
    if chars <= 0:
        return read_usage()
    usage = read_usage()
    usage["pendingChars"] = max(0, usage["pendingChars"] - chars)
    per = usage.setdefault("jobs", {}).setdefault(job_id, {"chars": 0, "requests": 0, "pendingChars": 0})
    per["pendingChars"] = max(0, per["pendingChars"] - chars)
    _write_usage_atomic(usage)
    return usage


# ---------------------------------------------------------------------------
# 認証 (gcloud ユーザー認証)
# ---------------------------------------------------------------------------

def get_access_token(account: str) -> str:
    """gcloud の既存ユーザー認証からアクセストークンを取得する。

    トークンの値を一切出力・記録しないこと (秘密情報はログ・PR・コミット禁止)。
    """
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token", f"--account={account}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        rc = result.returncode
        token = (result.stdout or "").strip()
    except OSError:
        rc, token = -1, ""
    if rc == 0 and token:
        return token
    raise TTSError(
        f"gcloud アクセストークンの取得に失敗しました (rc={rc})。"
        "`gcloud auth list` で認証状態を確認してください。"
    )


# ---------------------------------------------------------------------------
# TTS 呼び出し (ウォッチドッグ付き)
# ---------------------------------------------------------------------------

def synthesize(cfg: dict, text: str, voice_name: str, *, job_id: str, label: str) -> bytes:
    """1 ビート分の音声を合成して WAV bytes (LINEAR16) を返す。

    - タイムアウト (voice_config.watchdog.timeoutSec) でハングを自動切断し、
      上限付きリトライ (maxRetries / backoffSec) で再試行する。
    - 成功したリクエストのみ月間文字数カウンタに確定加算する。
    - 別エンジン・別声へのフォールバックは意図的に実装しない (単一構成固定)。
    """
    text = text.strip()
    if not text:
        raise TTSError(f"空のテキストで TTS を呼ぼうしました: {label}")
    if not voice_name.startswith(VOICE_PREFIX):
        # ゼロコスト制約: ja-JP-Neural2 以外 (Studio / Chirp / Wavenet など
        # 無料枠外・高単価の声) を設定ファイルへの誤記込みで使わないようにここで弾く。
        raise TTSError(
            f"{VOICE_PREFIX} 以外の声は使えません (ゼロコスト制約): {voice_name}")

    watchdog = cfg.get("watchdog", {})
    timeout_sec = float(watchdog.get("timeoutSec", 180))
    max_retries = int(watchdog.get("maxRetries", 3))
    backoff = list(watchdog.get("backoffSec", [15, 30, 60]))
    delay = float(cfg.get("requestDelaySec", 1.0))
    endpoint = cfg.get("apiEndpoint", "https://texttospeech.googleapis.com/v1/text:synthesize")

    body = {
        "input": {"text": text},
        "voice": {"languageCode": cfg["languageCode"], "name": voice_name},
        "audioConfig": cfg["audio"],
    }
    last = None
    for attempt in range(max_retries + 1):
        if attempt:
            wait = backoff[min(attempt - 1, len(backoff) - 1)]
            print(f"  retry {attempt}/{max_retries} in {wait}s: {last}", flush=True)
            time.sleep(wait)
        reserve_usage(cfg, len(text), job_id)
        try:
            token = get_access_token(cfg["gcloudAccount"])
            req = urllib.request.Request(
                endpoint, data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "X-Goog-User-Project": cfg["quotaProject"],
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            audio = base64.b64decode(data["audioContent"])
            finalize_usage(len(text), job_id)
            time.sleep(delay)
            return audio
        except UsageLimitExceeded:
            release_usage(len(text), job_id)
            raise
        except Exception as e:  # noqa: BLE001 — ウォッチドッグ: タイムアウト/HTTP エラー/JSON 壊れを全部リトライ対象にする
            release_usage(len(text), job_id)
            last = f"{type(e).__name__}: {e}"
    raise TTSError(f"TTS failed after {max_retries} retries: {last}")

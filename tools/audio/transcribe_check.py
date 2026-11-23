"""transcribe_check.py — 生成音声を全文書き起こしし、台本と全件照合する QC。

アニメ日本史ラボ tools/qa/asr_check.py の正規化・照合ロジックを単独ナレーター用に整理
したもの。**サンプリング禁止**: 台本の全ビートを順に照合する (一部だけの確認は不可)。

- 期待テキストは gen_narration と同一 (reading 優先 + 読み辞書適用済み TTS 入力)。
- faster-whisper (ja) で各ビート WAV を転写し、NFKC → 数字→漢数字 → pykakasi で
  かな化 → 記号除去 の正規化を両側に適用して difflib 類似度を算出。
- 全体一致率は全ビート連結で評価 (回帰検知)。ビート別は誤読・欠落の特定用。
- ゲート: 全体一致率 < overallThreshold またはビート別 < beatThreshold が 1 つでも
  あれば FAIL (終了コード 1)。該当ビートを修正 (reading 指定 or 辞書) し再生成する。

使い方 (リポジトリ ルートで):
  uv run --with faster-whisper --with pykakasi --with numpy \\
      python tools/audio/transcribe_check.py --episode <id>
  uv run --with faster-whisper --with pykakasi --with numpy \\
      python tools/audio/transcribe_check.py \\
      --audio-dir audio/audition/ja-JP-Neural2-B --script content/audition/test_script.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cloud_tts  # noqa: E402
import pronunciation as pn  # noqa: E402

_DIGITS = "零一二三四五六七八九"


def arabic_to_kanji_num(digits: str) -> str:
    """0-9999 のアラビア数字文字列を漢数字へ変換する (ASR 表記差の吸収用)。"""
    n = int(digits)
    if n > 9999:
        return digits
    if n == 0:
        return _DIGITS[0]
    parts: list[str] = []
    for unit, weight in (("千", 1000), ("百", 100), ("十", 10)):
        d, n = divmod(n, weight)
        if d:
            parts.append(((_DIGITS[d] if d != 1 else "") + unit))
    if n:
        parts.append(_DIGITS[n])
    return "".join(parts)


class Normalizer:
    """台本テキストと ASR 転写を同じ正規化パスに通して比較可能にする。

    pykakasi が無い環境では kanji→kana を行わないフォールバック (結果の
    normalizer フィールドに記録)。
    """

    def __init__(self) -> None:
        self.mode = "pykakasi"
        try:
            import pykakasi

            self._conv = pykakasi.kakasi()
        except ImportError:
            self._conv = None
            self.mode = "fallback"

    def text(self, raw: str) -> str:
        s = unicodedata.normalize("NFKC", raw)
        s = re.sub(r"\d+", lambda m: arabic_to_kanji_num(m.group()), s)
        if self._conv is not None:
            s = "".join(t["hira"] for t in self._conv.convert(s))
        return re.sub(r"[^ぁ-ゖーa-zA-Z]", "", s)


def decode_ffmpeg(wav: Path, sr: int = 16000):
    """WAV を ffmpeg で 16kHz mono float32 (whisper 入力) にデコードする。"""
    import numpy as np

    cmd = ["ffmpeg", "-v", "error", "-i", str(wav), "-ar", str(sr), "-ac", "1", "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"ffmpeg デコード失敗 ({wav}): {p.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.float32)


def ratio(a: str, b: str) -> float | None:
    if not a and not b:
        return None
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def main() -> int:
    ap = argparse.ArgumentParser(description="全文書き起こし照合 (全件・サンプリング禁止)")
    ap.add_argument("--episode", help="audio/<id>/narration + content/episodes/<id>/script.json")
    ap.add_argument("--audio-dir", help="ビート WAV のディレクトリ (--episode と排他)")
    ap.add_argument("--script", help="台本パス (--audio-dir と組で使う)")
    args = ap.parse_args()
    if bool(args.episode) == bool(args.audio_dir):
        ap.error("--episode か --audio-dir+--script のどちらかを指定してください")

    cfg = cloud_tts.load_config()
    tc = cfg["transcribeCheck"]
    pdict, dict_sha = pn.load_pronunciation_dict()

    if args.episode:
        audio_dir = REPO / "audio" / args.episode / "narration"
        script_path = REPO / "content/episodes" / args.episode / "script.json"
    else:
        audio_dir = REPO / args.audio_dir
        script_path = REPO / args.script
    script = json.loads(script_path.read_text(encoding="utf-8"))

    # 期待テキスト: gen_narration と同一の TTS 入力 (reading 優先 + 辞書適用)
    expected = []
    for scene in script["scenes"]:
        for bi, beat in enumerate(scene["beats"]):
            wav = audio_dir / f"{scene['id']}_b{bi:02d}.wav"
            if wav.exists():
                tts_text, _ = pn.apply_pronunciation(beat.get("reading") or beat["text"], pdict)
                expected.append({"file": wav.name, "tts_text": tts_text,
                                 "display": beat["text"]})
    if not expected:
        raise SystemExit(f"ビート WAV がありません: {audio_dir}")

    t0 = time.monotonic()
    from faster_whisper import WhisperModel

    model = WhisperModel(tc["model"], device=tc["device"], compute_type=tc["computeType"])
    norm = Normalizer()
    rows = []
    for e in expected:
        wav = audio_dir / e["file"]
        audio = decode_ffmpeg(wav)
        seg_iter, info = model.transcribe(audio,
                                          language=tc["language"], vad_filter=True,
                                          vad_parameters={"min_silence_duration_ms": 300},
                                          condition_on_previous_text=False)
        asr = "".join(s.text.strip() for s in seg_iter)
        exp_n, asr_n = norm.text(e["tts_text"]), norm.text(asr)
        r = ratio(exp_n, asr_n)
        rows.append({"file": e["file"], "expected": e["display"], "asr": asr,
                     "similarity": None if r is None else round(r, 4),
                     "ok": None if r is None else r >= float(tc["beatThreshold"])})
        print(f"  {e['file']}: sim={rows[-1]['similarity']} asr={asr[:40]}")
    asr_sec = time.monotonic() - t0

    overall = ratio(norm.text("".join(e["tts_text"] for e in expected)),
                    norm.text("".join(norm.text(r["asr"]) for r in rows)))
    n_fail = sum(1 for r in rows if r["ok"] is False)
    overall_pass = overall is not None and overall >= float(tc["overallThreshold"])
    pass_all = overall_pass and n_fail == 0

    result = {
        "audio_dir": str(audio_dir), "script": str(script_path),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": tc["model"], "device": tc["device"], "compute_type": tc["computeType"],
        "normalizer": norm.mode, "dict_sha": dict_sha,
        "coverage": f"all {len(rows)}/{len(rows)} beats (sampling forbidden)",
        "overall_similarity": None if overall is None else round(overall, 4),
        "overall_pass": overall_pass, "beat_fail": n_fail,
        "pass": pass_all, "asr_elapsed_sec": round(asr_sec, 1),
        "beats_detail": rows,
    }
    out = audio_dir / "transcribe_check_report.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[asr] 全体一致率={result['overall_similarity']} (ゲート {tc['overallThreshold']}) "
          f"ビート FAIL={n_fail}/{len(rows)} 転写時間={asr_sec:.1f}s")
    if pass_all:
        print(f"TRANSCRIBE PASS → {out}")
        return 0
    print(f"TRANSCRIBE FAIL → {out}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

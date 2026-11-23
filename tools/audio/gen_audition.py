"""gen_audition.py — 声候補オーディション用サンプル一括生成。

ja-JP-Neural2 の実在候補声 (voices list API で確認済み) ごとに、同一テスト台本から
サンプル音声を生成する。声の最終決定はここでは行わない (監督側の確認後)。

- 各候補は独立した出力先 audio/audition/<voice>/ を使い、manifest に
  「config ハッシュ + 上書き声」を記録する (候補間の混在防止)。
- ビート WAV の連結 (full.wav) も作り、耳確認と書き起こし照合に使う。
- 生成時間を計測し audio/audition/audition_report.json に残す。

使い方 (リポジトリ ルートで):
  uv run python tools/audio/gen_audition.py \
      --voices ja-JP-Neural2-B,ja-JP-Neural2-C,ja-JP-Neural2-D \
      --script content/audition/test_script.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cloud_tts  # noqa: E402
import gen_narration  # noqa: E402
import pronunciation as pn  # noqa: E402


def concat_beats(out_dir: Path, beats: list[dict], gap_sec: float, sr: int) -> Path:
    """ビート WAV を gap を挟んで連結し full.wav を作る (ffmpeg concat filter)。"""
    full = out_dir / "full.wav"
    cmd = ["ffmpeg", "-v", "error", "-y"]
    filters = []
    parts = []
    for i, b in enumerate(beats):
        cmd += ["-i", str(out_dir / b["wav"])]
        if gap_sec > 0 and i < len(beats) - 1:
            filters.append(
                f"[{i}:a]aformat=sample_rates={sr}:channel_layouts=mono,"
                f"apad=pad_dur={gap_sec}[a{i}]")
        else:
            filters.append(f"[{i}:a]aformat=sample_rates={sr}:channel_layouts=mono[a{i}]")
        parts.append(f"[a{i}]")
    filters.append("".join(parts) + f"concat=n={len(beats)}:v=0:a=1[out]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", str(full)]
    subprocess.run(cmd, check=True)
    return full


def main() -> int:
    ap = argparse.ArgumentParser(description="声候補オーディション用サンプル生成")
    ap.add_argument("--script", default="content/audition/test_script.json")
    ap.add_argument("--out", default="audio/audition")
    ap.add_argument("--voices", required=True,
                    help="カンマ区切りの ja-JP-Neural2 候補 (実在確認済みのもの)")
    ap.add_argument("--force", action="store_true", help="既存 WAV があっても上書き再生成")
    args = ap.parse_args()

    cfg = cloud_tts.load_config()
    script_path = REPO / args.script
    script = gen_narration.load_script(script_path)
    pdict, dict_sha = pn.load_pronunciation_dict()
    out_root = REPO / args.out
    out_root.mkdir(parents=True, exist_ok=True)

    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "script": args.script, "dict_sha": dict_sha, "candidates": {}}

    for voice in [v.strip() for v in args.voices.split(",") if v.strip()]:
        if not voice.startswith(cloud_tts.VOICE_PREFIX):
            raise SystemExit(f"候補声が ja-JP-Neural2 系ではありません (ゼロコスト制約): {voice}")
        vdir = out_root / voice
        if args.force:
            for old in vdir.glob("*.wav"):
                old.unlink()
        t0 = time.monotonic()
        timing = gen_narration.generate_beat_set(
            cfg, script, vdir, voice_name=voice,
            job_id=f"audition-{voice}", pdict=pdict,
            gap_sec=float(cfg.get("beatGapSec", 0.3)))
        gen_sec = time.monotonic() - t0
        full = concat_beats(vdir, timing["beats"], float(cfg.get("beatGapSec", 0.3)),
                            int(cfg["audio"]["sampleRateHertz"]))
        usage = cloud_tts.read_usage()
        report["candidates"][voice] = {
            "dir": str(vdir.relative_to(REPO)), "full_wav": str(full.relative_to(REPO)),
            "beats": len(timing["beats"]), "speech_sec": timing["total_speech_sec"],
            "generate_sec": round(gen_sec, 1),
            "monthly_chars_used": usage["chars"],
        }
        print(f"[audition] {voice}: {timing['beats']}beats "
              f"speech={timing['total_speech_sec']}s gen={gen_sec:.1f}s → {full}")

    (out_root / "audition_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[audition] report → {out_root / 'audition_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

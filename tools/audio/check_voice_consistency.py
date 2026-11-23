"""check_voice_consistency.py — 音声一貫性ゲート (単独ナレーター用)。

アニメ日本史ラボの同名ツールを単独ナレーター運用に調整したもの:

- 各ビート WAV の基本周波数 (F0) 中央値 (自己相関) と話速 (文字数/秒) を測定。
- 単独ナレーターのため、話者ごとではなく全ビートの中央値と各ビートを比較する
  (複数話者が混入した場合は話者単位にフォールバック)。
- 閾値は voice_config.json の consistencyGate (既定: F0 偏差 15% / 話速偏差 25%)。
- 外れ値ビートを検出したら GATE FAIL (終了コード 1)。該当 WAV を削除して再生成する。

使い方 (リポジトリ ルートで):
  uv run --with numpy python tools/audio/check_voice_consistency.py --episode <id>
  uv run --with numpy python tools/audio/check_voice_consistency.py \
      --audio-dir audio/audition/ja-JP-Neural2-B --script content/audition/test_script.json
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cloud_tts  # noqa: E402


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    import numpy as np

    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    return x, sr


def median_f0(x, sr: int) -> float:
    import numpy as np

    frame = int(sr * 0.04)
    hop = int(sr * 0.02)
    f0s = []
    lo = int(sr / 400)  # 400 Hz
    hi = int(sr / 60)   # 60 Hz
    for start in range(0, max(1, len(x) - frame), hop):
        seg = x[start:start + frame]
        if len(seg) < frame or float(np.sqrt(np.mean(seg ** 2))) < 0.02:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, mode="full")[len(seg) - 1:]
        if ac[0] <= 0:
            continue
        window = ac[lo:hi]
        if len(window) == 0:
            continue
        peak = int(np.argmax(window)) + lo
        if ac[peak] / ac[0] > 0.35:
            f0s.append(sr / peak)
    import numpy as np

    return float(np.median(f0s)) if f0s else 0.0


def collect_beats(audio_dir: Path, script: dict) -> list[dict]:
    """ビート WAV 名と台本テキストを対応付ける (gen_narration の命名規約に一致)。

    台本にあるのに WAV が無いビートがあれば停止する (欠落を黙殺して
    測定対象を減らさないため — ゲートの母数を台本どおりに保つ)。
    """
    rows, missing = [], []
    for scene in script["scenes"]:
        for bi, beat in enumerate(scene["beats"]):
            wav = audio_dir / f"{scene['id']}_b{bi:02d}.wav"
            if not wav.exists():
                missing.append(wav.name)
                continue
            rows.append({"wav": wav, "file": wav.name, "speaker": beat.get("speaker", "narrator"),
                         "text": beat.get("reading") or beat["text"]})
    if missing:
        raise SystemExit(f"ビート WAV が欠落しています (測定不可): {missing}")
    if not rows:
        raise SystemExit(f"台本にビートがありません (測定対象 0 件): {audio_dir}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="音声一貫性ゲート (F0/話速の外れ値検出)")
    ap.add_argument("--episode", help="audio/<id>/narration + content/episodes/<id>/script.json")
    ap.add_argument("--audio-dir", help="ビート WAV のディレクトリ (--episode と排他)")
    ap.add_argument("--script", help="台本パス (--audio-dir と組で使う)")
    args = ap.parse_args()
    if bool(args.episode) == bool(args.audio_dir):
        ap.error("--episode か --audio-dir+--script のどちらかを指定してください")

    cfg = cloud_tts.load_config()
    gate = cfg["consistencyGate"]
    f0_max = float(gate["f0DeviationMax"])
    rate_max = float(gate["rateDeviationMax"])

    if args.episode:
        audio_dir = REPO / "audio" / args.episode / "narration"
        script_path = REPO / "content/episodes" / args.episode / "script.json"
    else:
        audio_dir = REPO / args.audio_dir
        script_path = REPO / args.script
    script = json.loads(script_path.read_text(encoding="utf-8"))

    rows = []
    for b in collect_beats(audio_dir, script):
        x, sr = read_wav(b["wav"])
        dur = len(x) / sr
        f0 = median_f0(x, sr)
        chars = len(b["text"].replace(" ", "").replace("　", ""))
        rate = chars / dur if dur > 0 else 0.0
        rows.append({"file": b["file"], "speaker": b["speaker"], "f0": round(f0, 1),
                     "rate": round(rate, 2), "dur": round(dur, 2)})

    flagged = []
    # 単独ナレーター: 話者別に分けても 1 グループになる。複数話者混入時は話者別判定に落ちる。
    for spk in sorted({r["speaker"] for r in rows}):
        sub = [r for r in rows if r["speaker"] == spk and r["f0"] > 0]
        if not sub:
            continue
        import numpy as np

        med_f0 = float(np.median([r["f0"] for r in sub]))
        med_rate = float(np.median([r["rate"] for r in sub]))
        for r in sub:
            reasons = []
            if abs(r["f0"] - med_f0) / med_f0 > f0_max:
                reasons.append(f"F0 {r['f0']} vs median {med_f0:.1f}")
            if med_rate > 0 and abs(r["rate"] - med_rate) / med_rate > rate_max:
                reasons.append(f"rate {r['rate']} vs median {med_rate:.2f}")
            r["flag"] = "; ".join(reasons)
            if reasons:
                flagged.append(r)
        print(f"{spk}: beats={len(sub)} median F0={med_f0:.1f} Hz "
              f"median rate={med_rate:.2f} chars/s")

    report = {"audio_dir": str(audio_dir), "thresholds": {"f0DeviationMax": f0_max,
               "rateDeviationMax": rate_max}, "rows": rows, "flagged": flagged,
              "pass": not flagged}
    out = audio_dir / "voice_consistency_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if flagged:
        print(f"GATE FAIL: {len(flagged)} beat(s) flagged:")
        for r in flagged:
            print(f"  {r['file']} [{r['speaker']}] {r['flag']}")
        return 1
    print(f"GATE PASS: {len(rows)} beats consistent → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

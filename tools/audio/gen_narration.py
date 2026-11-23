"""gen_narration.py — 台本 → Google Cloud TTS → ナレーション WAV + timing (統一音声生成)。

アニメ日本史ラボ gen_narration_unified.py の仕組みを Google Cloud TTS / 単独ナレーター
向けに移植したもの:

- 全生成設定は voice_config.json のみから読む (モデル/声/パラメータ固定)。
- ナレーターは単独1名 (voices.narrator)。ビートごとの感情指示・スタイル切替はしない。
- TTS 入力は辞書適用済みテキスト (pronunciation.apply_pronunciation)。
- 出力先 audio/<ep>/narration/ に manifest.json (config ハッシュ付き) を書き、
  異なるハッシュの既存 WAV が混在する場合は生成を中止する。
- TTS 呼び出しは cloud_tts.synthesize (ウォッチドッグ: ハング自動切断 + 上限リトライ)。
- 既存 WAV は「同一 config ハッシュ」のときだけスキップ。再生成は WAV を削除して再実行。

使い方 (リポジトリ ルートで):
  uv run python tools/audio/gen_narration.py --episode 2026-11-24-test
  台本: content/episodes/<id>/script.json
    {"episode": "...", "title": "...",
     "scenes": [{"id": "s01", "section": "headline",
                 "beats": [{"speaker": "narrator", "text": "...", "reading": null}]}]}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cloud_tts  # noqa: E402
import pronunciation as pn  # noqa: E402


def load_script(path: Path) -> dict:
    script = json.loads(path.read_text(encoding="utf-8"))
    for scene in script.get("scenes", []):
        for beat in scene.get("beats", []):
            if beat.get("speaker") != "narrator":
                raise SystemExit(
                    f"本チャンネルは単独ナレーターのみです。speaker=narrator 以外が台本にあります: "
                    f"{scene.get('id')} speaker={beat.get('speaker')}")
    return script


def beat_wav(out_dir: Path, sid: str, bi: int) -> Path:
    return out_dir / f"{sid}_b{bi:02d}.wav"


def generate_beat_set(cfg: dict, script: dict, out_dir: Path, *, voice_name: str,
                      job_id: str, pdict: dict, gap_sec: float = 0.3) -> dict:
    """1 台本分のビート WAV を生成 (または同一ハッシュの既存分をスキップ) する。

    戻り値はビート メタ (scene_id, wav, duration, text, tts_text, speaker) と
    total_speech / config_hash を含む dict。監督側ツール (consistency / transcribe)
    もこの形式に依存する。
    """
    chash = cloud_tts.config_hash(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = {"config_hash": chash, "engine": cfg["engine"], "voice": voice_name, "beats": {}}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("config_hash") != chash and any(out_dir.glob("*.wav")):
            raise SystemExit(
                "ABORT: 出力先には異なる voice config (ハッシュ "
                f"{old.get('config_hash')}) で生成された音声があります。混在を防ぐため中止します。"
                f"作り直す場合は {out_dir} を消してから再実行してください。")
        manifest = old
        if manifest.get("voice") != voice_name:
            raise SystemExit(
                f"ABORT: 出力先 manifest の声 ({manifest.get('voice')}) と指定声 ({voice_name}) が"
                "不一致です。混在を防ぐため中止します。")

    beat_meta = []
    total_speech = 0.0
    start = 0.0
    for scene in script["scenes"]:
        sid = scene["id"]
        for bi, beat in enumerate(scene["beats"]):
            name = beat_wav(out_dir, sid, bi).name
            tts_text, _repls = pn.apply_pronunciation(
                beat.get("reading") or beat["text"], pdict)
            wav_path = out_dir / name
            if wav_path.exists() and wav_path.stat().st_size > 1000:
                dur = wav_duration_file(wav_path)
                print(f"skip {name} {dur:.2f}s", flush=True)
            else:
                t0 = time.monotonic()
                raw = cloud_tts.synthesize(cfg, tts_text, voice_name, job_id=job_id,
                                           label=name)
                gen_sec = time.monotonic() - t0
                tmp = out_dir / f"tmp_{name}"
                with wave.open(str(tmp), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(int(cfg["audio"]["sampleRateHertz"]))
                    w.writeframes(raw)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                                "-ar", "48000", "-ac", "1", str(wav_path)], check=True)
                tmp.unlink()
                dur = wav_duration_file(wav_path)
                print(f"gen  {name} {dur:.2f}s (tts {gen_sec:.1f}s) {beat['text'][:24]}", flush=True)
            manifest["beats"][name] = {"speaker": beat["speaker"], "config_hash": chash,
                                       "engine": cfg["engine"], "voice": voice_name}
            beat_meta.append({"scene_id": sid, "section": scene.get("section", ""),
                              "speaker": beat["speaker"], "wav": name,
                              "start": round(start, 3), "duration": dur,
                              "text": beat["text"], "tts_text": tts_text})
            start += dur + gap_sec
            total_speech += dur

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    timing = {"config_hash": chash, "voice": voice_name, "gap_sec": gap_sec,
              "total_speech_sec": round(total_speech, 3),
              "total_duration": round(max(start - gap_sec, 0.0), 3),
              "beats": beat_meta}
    return timing


def wav_duration_file(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def main() -> int:
    ap = argparse.ArgumentParser(description="台本 → Cloud TTS ナレーション生成")
    ap.add_argument("--episode", required=True, help="content/episodes/<id>/script.json の <id>")
    args = ap.parse_args()

    cfg = cloud_tts.load_config()
    chash = cloud_tts.config_hash(cfg)
    script_path = REPO / "content/episodes" / args.episode / "script.json"
    script = load_script(script_path)
    pdict, dict_sha = pn.load_pronunciation_dict()
    print(f"[gen] dict={len(pdict)}語 sha={dict_sha} config={chash} "
          f"voice={cfg['voices']['narrator']['voiceName']}")

    out_dir = REPO / "audio" / args.episode / "narration"
    timing = generate_beat_set(cfg, script, out_dir,
                               voice_name=cfg["voices"]["narrator"]["voiceName"],
                               job_id=args.episode, pdict=pdict,
                               gap_sec=float(cfg.get("beatGapSec", 0.3)))
    (REPO / "audio" / args.episode / "timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    usage = cloud_tts.read_usage()
    print(f"DONE beats={len(timing['beats'])} speech={timing['total_speech_sec']}s "
          f"total={timing['total_duration']}s 月間使用={usage['chars']}字 (上限"
          f"{cfg['limits']['monthlyStopChars']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

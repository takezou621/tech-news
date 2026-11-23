#!/usr/bin/env python3
"""selftest_guards.py — QC パイプラインのガード機構 自己テスト。

設計上の制約 (プロンプト固定事項の遵守):
- **成功する TTS 呼び出しを行わない** (プローブ目的の成功呼び出し禁止 / 枠消費しない)。
  ネットワーク系のテストは失敗経路 (無効クォータプロジェクトによる 403) のみ。
- 本番の voice_config.json と月間文字数カウンタ (tools/audio/usage/) は変更しない。
  テストは一時ディレクトリとモンキーパッチで隔離する。
- 期待値はリポジトリ内の実データ (pronunciation_dict.json 23語 /
  content/audition/test_script.json 4ビート) に固定してある。データを変えたら
  期待値も更新すること。

実行 (リポジトリ ルートで):
  uv run python tools/audio/selftest_guards.py
  uv run python tools/audio/selftest_guards.py --with-network  (403経路テストを含める)
終了コード: 全 PASS で 0、FAIL/ERROR があれば 1。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import check_voice_consistency as cvc  # noqa: E402
import cloud_tts  # noqa: E402
import gen_narration  # noqa: E402
import pronunciation as pn  # noqa: E402

AUDITION_SCRIPT = REPO / "content/audition/test_script.json"
EXPECTED_DICT_SIZE = 23

results: list[dict] = []


def check(name: str, fn) -> None:
    try:
        fn()
        results.append({"test": name, "result": "PASS", "detail": ""})
        print(f"PASS {name}")
    except AssertionError as e:
        results.append({"test": name, "result": "FAIL", "detail": str(e)})
        print(f"FAIL {name}: {e}")
    except SystemExit as e:
        # テスト本体から SystemExit が漏れた場合は FAIL (ハーネスを巻き込んで
        # 停止させず、残りの判定を必ず実行する)。ただし本体が意図的に
        # assert した SystemExit は本体側で捕捉済みのため、ここに来たら漏れ。
        results.append({"test": name, "result": "FAIL",
                        "detail": f"SystemExit escaped test body: {e}"})
        print(f"FAIL {name}: SystemExit がテスト本体から漏出: {e}")
    except Exception as e:  # noqa: BLE001 — テストランナーとして全例外を報告に変換する
        results.append({"test": name, "result": "ERROR", "detail": f"{type(e).__name__}: {e}"})
        print(f"ERROR {name}: {type(e).__name__}: {e}")


def t01_dict_apply_longest_match() -> None:
    d, _sha = pn.load_pronunciation_dict()
    assert len(d) == EXPECTED_DICT_SIZE, f"辞書 {len(d)}語 (期待 {EXPECTED_DICT_SIZE})"
    text, _ = pn.apply_pronunciation("OpenAIのChatGPTを使う", d)
    assert text == "オープンエーアイのチャットジーピーティーを使う", text


def t02_dict_apply_boundary() -> None:
    d, _ = pn.load_pronunciation_dict()
    # xAI 内の AI はトークン途中 → 置換しない。GPU は置換する。
    text, _ = pn.apply_pronunciation("xAIのGPU", d)
    assert text == "xAIのジーピーユー", text
    # NVIDIA社: ASCII キーの直後の漢字 (接尾) は置換を許可
    text, _ = pn.apply_pronunciation("NVIDIA社の製品", d)
    assert text == "エヌビディア社の製品", text
    # 漢字キーの途中一致はブロック (例: 脆弱性 の一部一致が起きない)
    text, _ = pn.apply_pronunciation("脆弱性", d)
    assert text == "ぜいじゃくせい", text


def t03_dict_validation_rejects_non_kana() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bad.json"
        p.write_text('{"グラフ": "graph"}', encoding="utf-8")
        try:
            pn.load_pronunciation_dict(p)
        except SystemExit as e:
            # 拒否を肯定検証: 非0 終了かつ拒否理由のメッセージ付きであること
            assert e.code, "終了コードが空 (正常終了扱い)"
            assert "かな文字" in str(e.code), f"拒否理由が不正: {e.code}"
        else:
            raise AssertionError("かな以外の値を含む辞書が読めてしまった")


def t04_single_narrator_only() -> None:
    script = {"scenes": [{"id": "s01", "beats": [{"speaker": "sensei", "text": "x"}]}]}
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "script.json"
        sp.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
        try:
            gen_narration.load_script(sp)
        except SystemExit as e:
            assert e.code, "終了コードが空 (正常終了扱い)"
            assert "単独ナレーター" in str(e.code), f"拒否理由が不正: {e.code}"
        else:
            raise AssertionError("narrator 以外の話者を含む台本が受理された")


def t05_config_mixing_abort() -> None:
    # 隔離: カウンタを一時ディレクトリへ、TTS を失敗経路 (無効クォータプロジェクト) へ。
    # ガードが壊れて生成が進んでも、本番カウンタの汚染と成功 TTS 呼び出しが起きない。
    cfg = cloud_tts.load_config()
    cfg["quotaProject"] = "invalid-project-selftest"
    cfg["watchdog"] = {"timeoutSec": 30, "maxRetries": 0, "backoffSec": [0]}
    script = gen_narration.load_script(AUDITION_SCRIPT)
    pdict, _ = pn.load_pronunciation_dict()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "mixing"
        out.mkdir()
        usage_td = Path(td) / "usage"
        old = cloud_tts.USAGE_DIR
        cloud_tts.USAGE_DIR = usage_td
        try:
            old_manifest = {"config_hash": "deadbeef00000000", "voice": "ja-JP-Neural2-C"}
            (out / "manifest.json").write_text(json.dumps(old_manifest), encoding="utf-8")
            (out / "s01_b00.wav").write_bytes(b"\0" * 2048)
            try:
                gen_narration.generate_beat_set(cfg, script, out, voice_name="ja-JP-Neural2-C",
                                                job_id="selftest", pdict=pdict)
                raise AssertionError("異なる設定ハッシュの既存音声との混在が許された")
            except SystemExit as e:
                assert e.code, "終了コードが空 (正常終了扱い)"
                assert "ABORT" in str(e.code), f"中止メッセージが ABORT でない: {e.code}"
        finally:
            cloud_tts.USAGE_DIR = old


def t06_usage_limit_stop() -> None:
    cfg = cloud_tts.load_config()
    small = dict(cfg)
    small["limits"] = {"monthlyStopChars": 1}
    with tempfile.TemporaryDirectory() as td:
        old = cloud_tts.USAGE_DIR
        cloud_tts.USAGE_DIR = Path(td)
        try:
            try:
                cloud_tts.reserve_usage(small, 100, "selftest-limit")
                raise AssertionError("月間上限超過の予約が許された")
            except cloud_tts.UsageLimitExceeded:
                pass
        finally:
            cloud_tts.USAGE_DIR = old


def t07_watchdog_retry_no_fallback() -> None:
    """無効クォータプロジェクト → 403 を maxRetries 回リトライして TTSError。

    成功呼び出しは行わない (403 は合成枠を消費しない)。別エンジン/別声への
    フォールバックが実装されていないことも、TTSError 以外が上がらないことで確認。
    """
    cfg = json.loads(json.dumps(cloud_tts.load_config()))
    cfg["quotaProject"] = "invalid-project-selftest"
    cfg["watchdog"] = {"timeoutSec": 30, "maxRetries": 2, "backoffSec": [0, 0]}
    with tempfile.TemporaryDirectory() as td:
        old = cloud_tts.USAGE_DIR
        cloud_tts.USAGE_DIR = Path(td)
        try:
            try:
                cloud_tts.synthesize(cfg, "自己テスト", "ja-JP-Neural2-C",
                                     job_id="selftest-watchdog", label="t07")
                raise AssertionError("失敗すべき呼び出しが成功した (フォールバックの疑い)")
            except cloud_tts.TTSError:
                pass
            usage = cloud_tts.read_usage()
            assert usage["chars"] == 0 and usage["pendingChars"] == 0, \
                f"失敗分がカウンタに計上されている: {usage}"
        finally:
            cloud_tts.USAGE_DIR = old


def t08_gate_missing_beat_abort() -> None:
    script = gen_narration.load_script(AUDITION_SCRIPT)
    with tempfile.TemporaryDirectory() as td:
        try:
            cvc.collect_beats(Path(td), script)
        except SystemExit as e:
            assert e.code, "終了コードが空 (正常終了扱い)"
            assert "欠落" in str(e.code), f"欠落として報告されない: {e.code}"
        else:
            raise AssertionError("欠落ビートが黙殺された")


def t09_gate_zero_beat_abort() -> None:
    script = {"scenes": [{"id": "s01", "beats": []}]}
    with tempfile.TemporaryDirectory() as td:
        try:
            cvc.collect_beats(Path(td), script)
        except SystemExit as e:
            assert e.code, "終了コードが空 (正常終了扱い)"
            assert "ビートがありません" in str(e.code), f"想定外の中止: {e.code}"
        else:
            raise AssertionError("ゼロビート台本でゲートが通った")


def t10_transcribe_missing_beat_abort() -> None:
    """CLI 経路で欠落ビート → 非0 終了 (faster-whisper 読み込み前に停止するため高速)。"""
    with tempfile.TemporaryDirectory() as td:
        cmd = ["uv", "run", "--with", "faster-whisper", "--with", "pykakasi", "--with", "numpy",
               "python", str(HERE / "transcribe_check.py"),
               "--audio-dir", td, "--script", "content/audition/test_script.json"]
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
        out = p.stdout + p.stderr
        assert p.returncode != 0, f"欠落ビートで終了コード 0: {out[-300:]}"
        assert "欠落" in out, f"欠落として報告されない: {out[-300:]}"


def main() -> int:
    # assert 文を検証に使うため、最適化モード (-O) では無意味になる。実行を拒否する。
    if not __debug__:
        print("FAIL selftest: python -O では assert が無効のため実行不可 (-O を外して実行)")
        return 1
    ap = argparse.ArgumentParser(description="ガード機構の自己テスト (成功TTS呼び出しなし)")
    ap.add_argument("--with-network", action="store_true",
                    help="403 経路のウォッチドッグ テストを含める (外部ネットワークを使用)")
    args = ap.parse_args()

    print(f"[selftest] dict={len(pn.load_pronunciation_dict()[0])}語 "
          f"script={AUDITION_SCRIPT.name} (成功TTS呼び出しは行わない)")
    check("t01 辞書適用 (最長一致: OpenAI→AI 部分置換なし)", t01_dict_apply_longest_match)
    check("t02 辞書適用 (境界: xAI 内 AI ブロック / NVIDIA社 接尾許可)", t02_dict_apply_boundary)
    check("t03 辞書検証 (かな以外の値を拒否)", t03_dict_validation_rejects_non_kana)
    check("t04 単独ナレーター固定 (narrator 以外を拒否)", t04_single_narrator_only)
    check("t05 混在防止 (異なる config ハッシュで ABORT)", t05_config_mixing_abort)
    check("t06 月間文字数上限 (monthlyStopChars で停止)", t06_usage_limit_stop)
    if args.with_network:
        check("t07 ウォッチドッグ (403 をリトライし TTSError / カウンタ計上なし)", t07_watchdog_retry_no_fallback)
    else:
        print("SKIP t07 ウォッチドッグ (--with-network で実行可能。失敗経路のみ使用)")
        results.append({"test": "t07 ウォッチドッグ", "result": "SKIP",
                        "detail": "--with-network 未指定"})
    check("t08 ゲート欠落ビート (黙殺せず停止)", t08_gate_missing_beat_abort)
    check("t09 ゲートゼロビート (黙って PASS にしない)", t09_gate_zero_beat_abort)
    check("t10 全件照合 欠落ビート (CLI 経路で非0 終了)", t10_transcribe_missing_beat_abort)

    n_fail = sum(1 for r in results if r["result"] in ("FAIL", "ERROR"))
    n_skip = sum(1 for r in results if r["result"] == "SKIP")
    print(f"[selftest] {len(results)} tests: "
          f"PASS={len(results) - n_fail - n_skip} FAIL/ERROR={n_fail} SKIP={n_skip}")
    (REPO / "audio/audition/selftest_report.json").write_text(
        json.dumps({"results": results,
                    "pass": n_fail == 0}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""pronunciation_audit.py — 生成前の読み辞書監査 (未登録語の洗い出し)。

台本の TTS 入力テキストに対して辞書を dry-run し、以下を報告する:

1. 辞書に登録済みの語と置換見込み (件数)
2. 辞書未登録の漢字連続 (2字以上) の候補 — 誤読リスクの要確認リスト
3. 辞書未登録の英字トークン (企業名・製品名候補) — 読み確定と登録の要確認リスト

**生成前に必ず実行する**工程。未登録語は (a) 出典を確認して辞書に登録するか、
(b) script.json の reading で読みを明示するか、(c) TTS 既定読みで問題ないと
判断して進める。推測の読みで辞書に登録してはいけない。

使い方 (リポジトリ ルートで):
  uv run python tools/audio/pronunciation_audit.py --episode <id>
  uv run python tools/audio/pronunciation_audit.py --script content/audition/test_script.json
  オプション: --strict (未登録語があれば終了コード 1) --out <md パス>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import pronunciation as pn  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="読み辞書監査 (生成前)")
    ap.add_argument("--episode", help="content/episodes/<id>/script.json の <id>")
    ap.add_argument("--script", help="台本パス (--episode と排他)")
    ap.add_argument("--strict", action="store_true", help="未登録語があったら終了コード 1")
    ap.add_argument("--out", help="レポート出力先 (markdown)。指定なければ標準出力のみ")
    args = ap.parse_args()
    if bool(args.episode) == bool(args.script):
        ap.error("--episode か --script のどちらか一方を指定してください")

    pdict, dict_sha = pn.load_pronunciation_dict()
    script_path = (REPO / "content/episodes" / args.episode / "script.json") if args.episode \
        else REPO / args.script
    script = json.loads(script_path.read_text(encoding="utf-8"))
    texts, repl_counts = [], {}
    for scene in script["scenes"]:
        for beat in scene["beats"]:
            raw = beat.get("reading") or beat["text"]
            texts.append(raw)
            _tts, repls = pn.apply_pronunciation(raw, pdict)
            for r in repls:
                repl_counts[r["from"]] = repl_counts.get(r["from"], 0) + 1

    cand = pn.audit_terms(texts, pdict)
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# 読み辞書監査 (生成前 dry-run)",
        "",
        f"- 実行: {now} / 台本: {script_path}",
        f"- 辞書: {len(pdict)}語 (sha256[:12]={dict_sha}) / "
        f"置換見込み: {sum(repl_counts.values())}件",
        f"- 置換語: " + (", ".join(f"{k}×{v}" for k, v in
                                    sorted(repl_counts.items(), key=lambda kv: -kv[1])) or "なし"),
        "",
        f"## 未登録漢字候補: {len(cand['kanji'])}語 (一般語ストップワード除外済み)",
        "",
    ]
    for k, v in sorted(cand["kanji"].items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"- {k} ×{v['count']} … 「{v['example']}」")
    lines += ["", f"## 未登録英字候補: {len(cand['ascii'])}語 (読み確定 + 登録が必要)", ""]
    for k, v in sorted(cand["ascii"].items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"- {k} ×{v['count']} … 「{v['example']}」")
    lines += [
        "",
        "## 対応ルール",
        "",
        "- 登録する: 出典を確認し pronunciation_sources.md に記録してから pronunciation_dict.json へ",
        "- reading 指定: script.json の該当ビートに reading を書く (辞書登録より局所的)",
        "- 既定読みで可: 判断メモを残す (このレポートに記録は残らないため、判断は台本リポジトリ側で)",
    ]
    report = "\n".join(lines) + "\n"
    if args.out:
        out_path = REPO / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(report)
        print(f"[audit] 出力: {out_path}")
    else:
        print(report)

    n_unknown = len(cand["kanji"]) + len(cand["ascii"])
    print(f"[audit] 未登録候補: 漢字 {len(cand['kanji'])} / 英字 {len(cand['ascii'])}")
    if args.strict and n_unknown:
        print("[audit] --strict: 未登録語があるため終了コード 1")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

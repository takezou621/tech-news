# フェーズ1 自己テスト 生結果 (v2 ルール第5章の証跡)

- 実行日時: 2026-11-24 00:2x JST / 環境: Mac mini (Apple M4), Python 3.12 (uv), ffmpeg homebrew
- 実装: `tools/audio/selftest_guards.py` — 再実行コマンド:
  `uv run python tools/audio/selftest_guards.py --with-network`
- 制約: **成功する TTS 呼び出しは行わない** (ネットワーク系テストは失敗経路のみ)。
  本番の voice_config.json と月間文字数カウンタは変更しない (実行後確認: 951字/12リクエスト/pending 0 のまま無影響)。

## 生結果 (最終版・標準出力そのまま)

```
[selftest] dict=23語 script=test_script.json (成功TTS呼び出しは行わない)
PASS t01 辞書適用 (最長一致: OpenAI→AI 部分置換なし)
PASS t02 辞書適用 (境界: xAI 内 AI ブロック / NVIDIA社 接尾許可)
PASS t03 辞書検証 (かな以外の値を拒否)
PASS t04 単独ナレーター固定 (narrator 以外を拒否)
PASS t05 混在防止 (異なる config ハッシュで ABORT)
PASS t06 月間文字数上限 (monthlyStopChars で停止)
  retry 1/2 in 0s: HTTPError: HTTP Error 400: Bad Request
  retry 2/2 in 0s: HTTPError: HTTP Error 400: Bad Request
PASS t07 ウォッチドッグ (403 をリトライし TTSError / カウンタ計上なし)
PASS t08 ゲート欠落ビート (黙殺せず停止)
PASS t09 ゲートゼロビート (黙って PASS にしない)
PASS t10 全件照合 欠落ビート (CLI 経路で非0 終了)
[selftest] 10 tests: PASS=10 FAIL/ERROR=0 SKIP=0
終了コード: 0
```

機械可読版: `audio/audition/selftest_report.json`

## セルフテスト自体の修正履歴 (オープンリビュー指摘 → 修正 → 再実行)

初版のセルフテストに対するコードレビューで 4 件の指摘があり、すべて修正の上
再実行して上記の生結果を得た (証跡: git 履歴):

1. テストが `assert` 依存のため `python -O` で無意味化 → main 冒頭で `-O` を拒否 (確認済み: `-O` 付き実行は FAIL で停止)
2. テスト本体から `SystemExit` が漏れるとハーネスが停止 → `check()` が `SystemExit` を FAIL として記録するよう修正 (残りの判定を必ず実行)
3. t03/t04 の `except SystemExit: pass` が「正常終了」と区別できず偽 PASS の恐れ → 終了コードが空でないこと + 拒否理由メッセージの肯定検証に修正 (t08/t09 も同様)
4. t05 が本番 usage カウンタを参照したまま実行される可能性 → カウンタを一時ディレクトリへ隔離し、TTS も失敗経路 (無効クォータプロジェクト) に固定。ガードが壊れても本番汚染・成功呼び出しが起きない

## 補記 (正直な備録)

- t07 で無効クォータプロジェクトに対する HTTP ステータスは **400 Bad Request** だった
  (予想していた 403 ではなく)。リトライ → TTSError → カウンタ計上なしという
  ウォッチドッグ経路の検証目的は達成されている。ステータスコードの詳細は
  Google 側の応答に依存するため、テスト名の「403」は「失敗応答」の意と読み替えること。
- t07 はリトライ3回 (初回+2) を確認。本番設定のバックオフは 15/30/60 秒
  (voice_config.watchdog)。ハング (応答なしでのタイムアウト到達) の再現テストは未実施 —
  タイムアウト経路は同じ try/except 経由のためコード共有しているが、
  「未テスト」として記録する (回帰時は長 timeout + 遅いエンドポイントで要確認)。

## E2E スモークテスト (2026-11-23 実施分 — 詳細は docs/setup-report.md)

- 台本 → 辞書監査 → 生成 → 一貫性ゲート → 全文書き起こし照合 を
  ja-JP-Neural2-B/C/D の3候補で実施。**3候補とも ゲート PASS・照合 PASS**。
- 生結果ファイル (すべてコミット済み):
  - 監査: `audio/audition/pronunciation_audit_report.md` (置換19件・未登録0)
  - ゲート: `audio/audition/<voice>/voice_consistency_report.json`
  - 照合: `audio/audition/<voice>/transcribe_check_report.json` (全件照合 4/4 ビート)
  - 生成: `audio/audition/<voice>/manifest.json` (config ハッシュ記録) + `full.wav`

## 未整備 (テストが存在しない工程 = 品質未担保工程の台帳記録用)

| 工程 | 状態 |
|---|---|
| ミックス (BGM/ラウドネス -14 LUFS) | 未実装 → テスト未整備 |
| 字幕・図解カード生成 | 未実装 → テスト未整備 |
| 映像レンダー / 映像系 QC | 未実装 → テスト未整備 |
| ハング再現による watchdog タイムアウト経路のテスト | 未実施 (上記補記参照) |
| 日次パイプライン全体の回帰自動実行 (CI 相当) | 未整備 — 現状は手動実行 (selftest_guards.py) |

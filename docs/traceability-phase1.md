# フェーズ1 トレーサビリティ対応表 (v2 ルール第6章の証跡)

主要要件の「仕様条項 → 実装 → テスト／証跡」。仕様の出典は README.md、
監督プロンプト (フェーズ1、2026-11-23)、docs/ROLES.md v2。
監査用: 各行の証跡はリポジトリ内の実物にリンクしている (Muse が実物照合可能)。

| # | 仕様条項 (出典) | 実装 | テスト／証跡 |
|---|---|---|---|
| 1 | リポジトリ構成案どおりの土台 (README「リポジトリ構成」) | content/episodes, content/audition, tools/audio, audio, video, youtube, docs | git tree (コミット 7afbf35)。video/youtube は .gitkeep のみ |
| 2 | モデル/声/スタイル/パラメータを voice_config で固定 (README §4, プロンプト A) | [tools/audio/voice_config.json](../tools/audio/voice_config.json) (単一ファイル一元, rules 配列) / gen_narration.py が config のみ読込 | 全 audition manifest に config_hash 記録。音声尺・話速は candidates 間で config 由来の共通パラメータ ([audition_report.json](../audio/audition/audition_report.json)) |
| 3 | 設定が異なる既存音声の混在防止 (README §4, プロンプト A) | gen_narration.generate_beat_set: manifest の config_hash 不一致で ABORT | **selftest t05 PASS** (ABORT 再現) + 各 audition manifest 実物 |
| 4 | TTS 呼び出しにウォッチドッグ (ハング自動切断+再試行) (README §4, プロンプト A) | [cloud_tts.py](../tools/audio/cloud_tts.py) synthesize: timeoutSec で切断, maxRetries/backoffSec で再試行, フォールバックなし | **selftest t07 PASS** (失敗応答 400 を3回リトライ→TTSError, カウンタ計上なし)。ハング再現テストは未実施 (docs/selftest-phase1.md 補記) |
| 5 | ゼロコスト: Neural2 無料枠内, 月間文字数計測 (README §4, プロンプト固定事項) | cloud_tts.py: ja-JP-Neural2 以外を拒否 / reserve-finalize-release カウンタ / monthlyStopChars 90万で停止 | **selftest t06 PASS** + 実測カウンタ 951字/12リクエスト (usage/monthly-2026-11.json, gitignore 対象でローカル) + voices API 実測 (setup-report §1) |
| 6 | Gemini TTS 不使用 (プロンプト禁止事項, ROLES §11) | cloud_tts.py に Gemini 経路なし・ja-JP-Neural2 prefix guard | コード検証 (cloud_tts.py 全文) + t07 で別経路フォールバックが起きないことを確認 |
| 7 | 単独ナレーター1名 (固定決定) | gen_narration.load_script: narrator 以外で SystemExit / voice_config.voices.narrator のみ | **selftest t04 PASS** |
| 8 | 読み辞書: 検証してから登録, 出典記録, 未確認分離 (README §3, プロンプト C) | [pronunciation_dict.json](../tools/audio/pronunciation_dict.json) (23語) / [pronunciation_sources.md](../tools/audio/pronunciation_sources.md) (語ごとに出典URL+取得日) / [pronunciation_unverified.md](../tools/audio/pronunciation_unverified.md) (GPT・従量課金・K8s異読) | **selftest t03 PASS** (かな以外を拒否) + sources.md の出典記録そのもの |
| 9 | 生成前の辞書監査 (README §3, プロンプト A) | [pronunciation_audit.py](../tools/audio/pronunciation_audit.py) (漢字連続+英字トークンの未登録抽出) | 実施証跡: [pronunciation_audit_report.md](../audio/audition/pronunciation_audit_report.md) (置換19件・未登録0) |
| 10 | 辞書置換の正しさ (最長一致・単語境界) | [pronunciation.py](../tools/audio/pronunciation.py) | **selftest t01, t02 PASS** (OpenAI/AI 部分置換なし, xAI ブロック, NVIDIA社 接尾許可) |
| 11 | 音声一貫性ゲートを単独ナレーター用に調整 (プロンプト A) | [check_voice_consistency.py](../tools/audio/check_voice_consistency.py) (全ビート中央値比較, 閾値は config) | 実測: 3声とも PASS ([B](../audio/audition/ja-JP-Neural2-B/voice_consistency_report.json)/[C](../audio/audition/ja-JP-Neural2-C/voice_consistency_report.json)/[D](../audio/audition/ja-JP-Neural2-D/voice_consistency_report.json)) |
| 12 | 全文書き起こし照合・サンプリング禁止 (README §5, プロンプト A) | [transcribe_check.py](../tools/audio/transcribe_check.py) (全ビートループ, 欠落/ゼロビートで停止) | 実測: 3声とも PASS (各 transcribe_check_report.json, coverage: all 4/4) + **selftest t08, t09, t10 PASS** |
| 13 | 台本の数字・固有名詞は一次情報で裏取り (README §1, プロンプト固定事項) | [content/audition/sources.md](../content/audition/sources.md) (台本の全数字・固有名詞に出典URL) | sources.md の記録 (ja/en Wikipedia 実取得, 2026-11-23) |
| 14 | 声候補は実在確認してから選ぶ (プロンプト B) | voices list API 実測 (ja-JP-Neural2 は B/C/D の3声のみ) | setup-report §1 (HTTP 200 実測記録) |
| 15 | ブランチ作業・コミット, main 未マージ (プロンプト A) | ブランチ setup/production-pipeline | git log (5d7fc63 = main から分岐, マージコミットなし) |
| 16 | push / PR 作成 (可能なら) (プロンプト A) | git push + gh pr create | [PR #1](https://github.com/takezou621/tech-news/pull/1) |
| 17 | 認証情報・キーの値を出力/記録しない (プロンプト禁止事項, ROLES §8) | cloud_tts.get_access_token: トークンを変数内で保持, ログ/ファイル出力なし | リポジトリ全体にトークン値なし (コード検証 + cloud_tts.py L.147-160) |
| 18 | SLO 下支え: 再現性ある実行環境・冪等再実行・工程ログ (ROLES §7) | uv 依存指定コマンド, 同一ハッシュ WAV スキップ (冪等), manifest/timing レポート | 冪等性は t05 関連の実動作 (2回目実行で全ビート skip を実測, gen_audition ログ) + docs/selftest-phase1.md 未整備欄 |
| 19 | 日次公開 SLO 監視 (ROLES §7) | **未整備** (運用開始前のため) | 未実装 — 台帳記録 (selftest-phase1.md「未整備」欄)。次フェーズで監視手順の実装を提案 |
| 20 | レンダー/映像 QC (README §6-7) | **未整備** (フェーズ1 スコープ外として報告済み) | 未実装 — setup-report §5 の整備状況表どおり |

## 仕様外実装の確認

- 仕様外の機能は追加していない (辞書の ASCII キー拡張は README §3 の目的
  「読みを検証してから登録」を Tech 用語で満たすための実装詳細。仕様化が必要なら
  変更管理 (ROLES §10) で Muse の指示を待つ)。

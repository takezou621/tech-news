# tools/audio — ナレーション生成パイプライン

Tech系ニュースチャンネル用の音声生成 QC パイプライン。アニメ日本史ラボ
(`anime_japanese_history/tools/audio`) と eng-listening (`eng-listening/tools/content`)
の実績ある仕組みを、**Google Cloud TTS (ja-JP-Neural2) / 単独ナレーター** 用に適応したもの。

## 構成

| ファイル | 役割 |
|---|---|
| `voice_config.json` | 生成設定の一元管理 (声・話速・ウォッチドッグ・月間文字数上限・QC 閾値・運用ルール)。設定ハッシュで既存音声との混在を防止 |
| `cloud_tts.py` | Cloud TTS クライアント。ウォッチドッグ (ハング自動切断 + 上限リトライ)、月間文字数カウンタ (予約/確定/解放)、ja-JP-Neural2 以外の声を拒否。Gemini TTS は意図的に非対応 |
| `pronunciation.py` | 読み辞書の読込/適用/未登録語スキャン (共有モジュール) |
| `pronunciation_audit.py` | 生成前監査: 台本から辞書未登録語を洗い出す |
| `pronunciation_dict.json` | 読み辞書 (verified のみ)。出典は `pronunciation_sources.md` |
| `pronunciation_unverified.md` | 出典が確保できていない語 (辞書に入れない) |
| `gen_narration.py` | 台本 → 音声生成 (manifest に config ハッシュを記録) |
| `gen_audition.py` | 声候補オーディション用サンプル一括生成 |
| `check_voice_consistency.py` | 一貫性ゲート: F0/話速の外れ値検出 (単独ナレーター用) |
| `transcribe_check.py` | 全文書き起こし照合 (faster-whisper、全件・サンプリング禁止) |

## 1エピソードの生成手順 (リポジトリ ルートで実行)

```bash
# 0. 台本を content/episodes/<id>/script.json に置く
#    {"scenes":[{"id":"s01","beats":[{"speaker":"narrator","text":"...","reading":null}]}]}

# 1. 生成前の辞書監査 (未登録語を洗い出す)
uv run python tools/audio/pronunciation_audit.py --episode <id> --out reports/audit_<id>.md

# 2. 音声生成 (混在防止: config ハッシュ不一致の出力先があると中止)
uv run python tools/audio/gen_narration.py --episode <id>

# 3. 一貫性ゲート (F0/話速の外れ値検出)
uv run --with numpy python tools/audio/check_voice_consistency.py --episode <id>

# 4. 全文書き起こし照合 (全件・サンプリング禁止)
uv run --with faster-whisper --with pykakasi --with numpy \
  python tools/audio/transcribe_check.py --episode <id>
```

3 または 4 で FAIL したビートは `audio/<id>/narration/<beat>.wav` を削除して 2 から再実行
(同一 config ハッシュの WAV は自動スキップ、削除した分だけ再生成)。

## 認証

- 既存の gcloud ユーザー認証 (`voice_config.json` の `gcloudAccount`) を使う。
  アクセストークンはプロセス内でのみ保持し、ログ・ファイル・コミットに出さない。
- ユーザー認証で呼ぶ際は `X-Goog-User-Project` (クォータプロジェクト) ヘッダが必須。
- 課金設定の変更 (API 有効化、予算変更) は行わない。必要になったら停止して報告する。

## 月間文字数上限

- Neural2 無料枠は月100万文字 (課金アカウント単位。eng-listening と実質共有)。
- 当リポジトリのカウンタ (`tools/audio/usage/`, gitignore 済み) は自チャンネル分のみ。
  `monthlyStopChars` (90万) 到達で生成停止。概算: 5分/日 ≒ 月5万字で十分枠内。

## 声について

- 単独ナレーター 1 名 (`voices.narrator`)。候補比較は `audio/audition/` の
  オーディション結果を参照。voice_config の声は暫定 (推奨案) で、最終確定は監督側確認後。
- 声を差し替えると config ハッシュが変わり、既存音声との混在防止により
  既存エピソードの生成は中止される (全再生成が必要 — 仕様)。

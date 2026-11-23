# 読み辞書 出典記録 (verified)

`tools/audio/pronunciation_dict.json` に登録済み (verified) の語と、読みの検証方法。
登録ルール: **出典を確認できた語のみ登録する。推測の読みは登録しない。**
未確認の語は `pronunciation_unverified.md` に分離する。

検証日: 2026-11-23 (すべてこの日の実取得データに基づく)
検証方法: 日本語 Wikipedia 冒頭文のカタカナ併記 / 国語辞書 (デジタル大辞泉・実用日本語表現辞典、Weblio 経由) の読み欄

| キー | 採用読み | 出典 (実取得) | 備考 |
|---|---|---|---|
| NVIDIA | エヌビディア | ja.wikipedia「NVIDIA」冒頭「NVIDIA Corporation（エヌビディア・コーポレーション）」 | https://ja.wikipedia.org/wiki/NVIDIA |
| OpenAI | オープンエーアイ | ja.wikipedia「OpenAI」冒頭「OpenAI（オープンエーアイ、オープンAI）」 | https://ja.wikipedia.org/wiki/OpenAI |
| Anthropic | アンスロピック | ja.wikipedia「Anthropic」冒頭「Anthropic, PBC（アンソロピック、アンスロピック）」 | 2つの併記のうち日本メディアで一般的な「アンスロピック」を採用 (異読は備録) https://ja.wikipedia.org/wiki/Anthropic |
| Google | グーグル | ja.wikipedia「Google」冒頭「Google LLC（グーグル）」 | https://ja.wikipedia.org/wiki/Google |
| Microsoft | マイクロソフト | ja.wikipedia「マイクロソフト」冒頭 | https://ja.wikipedia.org/wiki/%E3%83%9E%E3%82%A4%E3%82%AF%E3%83%AD%E3%82%BD%E3%83%95%E3%83%88 |
| Apple | アップル | ja.wikipedia「Apple」冒頭「Apple Inc.（アップル・インク）」 | https://ja.wikipedia.org/wiki/Apple |
| Amazon | アマゾン | ja.wikipedia「Amazon.com」冒頭「Amazon.com, Inc.（アマゾン・ドット・コム・インク）」 | https://ja.wikipedia.org/wiki/Amazon.com |
| Meta | メタ | ja.wikipedia「Meta (企業)」冒頭「Meta Platforms, Inc.（メタ・プラットフォームズ、通称：Meta）」 | https://ja.wikipedia.org/wiki/Meta_(%E4%BC%81%E6%A5%AD) |
| GitHub | ギットハブ | ja.wikipedia「GitHub」冒頭「GitHub（ギットハブ）」 | https://ja.wikipedia.org/wiki/GitHub |
| Kubernetes | クバネティス | ja.wikipedia「Kubernetes」冒頭「Kubernetes（クバネティス/クバネテス/クーべネティス）」 | 第一表記「クバネティス」を採用。異読は未解決のため備録 (unverified 参照) https://ja.wikipedia.org/wiki/Kubernetes |
| Docker | ドッカー | ja.wikipedia「Docker」冒頭「Docker（ドッカー）」 | https://ja.wikipedia.org/wiki/Docker |
| Python | パイソン | ja.wikipedia「Python」冒頭「Python（パイソン）」 | https://ja.wikipedia.org/wiki/Python |
| TypeScript | タイプスクリプト | デジタル大辞泉 (Weblio)「タイプスクリプト【TypeScript】 読み方：たいぷすくりぷと」 | https://www.weblio.jp/content/%E3%82%BF%E3%82%A4%E3%83%97%E3%82%B9%E3%82%AF%E3%83%AA%E3%83%97%E3%83%88 |
| Rust | ラスト | ja.wikipedia「Rust (プログラミング言語)」冒頭「Rust（ラスト）」 | https://ja.wikipedia.org/wiki/Rust_(%E3%83%97%E3%83%AD%E3%82%B0%E3%83%A9%E3%83%9F%E3%83%B3%E3%82%B0%E8%A8%80%E8%AA%9E) |
| Gemini | ジェミニ | ja.wikipedia「Gemini (チャットボット)」冒頭「Gemini（ジェミニ）、旧称Bard（バード）」 | https://ja.wikipedia.org/wiki/Gemini_(%E3%83%81%E3%83%A3%E3%83%83%E3%83%88%E3%83%9C%E3%83%83%E3%83%88) |
| ChatGPT | チャットジーピーティー | ja.wikipedia「ChatGPT」冒頭「ChatGPT（チャットジーピーティー）」 | 同冒頭に「2022年11月に公開」の記述あり (テスト台本の数字の出典) https://ja.wikipedia.org/wiki/ChatGPT |
| Claude | クロード | ja.wikipedia「Claude」冒頭「Claude（クロード）とは、Anthropic社が開発した大規模言語モデルを用いた生成的人工知能チャットボット」 | https://ja.wikipedia.org/wiki/Claude |
| AI | エーアイ | ja.wikipedia「人工知能」冒頭「AI（エーアイ）」 | https://ja.wikipedia.org/wiki/%E4%BA%BA%E5%B7%A5%E7%9F%A5%E8%83%BD |
| LLM | エルエルエム | デジタル大辞泉 (Weblio)「エル‐エル‐エム【LLM】 読み方：えるえるえむ」 | 同義のためカタカナ表記を採用 (TTS 安定読み) https://www.weblio.jp/content/LLM |
| API | エーピーアイ | 実用日本語表現辞典 (Weblio)「API 別表記：エーピーアイ」 | https://www.weblio.jp/content/%E3%82%A8%E3%83%BC%E3%83%94%E3%83%BC%E3%82%A2%E3%82%A4 |
| GPU | ジーピーユー | 実用日本語表現辞典 (Weblio)「GPU 別表記：ジーピーユー」 | https://www.weblio.jp/content/GPU |
| CPU | シーピーユー | ja.wikipedia「CPU」冒頭「CPU（シーピーユー、英: central processing unit）」 | https://ja.wikipedia.org/wiki/CPU |
| 脆弱性 | ぜいじゃくせい | ja.wikipedia「脆弱性 (コンピュータセキュリティ)」冒頭「脆弱性（ぜいじゃくせい、英: vulnerability）」 | https://ja.wikipedia.org/wiki/%E8%84%86%E5%BC%B1%E6%80%A7_(%E3%82%B3%E3%83%B3%E3%83%94%E3%83%A5%E3%83%BC%E3%82%BF%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3) |

## 運用メモ

- TTS 入力への置換は `pronunciation.py` の `apply_pronunciation` (最長一致 + 単語境界考慮)。
  例: 「OpenAI」(6字) は「AI」(2字) より先に置換されるため、「AI」の部分置換は起きない。
  「xAI」等の途中一致は前隣が英数字のためブロックされる。
- 新規登録の提出方法: この表に「キー / 採用読み / 出典 URL / 取得日」を追記してから
  `pronunciation_dict.json` に登録する (出典なしの登録は不可)。
- 一般漢字語 (「開発」「市場」等) は TTS 既定読みに任せ、辞書には入れない (監査は
  ストップワードで除外)。辞書は「誤読リスクが実在し、出典で読みが確定した語」に限定する。

"""pronunciation.py — 読み辞書の読込・適用・未登録語スキャン (共有モジュール)。

アニメ日本史ラボ tools/audio/make_narration.py の辞書機構を本チャンネル用に拡張したもの:

- キーは「漢字を含む語」または「ASCII 英字で始まる英数字語」(NVIDIA, Kubernetes など)。
- 値はひらがな / カタカナ (+ 長音記号)。英語固有名詞はカタカナ表記で TTS に渡す
  (ja-JP-Neural2 はカタカナを安定して読む)。
- 置換は最長一致優先 + 単語境界考慮:
  - 漢字キー: 前隣が漢字なら置換しない (より長い未知の固有名詞を保護)。
    後隣が漢字でも、その漢字連続が接尾辞許可リストに一致すれば置換する。
  - ASCII キー: 前隣 / 後隣が英数字なら置換しない (トークン途中保護)。
    後隣が漢字 (例: NVIDIA社) なら置換する。
- 辞書値はかな文字なので、置換結果が後続キーと再マッチすることはない。

検証ルール: 辞書への登録は出典確認済み (verified) の語のみ。出典は
tools/audio/pronunciation_sources.md に語ごとに記録する。推測の読みは登録しない。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DICT_PATH = HERE / "pronunciation_dict.json"
SOURCES_DOC_PATH = HERE / "pronunciation_sources.md"

# 漢字相当文字 (境界判定用)
_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff々〆]")
# 値として許可するかな (ひらがな + カタカナ + 長音記号)
_KANA_VALUE_RE = re.compile(r"^[ぁ-ゖァ-ヺー]+$")
# ASCII キーとして許可する語 (英字で始まる英数字 + . - )
_ASCII_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
# 数字のみのキー (アニメ側と同等)
_DIGIT_KEY_RE = re.compile(r"^[0-9%]+$")
# 漢字キーの後隣接で置換を許可する接尾辞 (「名前+接尾」形式)
NAME_SUFFIXES = ("社", "製", "系", "向け", "版", "的", "側", "上", "等", "ら")

# 監査ノイズ除去用の一般語ストップワード (固有名詞ではない頻出語)
STOPWORDS = {
    # 漢字語 (技術一般)
    "人工知能", "機械学習", "深層学習", "自己教師", "強化学習", "教師なし",
    "大規模", "言語処理", "自然言語", "画像認識", "音声認識", "情報処理",
    "電子計算", "計算機", "半導体", "集積回路", "電池", "充電", "放電",
    "経済", "市場", "産業", "企業", "会社", "事業", "製品", "商品", "販売",
    "開発", "発表", "公開", "提供", "開始", "終了", "決算", "売上", "利益",
    "四半期", "年度", "本日", "今日", "昨日", "明日", "現在", "当時", "最新",
    "調査", "報告", "発表資料", "報道", "取材", "記事", "記者", "会見",
    "問題", "課題", "対策", "影響", "効果", "結果", "理由", "経緯",
    "研究", "開発者", "技術者", "専門家", "識者", "有識者",
    "規制", "法律", "条例", "法案", "政府", "省庁", "当局",
    "実際", "本質", "概念", "定義", "理論", "方式", "手法", "方法",
    "性能", "能力", "精度", "速度", "容量", "面積", "面積密度",
    "昨年", "今年", "来年", "数年", "数ヶ月", "数日", "数時間",
    "利用", "活用", "使用", "導入", "運用", "保守", "管理", "運営",
    "需要", "供給", "投資", "出資", "買収", "合併", "提携", "契約",
    "時点", "段階", "状況", "事象", "事例", "実例", "具体例",
    "解説", "一次情報", "前提", "確認", "大手", "現場", "定番", "登場",
    "対応", "毎日", "習慣", "順番", "基本", "技術", "基盤", "整備",
}


def is_ascii_key(key: str) -> bool:
    return bool(_ASCII_KEY_RE.fullmatch(key))


def load_pronunciation_dict(path: str | Path | None = None) -> tuple[dict, str | None]:
    """読み辞書を読み込む。戻り値 (辞書, sha256 先頭12桁)。ファイルがなければ ({}, None)。

    検証ルール:
    - 値はひらがな / カタカナ (+ 長音記号) のみ。
    - キーは漢字を含むか、ASCII 英字で始まる英数字語、または数字 (+%) のみ。
    """
    p = Path(path) if path else DEFAULT_DICT_PATH
    if not p.exists():
        return {}, None
    raw = p.read_bytes()
    d = json.loads(raw.decode("utf-8"))
    for k, v in d.items():
        if not _KANA_VALUE_RE.match(v):
            raise SystemExit(f"pronunciation_dict.json の値がかな文字でありません: {k}={v}")
        has_kanji = bool(_KANJI_RE.search(k))
        if not (has_kanji or _ASCII_KEY_RE.fullmatch(k) or _DIGIT_KEY_RE.fullmatch(k)):
            raise SystemExit(
                f"pronunciation_dict.json のキーが不正です (漢字/ASCII英数字語/数字のいずれでもない): {k}")
    return d, hashlib.sha256(raw).hexdigest()[:12]


def apply_pronunciation(text: str, pdict: dict) -> tuple[str, list[dict]]:
    """辞書による読み置換。最長一致優先 + 単語境界考慮。

    戻り値 (置換後テキスト, 置換リスト [{"from", "to"}])。script.json は変更しない。
    """
    repls: list[dict] = []
    keys = sorted(pdict, key=lambda k: (-len(k), k))
    for key in keys:
        val = pdict[key]
        ascii_key = is_ascii_key(key)
        pos = 0
        while True:
            i = text.find(key, pos)
            if i < 0:
                break
            j = i + len(key)
            prev = text[i - 1] if i > 0 else ""
            nxt = text[j] if j < len(text) else ""
            if ascii_key:
                prev_blocked = bool(re.match(r"[A-Za-z0-9]", prev))
                next_blocked = bool(re.match(r"[A-Za-z0-9]", nxt))
            else:
                prev_blocked = bool(_KANJI_RE.match(prev)) if prev else False
                if _KANJI_RE.match(nxt) if nxt else False:
                    m = _KANJI_RE.match(text, j)
                    following = text[j: m.end()] if m else ""
                    next_blocked = following not in NAME_SUFFIXES
                else:
                    next_blocked = False
            if prev_blocked or next_blocked:
                pos = i + 1
                continue
            text = text[:i] + val + text[j:]
            repls.append({"from": key, "to": val})
            pos = i + len(val)
    return text, repls


def scan_kanji_runs(text: str) -> list[str]:
    """2字以上の漢字連続を抽出する (固有名詞候補)。"""
    return re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff々〆]{2,}", text)


def scan_ascii_tokens(text: str) -> list[str]:
    """ASCII 英字で始まる英数字トークンを抽出する (企業・製品名候補)。"""
    return re.findall(r"[A-Za-z][A-Za-z0-9._-]*", text)


def audit_terms(texts: list[str], pdict: dict) -> dict:
    """TTS 入力テキスト群から辞書未登録語を洗い出す (生成前監査)。

    texts には辞書適用「前」の台本テキストを渡す (辞書で置換した結果に
    辞書キーは残らないため、監査は原文に対して行う)。
    戻り値 {"kanji": {語: {"count", "example"}}, "ascii": {...}}。
    ストップワードと辞書登録済み語は除外する。
    """
    out = {"kanji": {}, "ascii": {}}
    for raw in texts:
        tts_text, _repls = apply_pronunciation(raw, pdict)
        for run in scan_kanji_runs(tts_text):
            if run in pdict or run in STOPWORDS:
                continue
            c = out["kanji"].setdefault(run, {"count": 0, "example": ""})
            c["count"] += 1
            if not c["example"]:
                c["example"] = _context(raw, run)
        for tok in scan_ascii_tokens(raw):
            if tok in pdict:
                continue
            if tok.isdigit() or not re.search(r"[A-Za-z]", tok):
                continue
            c = out["ascii"].setdefault(tok, {"count": 0, "example": ""})
            c["count"] += 1
            if not c["example"]:
                c["example"] = _context(raw, tok)
    return out


def _context(text: str, term: str, width: int = 14) -> str:
    snippet = re.sub(r"\s+", "", text)
    k = snippet.find(term)
    if k < 0:
        return term
    lo, hi = max(0, k - width), min(len(snippet), k + len(term) + width)
    return ("…" if lo else "") + snippet[lo:hi] + ("…" if hi < len(snippet) else "")

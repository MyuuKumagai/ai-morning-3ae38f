#!/usr/bin/env python3
"""毎朝のAIニュースレターを1枚作る。

ai_news.py が集めた新着ノート → Gemini(無料キー)で「重要な5本」を選び、
本人の生活・仕事に引きつけた『使い道』を付けて、雑誌風の1枚に組む。

設計判断（2026-07-21 本人ヒアリングで確定）:
- 出力は Markdown ではなく HTML。表紙に見出しを重ねる／左に朱の縦罫／写真つき2カラム
  という組版は Markdown では表現できないため。CSSは .obsidian/snippets/newsletter.css。
- 画像は i.ytimg.com のサムネイルを直リンク（実測: hqdefault=約30KB, 200 OK / ¥0）。
  ダウンロードして持つとVaultが太るだけなので持たない。
- 見出しも写真も元ソースへのリンク。どこを押しても元ネタに飛べる。

使い方: python3 ai_newsletter.py [--date YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations  # python3.9 では `dict | None` が実行時エラーになるため

import argparse
import datetime
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# gen_gists は import 時に .venv へ乗り換えようとするので argv[0] を空にして止める
# （理由の詳細は gist_folder.py の同じ箇所のコメント参照）
_argv0, sys.argv[0] = sys.argv[0], ""
import gen_gists as g
sys.argv[0] = _argv0
# クラウドではObsidianのVaultが無いので、この読み込みは必須にしない
try:
    import youtube_explain as yx  # noqa: F401
except Exception:
    yx = None


def _data_root():
    """記事の保管場所。

    Macで動くときはObsidianのVault、クラウド(GitHub Actions)で動くときは
    リポジトリ内のフォルダを使う。環境変数 AI_DATA_DIR があればそちらを優先する。
    こうしておくと、同じコードがMacでもクラウドでも動く。
    """
    import os
    override = os.environ.get("AI_DATA_DIR", "").strip()
    if override:
        return Path(override)
    import youtube_explain as _yx
    return _yx.VAULT / "60 Jibun-AI"

BASE = _data_root() / "captures" / "ai_news"
OUTDIR = _data_root() / "newsletter"
GISTS = Path(__file__).resolve().parent / "gists.json"

PICK = 5
LOOKBACK_DAYS = 3  # 新着が薄い日でも中身が空にならないよう遡る日数

# 本人の文脈。『使い道』をこの4観点に引きつけるために渡す。
# 読者の「今」は reader_context.md に外出しした。生活が変われば、あのファイルだけ直せばよい。
_CTX_FILE = Path(__file__).resolve().parent / "reader_context.md"
CONTEXT = _CTX_FILE.read_text(encoding="utf-8") if _CTX_FILE.exists() else "読者はMyuu。日本語話者。"

CATEGORIES = ["仕事", "お金", "暮らし", "未来"]

PROMPT = """あなたは日本語のAIニュース編集者です。下の候補から、読者にとって重要な{pick}本を選んでください。

{context}
【書き方のルール】
- category は必ず「仕事」「お金」「暮らし」「未来」のどれか1つ
- headline: 日本語28字以内。体言止め可。誇張しない
- summary: 日本語60〜90字。何が変わったのかを事実で書く。「〜と紹介されています」のような伝聞は書かない
- use: 日本語45字以内。読者の状況に引きつけた具体的な使い道。当てはまらないなら空文字にする
- 1本目には最も重要なものを置く
- 候補にYouTube動画（urlがyoutube.com）があれば、**最低1本は必ず選ぶ**。
  動画には具体的な手順や使い方が入っていて、記事より実用的なことが多い

【出力】JSON配列のみ。コードフェンス禁止。
[{{"id":"候補のid","category":"仕事","headline":"...","summary":"...","use":"..."}}]

【候補】
{items}
"""


def read_note(f: Path) -> dict | None:
    """ノートのフロントマターと見出しを読む。壊れていたら None。"""
    try:
        text = f.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    fm = text.split("---", 2)[1]
    meta = {}
    for line in fm.splitlines():
        m = re.match(r"^(\w+):\s*(.+?)\s*$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip('"')
    title = ""
    m = re.search(r"^# (.+)$", text, re.M)
    if m:
        title = m.group(1).strip()
    if not (meta.get("video_id") and meta.get("url")):
        return None
    return {
        "id": meta["video_id"],
        "url": meta["url"],
        "channel": meta.get("channel", ""),
        "published": meta.get("published", ""),
        "collected": meta.get("collected", ""),
        "title": title or meta.get("video_id"),
        # RSS記事は自前の画像URLと要約を持つ。YouTubeはサムネをIDから組み立てる。
        "image": meta.get("image", ""),
        "summary_fm": meta.get("summary", ""),
        "path": f,
    }


def candidates(today: datetime.date) -> list[dict]:
    """その日に取り込まれたノートを集める。薄ければ数日遡る。"""
    gists = json.loads(GISTS.read_text(encoding="utf-8")) if GISTS.exists() else {}
    notes = []
    for f in BASE.glob("*/*.md"):
        n = read_note(f)
        if n:
            n["gist"] = gists.get(n["id"], "") or n["summary_fm"]
            notes.append(n)

    for back in range(LOOKBACK_DAYS + 1):
        cutoff = (today - datetime.timedelta(days=back)).isoformat()
        hit = [n for n in notes if n["collected"] >= cutoff]
        if len(hit) >= PICK:
            break
    # 公開が新しい順。鮮度が命（取り込み完成基準 C章）
    hit.sort(key=lambda n: n["published"], reverse=True)
    return hit[:40]


def choose(items: list[dict]) -> list[dict]:
    """Geminiに5本選ばせる。失敗しても空にせず、素の新着順で返す。"""
    if not items:
        return []
    listing = "\n".join(
        f'- id:{n["id"]} / {n["channel"]} / {n["published"]} / {n["title"]}'
        + (f' / 要約:{n["gist"]}' if n["gist"] else "")
        for n in items
    )
    prompt = PROMPT.format(pick=PICK, context=CONTEXT, items=listing)
    try:
        raw = g.call(g.LITE, prompt)
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
        picked = json.loads(raw)
    except Exception as e:
        print(f"⚠️ 選定に失敗したので新着順で組みます: {e}", file=sys.stderr)
        picked = []

    by_id = {n["id"]: n for n in items}
    out = []
    for p in picked:
        n = by_id.get(str(p.get("id", "")))
        if not n:
            continue
        cat = p.get("category", "")
        n = dict(n)
        n["category"] = cat if cat in CATEGORIES else "未来"
        n["headline"] = (p.get("headline") or n["title"])[:40]
        n["summary"] = p.get("summary") or n["gist"]
        n["use"] = p.get("use") or ""
        out.append(n)
        if len(out) >= PICK:
            break

    # 動画には具体的な手順が入っていて記事より実用的なので、必ず1本は紙面に入れる。
    # プロンプトで頼むだけだと守られないことがあるため、ここで確実にする（2026-07-21 本人要望）。
    vids = [n for n in items if "youtube.com" in n.get("url", "")]
    if vids and not any("youtube.com" in n.get("url", "") for n in out):
        v = dict(vids[0])
        v["category"] = "仕事"
        v["headline"] = v["title"][:40]
        v["summary"] = v["gist"]
        v["use"] = ""
        out = out[:PICK - 1] + [v] if len(out) >= PICK else out + [v]

    # モデルが5本返さない／存在しないidを返すことがある。足りない分は新着順で埋める。
    # （実測 2026-07-21: 3本しか返らず紙面が薄くなった）
    used = {n["id"] for n in out}
    for n in items:
        if len(out) >= PICK:
            break
        if n["id"] in used:
            continue
        n = dict(n)
        n["category"] = "未来"
        n["headline"] = n["title"][:40]
        n["summary"] = n["gist"]
        n["use"] = ""
        out.append(n)
    return out


TEXT_CACHE = Path(__file__).resolve().parent / "article_text.json"
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

DETAIL_PROMPT = """あなたは日本語のAI専門記者です。下の{n}本について、読者が「これだけ読めば分かった」と
言える解説を書いてください。元記事に飛ばなくても中身が理解できることが最重要です。

{context}
【文体】※2026-07-21に本人が3案を聞き比べて決定
- **ですます調**。大人どうしの対等な会話。落ち着いたトーンを保つ
- ただし**わかりやすさを最優先**。難しい話は「ざっくり言うと」で要点を先に言い、
  身近なたとえを1つ入れて腑に落ちるようにする
- **タメ口・幼い言い回しは禁止**（「〜なんだよね」「〜ってこと！」など）。
  子ども扱いに聞こえる書き方をしない
- 読み上げ音声にもなるので、耳で聞いて分かる語順・長さにする
- **「AI」「ツール」「企業」のような曖昧な言葉で済ませない。**
  どのAIか（Claude / ChatGPT / Gemini など）、どの会社か（Anthropic / OpenAI / Google など）を
  具体名で書く。全般を指すなら「Claude や ChatGPT などのAIアシスタント」のように例を添える。
  ※2026-07-21に本人から「このAIって何を指しているの？」という指摘が出たため

【各本文の書き方】
- 日本語300〜420字。3つの段落に分け、段落の区切りは \\n で表す
- 1段落目: **今回いつ何が起きたのか**。「◯◯が△△を発表した」のように、
  **今回のニュースそのもの**を最初の1文で言い切る。制度や技術の一般的な説明から始めない。
  背景説明が要るなら2文目以降に回す。事実・固有名詞・数字は元テキストにあるものだけ使う
  ※2026-07-21に本人から「昔からある話を説明されてもニュースじゃない」と指摘されたため
- **「いつ」は2種類あるので必ず区別する**（2026-07-24に本人から指摘）:
  (a) **その動画・記事が公開された日**（元テキストの日付。読者にはこちらが「情報の鮮度」）
  (b) **その機能・サービスが実際に使えるようになった日／なる日**（提供開始日・リリース日）
  元テキストから (b) が分かるなら「◯月◯日から使えます」のように**本文にはっきり書く**。
  (a) と (b) を混同して書かない。**どちらも推測で作らない**。
  (b) が元テキストに無いなら「提供開始日は明示されていません」と一言添えるだけでよい（無理に探さない）
- 2段落目: なぜそれが重要なのか。今までと何が変わるのか
- 3段落目: **読者の「今」とのつながり**。上の表にある具体名（自分AI、こころの観察日記、Suno MV、
  焼きそばサイト、家計システム、英語学習 など）を必ず1つ以上出し、その場面で何が変わるかを書く。
  一般論（「業務効率が上がります」等）は禁止。本当に関係が薄いなら「今のあなたには直接は関係しない。
  ただし〜」と正直に書く
- 元テキストに書かれていないことは書かない。分からないことは書かない
- 「〜してください」「要チェック」のような指図・煽りは書かない。淡々と事実と意味を書く

【出力】JSON配列のみ。コードフェンス禁止。順番は入力と同じ。
[{{"id":"...","body":"1段落\\n2段落\\n3段落"}}]

【元テキスト】
{items}
"""


def source_text(n: dict, limit: int = 5000) -> str:
    """解説を書くための元テキスト。YouTubeはノート内の字幕、記事は本文を取りに行く。"""
    body = ""
    try:
        raw = n["path"].read_text(encoding="utf-8")
        body = raw.split("---", 2)[-1]
        body = re.sub(r"^#.*$", "", body, flags=re.M).strip()
    except Exception:
        body = ""
    if len(body) > 400:  # YouTubeノートは字幕全文が入っているので十分
        return body[:limit]

    # RSSノートは説明文が短い。記事ページから本文を取ってくる（要約の材料としてのみ使う）
    cache = {}
    if TEXT_CACHE.exists():
        try:
            cache = json.loads(TEXT_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    url = n.get("url", "")
    if url in cache:
        return (cache[url] or body)[:limit]

    text = ""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": UA_BROWSER})
        page = urllib.request.urlopen(req, timeout=20).read(400_000).decode("utf-8", "ignore")
        page = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
        page = re.sub(r"<[^>]+>", " ", page)
        text = re.sub(r"\s+", " ", html.unescape(page)).strip()
    except Exception:
        text = ""

    cache[url] = text[:limit]
    try:
        TEXT_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return (text or body)[:limit]


def add_details(stories: list[dict]) -> list[dict]:
    """各記事に読み応えのある本文をつける。

    本人の指摘（2026-07-21）:「読みにくいし、タイトル押しても中身見えない」
    ＝ 2文の要約しか無く、読むものが無かった。外部に飛ばずに読み切れる本文を持たせる。
    """
    if not stories:
        return stories
    blocks = []
    for s in stories:
        blocks.append(f'### id:{s["id"]} / {s["channel"]} / {s["headline"]}\n{source_text(s)}')
    prompt = DETAIL_PROMPT.format(n=len(stories), context=CONTEXT, items="\n\n".join(blocks))
    # 混雑(503)は一時的なので粘る。ここで諦めると本文の無い薄い紙面になってしまう
    # （実測2026-07-22 00:52: 503で全記事が要約1文だけになった）。
    got = {}
    import time
    for attempt in range(4):
        model = g.FLASH if attempt < 2 else g.LITE  # 粘っても駄目なら軽いモデルに落とす
        try:
            raw = g.call(model, prompt)  # 読み物の質を優先して上位モデルを使う
            raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
            got = {str(d.get("id", "")): d.get("body", "") for d in json.loads(raw)}
            if got:
                break
        except Exception as ex:
            wait = 20 * (attempt + 1)
            if attempt < 3:
                print(f"  本文生成が混雑。{wait}秒待って再試行 {attempt + 1}/3", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"⚠️ 本文生成に失敗（要約のみで出します）: {ex}", file=sys.stderr)
    for s in stories:
        s["body"] = got.get(s["id"], "")
    return stories


def thumb(s: dict) -> str:
    """画像URLを返す。無ければ空文字（呼び側が文字の枠に差し替える）。

    RSS記事のidはURLのハッシュなので、YouTubeのサムネURLに当てると必ず404になる。
    実測 2026-07-21: この取り違えで5本中4本の画像が壊れていた。
    """
    if s.get("image"):
        return s["image"]
    if "youtube.com/watch" in s.get("url", "") or "youtu.be/" in s.get("url", ""):
        return f"https://i.ytimg.com/vi/{s['id']}/hqdefault.jpg"
    return ""


def figure(s: dict, cls: str) -> str:
    """写真があれば写真、無ければ媒体名を置いた枠。紙面に穴を開けない。"""
    src = thumb(s)
    inner = (
        f'<img src="{src}" alt="">' if src
        else f'<span class="nl-noimg">{e(s.get("channel", ""))}</span>'
    )
    return f'<a class="{cls}" href="{e(s["url"])}">{inner}</a>'


def e(s: str) -> str:
    return html.escape(s or "", quote=True)


def cover_first(stories: list[dict]) -> list[dict]:
    """表紙には絵が要る。1本目に画像が無ければ、画像を持つ最上位の記事を表紙へ繰り上げる。"""
    if not stories or thumb(stories[0]):
        return stories
    for i, s in enumerate(stories):
        if thumb(s):
            return [s] + stories[:i] + stories[i + 1:]
    return stories


def render(day: datetime.date, stories: list[dict], vol: int, yesterday: list[dict]) -> str:
    stories = cover_first(stories)
    top, rest = stories[0], stories[1:]
    d = day.strftime("%Y.%m.%d")
    wd = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][day.weekday()]

    rows = []
    for s in rest:
        use = (
            f'<p class="nl-use nl-{CATEGORIES.index(s["category"])}">{e(s["use"])}</p>'
            if s["use"] else ""
        )
        rows.append(f'''<div class="nl-row">
{figure(s, "nl-thumb")}
<div class="nl-body">
<p class="nl-cat nl-{CATEGORIES.index(s["category"])}">{e(s["category"])}</p>
<h3 class="nl-h"><a href="{e(s["url"])}">{e(s["headline"])}</a></h3>
<p class="nl-sum">{e(s["summary"])}</p>
{use}
</div>
</div>''')

    back = ""
    if yesterday:
        links = "".join(
            f'<li><a href="{e(y["url"])}">{e(y["headline"])}</a></li>' for y in yesterday[:3]
        )
        back = f'<div class="nl-back"><p class="nl-cat">昨日の分</p><ul>{links}</ul></div>'

    top_use = f'<p class="nl-use nl-0">{e(top["use"])}</p>' if top["use"] else ""

    return f'''<div class="nl">

<div class="nl-cover">
{figure(top, "nl-cover-img")}
<div class="nl-cover-text">
<p class="nl-cat nl-{CATEGORIES.index(top["category"])}">{e(top["category"])} — TOP STORY</p>
<h2 class="nl-title"><a href="{e(top["url"])}">{e(top["headline"])}</a></h2>
</div>
</div>

<div class="nl-main">
<div class="nl-rule"><span>{d}</span></div>
<div class="nl-content">
<p class="nl-lede">{e(top["summary"])}</p>
{top_use}
{back}
{"".join(rows)}
<p class="nl-foot">YOUTUBE 6CH · NEWS 7SOURCES &nbsp;—&nbsp; {d} {wd} &nbsp;·&nbsp; VOL.{vol}</p>
</div>
</div>

</div>'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    day = datetime.date.fromisoformat(a.date) if a.date else datetime.date.today()
    items = candidates(day)
    if not items:
        print("候補が0本でした。ニュースレターは作りません。")
        return 0

    stories = add_details(choose(items))
    if not stories:
        print("選定結果が0本でした。")
        return 1

    OUTDIR.mkdir(parents=True, exist_ok=True)
    # 号数は「今日より前の号の数＋1」。同じ日に作り直しても番号が増えないようにする
    # （実測 2026-07-21: 単純に枚数を数えると再実行でVOL.2になってしまった）
    vol = len([p for p in OUTDIR.glob("20*.md") if p.stem < day.isoformat()]) + 1

    prev_path = OUTDIR / f"{(day - datetime.timedelta(days=1)).isoformat()}.md"
    yesterday = []
    if prev_path.exists():
        prev = prev_path.read_text(encoding="utf-8")
        for m in re.finditer(r'<h3 class="nl-h"><a href="([^"]+)">([^<]+)</a>', prev):
            yesterday.append({"url": m.group(1), "headline": m.group(2)})

    body = render(day, stories, vol, yesterday)
    note = f"""---
type: ai-newsletter
date: {day.isoformat()}
vol: {vol}
cssclasses: [newsletter]
tags: [jibun-ai, ai-news, newsletter]
---

{body}
"""
    out = OUTDIR / f"{day.isoformat()}.md"
    if a.dry_run:
        print(note)
        return 0
    out.write_text(note, encoding="utf-8")
    # 「今朝のAI」は常に最新号を指す固定の入口（Obsidianは裏の保管庫）。
    (OUTDIR / "今朝のAI.md").write_text(note, encoding="utf-8")
    print(f"✅ Obsidian: {out.name}  ({len(stories)}本 / VOL.{vol})")

    # 本人が読むのはこちら。iCloudに完全自己完結の1枚を書き出す（画像・CSS内蔵）。
    # 失敗しても棚とノートは守るので握りつぶさず表示だけする。
    try:
        import ai_newsletter_page as page
        p = page.write_page(day, stories, vol, yesterday)
        print(f"✅ iCloud: {p} ({p.stat().st_size // 1024} KB)")
    except Exception as ex:
        print(f"⚠️ iCloudページの書き出しに失敗: {ex}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

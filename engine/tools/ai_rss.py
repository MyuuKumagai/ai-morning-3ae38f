#!/usr/bin/env python3
"""AIニュースをRSSから取り込む（YouTubeより速報が速い層をカバーする）。

なぜXではなくRSSなのか（2026-07-21 実測）:
- X公式APIは2026年2月に無料枠が廃止。新規は従量課金のみで1投稿$0.005
- Nitter（Xの無料ミラー）は応答0バイト＝死んでいる
- Bluesky検索API(public.api.bsky.app)は 403＝認証必須になっている
→ 「Xが速い」の本質は“速報が欲しい”こと。それは下のRSS群で¥0のまま満たせる。
   全ソース実測でHTTP 200・キー不要・課金なしを確認済み。

書き出し先は ai_news.py と同じ captures/ai_news 配下なので、
ai_newsletter.py は何も変えずにこれらも候補として拾う。

使い方: python3 ai_rss.py [--days 3]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import re
import sys
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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

# "媒体名|URL"
FEEDS = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Anthropic", "https://feeds.feedburner.com/anthropic"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 jibun-ai/1.0"
TAG = re.compile(r"<[^>]+>")


def clean(s: str, limit: int = 300) -> str:
    """HTMLタグとCDATAを落として1行にする。フロントマターに入れるので改行は許さない。"""
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s or "", flags=re.S)
    s = TAG.sub(" ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()[:limit]


def parse_date(block: str) -> str:
    for pat in (r"<pubDate>(.*?)</pubDate>", r"<published>(.*?)</published>", r"<updated>(.*?)</updated>"):
        m = re.search(pat, block, re.S)
        if not m:
            continue
        raw = m.group(1).strip()
        try:
            return parsedate_to_datetime(raw).date().isoformat()
        except Exception:
            pass
        try:
            return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except Exception:
            pass
    return ""


def parse_image(block: str) -> str:
    for pat in (
        r'<media:thumbnail[^>]+url="([^"]+)"',
        r'<media:content[^>]+url="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'<enclosure[^>]+url="([^"]+)"[^>]*type="image/',
        r'<img[^>]+src="([^"]+)"',
        r'&lt;img[^&]+src=[\'"]([^\'"]+)',
    ):
        m = re.search(pat, block, re.I)
        if m:
            url = html.unescape(m.group(1))
            if url.startswith("http"):
                return url
    return ""


def parse_link(block: str) -> str:
    m = re.search(r"<link>(.*?)</link>", block, re.S)
    if m and m.group(1).strip().startswith("http"):
        return clean(m.group(1), 400)
    m = re.search(r'<link[^>]+rel="alternate"[^>]*href="([^"]+)"', block)
    if m:
        return html.unescape(m.group(1))
    m = re.search(r'<link[^>]+href="([^"]+)"', block)
    return html.unescape(m.group(1)) if m else ""


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "ignore")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args()

    today = datetime.date.today()
    since = (today - datetime.timedelta(days=a.days)).isoformat()
    added = skipped = 0

    for name, url in FEEDS:
        try:
            raw = fetch(url)
        except Exception as e:
            print(f"⚠️ {name}: 取得できず ({e})", file=sys.stderr)
            continue

        blocks = re.findall(r"<item>.*?</item>|<entry>.*?</entry>", raw, re.S)
        folder = BASE / name
        folder.mkdir(parents=True, exist_ok=True)

        for b in blocks[:30]:
            pub = parse_date(b)
            if not pub or pub < since:
                continue
            link = parse_link(b)
            if not link:
                continue
            m = re.search(r"<title[^>]*>(.*?)</title>", b, re.S)
            title = clean(m.group(1), 160) if m else ""
            if not title:
                continue

            # URLから安定したIDを作る（同じ記事を二度取らないため）
            nid = hashlib.sha1(link.encode()).hexdigest()[:11]
            f = folder / f"{nid}.md"
            if f.exists():
                skipped += 1
                continue

            m = re.search(r"<description>(.*?)</description>|<summary[^>]*>(.*?)</summary>|<content[^>]*>(.*?)</content>", b, re.S)
            desc = clean((m.group(1) or m.group(2) or m.group(3)) if m else "", 400)
            img = parse_image(b)

            f.write_text(
                "---\n"
                "type: ai-news\n"
                f"channel: {name}\n"
                f"video_id: {nid}\n"
                f"published: {pub}\n"
                f"collected: {today.isoformat()}\n"
                f"url: {link}\n"
                + (f"image: {img}\n" if img else "")
                + f'summary: "{desc.replace(chr(34), chr(39))}"\n'
                "tags: [jibun-ai, ai-news, rss]\n"
                "---\n\n"
                f"# {title}\n\n"
                f"**公開日: {pub}**（取得: {today.isoformat()}）\n"
                f"出典: {link}\n\n"
                f"{desc}\n",
                encoding="utf-8",
            )
            added += 1

    print(f"✅ RSS取り込み: 新規{added}本 / 既存スキップ{skipped}本")
    return 0


if __name__ == "__main__":
    sys.exit(main())

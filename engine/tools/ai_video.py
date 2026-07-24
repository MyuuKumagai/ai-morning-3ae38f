#!/usr/bin/env python3
"""字幕が無いYouTube動画を、動画そのものから理解してノートにする。

なぜ必要か（2026-07-21 実測）:
- 既存の ai_news.py は**字幕（文字起こし）が取れない動画をスキップ**していた。
  今朝8時の実行ログでは AI大学だけで「字幕なし14本」。つまり日本語チャンネルの新着が
  ほぼ丸ごと落ちており、ニュースレターがRSS記事ばかりになっていた
- 本人の要望「YouTubeの動画の内容も持ってきて。動画を見なくても実用で使えるくらい理解したい」

Gemini に YouTube の URL をそのまま渡すと、字幕が無くても中身を説明できることを実測で確認
（gemini-3.5-flash / 1本あたり約6万トークン）。それを使って解説ノートを作る。

出力先は ai_news.py と同じ captures/ai_news/<チャンネル名>/ なので、
ニュースレター側は何も変えずにこれらを候補として拾う。

使い方: python3 ai_video.py [--days 2] [--max 6]
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import urllib.request
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
MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]

# ai_auto_update.sh と同じ並び・同じ指定方法（ハンドル or 完全URL）。
# YouTubeのRSSは ?user=<handle> では引けない（実測2026-07-21: 0本）。
# 既存の ai_news.py と同じく yt-dlp で動画一覧を取る方が確実なので、そちらに揃える。
CHANNELS = [
    ("チャエン【AI研究所】", "chaen-ai-lab"),
    ("AI大学", "https://www.youtube.com/channel/UCXo1SsIDZ_dke2Nr1r3qk6w/videos"),
    ("池田朋弘の生成AIビジネス活用研究所", "iketomo-gai-lab"),
    ("秋好陽介(ランサーズ)", "https://www.youtube.com/@%E3%82%89%E3%82%93%E3%81%95%E3%83%BC%E3%81%9A/videos"),
    ("Matt Wolfe", "mreflow"),
    ("AI Explained", "aiexplained-official"),
]

PROMPT = """この動画を見て、日本語で解説ノートを書いてください。
読む人が **動画を見なくても実際に使えるレベル** で理解できることが最重要です。

【書き方】
- 見出しは付けず、本文だけ
- 全体で700〜1000字
- 次の順で書く:
  1. この動画で紹介されている中心のもの（サービス名・機能名を正確に）と、何ができるのか
  2. **具体的な手順や使い方**。動画で示された操作・設定・コツを、順番が分かるように書く
  3. 料金や制限（無料でどこまでできるか）。動画で触れていなければ書かない
  4. 注意点・向いていない場面
- 動画で言っていないことは書かない。推測で補わない
- ですます調。専門用語には短い言い換えを添える
"""


def _yt_dlp() -> str:
    """yt-dlpの場所。launchdやここからの実行ではPATHに入っていないので明示的に探す
    （実測2026-07-21: `No such file or directory: 'yt-dlp'` で一覧が0本になった）。"""
    import shutil
    found = shutil.which("yt-dlp")
    if found:
        return found
    for p in (Path.home() / "Library/Python/3.9/bin/yt-dlp", Path("/usr/local/bin/yt-dlp")):
        if p.exists():
            return str(p)
    return "yt-dlp"


def recent_videos(target: str, limit: int = 6) -> list[dict]:
    """チャンネルの新しい動画を yt-dlp で取る（ai_news.py と同じ手段）。"""
    url = target if target.startswith("http") else f"https://www.youtube.com/@{target}/videos"
    try:
        r = subprocess.run(
            [_yt_dlp(), "--flat-playlist", "--playlist-end", str(limit),
             "--print", "%(id)s\t%(title)s\t%(upload_date)s", url],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as ex:
        print(f"  一覧取得に失敗: {str(ex)[:100]}", file=sys.stderr)
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        d = parts[2].strip() if len(parts) > 2 else ""
        day = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else ""
        out.append({"id": parts[0].strip(), "title": parts[1].strip(), "published": day})
    return out


def date_from_watch_page(vid: str) -> str:
    """YouTubeの動画ページのHTMLから公開日を読む（yt-dlpが返さない時の2番目の手段）。

    実測2026-07-24: yt-dlp が upload_date を空で返す動画が実際にあった
    （例 qWKa5Z8BKWs / 8MRUgzC6r6I）。だがページのHTMLには
    "publishDate":"2026-07-12T04:00:12-07:00" の形で必ず入っていた。
    ここを読めば取りこぼしを防げる。
    """
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={vid}",
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
        m = re.search(r'"(?:publishDate|uploadDate)":"(\d{4}-\d{2}-\d{2})', html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def upload_date(vid: str) -> str:
    """公開日を1本ずつ取り直す。

    実測2026-07-21: `--flat-playlist` では upload_date が空で返り、公開日なしのノートが
    できてしまった。鮮度の判定に使う値なので、空のままにはしない。
    実測2026-07-24: yt-dlp 自体が空を返す動画もあったため、ページHTMLを読む手段も足した。
    """
    try:
        r = subprocess.run(
            [_yt_dlp(), "--skip-download", "--print", "%(upload_date)s",
             f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=120,
        )
        d = r.stdout.strip()
        if len(d) == 8 and d.isdigit():
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    except Exception:
        pass
    # yt-dlpで取れなかった時は、動画ページのHTMLから読む
    return date_from_watch_page(vid)


def dates_from_feed(target: str) -> dict:
    """チャンネルRSSから 動画ID→公開日 を作る。

    yt-dlpは動画によってはYouTubeに弾かれて日付を返さない
    （実測2026-07-21: "The page needs to be reloaded."）。
    チャンネルIDが分かる指定ならRSSの方が確実なので、そちらも当たる。
    取れなければ**空のままにする。今日の日付で埋めるような捏造はしない。**
    """
    m = re.search(r"/channel/(UC[\w-]{22})", target)
    if not m:
        return {}
    try:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
        req = urllib.request.Request(url, headers={"User-Agent": "jibun-ai/1.0"})
        xml = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception:
        return {}
    out = {}
    for entry in re.findall(r"<entry>.*?</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", entry)
        pub = re.search(r"<published>([^<]+)", entry)
        if vid and pub:
            out[vid.group(1)] = pub.group(1)[:10]
    return out


def explain(url: str) -> str:
    """動画そのものをGeminiに見せて解説を書かせる。"""
    from google import genai
    from google.genai import types
    key = os.environ.get("GEMINI_FREE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=key)
    content = types.Content(parts=[
        types.Part(text=PROMPT),
        types.Part(file_data=types.FileData(file_uri=url)),
    ])
    for m in MODELS:
        try:
            return (client.models.generate_content(model=m, contents=content).text or "").strip()
        except Exception as ex:
            print(f"  {m} で失敗: {str(ex)[:110]}", file=sys.stderr)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--max", type=int, default=6, help="1回に処理する上限（無料枠を使い切らないため）")
    a = ap.parse_args()

    today = datetime.date.today()
    since = (today - datetime.timedelta(days=a.days)).isoformat()
    added = skipped = 0

    for name, target in CHANNELS:
        folder = BASE / name
        folder.mkdir(parents=True, exist_ok=True)
        feed_dates = dates_from_feed(target)
        for v in recent_videos(target):
            if added >= a.max:
                print(f"✅ 動画取り込み: 新規{added}本 / 既存{skipped}本（上限{a.max}に到達）")
                return 0
            f = folder / f"{v['id']}.md"
            if f.exists():
                skipped += 1
                continue
            # 公開日は一覧では取れないので、取り込む本だけ個別に引く
            if not v["published"]:
                v["published"] = feed_dates.get(v["id"]) or upload_date(v["id"])
            if v["published"] and v["published"] < since:
                continue
            url = f"https://www.youtube.com/watch?v={v['id']}"
            body = explain(url)
            if not body:
                continue
            f.write_text(
                "---\n"
                "type: ai-news\n"
                f"channel: {name}\n"
                f"video_id: {v['id']}\n"
                f"published: {v['published']}\n"
                f"collected: {today.isoformat()}\n"
                f"url: {url}\n"
                "source: video\n"
                "tags: [jibun-ai, ai-news, video]\n"
                "---\n\n"
                f"# {v['title']}\n\n"
                f"**公開日: {v['published']}**（取得: {today.isoformat()}）\n"
                f"出典: {url}\n\n"
                "## 動画から起こした解説\n\n"
                f"{body}\n",
                encoding="utf-8",
            )
            print(f"  取り込み: [{name}] {v['title'][:40]}")
            added += 1

    print(f"✅ 動画取り込み: 新規{added}本 / 既存スキップ{skipped}本")
    return 0


if __name__ == "__main__":
    sys.exit(main())

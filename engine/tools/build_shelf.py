#!/usr/bin/env python3
# AIニュースの棚ページ(shelf.html)を作る。AIは呼ばない＝¥0。
# 使い方: python3 build_shelf.py <captures_dir> <gists.json> <out.html>
# 元ロジックは jibun-ai/tools/ai_hub.py（新しい順＋3ヶ月超に⚠️）をHTMLにしたもの。
import sys, re, html, json, datetime
from pathlib import Path

STALE_DAYS = 90
JA = re.compile(r"[ぁ-んァ-ヴ]")   # ひらがな・カタカナがあれば日本語とみなす


def esc(s):
    return html.escape(s or "", quote=True)


def main():
    captures = Path(sys.argv[1])
    gists = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if Path(sys.argv[2]).exists() else {}
    out = Path(sys.argv[3])
    today = datetime.date.today()

    rows = []          # (published, channel, video_id, title)
    per_ch = {}
    for ch_dir in sorted(p for p in captures.iterdir() if p.is_dir()):
        n = 0
        for f in ch_dir.glob("*.md"):
            head = f.read_text(encoding="utf-8")[:600]
            pub = re.search(r"^published:\s*(\S+)", head, re.M)
            ttl = re.search(r"^# (.+)$", head, re.M)
            pub = pub.group(1) if pub else "不明"
            title = ttl.group(1).strip() if ttl else f.stem
            rows.append((pub, ch_dir.name, f.stem, title))
            n += 1
        per_ch[ch_dir.name] = n

    # 新しい順。不明は最下部（鮮度が命の棚なので最新に見せない）
    rows.sort(key=lambda r: ("0000-00-00" if r[0] == "不明" else r[0]), reverse=True)

    fresh = 0
    items_html = []
    for pub, ch, vid, title in rows:
        stale_tag = ""
        datestr = pub
        if pub != "不明":
            try:
                d = datetime.date.fromisoformat(pub)
                age = (today - d).days
                if age <= STALE_DAYS:
                    fresh += 1
                else:
                    stale_tag = (f'<span class="stale">&#9888; {age // 30}ヶ月前・古い可能性</span>')
                datestr = pub.replace("-", ".")
            except Exception:
                pass
        t = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", title)[:70]
        summary = gists.get(vid, "")

        # 日本語で読める見出しを主役にする。
        # 元タイトルは英語や記号のID（例 e7bd166c2dc）のことがあり、そのままでは読めない。
        # 日本語の要約がすでにあるので、タイトルが日本語でなければ要約を見出しに使う。
        is_id = bool(re.fullmatch(r"[0-9a-fA-F_\-]{8,}", t))
        headline, sub = t, summary
        if (not JA.search(t) or is_id) and summary:
            headline = summary[:60]          # 日本語の要約を見出しに
            sub = "" if is_id else t         # 元タイトルは小さく添える（IDなら出さない）
        elif is_id:
            headline = "（タイトル未取得）"
            sub = summary

        url = f"https://www.youtube.com/watch?v={vid}"
        items_html.append(
            '<a class="row" href="' + esc(url) + '" target="_blank" rel="noopener">'
            + '<div class="meta"><span class="date">' + esc(datestr) + '</span>' + stale_tag + '</div>'
            + '<h2>' + esc(headline) + '</h2>'
            + '<div class="ch">' + esc(ch) + '</div>'
            + ('<p class="sum">' + esc(sub) + '</p>' if sub else '')
            + '</a>'
        )

    total = len(rows)
    updated = today.isoformat().replace("-", ".")
    page = """<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIの棚 — 今朝のAI</title>
<style>
:root{--bg:#0E0D0C;--card:#171614;--ink:#F2EFE6;--mute:#9A9284;--line:#2A2723;--rule:#C0704A}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Hiragino Sans',sans-serif;
 -webkit-font-smoothing:antialiased;line-height:1.6}
.wrap{max-width:640px;margin:0 auto;padding:26px 20px 60px}
.kicker{font-size:13px;color:var(--mute)}
.h1{font-family:'Hiragino Mincho ProN',serif;font-size:26px;margin:10px 0 0}
.rule{height:1px;background:var(--rule);margin:12px 0 10px}
.fresh{font-size:12.5px;color:var(--mute);margin-bottom:6px}
.fresh b{color:var(--rule);font-weight:600}
.back{display:inline-block;margin-top:14px;font-size:13px;color:var(--rule);text-decoration:none}
.row{display:block;text-decoration:none;color:inherit;border-top:1px solid var(--line);padding:15px 0}
.row:active{opacity:.7}
.meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.date{font-size:11px;color:var(--rule);letter-spacing:.04em}
.stale{font-size:10px;color:var(--rule);border:1px solid var(--rule);border-radius:4px;padding:1px 6px}
.row h2{font-family:'Hiragino Mincho ProN',serif;font-size:17px;font-weight:600;line-height:1.5;margin:5px 0}
.ch{font-size:11px;color:var(--mute)}
.sum{font-size:13px;color:var(--mute);line-height:1.75;margin:5px 0 0}
.foot{margin-top:34px;font-size:11px;color:var(--mute);opacity:.7;border-top:1px solid var(--line);padding-top:16px}
</style></head><body><div class="wrap">
<div class="kicker">今朝のAI</div>
<div class="h1">AIの棚</div>
<div class="rule"></div>
<div class="fresh">全 __TOTAL__本 ・ 新しい順 ／ 直近3ヶ月 <b>__FRESH__本</b></div>
<a class="back" href="index.html">&larr; 今朝のAI（今日の5本）にもどる</a>
<div class="list">
__ITEMS__
</div>
<div class="foot">AIの情報は数ヶ月で古くなります。&#9888;は公開から3ヶ月超＝内容が古い可能性。毎朝クラウドが自動更新（更新: __UPDATED__）。</div>
</div></body></html>"""
    page = (page.replace("__TOTAL__", str(total)).replace("__FRESH__", str(fresh))
                .replace("__UPDATED__", updated).replace("__ITEMS__", "\n".join(items_html)))
    out.write_text(page, encoding="utf-8")
    print(f"棚ページ作成: {total}本（直近3ヶ月={fresh}本）→ {out}")


if __name__ == "__main__":
    main()

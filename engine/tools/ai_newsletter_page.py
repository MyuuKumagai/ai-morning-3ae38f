#!/usr/bin/env python3
"""ニュースレターを「普通のWebサイト」として書き出す。

経緯（2026-07-21 本人フィードバック）:
- Obsidianモバイル → 起動が遅い・画像が出ない・HTMLがコードのまま見える → 却下
- iCloud + ショートカット(Quick Look) → ファイルが開けず断念。PDFは触っても何も起きない
- 本人「普通のリンクでもいいよ／普通のウェブサイトみたいのがいい。
  普通にクリックタップできて、中身が出てきて、参照先のリンクもある」

→ 一覧をタップすると記事が開く、戻るボタンで一覧に戻る、出典リンクも押せる、
  という当たり前のサイトを1枚のHTMLで作る。GitHub Pagesで公開して普通のURLで開く。

画像とフォントはHTMLに内蔵する（外部読み込みが失敗して絵が出ない事故を防ぐ）。
"""
from __future__ import annotations

import base64
import datetime
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FONT_DIR = Path(__file__).resolve().parent / "fonts"
OG_CACHE = Path(__file__).resolve().parent / "og_cache.json"
# iPhoneのショートカットにパスを手入力させるので、日本語を使わない（打ちにくいため）
ICLOUD = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "AI"

# ニュースサイトは素っ気ないUAを弾くことがあるので普通のブラウザを名乗る
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

OG_PATTERNS = (
    r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
)


def og_image(url: str) -> str:
    """記事ページの代表画像を拾う。

    実測 2026-07-21: TechCrunchのRSSには画像タグが1つも無い（<title><link><description>のみ）。
    記事ページの og:image なら TechCrunch 199KB / The Verge 474KB が取れた。
    取れないサイト（Simon Willison＝文章ブログ、OpenAI＝取得拒否）は空を返し、枠に差し替わる。
    一度引いた結果はキャッシュして毎朝取り直さない。
    """
    if not url.startswith("http"):
        return ""
    cache = {}
    if OG_CACHE.exists():
        try:
            cache = json.loads(OG_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    if url in cache:
        return cache[url]

    found = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        page = urllib.request.urlopen(req, timeout=20).read(300_000).decode("utf-8", "ignore")
        for p in OG_PATTERNS:
            m = re.search(p, page)
            if m:
                found = html.unescape(m.group(1))
                break
    except Exception:
        found = ""

    cache[url] = found
    try:
        OG_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return found


def _b64_font(name: str) -> str:
    p = FONT_DIR / name
    if not p.exists():
        return ""
    return base64.b64encode(p.read_bytes()).decode()


def _img_data(url: str, max_w: int = 760) -> str:
    """画像を取ってきて縮小し data URI にする。失敗したら空（枠に差し替わる）。

    元画像は数百KBあるが、スマホで見る幅は最大でも760px。縮小しないとページが
    1MB近くなり「開くのが遅い」という当初の不満に戻ってしまう。
    """
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70, optimize=True, progressive=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        # Pillowが無い/読めない形式のときは、大きすぎなければ元のまま載せる
        if len(raw) > 400_000:
            return ""
        mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(raw).decode()


def e(s: str) -> str:
    return html.escape(s or "", quote=True)


CATEGORIES = ["仕事", "お金", "暮らし", "未来"]

SITE_DIR = Path(__file__).resolve().parent / "site"

CSS = """
:root{--bg:#FBF7EF;--card:#fff;--ink:#1B1813;--mute:#5C5648;--line:#E6E0D4;--rule:#A8412C;
 --c0:#8F4A2E;--c1:#3F6B52;--c2:#4A5570;--c3:#6A4F78;--sh:0 1px 3px rgba(0,0,0,.06)}
@media (prefers-color-scheme:dark){
 :root{--bg:#0E0D0C;--card:#171614;--ink:#F2EFE6;--mute:#9A9284;--line:#2A2723;--rule:#C0704A;
  --c0:#C08B5E;--c1:#7D9B87;--c2:#8A93A8;--c3:#A08FB0;--sh:none}}
@font-face{font-family:'IS';src:url(data:font/woff2;base64,__IS__) format('woff2');font-display:swap}
@font-face{font-family:'DM';src:url(data:font/woff2;base64,__DM__) format('woff2');font-display:swap}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--ink);font-family:'Hiragino Sans',sans-serif;
 -webkit-font-smoothing:antialiased;padding-bottom:60px}
.mincho{font-family:'Hiragino Mincho ProN','YuMincho',serif}
.wrap{max-width:680px;margin:0 auto;padding:0 18px}
a{color:inherit;text-decoration:none}

/* ヘッダー */
.hd{padding:26px 0 18px;border-bottom:1px solid var(--rule);margin-bottom:20px;
 display:flex;justify-content:space-between;align-items:flex-end;gap:12px}
.hd h1{font-family:'Hiragino Mincho ProN',serif;font-size:26px;font-weight:600;line-height:1.1}
.hd .meta{font-family:'DM';font-size:10px;letter-spacing:.14em;color:var(--mute);text-align:right;line-height:1.9}

/* 一覧 */
.card{background:var(--card);border-radius:14px;overflow:hidden;box-shadow:var(--sh);
 margin-bottom:14px;cursor:pointer;display:block;transition:transform .12s ease}
.card:active{transform:scale(.985)}
.card img{width:100%;height:180px;object-fit:cover;display:block}
.card .tx{padding:15px 16px 17px}
.cat{font-family:'DM';font-size:10px;letter-spacing:.16em;margin-bottom:8px}
.card h2{font-family:'Hiragino Mincho ProN',serif;font-size:19px;font-weight:600;
 line-height:1.45;margin-bottom:8px}
.card p{font-size:13.5px;line-height:1.8;color:var(--mute)}
.card .more{font-family:'DM';font-size:10px;letter-spacing:.12em;margin-top:12px;display:block}
.row{display:grid;grid-template-columns:104px 1fr;gap:0}
.row.noimg{grid-template-columns:1fr}
.row img{height:100%;min-height:104px}
.row .tx{padding:14px 15px}
.row h2{font-size:16px;margin-bottom:6px}
.row p{font-size:12.5px;line-height:1.75}

/* 記事 */
.back{font-family:'DM';font-size:11px;letter-spacing:.12em;color:var(--rule);
 padding:22px 0 16px;display:inline-block;cursor:pointer}
.art img{width:100%;height:220px;object-fit:cover;border-radius:12px;margin-bottom:20px;display:block}
.art h2{font-family:'Hiragino Mincho ProN',serif;font-size:27px;font-weight:600;
 line-height:1.35;margin-bottom:20px}
.art .bd{font-size:15.5px;line-height:2.1;margin-bottom:18px}
.art .use{font-size:15px;line-height:2;border-left:2px solid currentColor;
 padding:2px 0 2px 16px;margin:24px 0}
.player{background:var(--card);border-radius:12px;padding:12px 14px 14px;margin-bottom:22px;box-shadow:var(--sh)}
.plbl{font-family:'DM';font-size:10px;letter-spacing:.16em;color:var(--mute);margin-bottom:8px}
.player audio{width:100%;height:34px;display:block}
/* メモ欄。記事を読んで思いついたことをその場で書き留める */
.memo{background:var(--card);border-radius:12px;padding:14px 15px 15px;margin:26px 0 0;box-shadow:var(--sh)}
.memolbl{font-family:'DM';font-size:10px;letter-spacing:.16em;color:var(--mute);margin-bottom:9px}
.memo textarea{width:100%;min-height:82px;background:transparent;border:1px solid var(--line);
 border-radius:8px;padding:11px 12px;font-family:'Hiragino Sans',sans-serif;font-size:15px;
 line-height:1.8;color:var(--ink);resize:vertical;outline:none}
.memo textarea:focus{border-color:var(--rule)}
.memohint{font-size:12px;color:var(--mute);margin-top:8px;line-height:1.7}
.saved{color:var(--rule)}
/* 記事についてAIに質問する欄 */
.askai{background:var(--card);border-radius:12px;padding:14px 15px 15px;margin:26px 0 0;box-shadow:var(--sh)}
.askai textarea{width:100%;min-height:58px;background:transparent;border:1px solid var(--line);
 border-radius:8px;padding:11px 12px;font-family:'Hiragino Sans',sans-serif;font-size:15px;
 line-height:1.8;color:var(--ink);resize:vertical;outline:none}
.askai textarea:focus{border-color:var(--rule)}
.askbtn{margin-top:10px;padding:11px 18px;border:1px solid var(--rule);border-radius:8px;
 background:transparent;color:var(--rule);font-family:'Hiragino Sans',sans-serif;font-size:14px;cursor:pointer}
.askbtn:active{transform:scale(.99)}
.askbtn[disabled]{opacity:.5}
.aians{margin-top:13px;font-size:15px;line-height:1.9;color:var(--ink);white-space:pre-wrap}
.srcbox{border-top:1px solid var(--line);margin-top:28px;padding-top:18px}
.srcbox .lbl{font-family:'DM';font-size:10px;letter-spacing:.14em;color:var(--mute);margin-bottom:10px}
.srcbox a{display:flex;align-items:center;justify-content:space-between;gap:12px;
 background:var(--card);border-radius:10px;padding:14px 16px;box-shadow:var(--sh);font-size:14px}
.srcbox .host{font-family:'DM';font-size:11px;color:var(--mute)}
.nextlbl{font-family:'DM';font-size:10px;letter-spacing:.14em;color:var(--mute);
 margin:34px 0 12px;padding-top:20px;border-top:1px solid var(--line)}

.c0{color:var(--c0)}.c1{color:var(--c1)}.c2{color:var(--c2)}.c3{color:var(--c3)}

.mallbtn{display:block;width:100%;margin-top:22px;padding:14px;border:1px solid var(--rule);
 border-radius:10px;background:transparent;color:var(--rule);font-family:'Hiragino Sans',sans-serif;
 font-size:14px;cursor:pointer}
.mallbtn:active{transform:scale(.99)}
.backs{margin-top:26px;padding-top:20px;border-top:1px solid var(--line)}
.bklbl{font-family:'DM';font-size:10px;letter-spacing:.16em;color:var(--mute);margin-bottom:10px}
.bk{display:block;background:var(--card);border-radius:10px;padding:13px 15px;margin-bottom:8px;
 font-family:'Hiragino Mincho ProN',serif;font-size:15px;box-shadow:var(--sh)}
.bk:active{transform:scale(.985)}
.foot{font-family:'DM';font-size:10px;letter-spacing:.14em;color:var(--mute);opacity:.7;
 border-top:1px solid var(--line);padding-top:18px;margin-top:30px}
.hide{display:none}
"""

JS = """
var D=__DATA__,L=document.getElementById('list'),A=document.getElementById('art');
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML}
function show(){
 var m=location.hash.match(/^#a(\\d+)$/);
 if(!m){L.classList.remove('hide');A.classList.add('hide');A.innerHTML='';document.title='今朝のAI';window.scrollTo(0,0);return}
 var s=D[+m[1]];if(!s){location.hash='';return}
 window.__cur=s;
 var ps=s.body.filter(Boolean),last=ps.length>1?ps.pop():null;
 var h='<div class="back" onclick="history.back()">&larr; 一覧にもどる</div>';
 if(s.img)h+='<img src="'+s.img+'" alt="">';
 h+='<p class="cat c'+s.ci+'">'+esc(s.cat)+(s.date?' &nbsp;·&nbsp; '+esc(s.date.replace(/-/g,'.')):'')+'</p><h2>'+esc(s.title)+'</h2>';
 if(s.audio)h+='<div class="player"><p class="plbl">きく</p><audio controls preload="none" src="'+s.audio+'"></audio></div>';
 h+=ps.map(function(t){return '<p class="bd">'+esc(t)+'</p>'}).join('');
 if(last)h+='<p class="use c'+s.ci+'">'+esc(last)+'</p>';
 h+='<div class="askai"><p class="memolbl">この記事についてAIに質問</p>'
   +'<textarea id="qai" placeholder="例：これは私にどう関係ある？"></textarea>'
   +'<button class="askbtn" id="qbtn" onclick="askAI()">聞いてみる</button>'
   +'<div id="aians" class="aians"></div></div>';
 h+='<div class="memo"><p class="memolbl">メモ <span id="mst"></span></p>'
   +'<textarea id="mtx" placeholder="どう使えそう？ やってみたいことは？"></textarea>'
   +'<p class="memohint">書くと自動で保存されます。一覧の下から全部まとめてコピーできます。</p></div>';
 h+='<div class="srcbox"><p class="lbl">もっと詳しく</p><a href="'+s.url+'" target="_blank" rel="noopener">'
   +'<span>'+esc(s.ch)+'の元記事をひらく</span><span class="host">'+esc(s.host)+' &nearr;</span></a></div>';
 var n=(+m[1]+1)%D.length;
 h+='<p class="nextlbl">つぎの記事</p><a class="card row'+(D[n].img?'':' noimg')+'" href="#a'+n+'">'
   +(D[n].img?'<img src="'+D[n].img+'" alt="">':'')
   +'<div class="tx"><p class="cat c'+D[n].ci+'">'+esc(D[n].cat)+'</p><h2>'+esc(D[n].title)+'</h2></div></a>';
 A.innerHTML=h;A.classList.remove('hide');L.classList.add('hide');
 var tx=document.getElementById('mtx'),st=document.getElementById('mst'),k='memo:'+s.url;
 if(tx){
  tx.value=localStorage.getItem(k)||'';
  var t=null;
  tx.addEventListener('input',function(){
   clearTimeout(t);
   t=setTimeout(function(){
    if(tx.value.trim()){localStorage.setItem(k,tx.value);
     localStorage.setItem('meta:'+s.url,JSON.stringify({t:s.title,d:s.date||'',u:s.url}));}
    else{localStorage.removeItem(k);localStorage.removeItem('meta:'+s.url);}
    st.textContent='ほぞんしました';st.className='saved';
    setTimeout(function(){st.textContent=''},1600);
   },500);
  });
 }
 document.title=s.title;window.scrollTo(0,0);
}
// 記事についてAIに質問する。鍵は中継役(Google Apps Script)側に置き、ここには出さない。
var ASK_URL='https://script.google.com/macros/s/AKfycbxwifQsVl8vNMeh-umo4ydLRswAERePoSYmKc7gewg0_rxHZhbogCYpXQ9ZgeMSIeE9-Q/exec';
window.askAI=function(){
 var q=document.getElementById('qai'),a=document.getElementById('aians'),b=document.getElementById('qbtn');
 if(!q||!a)return;
 var t=q.value.trim();
 if(!t){a.textContent='聞きたいことを書いてください。';return}
 var s=window.__cur||{};
 var ctx=(s.title||'')+'\\n'+((s.body||[]).join('\\n'));
 a.textContent='考えています…';
 if(b)b.disabled=true;
 fetch(ASK_URL,{method:'POST',headers:{'Content-Type':'text/plain;charset=utf-8'},
  body:JSON.stringify({q:t,ctx:ctx})})
  .then(function(r){return r.json()})
  .then(function(d){
   var msg=d.answer;
   if(!msg){
    var e=d.error||'';
    if(/too many times/i.test(e))msg='今日はもう質問できる回数の上限に達しました。明日また聞いてください。';
    else if(/未設定/.test(e))msg='準備がまだ整っていません。';
    else msg='うまく答えられませんでした。少し時間をおいて試してください。';
   }
   a.textContent=msg;
  })
  .catch(function(){a.textContent='つながりませんでした。少し時間をおいて試してください。'})
  .then(function(){if(b)b.disabled=false});
};
function allMemos(){
 var out=[],i,k;
 for(i=0;i<localStorage.length;i++){
  k=localStorage.key(i);
  if(k.indexOf('memo:')!==0)continue;
  var m={};try{m=JSON.parse(localStorage.getItem('meta:'+k.slice(5))||'{}')}catch(e){}
  out.push('■ '+(m.t||'')+(m.d?'（'+m.d+'）':'')+'\\n'+m.u+'\\nメモ: '+localStorage.getItem(k));
 }
 return out;
}
function refreshMemoBtn(){
 var b=document.getElementById('mall');if(!b)return;
 var n=allMemos().length;
 b.style.display=n?'block':'none';
 b.textContent='メモを'+n+'件まとめてコピー';
}
window.copyMemos=function(){
 var t='【今朝のAI メモ】\\n\\n'+allMemos().join('\\n\\n');
 navigator.clipboard.writeText(t).then(function(){
  var b=document.getElementById('mall');b.textContent='コピーしました。クロちゃんに貼ってください';
  setTimeout(refreshMemoBtn,2500);
 });
};
window.addEventListener('hashchange',function(){show();refreshMemoBtn()});show();refreshMemoBtn();
"""


def _audio_for(s: dict, body: list[str]) -> str:
    """記事の読み上げ音声。見出しから読み始めて、本文をそのまま読む。"""
    try:
        import ai_tts
    except Exception:
        return ""
    text = s["headline"] + "。\n" + "\n".join(body)
    return ai_tts.speak(text)


def _story_data(stories: list[dict]) -> list[dict]:
    """サイトに埋め込むデータ。画像はここでdata URIにしておく。"""
    out = []
    for s in stories:
        body = [t.strip() for t in re.split(r"\\n|\n", (s.get("body") or "").strip()) if t.strip()]
        if not body:
            body = [s.get("summary", "")]
        host = re.sub(r"^https?://(www\.)?", "", s.get("url", "")).split("/")[0]
        out.append({
            "title": s["headline"],
            "lede": s.get("summary") or body[0][:70],
            "cat": s["category"],
            "ci": CATEGORIES.index(s["category"]) if s["category"] in CATEGORIES else 3,
            "body": body,
            "url": s.get("url", ""),
            "ch": s.get("channel", ""),
            "date": s.get("published", ""),
            "host": host,
            "img": _img_data(s.get("_thumb", ""), 720),
            "audio": _audio_for(s, body),
        })
    return out


KEEP_DAYS = 30  # 残す号の数。音声込みで1号2MBほどあるので上限を決めておく


def _back_issues(day: datetime.date) -> str:
    """これまでの号の一覧。日付をタップするとその日の号がそのまま開く。"""
    files = sorted(
        (p for p in SITE_DIR.glob("20*.html") if p.stem != day.isoformat()),
        reverse=True,
    )
    if not files:
        return ""
    wds = ["月", "火", "水", "木", "金", "土", "日"]
    links = ""
    for p in files[:KEEP_DAYS]:
        try:
            d = datetime.date.fromisoformat(p.stem)
        except ValueError:
            continue
        links += f'<a class="bk" href="{p.name}">{d.month}月{d.day}日（{wds[d.weekday()]}）の号</a>'
    return f'<div class="backs"><p class="bklbl">これまでの号</p>{links}</div>'


def build_page(day: datetime.date, stories: list[dict], vol: int, yesterday: list[dict]) -> str:
    from ai_newsletter import thumb  # YouTubeサムネの決定ロジックは共有する

    # 画像を先に確定させる（表紙を決めるより前に og:image を引く必要がある）
    for s in stories:
        s["_thumb"] = thumb(s) or og_image(s.get("url", ""))
    if stories and not stories[0]["_thumb"]:
        for i, s in enumerate(stories):
            if s["_thumb"]:
                stories = [s] + stories[:i] + stories[i + 1:]
                break

    data = _story_data(stories)
    d = day.strftime("%Y.%m.%d")
    wd = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][day.weekday()]

    cards = ""
    for i, s in enumerate(data):
        img = f'<img src="{s["img"]}" alt="">' if s["img"] else ""
        big = (i == 0)
        cards += (
            f'<a class="card{"" if big else (" row" if img else " row noimg")}" href="#a{i}">{img}'
            f'<div class="tx"><p class="cat c{s["ci"]}">{e(s["cat"])}</p>'
            f'<h2>{e(s["title"])}</h2><p>{e(s["lede"])}</p>'
            + ('<span class="more c%d">つづきを読む &rarr;</span>' % s["ci"] if big else "")
            + "</div></a>"
        )

    css = CSS.replace("__IS__", _b64_font("instrument.woff2")).replace("__DM__", _b64_font("dmmono.woff2"))
    js = JS.replace("__DATA__", json.dumps(data, ensure_ascii=False))

    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="今朝のAI">
<!-- ホーム画面のアイコン。これが無いとiOSはページの写しを勝手に使う（＝本人が「ダサい」と指摘） -->
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" href="icon-512.png">
<meta name="theme-color" content="#0E0D0C">
<title>今朝のAI</title><style>{css}</style></head>
<body><div class="wrap">
<div class="hd"><h1 class="mincho">今朝のAI</h1>
<div class="meta">{d} {wd}<br>VOL.{vol} &nbsp;·&nbsp; {len(data)} STORIES</div></div>
<div id="list">{cards}{_back_issues(day)}
<button id="mall" class="mallbtn" onclick="copyMemos()" style="display:none"></button>
<p class="foot">YOUTUBE 6CH · NEWS 7SOURCES &nbsp;—&nbsp; まいあさ8:00 こうしん</p></div>
<div id="art" class="art hide"></div>
</div><script>{js}</script></body></html>'''


def write_page(day, stories, vol, yesterday) -> Path:
    """サイトを書き出す。公開用フォルダと、オフライン用のiCloudの両方へ。"""
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    page = build_page(day, stories, vol, yesterday)
    out = SITE_DIR / "index.html"
    out.write_text(page, encoding="utf-8")
    # その日の号を日付つきで残す（トップは常に最新号、過去は日付ファイルで読める）
    (SITE_DIR / f"{day.isoformat()}.html").write_text(page, encoding="utf-8")
    # 古い号は捨てる。1号2MBほどあるので置きっぱなしにしない
    olds = sorted((p for p in SITE_DIR.glob("20*.html")), reverse=True)[KEEP_DAYS:]
    for p in olds:
        p.unlink(missing_ok=True)

    # Claudeの非公開ページ(Artifact)用の控え。<html>や<body>は向こうが付けるので中身だけ出す。
    # site/ の外に置く —— 中に置くと公開サイトに同じ中身が二重に出てしまうため
    # （実測2026-07-22: artifact.html が893KBで公開されていた）。
    m_style = re.search(r"<style>(.*?)</style>", page, re.S)
    m_body = re.search(r"<body>(.*)</body>", page, re.S)
    if m_style and m_body:
        (SITE_DIR.parent / "artifact.html").write_text(
            f"<title>今朝のAI</title>\n<style>{m_style.group(1)}</style>\n{m_body.group(1)}",
            encoding="utf-8",
        )
    try:
        ICLOUD.mkdir(parents=True, exist_ok=True)
        (ICLOUD / "today.html").write_text(page, encoding="utf-8")
    except Exception:
        pass  # iCloud側は控え。失敗しても公開用は守る
    return out


if __name__ == "__main__":
    import ai_newsletter as nl
    today = datetime.date.today()
    st = nl.add_details(nl.choose(nl.candidates(today)))
    p = write_page(today, st, 1, [])
    print(f"✅ {p} ({p.stat().st_size // 1024} KB)")

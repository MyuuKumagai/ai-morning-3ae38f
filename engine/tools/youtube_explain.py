#!/usr/bin/env python3
"""YouTube/記事を Gemini に渡して日本語で詳しく解説し、Obsidian に保存する。

用途:
  - explain モード: 動画/記事の内容を詳細に日本語解説（今までの手作業コピペを廃止）
  - mentor  モード: 尊敬する経営者の「思考・原則・意思決定の型」を抽出（判断核への昇格候補）

使い方:
  export GEMINI_API_KEY=...   # Google AI Studio で無料取得
  python3 youtube_explain.py <YouTube URL または 記事URL> [--mode explain|mentor] [--name 人名]

前提: pip install google-genai
コスト: Gemini Flash は激安。個人利用なら無料枠内の見込み（1本あたり数円レベル）。
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  # 依存を積んだvenvへ自動で切り替える
import _safe_write
import argparse
import datetime
import os
import re
import sys
from pathlib import Path

# Obsidian 保存先（バックボーン）
VAULT = Path(
    "/Users/myuukumagai/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian"
)
YT_DIR = VAULT / "60 Jibun-AI" / "captures" / "youtube"
MENTOR_DIR = VAULT / "60 Jibun-AI" / "captures" / "mentors"

# 無料枠で使えるのは flash 系のみ（pro は課金必須）。
# 既定=flash＋高解像度で精度最大化。--fast で標準解像度(軽い)。課金後は --model gemini-2.5-pro も可。
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

EXPLAIN_PROMPT = """あなたは優秀な解説者です。この動画（またはコンテンツ）の内容を、日本語で「詳細に・分かりやすく」解説してください。中学生でも理解できる平易な言葉を基本にしつつ、内容の解像度は落とさないでください。

この動画は「音声」だけでなく「映像」も必ず観察してください。画面に映るスライド・テロップ・図表・数字・画面共有・デモ・登場人物の表情や動作など、**話し言葉には出てこない視覚情報も漏らさず**拾ってください。目標は「読んだ人が、実際に動画を最後まで観たのとほぼ同じ理解に到達する」ことです。

次の構成で書いてください:
1. 概要（誰が/何を/主張の要点、可能なら数値の成果）
2. 具体的な仕組み・手順（ステップやデータ構造があれば分解して。スライドや図の内容も文章化）
3. 具体的な効果・事例（画面に出た数字・グラフ・実例を含める）
4. 導入時の注意点・ボトルネック
5. 今後の展望・まとめ
6. 映像だけにあった情報（音声では言っていないが画面に映っていたもの）
   - 画面のテキスト/スライド/テロップの要点、図解・チャートの内容、画面共有・デモで見せたもの、登場人物の表情・反応など
7. 重要タイムライン（[MM:SS] で主要トピックの流れ）

重要な発言・場面には [MM:SS] のタイムスタンプを添える。事実と推測を区別し、動画にない情報を断定で足さない。詳細に、しかし冗長になりすぎず。出力はMarkdown、日本語。"""

MENTOR_PROMPT = """あなたは経営メンターの思考を言語化する専門家です。この動画（またはコンテンツ）に登場する成功者・経営者の「思考・原則・意思決定の型」を、後で自分の判断基準に取り込めるように抽出してください。

次の構成で、日本語Markdownで書いてください:
1. 人物・出典（誰の、何についての発言か）
2. 核心的な原則・信念（箇条書き。その人が繰り返す判断軸・価値観）
3. 意思決定の型（「こういう時はこう動く」という再現可能なパターン）
4. 具体的な打ち手・戦術（原則を実行に落とした具体例）
5. NG・やらないこと（その人が避けている失敗）
6. 取り込み検討メモ（この原則を個人起業家が使う際の注意・応用アイデア）

抽象論でなく、実際に真似できる粒度で。動画にない主張を捏造しないこと。"""


def extract_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def slugify(text: str, maxlen: int = 50) -> str:
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"[^\wぁ-んァ-ヶ一-龠ー-]", "", text)
    return text[:maxlen] or "untitled"


# 有料キーの末尾。Google AI Studio で請求階層を実測して確認したもの
# (2026-07-22: ...JDog = プロジェクト"Mentors" / My Billing Account / Tier 1・Prepay = 有料)。
# 本人の指示「必ず無料枠を使う。有料枠は使わない」を、注意ではなくコードで守る。
PAID_KEY_SUFFIXES = ("JDog",)
# 無料枠と実測確認済みのキーを入れる環境変数（上から順に使う）
FREE_KEY_ENVS = ("JIBUN_GEMINI_API_KEY", "FREE_GEMINI_API_KEY")


def _pick_free_key() -> tuple[str, str]:
    """無料枠と確認済みのキーを選ぶ。見つからなければ止める（勝手に有料へ落ちない）。"""
    for name in FREE_KEY_ENVS:
        v = os.environ.get(name)
        if v and not v.endswith(PAID_KEY_SUFFIXES):
            return v, name
    # 明示許可があるときだけ、通常のキーを使う
    if os.environ.get("ALLOW_PAID_GEMINI") == "1":
        v = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if v:
            return v, "GEMINI_API_KEY(有料許可あり)"
    return "", ""


def build_client():
    api_key, key_src = _pick_free_key()
    if api_key:
        print(f"[課金チェック] 無料枠キーを使用: {key_src} (...{api_key[-4:]})", file=sys.stderr)
    if not api_key:
        cur = os.environ.get("GEMINI_API_KEY", "")
        if cur.endswith(PAID_KEY_SUFFIXES):
            sys.exit(
                f"停止: GEMINI_API_KEY (...{cur[-4:]}) は有料キーです"
                "（AI Studio 実測: プロジェクト Mentors / Tier 1・Prepay）。\n"
                "無料枠のキーを次のいずれかに設定してください:\n"
                "  export JIBUN_GEMINI_API_KEY=xxxx   # 無料枠(Free tier)のキー\n"
                "どうしても有料キーで実行する場合のみ ALLOW_PAID_GEMINI=1 を付けてください。"
            )
        sys.exit(
            "エラー: 無料枠のGeminiキーが未設定です。\n"
            "Google AI Studio (https://aistudio.google.com/apikey) の Billing Tier が\n"
            "「Free tier」のキーを  export JIBUN_GEMINI_API_KEY=xxxx  に設定してください。"
        )
    try:
        from google import genai  # noqa
    except ImportError:
        sys.exit("エラー: google-genai 未導入。`pip3 install google-genai` を実行してください。")
    from google import genai
    return genai.Client(api_key=api_key)


def generate(url: str, prompt: str, model: str, fps: float, high_res: bool) -> str:
    from google.genai import types

    client = build_client()
    is_youtube = "youtube.com" in url or "youtu.be" in url

    # 高精度: 画面の文字まで読めるよう解像度を上げる（対応SDKのみ）
    config = None
    if high_res:
        try:
            config = types.GenerateContentConfig(
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH
            )
        except (AttributeError, TypeError):
            config = None

    if is_youtube:
        # fps を上げると多くのコマを解析＝映像の取りこぼしが減る（コスト増）
        try:
            video_part = types.Part(
                file_data=types.FileData(file_uri=url),
                video_metadata=types.VideoMetadata(fps=fps),
            )
        except (AttributeError, TypeError):
            video_part = types.Part(file_data=types.FileData(file_uri=url))
        contents = types.Content(parts=[video_part, types.Part(text=prompt)])
    else:
        contents = f"{prompt}\n\n対象URL: {url}\nこのURLの内容を取得して上記の指示に従ってください。"

    resp = client.models.generate_content(model=model, contents=contents, config=config)
    return resp.text or ""


def save(mode: str, url: str, body: str, name: str | None) -> Path:
    today = datetime.date.today().isoformat()
    if mode == "mentor":
        MENTOR_DIR.mkdir(parents=True, exist_ok=True)
        base = slugify(name) if name else (extract_video_id(url) or "mentor")
        path = MENTOR_DIR / f"{base}.md"
        title = f"メンター原則: {name or base}"
        tags = "[jibun-ai, mentor, capture]"
        related = "[founder_decision_core]"
        footer = (
            "\n\n---\n"
            "## 判断核への昇格\n"
            "取り込みたい原則を選び、承認の上で [[founder_decision_core]] の「7. 取り込んだ外部原則」へ、"
            "出典と『自分の価値観との整合/衝突』を明記して追記する。\n"
        )
    else:
        YT_DIR.mkdir(parents=True, exist_ok=True)
        vid = extract_video_id(url) or "video"
        base = f"{today}-{slugify(name) if name else vid}"
        path = YT_DIR / f"{base}.md"
        title = f"YouTube解説: {name or vid}"
        tags = "[jibun-ai, youtube, capture]"
        related = "[index]"
        footer = ""

    front = (
        f"---\ntype: capture\nmode: {mode}\nstatus: active\n"
        f"created: {today}\nsource_url: {url}\ntags: {tags}\nrelated: {related}\n---\n\n"
    )

    # mentorモードは `<人物名>.md` の固定パスへ書くため、mentor_batch等が積み上げた
    # 大きな蓄積ファイルを動画1本分の抽出で消してしまう。上書き前に必ず退避する。
    _safe_write.backup_if_exists(path)

    path.write_text(f"{front}# {title}\n\n出典: {url}\n\n{body}{footer}", encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--mode", choices=["explain", "mentor"], default="explain")
    ap.add_argument("--name", default=None, help="保存ファイル名/人物名")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--fast", action="store_true", help="速く安く(flash・標準解像度)")
    ap.add_argument("--fps", type=float, default=1.0, help="映像の解析コマ/秒(上げると精細・高コスト)")
    args = ap.parse_args()

    model = "gemini-3.5-flash" if args.fast else args.model
    high_res = not args.fast
    prompt = MENTOR_PROMPT if args.mode == "mentor" else EXPLAIN_PROMPT
    mode_label = "高速" if args.fast else "高精度(映像も精読)"
    print(f"[{args.mode}/{mode_label}] Geminiで処理中... ({model})", file=sys.stderr)
    body = generate(args.url, prompt, model, args.fps, high_res)
    if not body.strip():
        sys.exit("エラー: Geminiから空の応答。URL・モデル・APIキーを確認してください。")
    path = save(args.mode, args.url, body, args.name)
    print(body)
    print(f"\n---\n保存先: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()

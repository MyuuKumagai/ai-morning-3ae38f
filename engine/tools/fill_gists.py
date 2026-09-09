#!/usr/bin/env python3
# 棚の見出しが英語のままの記事に、日本語の一言要約を作って gists.json に保存する。
# ・すでに要約がある記事は飛ばす＝走らせるほど残りが減り、いずれ0本になって¥0で終わる
# ・1回の上限(--max)で無料枠を守る。毎朝ちょっとずつ埋める運用
# 使い方: python3 fill_gists.py <captures_dir> <gists.json> [--max 40]
import os, re, json, time, argparse
from pathlib import Path
from google import genai

JA = re.compile(r"[ぁ-んァ-ヴ]")
MODEL = "gemini-3.1-flash-lite"


def build_client():
    """Vertex(無料クレジット)優先。GEMINI_VERTEX_PROJECT があればそれ、無ければ従来のAPIキー。"""
    proj = os.environ.get("GEMINI_VERTEX_PROJECT")
    if proj:
        loc = os.environ.get("GEMINI_VERTEX_LOCATION", "global")
        return genai.Client(vertexai=True, project=proj, location=loc)
    k = (os.environ.get("GEMINI_FREE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not k:
        return None
    return genai.Client(api_key=k)


def gen(client, title: str, body: str) -> str:
    prompt = (
        "次の英語のAIニュースを、日本語の短い見出しにしてください。\n"
        "・日本語30字以内。体言止め可。誇張しない。事実だけ。\n"
        "・見出しだけを1行で返す。説明や記号は付けない。\n\n"
        f"【タイトル】{title}\n【本文】{body[:1200]}"
    )
    r = client.models.generate_content(model=MODEL, contents=prompt)
    return (r.text or "").strip().split("\n")[0][:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("captures")
    ap.add_argument("gists")
    ap.add_argument("--max", type=int, default=40)
    a = ap.parse_args()

    client = build_client()
    if client is None:
        print("Vertexの設定もAPIキーも無いのでスキップ")
        return

    gp = Path(a.gists)
    gists = json.loads(gp.read_text(encoding="utf-8")) if gp.exists() else {}

    todo = []
    for f in Path(a.captures).rglob("*.md"):
        if gists.get(f.stem):
            continue
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^# (.+)$", text, re.M)
        t = m.group(1).strip() if m else f.stem
        if JA.search(t):
            continue          # すでに日本語なら要らない
        body = re.sub(r"^---.*?---", "", text, flags=re.S)[:1500]
        todo.append((f.stem, t, body))

    print(f"日本語見出しが要る記事: {len(todo)}本（今回は最大{a.max}本）")
    done = 0
    for vid, t, body in todo[: a.max]:
        try:
            g = gen(client, t, body)
            if g:
                gists[vid] = g
                done += 1
                print(f"  OK {vid}: {g[:40]}")
        except Exception as e:
            print(f"  スキップ {vid}: {type(e).__name__}")
        time.sleep(1.2)          # ペースを守る

    if done:
        gp.write_text(json.dumps(gists, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"完了: {done}本 追加（残り {max(len(todo)-a.max, 0)}本）")


if __name__ == "__main__":
    main()

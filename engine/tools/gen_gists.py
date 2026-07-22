#!/usr/bin/env python3
"""各動画の「伝えたいこと」1行要約を生成し gists.json に保存。

- 材料は手元の _read_cache/<名>.json（YouTube再アクセス不要・Vault非接触）。
- flash-lite で20本ずつまとめて生成（安い）。壊れた出力（繰り返しバグ・長すぎ等）は
  自動検知して flash（上位）で作り直す品質ゲート付き。
- 逐次保存＝途中で止まっても再開可能（生成済みIDはスキップ、再課金なし）。
- 混雑(503)等は待って再試行。逐次実行＋小休止で混雑を起こさない。
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path

socket.setdefaulttimeout(120)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import youtube_explain as yx

TOOLS = Path(__file__).resolve().parent
READ_CACHE = TOOLS / "_read_cache"
OUT = TOOLS / "gists.json"

# ここで扱うのは公開YouTubeの内容だけ＝無料枠(Free tier)に流して代償が無い。
# 無料キーがあればそれを使い、有料残高を動画解析など有料が要る用途のために温存する。
# ⚠️ 私的データ(録音・日記・評議会への相談)はここを通さないこと。無料枠は
#    入力も出力もGoogleの学習に使われ、人間のレビュアーが読む場合がある（公式規約）。
FREE_KEY = os.environ.get("GEMINI_FREE_API_KEY", "").strip()

# 無料プロジェクトのキーでは2.5系が404になる（2026-07-17実測）。3系のみ提供される。
LITE = "gemini-3.1-flash-lite" if FREE_KEY else "gemini-2.5-flash-lite"  # 主力 500 RPD / 15 RPM
FLASH = "gemini-3.5-flash" if FREE_KEY else "gemini-2.5-flash"  # 品質ゲート 20 RPD（失敗時のみ）
GROUP = 20
DELAY = 4.5 if FREE_KEY else 1.0  # 無料枠は15 RPM＝1本あたり4秒以上あけないと429になる
BAD_RE = re.compile(r"(.{1,4}?)\1{7,}")

PROMPT = """以下は複数のYouTube動画から抽出した思考メモです。各動画IDごとに「この動画が一番伝えたいこと」を日本語1行（45字以内、体言止めか言い切り）で要約してください。
出力は純粋なJSONのみ: {"動画ID": "要約", ...}。コードフェンス・説明文は不要。

"""


def load_items() -> list[tuple[str, str]]:
    items = []
    seen = set()
    for jf in sorted(READ_CACHE.glob("*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        for d in data["items"]:
            if d["id"] not in seen:
                seen.add(d["id"])
                items.append((d["id"], d["body"]))
    return items


def build_client():
    """無料キーがあれば無料枠で、無ければ従来の有料キーで動く（環境が欠けても止めない）。"""
    if not FREE_KEY:
        return yx.build_client()
    from google import genai
    return genai.Client(api_key=FREE_KEY)


def call(model: str, prompt: str) -> str:
    client = build_client()
    last = None
    for attempt in range(6):
        try:
            r = client.models.generate_content(model=model, contents=prompt)
            return r.text or ""
        except Exception as e:  # noqa: BLE001
            s = (type(e).__name__ + " " + str(e)).lower()
            transient = any(k in s for k in (
                "503", "unavailable", "500", "internal", "502", "504", "429", "resource_exhausted",
                "deadline", "timeout", "timed out", "remoteprotocol", "disconnect", "connection",
                "protocol", "reset", "broken pipe", "eof", "aborted", "temporarily"))
            if not transient or attempt == 5:
                raise
            wait = 20 * (attempt + 1)
            print(f"  [リトライ{attempt+1}/5] {type(e).__name__} {wait}s待機", flush=True)
            last = e
            time.sleep(wait)
    raise last


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        return json.loads(m.group()) if m else {}


def ok_gist(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and len(s) <= 70 and "\n" not in s and not BAD_RE.search(s)


def save(gists: dict):
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(gists, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def run_groups(pairs: list[tuple[str, str]], model: str, gists: dict, label: str) -> list[tuple[str, str]]:
    """pairsをGROUP本ずつ生成。失敗分のpairsを返す。"""
    failed = []
    groups = [pairs[i:i + GROUP] for i in range(0, len(pairs), GROUP)]
    for gi, g in enumerate(groups, 1):
        body = "\n\n".join(f"[動画ID: {vid}]\n{txt[:2500]}" for vid, txt in g)
        try:
            res = parse_json(call(model, PROMPT + body))
        except Exception as e:  # noqa: BLE001
            print(f"  [{label} {gi}/{len(groups)}] グループ失敗 {type(e).__name__}", flush=True)
            failed.extend(g)
            continue
        ng = 0
        for vid, txt in g:
            v = res.get(vid, "")
            if ok_gist(v):
                gists[vid] = v.strip()
            else:
                failed.append((vid, txt))
                ng += 1
        save(gists)
        if gi % 10 == 0 or ng:
            print(f"  [{label} {gi}/{len(groups)}] 累計{len(gists)}件 (この回の不良{ng})", flush=True)
        time.sleep(DELAY)
    return failed


def main():
    gists: dict[str, str] = {}
    if OUT.exists():
        gists = json.loads(OUT.read_text(encoding="utf-8"))
    items = load_items()
    todo = [(v, b) for v, b in items if v not in gists]
    print(f"全{len(items)}件 / 生成済{len(items) - len(todo)} / 残り{len(todo)}", flush=True)

    failed = run_groups(todo, LITE, gists, "lite")
    if failed:
        print(f"品質ゲート: {len(failed)}件を上位モデル(flash)で再生成", flush=True)
        failed2 = run_groups(failed, FLASH, gists, "flash")
        for vid, _ in failed2:
            gists.setdefault(vid, "")  # 最終手段: 空（後で個別対応）
        save(gists)
        print(f"再生成後も不良: {len(failed2)}件", flush=True)

    ok = sum(1 for v in gists.values() if v)
    print(f"完了: 要約 {ok}/{len(items)}件", flush=True)


if __name__ == "__main__":
    main()

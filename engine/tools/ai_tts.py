#!/usr/bin/env python3
"""記事を自然な声で読み上げた音声を作る（Gemini TTS・無料キー）。

なぜこれなのか（2026-07-21 実測）:
- 本人「活字が苦手。自然な声で読み上げしてくれる機能が欲しい」
- ElevenLabs = 残クレジット10・無料プラン → 毎日は回せない
- Gemini TTS = 無料キーで HTTP 200 を確認。gemini-2.5-flash-preview-tts が使える
- iPhone内蔵の読み上げ(Web Speech API)は¥0だが、日本語の声が機械的なので採用しない

返ってくるのは生のPCMなので、そのままだと巨大（3.8秒で181KB）。
ffmpegでモノラルMP3に落としてからページに埋め込む。
一度作った音声はキャッシュして作り直さない。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / "audio_cache"
# 無料枠は「1モデルあたり1日10リクエスト」（2026-07-21 実測。エラー詳細に
# GenerateRequestsPerDayPerProjectPerModel-FreeTier = 10 と明記されていた）。
# 1日5本なら1モデルで足りるが、余裕を持たせるため使い切ったら次のモデルへ回す。
MODELS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-pro-preview-tts",
]
VOICE = "Kore"  # 落ち着いた女性の声。他の声に変えたければここだけ差し替える
RATE = 24000  # Gemini TTSが返すPCMのサンプリングレート
# data URIで埋め込む＝再生前にページごと全部ダウンロードされる。だから容量が体感速度に直結する。
# 実測 2026-07-21: 48kbpsだと5本で約2MB・ページ2.9MBになったので32kbpsに落とした（話し声には十分）
BITRATE = "32k"


def _key() -> str:
    return (os.environ.get("GEMINI_FREE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()


def _pcm(text: str) -> bytes:
    """Gemini TTSから生のPCMを受け取る。失敗したら空。"""
    key = _key()
    if not key or not text.strip():
        return b""
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
    }
    # 429は「1日の上限」なので待っても回復しない。次のモデルに切り替えるのが正解。
    last = ""
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=180).read())
            part = res["candidates"][0]["content"]["parts"][0]["inlineData"]
            return base64.b64decode(part["data"])
        except urllib.error.HTTPError as ex:
            last = f"{model}: HTTP {ex.code}"
            if ex.code == 429:
                print(f"  {model} は本日の無料枠を使い切り。次のモデルを試します", file=sys.stderr)
                continue
            break
        except Exception as ex:
            last = f"{model}: {ex}"
            break
    print(f"⚠️ 読み上げを作れませんでした（{last}）。文字だけで出します", file=sys.stderr)
    return b""


def _mp3(pcm: bytes) -> bytes:
    """PCMをモノラルMP3へ。話し声なので48kbpsで十分（容量を10分の1にする）。"""
    if not pcm:
        return b""
    with tempfile.TemporaryDirectory() as d:
        raw, out = Path(d) / "a.pcm", Path(d) / "a.mp3"
        raw.write_bytes(pcm)
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", str(raw),
             "-b:a", BITRATE, str(out)],
            capture_output=True,
        )
        if r.returncode != 0 or not out.exists():
            print(f"⚠️ MP3変換に失敗: {r.stderr[:200]!r}", file=sys.stderr)
            return b""
        return out.read_bytes()


def speak(text: str) -> str:
    """読み上げ音声の data URI を返す。作れなければ空文字。"""
    text = (text or "").strip()
    if not text:
        return ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha1(f"{VOICE}|{BITRATE}|{text}".encode()).hexdigest()[:16]
    f = CACHE_DIR / f"{tag}.mp3"
    if not f.exists():
        data = _mp3(_pcm(text))
        if not data:
            return ""
        f.write_bytes(data)
        time.sleep(8)  # 次の記事の生成まで少し空ける（429の予防）
    return "data:audio/mpeg;base64," + base64.b64encode(f.read_bytes()).decode()


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "おはようございます。今朝のAIニュースをお届けします。"
    uri = speak(t)
    kb = (len(uri) * 3 // 4) // 1024 if uri else 0
    print(f"文字数 {len(t)} → 音声 {kb} KB" if uri else "生成できませんでした")

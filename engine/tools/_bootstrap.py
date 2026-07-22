"""依存パッケージを積んだ専用venvへ自動で橋渡しするモジュール。

なぜ必要か:
    macOSのシステムPythonはPEP 668で保護されており `pip install` できない。
    そのため google-genai などの依存は同プロジェクトの `.venv` 側に置く。
    一方でスラッシュコマンド類は `python3 xxx.py` という固定の呼び方をする
    （権限設定 `Bash(python3:*)` を広げないため）。
    このモジュールを import すると、venvのPythonでなければ自動で再実行し、
    呼び出し方を変えずに依存を解決する。

使い方:
    他のimportより前に一度だけ書く。

        import _bootstrap  # noqa: F401

venvが無い場合は何もしない（従来どおりのImportErrorに任せる）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

VENV_PY = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"


def _switch_to_venv() -> None:
    if not VENV_PY.exists():
        return

    try:
        if Path(sys.executable).resolve() == VENV_PY.resolve():
            return  # すでにvenv内。再実行すると無限ループになるので抜ける
    except OSError:
        return

    # 今のPythonで依存が満たせるなら、venvへ切り替えない。
    # 理由(2026-07-19〜20 実測): .venv は iCloud同期される ~/Documents 配下にあり、
    # ディスク逼迫時にmacOSが中身を退避(dataless)する。退避状態のvenvで起動すると
    # import が終わらず **CPU 0%のまま数十分固まる**（実測: 43分で0本／18分で0出力）。
    # python3.9 本体の site-packages は /usr/local にあり退避対象外なので、
    # そちらで動けるならそのまま動かすのが確実。
    try:
        import importlib.util
        if importlib.util.find_spec("google.genai") is not None:
            return
    except Exception:  # noqa: BLE001
        pass  # 判定できない時は従来どおりvenvへ切り替える

    if not sys.argv or not sys.argv[0]:
        return
    script = Path(sys.argv[0])
    if not script.exists():
        return

    os.execv(str(VENV_PY), [str(VENV_PY), str(script.resolve()), *sys.argv[1:]])


_switch_to_venv()

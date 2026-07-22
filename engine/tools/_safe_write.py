"""既存ファイルを黙って消さないための共通ガード。

背景（2026-07-17）:
    mentors配下は保存先が `<人物名>.md` などの固定パスで、複数のツールが同じ場所へ書く。
    そのため mentor_batch/pipeline が何十本もの動画から積み上げた大きな蓄積
    （実測: 八木仁平.md=224KB, あさぎ.md=172KB）を、単発の抽出が警告なく上書きして
    消してしまう事故が起きる設計になっていた。

方針:
    固定パスへ書き込む前に必ず backup_if_exists() を呼ぶ。既存があれば
    タイムスタンプ付きバックアップを残し、stderr に警告を出す。
    「消えていいデータかどうか」をツール側が勝手に判断しない。
"""

from __future__ import annotations

import datetime
import shutil
import sys
from pathlib import Path


def backup_if_exists(path: str | Path) -> Path | None:
    """path が既にあれば `<stem>.bak-YYYYMMDD-HHMMSS<suffix>` へ退避する。

    Returns:
        作成したバックアップのパス。既存ファイルが無ければ None。
    """
    path = Path(path)
    if not path.exists():
        return None

    size = path.stat().st_size
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")

    # 同一秒に複数回呼ばれても上書きしない
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.stem}.bak-{stamp}-{n}{path.suffix}")
        n += 1

    shutil.copy2(path, backup)
    print(
        f"[警告] 既存の {path.name}（{size:,}バイト）を上書きします。\n"
        f"        バックアップ: {backup.name}",
        file=sys.stderr,
    )
    return backup

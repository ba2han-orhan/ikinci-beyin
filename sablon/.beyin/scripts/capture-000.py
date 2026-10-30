#!/usr/bin/env python3
"""Append UserPromptSubmit messages ending in a standalone 000 to the inbox."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vault_write import write


MARKER = re.compile(r"(?:^|\s)000\s*$")
INBOX = "000-gelen-kutusu/hizli-not-yakalama.md"


def capture(payload: dict, root: Path) -> str | None:
    prompt = payload.get("prompt") or payload.get("user_prompt")
    if not isinstance(prompt, str):
        return None
    match = MARKER.search(prompt)
    if match is None:
        return None
    note = prompt[: match.start()].rstrip()
    if not note:
        return None

    stamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")
    quoted = "\n".join("> " + line if line else ">" for line in note.splitlines())
    entry = f"### {stamp} · Hızlı yakalama\n\n{quoted}\n"
    write(root, INBOX, entry, append=True)
    return f"Not yakalama dosyasına kaydedildi ({stamp}); sondaki 000 işareti nota eklenmedi."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook-input", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.hook_input.read_text(encoding="utf-8"))
        result = capture(payload, args.root)
        if result:
            print(result)
    except Exception:
        # The caller surfaces a clear failure message; hook failures must not
        # prevent the user's prompt from reaching the model.
        print("__CAPTURE_FAILED__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

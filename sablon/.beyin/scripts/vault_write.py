#!/usr/bin/env python3
"""Shared, optimistic Markdown memory writer."""

import argparse
import hashlib
import os
import tempfile
from pathlib import Path

import _portalock


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def headings(text, levels=("# ", "## ")):
    return [line for line in text.splitlines() if line.startswith(levels)]


def write(root, relative, text, expected=None, append=False):
    root = Path(root).resolve()
    path = root / relative
    resolved = path.resolve()
    if (not resolved.is_relative_to(root) or path.suffix != ".md"
            or resolved.relative_to(root).parts[0].startswith(("550-", "800-"))
            or path.name in ("AGENTS.md", "CLAUDE.md") or resolved.name in ("AGENTS.md", "CLAUDE.md")):
        raise ValueError("İzin verilmeyen hafıza yolu")
    if not append and not expected:
        raise ValueError("Değiştirme için --expected SHA-256 zorunlu; yeni not için 'new'")
    folder = root / ".beyin/scripts/.state/write-locks"
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    with (folder / (key + ".lock")).open("a") as handle, _portalock.exclusive(handle):
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if expected and expected != (digest(before) if before is not None else "new"):
            raise ValueError("Kaynak değişti; yeniden okuyup hash hesapla")
        after = text
        if append:
            old = before or ""
            # 16.10: a caller passed current+new and the file doubled. An appended entry
            # never repeats an existing H1/H2 heading, and only adds its own H2 count.
            if set(headings(text)) & set(headings(old)):
                raise ValueError("Eklenen metin mevcut başlık içeriyor; yalnız yeni girişi ver")
            head, sep, links = old.rpartition("\n## İlgili")
            after = ((head if sep else old).rstrip() + "\n\n" + text.rstrip() + "\n"
                     + (sep + links if sep else ""))
            if len(headings(after, "## ")) != len(headings(old, "## ")) + len(headings(text, "## ")):
                raise ValueError("Ekleme sonrası başlık sayısı tutmuyor; yazılmadı")
        if before is not None:
            backup = root / ".beyin/scripts/.state/write-backups" / (digest(before) + ".md")
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_text(before, encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != before:
            raise ValueError("Kaynak yazım sırasında değişti; yeniden oku")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".beyin-write-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return digest(after)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Vault'a göre göreli .md yolu")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--text-file", required=True, help="Yeni içerik veya eklenecek metin dosyası")
    parser.add_argument("--expected", help="Okunan dosyanın SHA-256'sı; yeni not için new")
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    try:
        print(write(args.root, args.path, Path(args.text_file).read_text(encoding="utf-8"),
                    args.expected, args.append))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")

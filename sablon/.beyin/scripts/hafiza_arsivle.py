#!/usr/bin/env python3
"""Eski tamamlanmış thread, günlük ve oturum özeti girişlerini güvenli biçimde arşivle."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from vault_write import digest, write


VAULT = Path(__file__).resolve().parents[2]
THREAD = Path("850-hafiza/aktif-konu-takibi.md")
JOURNAL = Path("850-hafiza/gunluk-gozlemleri.md")
THREAD_ARCHIVE = Path("900-arsiv/aktif-konu-arsivi.md")
JOURNAL_ARCHIVE = Path("900-arsiv/gunluk-gozlemleri-arsivi.md")
SESSIONS = Path("850-hafiza/son-oturum-ozetleri.md")
SESSION_ARCHIVE = Path("900-arsiv/son-oturum-ozetleri-arsivi.md")
# Arşivde ilk kayıt: önceki taşımanın notu ya da ilk ## / ### başlığı (İlgili dahil).
FIRST_ENTRY = re.compile(r"(?m)^(?:> \*\*Arşive taşındı:\*\*|#{2,3} )")
DATE = re.compile(r"(?<!\d)(\d{2}\.\d{2}\.\d{4})(?!\d)")
HEADING = re.compile(r"(?m)^(?:## (?!#)|### Thread:)")
JOURNAL_DATE = re.compile(r"^## (\d{2}\.\d{2}\.\d{4})(?!\d)")
STATUS = re.compile(r"(?m)^\*\*Status:\*\*\s*([^\n]+)")


def blocks(text: str) -> list[str]:
    """Başlık dahil ham parçaları döndür; birleştirilince girdi birebir oluşur."""
    # Kod bloğu içindeki "## " satırı başlık değildir (29.09 inceleme): bölünürse blok
    # kapanmamış çitle arşive gider, kuyruğu kaynakta sahipsiz kalır.
    fences = []
    acik = None
    for match in re.finditer(r"(?m)^[ \t]*(```|~~~)", text):
        if acik is None:
            acik = match.start()
        else:
            fences.append((acik, match.end()))
            acik = None
    if acik is not None:
        fences.append((acik, len(text)))
    starts = [match.start() for match in HEADING.finditer(text)
              if not any(a < match.start() < b for a, b in fences)]
    if not starts:
        return [text]
    return [text[: starts[0]]] + [text[start:end] for start, end in
                                   zip(starts, starts[1:] + [len(text)])]


def latest_date(text: str) -> date | None:
    found = []
    for raw in DATE.findall(text):
        try:
            found.append(datetime.strptime(raw, "%d.%m.%Y").date())
        except ValueError:
            continue
    return max(found) if found else None


def thread_date(block: str, cutoff: date) -> date | None:
    if not block.startswith("### Thread:"):
        return None
    status = STATUS.search(block)
    if not status:
        return None
    line = status.group(1).strip()
    if re.search(r"\bActive\b", line, re.IGNORECASE):
        return None
    if line.startswith("🟢"):
        if not re.search(r"tamamlan|çözül|kurul", line, re.IGNORECASE):
            return None
    elif not line.startswith("⚪"):
        return None
    newest = latest_date(block)
    return newest if newest and newest < cutoff else None


def journal_date(block: str, cutoff: date) -> date | None:
    match = JOURNAL_DATE.match(block)
    if not match:
        return None
    try:
        day = datetime.strptime(match.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None
    return day if day < cutoff else None


def session_date(block: str, cutoff: date) -> date | None:
    """Oturum yaşı başlıktaki en geç tarihtir ("30.09–01.10.2026" → 01.10)."""
    heading = block.split("\n", 1)[0]
    if not heading.startswith("## ") or heading.startswith("## İlgili"):
        return None
    newest = latest_date(heading)
    return newest if newest and newest < cutoff else None


def archive_template(kind: str, today: date) -> str:
    day = today.strftime("%d.%m.%Y")
    if kind == "thread":
        title, source, summary = ("Aktif konu arşivi", "aktif-konu-takibi",
                                  "Tamamlanan veya kapatılan eski thread'ler; en yenisi üstte")
    elif kind == "session":
        title, source, summary = ("Son oturum özetleri arşivi", "son-oturum-ozetleri",
                                  "Eski oturum anlatıları; en yenisi üstte")
    else:
        title, source, summary = ("Günlük gözlemleri arşivi", "gunluk-gozlemleri",
                                  "Eski günlük gözlemleri; en yenisi üstte")
    return (f"---\ntitle: {title}\ncreated: {day}\nmodified: {day}\n"
            "type: log\nstatus: archived\ntags: [hafiza, arsiv]\n---\n\n"
            f"# {title}\n\n> ⬆️ [[arsiv-genel-bakis]] · [[{source}]] kaynağından taşınan kayıtlar. {summary}.\n\n"
            f"## İlgili\n\n- [[{source}]] — kayıtların güncel kaynağı; yeni girişler orada tutulur.\n")


def prepare(source: str, archive: str | None, kind: str, days: int,
            today: date) -> tuple[str, str | None, list[tuple[date, str]]]:
    cutoff = today - timedelta(days=days)
    selected = []
    remaining = []
    checker = {"thread": thread_date, "journal": journal_date, "session": session_date}[kind]
    original = blocks(source)
    for block in original:
        day = checker(block, cutoff)
        if day is None:
            remaining.append(block)
        else:
            selected.append((day, block))
    if not selected:
        return source, archive, []
    # Taşınan metinler dönüştürülmez. Taşınma notu her ham bloğun önüne eklenir.
    selected.sort(key=lambda item: item[0], reverse=True)
    # Arşiv yazılıp kaynakta CAS çakışırsa sonraki deneme aynı bloğu çoğaltmaz.
    fresh = [(day, block) for day, block in selected if archive is None or block not in archive]
    moved = "".join(f"> **Arşive taşındı:** {today:%d.%m.%Y}\n\n{block}"
                    for _, block in fresh)
    before = archive if archive is not None else archive_template(kind, today)
    if "## İlgili\n" not in before:
        raise ValueError("Arşiv notunda ## İlgili bölümü yok")
    # Arşivler "en yenisi üstte": yeni taşınanlar mevcut kayıtların üstüne girer.
    index = FIRST_ENTRY.search(before).start()
    result = before[:index] + moved + before[index:]
    assert Counter(remaining + [block for _, block in selected]) == Counter(original)
    return "".join(remaining), result, selected


def run(root: Path, days: int | None = None, apply: bool = False,
        today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    root = root.resolve()
    counts = {}
    for source_path, archive_path, kind, span in (
        (THREAD, THREAD_ARCHIVE, "thread", 14 if days is None else days),
        (JOURNAL, JOURNAL_ARCHIVE, "journal", 30 if days is None else days),
        # 27.10.2026: dosya 323 KB'ye çıkmıştı; 7 gün ~30 KB bırakır.
        (SESSIONS, SESSION_ARCHIVE, "session", 7 if days is None else days),
    ):
        if not (root / source_path).exists():
            continue
        source = (root / source_path).read_text(encoding="utf-8")
        target = root / archive_path
        archive = target.read_text(encoding="utf-8") if target.exists() else None
        remaining, new_archive, selected = prepare(source, archive, kind, span, today)
        counts[kind] = len(selected)
        print(f"{source_path}: {len(selected)} kayıt taşınacak (eşik {span} gün)")
        for day, block in selected:
            print(f"  {day:%d.%m.%Y}  {block.splitlines()[0]}")
        if selected and archive is None:
            print(f"  Öneri: {archive_path.name} için [[arsiv-genel-bakis]] indeksine bağlantı ekleyin.")
        if not apply or not selected:
            continue
        # Önce arşiv yazılır: ikinci yazım çakışırsa veri kaybolmaz, kopya kalır.
        # İki kaynak da yazım öncesinde tekrar denetlenir; her yazım ayrıca CAS kullanır.
        if digest((root / source_path).read_text(encoding="utf-8")) != digest(source):
            raise ValueError(f"{source_path}: kaynak değişti; işlem iptal edildi")
        current_archive = target.read_text(encoding="utf-8") if target.exists() else None
        if current_archive != archive:
            raise ValueError(f"{archive_path}: arşiv değişti; işlem iptal edildi")
        if new_archive != archive:
            write(root, str(archive_path), new_archive, expected=digest(archive) if archive is not None else "new")
        write(root, str(source_path), remaining, expected=digest(source))
        print(f"  Yazıldı: {archive_path} ve {source_path}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=VAULT, help="Vault kökü")
    parser.add_argument("--gun", type=int,
                        help="Tüm dosyalar için gün eşiği (varsayılan: thread 14, günlük 30, oturum özeti 7)")
    parser.add_argument("--uygula", action="store_true", help="Kilitli yazımı uygula; varsayılan yalnız önizleme")
    args = parser.parse_args()
    if args.gun is not None and args.gun < 0:
        parser.error("--gun sıfır veya pozitif olmalı")
    try:
        run(args.vault, args.gun, args.uygula)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Arşivleme iptal edildi: {error}\n")


if __name__ == "__main__":
    main()

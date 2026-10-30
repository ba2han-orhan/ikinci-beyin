#!/usr/bin/env python3
"""Haftalık özet / proje durum raporu — deterministik, LLM çağrısı yok.

Kontrol panelinin "Bu hafta" bölümü elle yazılınca tazeliğini kaybeder. Bu script aynı bilgiyi
vault'un kendi kayıtlarından (thread'ler, proje frontmatter'ı, günlük loglar, git log,
hedef tarihleri) her çalıştırıldığında yeniden üretir.

    python3 .beyin/scripts/haftalik_ozet.py [--gun 7] [--bitis GG.AA.YYYY] [--yaz] [--json]
                                          [--depo YOL ...] [--vault YOL]

Varsayılan: stdout'a Türkçe Markdown basar. --yaz ile 100-komuta-merkezi/haftalik-ozet.md
tek dönen dosya olarak (üstüne yazılarak) güncellenir. --json ile makine formatı.

`850-hafiza/aktif-konu-takibi.md` bu script tarafından SADECE okunur, asla düzenlenmez.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
STATUS_EMOJI = "🟢🟡🔴⚪🟠🔵🟣"
BAYAT_ESIK_GUN = 14


def gg_aa_yyyy(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def parse_tarih(metin: str) -> dt.date | None:
    m = DATE_RE.search(metin)
    if not m:
        return None
    gun, ay, yil = m.groups()
    try:
        return dt.date(int(yil), int(ay), int(gun))
    except ValueError:
        return None


def tum_tarihler(metin: str) -> list[dt.date]:
    out = []
    for gun, ay, yil in DATE_RE.findall(metin):
        try:
            out.append(dt.date(int(yil), int(ay), int(gun)))
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------
# 1. Threadler
# --------------------------------------------------------------------------

def threadleri_oku(vault: Path, bitis: dt.date, baslangic: dt.date) -> list[dict]:
    yol = vault / "850-hafiza" / "aktif-konu-takibi.md"
    if not yol.exists():
        return []
    metin = yol.read_text(encoding="utf-8")
    parcalar = re.split(r"(?m)^### Thread: ", metin)[1:]
    threadler = []
    for parca in parcalar:
        satir_sonu = parca.find("\n")
        baslik = parca[:satir_sonu].strip() if satir_sonu != -1 else parca.strip()
        govde = parca[satir_sonu:] if satir_sonu != -1 else ""
        durum_m = re.search(r"\*\*Status:\*\*\s*([^\n]*)", govde)
        durum_satiri = durum_m.group(1).strip() if durum_m else ""
        emoji = next((c for c in durum_satiri if c in STATUS_EMOJI), None)
        tarihler = tum_tarihler(govde)
        son_tarih = max(tarihler) if tarihler else None
        acik = emoji in ("🟡", "🔴")
        bayat = False
        if acik:
            if son_tarih is None:
                bayat = True
            elif (bitis - son_tarih).days > BAYAT_ESIK_GUN:
                bayat = True
        pencerede = son_tarih is not None and baslangic <= son_tarih <= bitis
        threadler.append({
            "baslik": baslik,
            "emoji": emoji,
            "acik": acik,
            "son_tarih": gg_aa_yyyy(son_tarih) if son_tarih else None,
            "bayat": bayat,
            "pencerede": pencerede,
        })
    return threadler


# --------------------------------------------------------------------------
# 2. Projeler
# --------------------------------------------------------------------------

def frontmatter_oku(metin: str) -> dict:
    if not metin.startswith("---"):
        return {}
    m = re.match(r"^---\n(.*?)\n---\n", metin, re.DOTALL)
    if not m:
        return {}
    alanlar = {}
    for satir in m.group(1).splitlines():
        if ":" not in satir:
            continue
        anahtar, _, deger = satir.partition(":")
        alanlar[anahtar.strip()] = deger.strip()
    return alanlar


def projeleri_oku(vault: Path, bitis: dt.date) -> list[dict]:
    kok = vault / "300-projeler"
    sonuc = []
    for yol in sorted(kok.glob("*/*-proje-durum-ozeti.md")):
        metin = yol.read_text(encoding="utf-8")
        fm = frontmatter_oku(metin)
        modified = parse_tarih(fm.get("modified", ""))
        status = fm.get("status", "")
        bosta_gun = (bitis - modified).days if modified else None
        bayat = status == "active" and bosta_gun is not None and bosta_gun > BAYAT_ESIK_GUN
        sonuc.append({
            "proje": fm.get("title", yol.stem),
            "dosya": str(yol.relative_to(vault)),
            "status": status or "bilinmiyor",
            "modified": gg_aa_yyyy(modified) if modified else None,
            "bosta_gun": bosta_gun,
            "bayat": bayat,
        })
    return sonuc


# --------------------------------------------------------------------------
# 3. Günlük oturum kayıtları
# --------------------------------------------------------------------------

def oturum_sayilarini_oku(vault: Path, baslangic: dt.date, bitis: dt.date) -> list[dict]:
    kok = vault / "800-gunluk-oturum-kayitlari"
    if not kok.exists():
        return []
    sonuc = []
    for yol in sorted(kok.glob("*.md")):
        tarih = parse_tarih(yol.stem)
        if tarih is None or not (baslangic <= tarih <= bitis):
            continue
        metin = yol.read_text(encoding="utf-8")
        sayi = len(re.findall(r"(?m)^### Oturum", metin))
        sonuc.append({"tarih": gg_aa_yyyy(tarih), "oturum": sayi})
    sonuc.sort(key=lambda r: r["tarih"])
    return sonuc


# --------------------------------------------------------------------------
# 4. Git log
# --------------------------------------------------------------------------

def depo_gunlugu(depo: Path, baslangic: dt.date, bitis: dt.date, limit: int = 10) -> dict:
    if shutil.which("git") is None:
        return {"depo": str(depo), "hata": "git bulunamadı"}
    since = baslangic.strftime("%Y-%m-%d") + " 00:00:00"
    until = bitis.strftime("%Y-%m-%d") + " 23:59:59"
    try:
        tamamlanan = subprocess.run(
            ["git", "-C", str(depo), "log", f"--since={since}", f"--until={until}",
             "--pretty=format:%ad\t%s", "--date=format:%d.%m.%Y"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError) as hata:
        return {"depo": str(depo), "hata": str(hata)}
    if tamamlanan.returncode != 0:
        return {"depo": str(depo), "hata": tamamlanan.stderr.strip() or "git log başarısız"}
    satirlar = [s for s in tamamlanan.stdout.splitlines() if s.strip()]
    commitler = []
    for satir in satirlar:
        tarih, _, konu = satir.partition("\t")
        commitler.append({"tarih": tarih, "konu": konu})
    return {
        "depo": str(depo),
        "commit_sayisi": len(commitler),
        "ornekler": commitler[:limit],
    }


# --------------------------------------------------------------------------
# 5. Yaklaşan tarihler (200-hedefler)
# --------------------------------------------------------------------------

def yaklasan_tarihleri_oku(vault: Path, bugun: dt.date, ufuk_gun: int = 14) -> list[dict]:
    kok = vault / "200-hedefler"
    if not kok.exists():
        return []
    son = bugun + dt.timedelta(days=ufuk_gun)
    bulunan = []
    for yol in sorted(kok.rglob("*.md")):
        metin = yol.read_text(encoding="utf-8")
        # Frontmatter'daki created/modified tarihleri deadline değildir, gövdeyi tara.
        gövde_m = re.match(r"^---\n.*?\n---\n(.*)$", metin, re.DOTALL)
        govde = gövde_m.group(1) if gövde_m else metin
        for tarih in set(tum_tarihler(govde)):
            if bugun <= tarih <= son:
                satir = ""
                for line in metin.splitlines():
                    if gg_aa_yyyy(tarih) in line:
                        satir = line.strip()
                        break
                bulunan.append({
                    "dosya": str(yol.relative_to(vault)),
                    "tarih": gg_aa_yyyy(tarih),
                    "baglam": satir[:160],
                })
    bulunan.sort(key=lambda r: r["tarih"])
    return bulunan


# --------------------------------------------------------------------------
# Toplama
# --------------------------------------------------------------------------

def ozet_topla(vault: Path, gun: int, bitis: dt.date, depolar: list[Path]) -> dict:
    baslangic = bitis - dt.timedelta(days=gun - 1)
    threadler = threadleri_oku(vault, bitis, baslangic)
    projeler = projeleri_oku(vault, bitis)
    oturumlar = oturum_sayilarini_oku(vault, baslangic, bitis)
    gitler = [depo_gunlugu(d, baslangic, bitis) for d in ([vault] + depolar)]
    yaklasan = yaklasan_tarihleri_oku(vault, bitis)
    return {
        "baslangic": gg_aa_yyyy(baslangic),
        "bitis": gg_aa_yyyy(bitis),
        "gun": gun,
        "threadler": threadler,
        "projeler": projeler,
        "oturumlar": oturumlar,
        "git": gitler,
        "yaklasan_tarihler": yaklasan,
    }


# --------------------------------------------------------------------------
# Markdown çıktı
# --------------------------------------------------------------------------

def markdown_gövde(veri: dict) -> str:
    s = []
    s.append(f"## Pencere: {veri['baslangic']} – {veri['bitis']} ({veri['gun']} gün)\n")

    s.append("## Açık thread'ler")
    acik = [t for t in veri["threadler"] if t["acik"]]
    if not acik:
        s.append("- Açık (🟡/🔴) thread yok.")
    else:
        for t in acik:
            bayat_etiketi = " — **bayat**, 14 günden uzun süredir güncellenmedi" if t["bayat"] else ""
            tarih = t["son_tarih"] or "tarih yok"
            s.append(f"- {t['emoji'] or '?'} {t['baslik']} — son güncelleme {tarih}{bayat_etiketi}")
    s.append("")

    s.append("## Bu pencerede güncellenen thread'ler")
    pencerede = [t for t in veri["threadler"] if t["pencerede"]]
    if not pencerede:
        s.append("- Bu pencerede güncellenen thread yok.")
    else:
        for t in pencerede:
            s.append(f"- {t['emoji'] or '?'} {t['baslik']} — {t['son_tarih']}")
    s.append("")

    s.append("## Proje durumu")
    bayat_projeler = [p for p in veri["projeler"] if p["bayat"]]
    if bayat_projeler:
        s.append("**Bayat (aktif ama 14 günden uzun süredir dokunulmamış):**")
        for p in bayat_projeler:
            s.append(f"- {p['proje']} — son değişiklik {p['modified']} ({p['bosta_gun']} gün önce)")
    else:
        s.append("- Bayat aktif proje yok.")
    diger = [p for p in veri["projeler"] if not p["bayat"]]
    if diger:
        s.append("\nDiğer projeler:")
        for p in diger:
            modified = p["modified"] or "bilinmiyor"
            s.append(f"- {p['proje']} ({p['status']}) — son değişiklik {modified}")
    s.append("")

    s.append("## Günlük oturum sayıları")
    if not veri["oturumlar"]:
        s.append("- Bu pencerede günlük log kaydı yok.")
    else:
        for o in veri["oturumlar"]:
            s.append(f"- {o['tarih']}: {o['oturum']} oturum")
    s.append("")

    s.append("## Git aktivitesi")
    for g in veri["git"]:
        if "hata" in g:
            s.append(f"- `{g['depo']}`: ölçülemedi ({g['hata']})")
            continue
        s.append(f"- `{g['depo']}`: {g['commit_sayisi']} commit")
        for c in g["ornekler"]:
            s.append(f"  - {c['tarih']} {c['konu']}")
    s.append("")

    s.append("## Yaklaşan tarihler (200-hedefler, 14 gün ufku)")
    if not veri["yaklasan_tarihler"]:
        s.append("- Yaklaşan tarih yok.")
    else:
        for y in veri["yaklasan_tarihler"]:
            s.append(f"- {y['tarih']} — {y['dosya']}: {y['baglam']}")
    return "\n".join(s).rstrip() + "\n"


def markdown_dosya(veri: dict, bugun: dt.date) -> str:
    frontmatter = (
        "---\n"
        "title: Haftalık Özet\n"
        f"created: {gg_aa_yyyy(bugun)}\n"
        f"modified: {gg_aa_yyyy(bugun)}\n"
        "type: dashboard\n"
        "---\n"
    )
    baslik = (
        "# Haftalık Özet\n\n"
        "> ⬆️ [[kontrol-paneli]] · `.beyin/scripts/haftalik_ozet.py` ile üretilir, "
        "elle düzenlenmez; yeniden çalıştırınca üstüne yazılır.\n\n"
    )
    govde = markdown_gövde(veri)
    ilgili = (
        "\n## İlgili\n\n"
        "- [[aktif-konu-takibi]] — açık thread'lerin kaynağı; bu özet oradan okur, yazmaz.\n"
        "- [[projeler-genel-bakis]] — proje bayatlık kontrolünün kaynağı olan proje notları.\n"
        "- [[hedefler-genel-bakis]] — yaklaşan tarihler bölümünün dayandığı hedef notları.\n"
    )
    return frontmatter + "\n" + baslik + govde + ilgili


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gun", type=int, default=7, help="Pencere uzunluğu, gün (varsayılan 7)")
    ap.add_argument("--bitis", default=None, help="Pencerenin son günü, GG.AA.YYYY (varsayılan bugün)")
    ap.add_argument("--vault", default=str(VAULT_ROOT), help="Vault kökü")
    ap.add_argument("--depo", action="append", default=[], help="Ek git deposu (tekrarlanabilir)")
    ap.add_argument("--yaz", action="store_true", help="100-komuta-merkezi/haftalik-ozet.md dosyasına yaz")
    ap.add_argument("--json", action="store_true", help="JSON çıktı ver")
    args = ap.parse_args(argv)

    vault = Path(args.vault).resolve()
    if args.bitis:
        bitis = parse_tarih(args.bitis)
        if bitis is None:
            ap.error("--bitis GG.AA.YYYY biçiminde olmalı")
    else:
        bitis = dt.date.today()
    if args.gun < 1:
        ap.error("--gun en az 1 olmalı")

    depolar = [Path(d).resolve() for d in args.depo]
    veri = ozet_topla(vault, args.gun, bitis, depolar)

    if args.json:
        print(json.dumps(veri, ensure_ascii=False, indent=2))
        return 0

    if args.yaz:
        icerik = markdown_dosya(veri, dt.date.today())
        hedef = vault / "100-komuta-merkezi" / "haftalik-ozet.md"
        sys.path.insert(0, str((vault / ".beyin" / "scripts").resolve()))
        try:
            import vault_write  # type: ignore
        except ImportError:
            vault_write = None
        if vault_write is not None:
            # Çakışma (kaynak değişti) ya da izin hatası yedek yola düşmez: kilitsiz
            # yazım araya giren düzenlemeyi silerdi (29.09 çapraz inceleme).
            mevcut = hedef.read_text(encoding="utf-8") if hedef.exists() else None
            expected = vault_write.digest(mevcut) if mevcut is not None else "new"
            try:
                vault_write.write(str(vault), "100-komuta-merkezi/haftalik-ozet.md", icerik, expected=expected)
            except (ValueError, OSError) as hata:
                print(f"Yazılamadı: {hata}", file=sys.stderr)
                return 1
            yazma_bilgisi = "vault_write"
        else:
            hedef.parent.mkdir(parents=True, exist_ok=True)
            import os
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=hedef.parent, prefix=".haftalik-ozet-", delete=False
            ) as f:
                gecici = Path(f.name)
                f.write(icerik)
                f.flush()
                os.fsync(f.fileno())
            os.replace(gecici, hedef)
            yazma_bilgisi = "atomik"
        print(f"Yazıldı ({yazma_bilgisi}): {hedef.relative_to(vault)}")
        return 0

    print(markdown_gövde(veri))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

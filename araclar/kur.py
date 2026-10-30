#!/usr/bin/env python3
"""İkinci beyin şablonunu bir Obsidian vault'una zarar vermeden kurar.

Kullanım:
  python3 araclar/kur.py --hedef /vault/yolu --degerler degerler.json --kuru   # plan, hiçbir şey yazmaz
  python3 araclar/kur.py --hedef /vault/yolu --degerler degerler.json          # uygula
  python3 araclar/kur.py --hedef /vault/yolu --profil profil.json              # anket çıktısıyla

Kurallar:
- Hedefte zaten olan dosyanın üzerine asla yazılmaz; atlanır ve raporda listelenir.
- Yer tutucular ({{AD}}) yalnız bu çalıştırmada kopyalanan dosyalarda doldurulur.
- `.claude/settings.json` varsa hook'lar birleştirilir (mevcut girdiler korunur), önce
  `.claude/settings.json.kurulum-oncesi` kopyası alınır.
- `.claude/skills` ve `.agents/skills` (Codex) bir klasörse beyin skill'leri tek tek bağlanır.
- `AGENTS.md` (Codex'in okuduğu yönlendirici) yoksa `CLAUDE.md`'ye bağlantı olarak açılır.
- `--codex` verilirse hook'lar ayrıca `~/.codex/hooks.json`'a yazılır (`.beyin/scripts/codex_kur.py`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
SABLON = KOK / "sablon"
GEREKLI = ("VAULT_ADI", "ASISTAN_ADI", "KULLANICI_ADI", "KULLANICI_BAGLAM", "ODAK_ALANLARI", "TON", "BUGUN")
ISTEGE_BAGLI = {"MEVCUT_NOTLAR_SATIRI": ""}
YER_TUTUCU = re.compile(r"\{\{([A-Z_]+)\}\}")
METIN_UZANTILARI = {".md", ".json", ".sh", ".py", ".txt", ""}
OZEL = {".claude/settings.json", ".claude/skills"}


def degerleri_oku(yol: Path | None, profil: dict, hedef: Path) -> dict[str, str]:
    from datetime import date
    veri = {"VAULT_ADI": hedef.name, "BUGUN": date.today().strftime("%d.%m.%Y")}
    veri.update(profil.get("degerler", {}))
    if yol:
        veri.update(json.loads(yol.read_text(encoding="utf-8")))
    eksik = [k for k in GEREKLI if not str(veri.get(k, "")).strip()]
    if eksik:
        sys.exit(f"HATA: degerler.json içinde eksik alan: {', '.join(eksik)}")
    if not re.fullmatch(r"\d\d\.\d\d\.\d{4}", veri["BUGUN"]):
        sys.exit("HATA: BUGUN GG.AA.YYYY biçiminde olmalı")
    return {**ISTEGE_BAGLI, **{k: str(v) for k, v in veri.items()}}


PROFIL_ETIKETLERI = (
    ("uc_sey", "Kendini anlatan üç şey"), ("projeler", "Aktif projeler"),
    ("hedef_3_ay", "3 aylık hedef"), ("hedef_1_yil", "1 yıllık hedef"),
    ("tarihler", "Yaklaşan tarihler"), ("uzunluk", "Cevap uzunluğu"),
    ("itiraz", "Katılmadığında"), ("emoji", "Emoji"), ("ogrenme", "Öğrenme tarzı"),
    ("saatler", "Verimli saatler"), ("oturum", "Oturum düzeni"),
    ("hatirlatma", "Oturum başı hatırlatma"), ("onaysiz_yapmasin", "Onaysız yapmasın"),
    ("sinir_eden", "Sinir eden davranış"), ("ek_not", "Ek not"),
)


def profil_notu(profil: dict, degerler: dict[str, str]) -> str:
    """Anket cevaplarından 850-hafiza/kullanici-profili.md üretir."""
    cevaplar = profil.get("profil", {})
    satirlar = [
        f"# {degerler['KULLANICI_ADI']}: Profil",
        "",
        "> ⬆️ [[kimlik-cekirdegi]] · Kurulum anketinden gelen tercihler",
        "",
    ]
    dolu = False
    for anahtar, etiket in PROFIL_ETIKETLERI:
        deger = cevaplar.get(anahtar)
        if not deger:
            continue
        dolu = True
        if isinstance(deger, list) and anahtar in ("projeler", "tarihler"):
            satirlar += [f"## {etiket}", "", *[f"- {d}" for d in deger], ""]
        else:
            metin = ", ".join(deger) if isinstance(deger, list) else str(deger)
            satirlar += [f"- **{etiket}:** {metin}"]
    if not dolu:
        satirlar.append("Anket doldurulmadı. Tercihler ortaya çıktıkça buraya eklenir.")
    satirlar += [
        "",
        "## Asistan için",
        "",
        "İlk oturumda bu notu oku: projeler için `300-projeler/` altında durum notu, tarihler için",
        "[[hedefler-genel-bakis]] girdisi aç; \"onaysız yapmasın\" ve \"sinir eden davranış\" maddelerini",
        "[[davranis-kurallari]] dosyasına kural olarak yaz. Her adımı kullanıcıya kısaca bildir.",
        "",
        "## İlgili",
        "",
        "- [[kimlik-cekirdegi]] — bu tercihlerin özetlendiği kimlik çapası.",
        "- [[davranis-kurallari]] — sınırların bağlayıcı kurala dönüştüğü yer.",
        "",
    ]
    return "\n".join(satirlar)


def sablon_dosyalari() -> list[Path]:
    dosyalar = []
    for yol in sorted(SABLON.rglob("*")):
        goreli = yol.relative_to(SABLON)
        if "__pycache__" in goreli.parts or goreli.as_posix() in OZEL:
            continue
        if goreli.parts[:2] == (".claude", "skills"):
            continue
        if yol.is_file() and not yol.is_symlink():
            dosyalar.append(goreli)
    return dosyalar


def doldur(metin: str, degerler: dict[str, str]) -> str:
    def degistir(m: re.Match) -> str:
        return degerler.get(m.group(1), m.group(0))
    return YER_TUTUCU.sub(degistir, metin)


def ayarlari_birlestir(hedef: Path, kuru: bool, rapor: list[str]) -> None:
    kaynak = json.loads((SABLON / ".claude/settings.json").read_text(encoding="utf-8"))
    yol = hedef / ".claude/settings.json"
    if not yol.exists():
        rapor.append("YAZ   .claude/settings.json (yeni)")
        if not kuru:
            yol.parent.mkdir(parents=True, exist_ok=True)
            yol.write_text(json.dumps(kaynak, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    mevcut = json.loads(yol.read_text(encoding="utf-8"))
    hooks = mevcut.setdefault("hooks", {})
    eklenen = 0
    for olay, gruplar in kaynak["hooks"].items():
        var = json.dumps(hooks.get(olay, []))
        for grup in gruplar:
            komutlar = [h["command"] for h in grup["hooks"]]
            if all(k in var for k in komutlar):
                continue
            hooks.setdefault(olay, []).append(grup)
            eklenen += 1
    mevcut.setdefault("autoMemoryEnabled", False)
    rapor.append(f"BIRLES .claude/settings.json ({eklenen} hook grubu eklendi, mevcutlar korundu)")
    if not kuru and eklenen:
        shutil.copy2(yol, yol.with_name("settings.json.kurulum-oncesi"))
        yol.write_text(json.dumps(mevcut, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def agents_bagla(hedef: Path, kuru: bool, rapor: list[str]) -> None:
    yol = hedef / "AGENTS.md"
    if yol.exists() or yol.is_symlink():
        rapor.append("ATLA  AGENTS.md (zaten var; CLAUDE.md içeriğini oraya eklemeyi öner)")
        return
    rapor.append("BAGLA AGENTS.md -> CLAUDE.md")
    if not kuru:
        os.symlink("CLAUDE.md", yol)


def skilleri_bagla(hedef: Path, kuru: bool, rapor: list[str], kok: str = ".claude") -> None:
    yol = hedef / kok / "skills"
    if not yol.exists() and not yol.is_symlink():
        rapor.append(f"BAGLA {kok}/skills -> ../.beyin/skills")
        if not kuru:
            yol.parent.mkdir(parents=True, exist_ok=True)
            os.symlink("../.beyin/skills", yol)
        return
    if yol.is_symlink():
        rapor.append(f"ATLA  {kok}/skills zaten bağlantı ({os.readlink(yol)})")
        return
    for skill in sorted((SABLON / ".beyin/skills").iterdir()):
        alt = yol / skill.name
        if alt.exists() or alt.is_symlink():
            rapor.append(f"ATLA  {kok}/skills/{skill.name} (zaten var)")
            continue
        rapor.append(f"BAGLA {kok}/skills/{skill.name} -> ../../.beyin/skills/{skill.name}")
        if not kuru:
            os.symlink(f"../../.beyin/skills/{skill.name}", alt)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hedef", type=Path, required=True)
    ap.add_argument("--degerler", type=Path, help="elle doldurulmuş değerler (profildekileri ezer)")
    ap.add_argument("--profil", type=Path, help="araclar/profil-anketi.html çıktısı")
    ap.add_argument("--kuru", action="store_true", help="yalnız planı göster")
    ap.add_argument("--codex", action="store_true", help="hook'ları ~/.codex/hooks.json'a da yaz")
    args = ap.parse_args()

    hedef = args.hedef.expanduser().resolve()
    if not (args.degerler or args.profil):
        ap.error("--degerler ya da --profil gerekli")
    profil = json.loads(args.profil.read_text(encoding="utf-8")) if args.profil else {}
    degerler = degerleri_oku(args.degerler, profil, hedef)
    if not args.kuru:
        hedef.mkdir(parents=True, exist_ok=True)

    rapor: list[str] = []
    atlanan: list[str] = []
    for goreli in sablon_dosyalari():
        kaynak, hedef_yol = SABLON / goreli, hedef / goreli
        if hedef_yol.exists() or hedef_yol.is_symlink():
            atlanan.append(goreli.as_posix())
            continue
        rapor.append(f"YAZ   {goreli.as_posix()}")
        if args.kuru:
            continue
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        if kaynak.suffix in METIN_UZANTILARI:
            hedef_yol.write_text(doldur(kaynak.read_text(encoding="utf-8"), degerler), encoding="utf-8")
            shutil.copymode(kaynak, hedef_yol)
        else:
            shutil.copy2(kaynak, hedef_yol)

    profil_yolu = hedef / "850-hafiza/kullanici-profili.md"
    if profil_yolu.exists():
        atlanan.append("850-hafiza/kullanici-profili.md")
    else:
        rapor.append("YAZ   850-hafiza/kullanici-profili.md" + ("" if args.profil else " (boş)"))
        if not args.kuru:
            profil_yolu.parent.mkdir(parents=True, exist_ok=True)
            profil_yolu.write_text(profil_notu(profil, degerler), encoding="utf-8")

    ayarlari_birlestir(hedef, args.kuru, rapor)
    skilleri_bagla(hedef, args.kuru, rapor)
    skilleri_bagla(hedef, args.kuru, rapor, ".agents")
    agents_bagla(hedef, args.kuru, rapor)

    if not args.kuru:
        for yol in list((hedef / ".beyin/hooks").glob("*")) + list((hedef / ".beyin/scripts").glob("*.sh")):
            if yol.is_file():
                yol.chmod(yol.stat().st_mode | 0o111)

    if args.codex:
        rapor.append("CODEX ~/.codex/hooks.json (beyin hook'ları eklenir, diğerleri korunur)")
        if not args.kuru:
            sonuc = subprocess.run([sys.executable, str(hedef / ".beyin/scripts/codex_kur.py")],
                                   capture_output=True, text=True)
            rapor.append("      " + (sonuc.stdout.strip() or sonuc.stderr.strip()).replace("\n", "\n      "))

    print("\n".join(rapor))
    if atlanan:
        print(f"\nATLANAN ({len(atlanan)}; hedefte zaten var, dokunulmadı):")
        print("\n".join(f"  {a}" for a in atlanan))
    if not args.kuru:
        kalan = []
        for goreli in sablon_dosyalari():
            yol = hedef / goreli
            if goreli.as_posix() in atlanan or yol.suffix not in METIN_UZANTILARI:
                continue
            if YER_TUTUCU.search(yol.read_text(encoding="utf-8", errors="ignore")):
                kalan.append(goreli.as_posix())
        print("\nYER TUTUCU KONTROLÜ: " + ("temiz" if not kalan else "KALDI → " + ", ".join(kalan)))
        return 1 if kalan else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

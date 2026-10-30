#!/usr/bin/env python3
"""Hata defteri: hataları tek kayıtta topla, tekrarı bul, onaylı çözüm öner.

Üç kaynak aynı kayda düşer (`.state/hata-olaylari.jsonl`, satır başına bir olay):
- arac: başarısız araç çağrısı (Claude PostToolUseFailure, Codex PostToolUse);
  `.beyin/hooks/hata-yakalayici.py` yazar.
- davranis: Kullanıcının asistanı düzelttiği an. Oturum sonunda flush özetinin
  `DUZELTMELER:` bloğundan gelir; istemdeki düzeltme cümlesi ayrıca
  `davranis-sinyal` olarak sayılır (öneri üretmez, yalnız rapor).
- hook: `hata_sayaci.kaydet` ile yutulan hook içi istisnalar.

İçerik saklanmaz: komut çıktısı, istem metni ya da istisna mesajı yok. `imza`
normalize edilmiş kısa sınıftır, `ozet` maskelenmiş ve 120 karakterle sınırlıdır.

Çözüm otomatik uygulanmaz (öneri + kullanıcı onayı). Analiz
tekrar edenleri `850-hafiza/hata-defteri.md` notuna "Onay bekleyen" olarak
yazar; `onayla` ile uygulanan çözüm kaydedilir, aynı imza sonra yeniden görülürse
"Tekrarladı" bölümüne düşer; `reddet` edilen bir daha önerilmez.

Kullanım:
  hata_defteri.py rapor
  hata_defteri.py analiz
  hata_defteri.py onayla IMZA --cozum "ne yapıldı, hangi dosya"
  hata_defteri.py reddet IMZA [--neden "..."]
  hata_defteri.py kaydet --tur davranis --imza davranis:baglam:ornek --ozet "..."
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True

try:
    import _portalock
except Exception:  # pragma: no cover - portalock her zaman yanında durur
    _portalock = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).resolve().parent
# BEYIN_HATA_STATE_DIR yalnız testler ve kuru koşu içindir.
STATE_DIR = Path(os.environ.get("BEYIN_HATA_STATE_DIR") or SCRIPT_DIR / ".state")
VAULT_ROOT = SCRIPT_DIR.parent.parent
OLAY_DOSYASI = "hata-olaylari.jsonl"
KARAR_DOSYASI = "hata-kararlari.json"
OZET_DOSYASI = "hata-defteri-ozet.txt"
DEFTER = "850-hafiza/hata-defteri.md"

TURLER = ("arac", "davranis", "davranis-sinyal", "hook")
# Öneri eşiği, 30 günlük pencerede. Davranış hatası pahalıdır (Kullanıcının
# zamanı), araç hatası çoğu zaman tek seferlik gürültüdür.
ESIK = {"arac": 3, "davranis": 2, "hook": 2}
PENCERE_GUN = 30
OZET_SINIRI = 120
# flush istemindeki kategori sözlüğü, kalite_gunlugu.REPAIR_REASONS ile aynı.
KATEGORILER = ("olgu", "baglam", "kisit", "test", "arac", "guvenlik", "eskime", "anlatim", "diger")

# Çıkış kodu 1'i "bulunamadı" anlamında kullanan komutlar: hata değil, cevap.
_SESSIZ_CIKIS_1 = frozenset({"grep", "rg", "egrep", "fgrep", "ugrep", "diff", "cmp", "test", "[",
                             "pgrep", "which", "command", "type", "git-diff"})
_KOMUT_ONEKLERI = frozenset({"sudo", "timeout", "time", "env", "nohup", "exec", "command", "uv",
                             "run", "nice"})


# --------------------------------------------------------------------------- yardımcılar

def _simdi() -> float:
    return time.time()


def _tarih(epoch: float) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(epoch))


def _kebab(text: str, sinir: int = 40) -> str:
    tablo = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    text = text.translate(tablo).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:sinir].strip("-") or "bilinmiyor"


_YEDEK_MASKELER = (
    (re.compile(r"(?i)\b(sk|pk|ghp|gho|xox[abp]|glpat|AKIA)[-_A-Za-z0-9]{12,}"), "[MASKE:anahtar]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[MASKE:eposta]"),
    (re.compile(r"(?i)(token|secret|password|parola|sifre|api[_-]?key)\s*[=:]\s*\S+"), r"\1=[MASKE]"),
    (re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b"), "[MASKE:uzun]"),
)


def maskele(text: str, sinir: int = OZET_SINIRI) -> str:
    """Tek satır, maskeli, en fazla `sinir` karakter."""
    text = " ".join(str(text or "").split())
    for desen, yerine in _YEDEK_MASKELER:
        text = desen.sub(yerine, text)
    home = str(Path.home())
    text = text.replace(home, "~")
    return text[:sinir]


def _kilitli(hedef: Path, islem):
    hedef.parent.mkdir(parents=True, exist_ok=True)
    if _portalock is None:
        return islem()
    kilit = hedef.with_suffix(hedef.suffix + ".lock")
    with kilit.open("a", encoding="utf-8") as tutamak, _portalock.exclusive(tutamak):
        return islem()


def _json_oku(hedef: Path) -> dict[str, Any]:
    try:
        veri = json.loads(hedef.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return veri if isinstance(veri, dict) else {}


def _atomik_yaz(hedef: Path, metin: str) -> None:
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.name}.{os.getpid()}.tmp")
    try:
        gecici.write_text(metin, encoding="utf-8")
        os.replace(gecici, hedef)
    finally:
        gecici.unlink(missing_ok=True)


# --------------------------------------------------------------------------- kayıt

def kaydet(tur: str, imza: str, *, istemci: str = "bilinmiyor", oturum: str = "",
           arac: str = "", kategori: str = "", ozet: str = "", kaynak: str = "",
           state_dir: Path = STATE_DIR, now: float | None = None) -> dict | None:
    """Bir hata olayı ekle. Asla istisna fırlatmaz; başarısızlıkta None döner."""
    try:
        if tur not in TURLER or not imza:
            return None
        olay = {
            "zaman": now if now is not None else _simdi(),
            "tur": tur,
            "imza": imza[:120],
            "istemci": istemci or "bilinmiyor",
            "oturum": "".join(c for c in str(oturum) if c.isalnum() or c == "-")[:64],
            "arac": str(arac)[:40],
            "kategori": kategori if kategori in KATEGORILER else "",
            "ozet": maskele(ozet),
            "kaynak": str(kaynak)[:60],
        }
        hedef = state_dir / OLAY_DOSYASI

        def ekle() -> None:
            with hedef.open("a", encoding="utf-8") as akis:
                akis.write(json.dumps(olay, ensure_ascii=False, sort_keys=True) + "\n")

        _kilitli(hedef, ekle)
        return olay
    except Exception:
        return None


def olaylar(state_dir: Path = STATE_DIR) -> list[dict]:
    try:
        satirlar = (state_dir / OLAY_DOSYASI).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    sonuc = []
    for satir in satirlar:
        try:
            olay = json.loads(satir)
        except ValueError:
            continue
        if isinstance(olay, dict) and olay.get("imza") and olay.get("tur") in TURLER:
            sonuc.append(olay)
    return sonuc


# --------------------------------------------------------------------------- imza üretimi

def _komutlar(komut: str) -> list[str]:
    """`cd x && FOO=1 timeout 5 python3 -m pytest` → `["python3"]` (cd ve önekler atlanır)."""
    adlar = []
    for aday in re.split(r"&&|\|\||;|\||\n", komut or ""):
        kelimeler = aday.split()
        while kelimeler and (re.match(r"^\w+=", kelimeler[0]) or kelimeler[0] in _KOMUT_ONEKLERI
                             or re.match(r"^-{1,2}\w", kelimeler[0]) or kelimeler[0].isdigit()):
            kelimeler.pop(0)
        if kelimeler and kelimeler[0] not in ("cd", "echo", "printf", "then", "do", "fi", "done"):
            ad = Path(kelimeler[0].strip("'\"()")).name[:30]
            if ad and re.match(r"^[\w.+-]+$", ad):
                adlar.append(ad)
    return adlar


def _komut_adi(komut: str, hata: str = "") -> str:
    """Zincirde hatayı veren komut: hata metni `ad:` ile başlıyorsa o, Python izi varsa
    python, yoksa zincirin son komutu (&& zincirinde çoğu zaman düşen odur)."""
    adlar = _komutlar(komut)
    if not adlar:
        return "bilinmiyor"
    for satir in hata.splitlines():
        m = re.match(r"^(?:\S*/)?([\w.+-]+): ", satir.strip())
        if m and m.group(1) in adlar:
            return m.group(1)
    if "Traceback" in hata or re.search(r"(?m)^\w+Error\b", hata):
        python = [a for a in adlar if a.startswith("python") or a in ("uv", "pytest")]
        if python:
            return python[-1]
    return adlar[-1]


def _bash_sinifi(metin: str) -> str:
    if m := re.search(r"No module named '?([\w.]+)", metin):
        return f"modul_yok:{m.group(1).split('.')[0]}"
    if re.search(r"command not found|komut bulunamadı", metin):
        return "komut_yok"
    if re.search(r"No such file or directory|cannot access|does not exist", metin):
        return "yol_yok"
    if re.search(r"Permission denied|Operation not permitted", metin):
        return "izin"
    if re.search(r"unrecognized option|invalid option|invalid value|unknown option|"
                 r"unexpected argument|usage:", metin, re.I):
        return "gecersiz_secenek"
    if m := re.search(r"^(\w+(?:Error|Exception))\b", metin, re.M):
        return f"istisna:{m.group(1)}"
    if re.search(r"timed out|timeout", metin, re.I):
        return "zaman_asimi"
    if re.search(r"syntax error|parse error", metin, re.I):
        return "sozdizimi"
    if re.search(r"(?m)^(FAILED|ERROR)\b|\d+ failed|FAILED \(", metin):
        return "test_basarisiz"
    return ""


def _cikis_kodu(metin: str) -> int | None:
    m = re.search(r"Exit code (\d+)", metin)
    return int(m.group(1)) if m else None


def ozet_satiri_sec(hata: str) -> str:
    """İnsan için tek anlamlı satır: Python izinde son satır, yoksa ilk hata satırı
    (`fatal:`, `error:`, `…Error`), o da yoksa ilk gerçek satır. Komutun normal çıktısı
    hatadan önce gelebilir (01.10.2026: `git branch` listesi özete düşüyordu)."""
    satirlar = [s.strip() for s in (hata or "").splitlines() if s.strip()]
    satirlar = [s for s in satirlar if not re.match(r"^(Exit code \d+|exited \d+ in)", s)]
    if not satirlar:
        return ""
    if any(s.startswith("Traceback") for s in satirlar):
        return satirlar[-1]
    hata_satiri = re.compile(r"^(?:fatal|error)\b|^\w*(?:Error|Exception)\b", re.I)
    return next((s for s in satirlar if hata_satiri.match(s)), satirlar[0])


def arac_imzasi(arac: str, girdi: Any, hata: str, cikis: int | None = None) -> str | None:
    """Araç hatasını kısa bir sınıfa indir. Gürültüyse None."""
    arac = str(arac or "bilinmiyor")
    metin = str(hata or "")
    if re.search(r"doesn't want to proceed|user (?:rejected|denied)|interrupted by user|"
                 r"Request interrupted", metin, re.I):
        return None  # kullanıcı reddi/kesmesi araç hatası değil
    kod = cikis if cikis is not None else _cikis_kodu(metin)
    if arac in ("Bash", "exec_command", "shell", "local_shell", "unified_exec"):
        komut = ""
        if isinstance(girdi, dict):
            komut = str(girdi.get("command") or girdi.get("cmd") or "")
            if isinstance(girdi.get("command"), list):
                komut = " ".join(map(str, girdi["command"]))
        ad = _komut_adi(komut, metin)
        sinif = _bash_sinifi(metin)
        if not sinif and kod == 1 and ad in _SESSIZ_CIKIS_1:
            return None
        if not sinif and kod == 124:
            sinif = "zaman_asimi"
        if not sinif:
            sinif = f"exit{kod}" if kod is not None else "exit?"
        return f"Bash:{ad}:{sinif}"
    if arac in ("Edit", "MultiEdit", "Write", "NotebookEdit", "apply_patch"):
        if re.search(r"has not been read|read it first|Read it first", metin, re.I):
            return f"{arac}:okunmadan_yazma"
        if re.search(r"modified since|has been modified|changed since", metin, re.I):
            return f"{arac}:dosya_degismis"
        if re.search(r"Found \d+ matches|multiple (?:matches|occurrences)|not unique", metin, re.I):
            return f"{arac}:coklu_eslesme"
        if re.search(r"not found|No match|did not match|failed to find", metin, re.I):
            return f"{arac}:eslesme_yok"
    if arac == "Read":
        if re.search(r"does not exist|ENOENT|No such file", metin, re.I):
            return "Read:dosya_yok"
        if re.search(r"exceeds|too large|maximum", metin, re.I):
            return "Read:cok_buyuk"
    if re.search(r"does not exist|No such file|ENOENT", metin, re.I):
        return f"{arac}:yol_yok"
    if re.search(r"timed out|timeout", metin, re.I):
        return f"{arac}:zaman_asimi"
    if re.search(r"InputValidationError|invalid (?:input|param)", metin, re.I):
        return f"{arac}:gecersiz_girdi"
    ilk = re.sub(r"[\d/~._-]+", " ", metin.splitlines()[0] if metin.strip() else "")
    return f"{arac}:{_kebab(' '.join(ilk.split()[:4]), 30)}"


# İstemdeki düzeltme cümlesi. Bilerek dar: "hayır şunu kastettim" gibi netleştirme,
# "devam et" gibi akış komutu düzeltme değildir.
_DUZELTME_DESENLERI = (
    ("bir-daha", r"\bbir daha\b[^.?!\n]{0,40}\b(yapma|etme|olmasın|olmasin|yazma|kullanma|sorma)"),
    ("boyle-yapma", r"\b(bunu|böyle|boyle|öyle|oyle)\s+(yapma|yazma|etme)\b"),
    ("istemiyorum", r"\b(böyle|boyle|bunu|öyle|oyle)\s+istemiyorum\b"),
    ("demedim", r"\b(ben )?(bunu|öyle|oyle|böyle|boyle)?\s*demedim\b"),
    ("kac-kere", r"\b(kaç|kac) (kere|kez|defa)\b[^?\n]{0,40}(söyle|soyle|dedim)"),
    ("yine-ayni", r"\b(yine|gene|hep) (aynı|ayni) (hata|şey|sey)"),
    ("soylemistim", r"\b(söylemiştim|soylemistim|demiştim|demistim)\b"),
    ("kurallara-ekle", r"\bkurallar(a|ına|ina) (ekle|yaz)\b"),
    ("bundan-sonra", r"\bbundan sonra\b[^.?!\n]{0,60}\b(yapma|etme|yaz|kullan|sor|söyle|soyle)"),
)


def duzeltme_sinyali(istem: str) -> str | None:
    metin = (istem or "").replace("İ", "i").replace("I", "ı").lower()
    for anahtar, desen in _DUZELTME_DESENLERI:
        if re.search(desen, metin):
            return anahtar
    return None


# flush özetinin sonundaki blok:
# DUZELTMELER:
# - baglam | yanlis-klasor | Vault dışındaki kodu vault'ta aradı; proje kodu ~/Projects altında.
_DUZELTME_BLOK = re.compile(r"\n*^DUZELTMELER:[ \t]*(?P<govde>(?:yok)?[ \t]*(?:\n[ \t]*-[^\n]*)*)\s*\Z",
                            re.M)


def duzeltmeleri_ayir(ozet: str) -> tuple[str, list[dict]]:
    """Özetten DUZELTMELER bloğunu ayır; (temiz özet, düzeltmeler)."""
    m = _DUZELTME_BLOK.search(ozet or "")
    if not m:
        return ozet, []
    kalan = ozet[: m.start()].rstrip()
    liste = []
    for satir in m.group("govde").splitlines():
        satir = satir.strip().lstrip("-").strip()
        parcalar = [p.strip() for p in satir.split("|")]
        if len(parcalar) < 3 or not parcalar[2]:
            continue
        kategori = parcalar[0] if parcalar[0] in KATEGORILER else "diger"
        liste.append({"kategori": kategori, "anahtar": _kebab(parcalar[1]),
                      "ders": parcalar[2]})
    return kalan, liste[:5]


def duzeltme_istemi(state_dir: Path = STATE_DIR) -> str:
    """flush istemine eklenecek talimat; tutarlı imza için bilinen anahtarlar da verilir."""
    bilinen = sorted({o["imza"].split(":", 2)[2] for o in olaylar(state_dir)
                      if o["tur"] == "davranis" and o["imza"].count(":") >= 2})[:25]
    ipucu = (f"\nDaha önce kullanılan anahtarlar (aynı hataysa aynısını kullan): {', '.join(bilinen)}"
             if bilinen else "")
    return f"""
Beş bölümden sonra, en sona ayrı bir satırda `DUZELTMELER:` bloğu yaz. Bu blok, kullanıcının
asistanın davranışını düzelttiği ya da asistanın hatası yüzünden işi yeniden anlatmak zorunda
kaldığı anları listeler. Her satır: `- kategori | kisa-anahtar | tek cümlelik ders`.
Kategori şunlardan biri: {", ".join(KATEGORILER)}. kisa-anahtar ASCII kebab-case, en fazla
beş kelime. Böyle bir an yoksa yalnız `DUZELTMELER: yok` yaz. Akış komutları ("devam et"),
iş kararları ve netleştirmeler düzeltme değildir.{ipucu}
"""


# --------------------------------------------------------------------------- kararlar

def kararlar(state_dir: Path = STATE_DIR) -> dict[str, dict]:
    return {k: v for k, v in _json_oku(state_dir / KARAR_DOSYASI).items() if isinstance(v, dict)}


def _karar_yaz(imza: str, durum: str, not_: str, state_dir: Path, now: float | None) -> dict:
    hedef = state_dir / KARAR_DOSYASI

    def guncelle() -> dict:
        veri = _json_oku(hedef)
        kayit = {"durum": durum, "zaman": now if now is not None else _simdi(), "not": not_[:300]}
        veri[imza] = kayit
        _atomik_yaz(hedef, json.dumps(veri, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
        return kayit

    return _kilitli(hedef, guncelle)


def onayla(imza: str, cozum: str, state_dir: Path = STATE_DIR, now: float | None = None) -> dict:
    if not cozum.strip():
        raise ValueError("--cozum boş olamaz: ne yapıldığı ve hangi dosya")
    return _karar_yaz(imza, "uygulandi", cozum, state_dir, now)


def reddet(imza: str, neden: str = "", state_dir: Path = STATE_DIR, now: float | None = None) -> dict:
    return _karar_yaz(imza, "reddedildi", neden, state_dir, now)


# --------------------------------------------------------------------------- analiz

_ARAC_IPUCLARI = {
    "modul_yok": "Modül bu Python'da yok. Kalıcı çözüm: doğru çalıştırıcıyı kurala yaz "
                 "(ör. `python3 -m unittest`, `uv run`) ya da modülü kur.",
    "komut_yok": "Komut kurulu değil. Kurala 'X yok, Y kullan' yaz ya da aracı kur.",
    "yol_yok": "Yol tahmin ediliyor. Kalıcı çözüm: önce `ls`/`find` ile doğrula; sık tekrar "
               "ediyorsa doğru yolu ilgili skill'e ya da kurala yaz.",
    "gecersiz_secenek": "Seçenek ezberden yazılıyor. Kalıcı çözüm: `--help` ile doğrula; "
                        "doğru kullanımı ilgili skill'e ekle.",
    "izin": "İzin/sandbox sınırı. Kalıcı çözüm: kurala sınırı yaz ya da ayarı düzelt.",
    "zaman_asimi": "Komut zaman aşımına uğruyor. Arka planda çalıştır ya da daha dar kapsam kullan.",
    "sozdizimi": "Kabuk/kod sözdizimi hatası. Uzun komutu betik dosyasına taşı.",
    "test_basarisiz": "Tekrarlayan test kırılması. Kök nedeni `debugging` skill'iyle bul, "
                      "gerekirse regresyon testi ekle.",
    "okunmadan_yazma": "Dosya okunmadan düzenleniyor. Kalıcı çözüm: davranış kuralı "
                       "'düzenlemeden önce oku' zaten var; tekrarlıyorsa PreToolUse uyarısı ekle.",
    "dosya_degismis": "Dosya okunduktan sonra değişmiş (başka ajan/hook). Tek yazar kuralını "
                      "kontrol et; düzenlemeden hemen önce yeniden oku.",
    "eslesme_yok": "Edit metni dosyayla eşleşmiyor. Kalıcı çözüm: düzenlemeden önce hedef kesiti "
                   "yeniden oku; satır numarası önekini kopyalama.",
    "coklu_eslesme": "Edit metni tekil değil. Daha uzun bağlam ver ya da replace_all kullan.",
    "dosya_yok": "Olmayan dosya okunuyor. Yolu önce doğrula.",
    "cok_buyuk": "Dosya tek seferde okunamayacak kadar büyük. offset/limit ya da grep kullan.",
    "gecersiz_girdi": "Araç şeması yanlış kullanılıyor. Şemayı yükleyip doğru parametreyle çağır.",
}


def oneri(grup: dict) -> tuple[str, str, str]:
    """(çözüm türü, hedef dosya, öneri metni) — deterministik."""
    tur, imza = grup["tur"], grup["imza"]
    if tur == "davranis":
        ders = grup["ozetler"][-1] if grup["ozetler"] else imza
        return ("kural", "850-hafiza/davranis-kurallari.md",
                f"Kural taslağı: {ders} **neden:** {grup['sayi']} kez düzeltildi ({grup['son_tarih']}).")
    if tur == "hook":
        return ("kod", f".beyin/scripts/ ({grup['arac'] or imza})",
                "Hook içi istisna tekrar ediyor. `debugging` skill'iyle kök nedeni bul, düzelt, "
                "regresyon testi ekle.")
    sinif = imza.split(":")[-1]
    anahtar = next((k for k in _ARAC_IPUCLARI if sinif.startswith(k)), "")
    metin = _ARAC_IPUCLARI.get(anahtar, "Aynı araç hatası tekrar ediyor. Kök nedeni bul; "
                                          "önleyici kural, skill adımı ya da PreToolUse hook'u öner.")
    hedef = ("850-hafiza/davranis-kurallari.md" if anahtar in
             ("modul_yok", "komut_yok", "izin", "okunmadan_yazma", "eslesme_yok")
             else ".beyin/skills/ veya .beyin/hooks/")
    return ("kural" if hedef.startswith("850") else "skill/hook", hedef, metin)


def analiz(state_dir: Path = STATE_DIR, now: float | None = None) -> dict:
    now = now if now is not None else _simdi()
    alt = now - PENCERE_GUN * 86400
    yedi = now - 7 * 86400
    gruplar: dict[str, dict] = {}
    sinyal = 0
    tum = olaylar(state_dir)
    for olay in tum:
        zaman = float(olay.get("zaman") or 0)
        if olay["tur"] == "davranis-sinyal":
            sinyal += zaman >= alt
            continue
        g = gruplar.setdefault(olay["imza"], {
            "tur": olay["tur"], "imza": olay["imza"], "sayi": 0, "sayi_7": 0, "ilk_zaman": zaman,
            "son_zaman": 0.0, "arac": olay.get("arac", ""), "istemciler": set(), "ozetler": [],
            "zamanlar": []})
        g["zamanlar"].append(zaman)
        if zaman < alt:
            continue
        g["sayi"] += 1
        g["sayi_7"] += zaman >= yedi
        g["son_zaman"] = max(g["son_zaman"], zaman)
        g["istemciler"].add(olay.get("istemci", "bilinmiyor"))
        if olay.get("ozet") and olay["ozet"] not in g["ozetler"]:
            g["ozetler"] = (g["ozetler"] + [olay["ozet"]])[-3:]
    for g in gruplar.values():
        pencere = [z for z in g["zamanlar"] if z >= alt]
        g["ilk_tarih"] = _tarih(min(pencere)) if pencere else "?"
        g["son_tarih"] = _tarih(g["son_zaman"]) if g["son_zaman"] else "?"
        g["istemciler"] = sorted(g["istemciler"])
    liste = list(gruplar.values())

    karar = kararlar(state_dir)
    sonuc: dict[str, Any] = {"zaman": now, "bekleyen": [], "uygulanan": [], "tekrarladi": [],
                             "reddedilen": [], "olay_sayisi": sum(g["sayi"] for g in liste),
                             "sinyal": sinyal, "gruplar": len(liste)}
    for g in sorted(liste, key=lambda x: (-x["sayi"], x["imza"])):
        k = karar.get(g["imza"])
        g.pop("zamanlar", None)
        if k:
            g["karar"] = k
            if k["durum"] == "reddedildi":
                sonuc["reddedilen"].append(g)
                continue
            sonra = [o for o in tum if o["imza"] == g["imza"] and float(o["zaman"]) > k["zaman"]]
            g["sonra"] = len(sonra)
            (sonuc["tekrarladi"] if sonra else sonuc["uygulanan"]).append(g)
            continue
        esik = ESIK.get(g["tur"], 2)
        if g["sayi"] >= esik:
            g["cozum_turu"], g["hedef"], g["oneri_metni"] = oneri(g)
            sonuc["bekleyen"].append(g)
    return sonuc


# --------------------------------------------------------------------------- çıktı

def _grup_satiri(g: dict) -> str:
    istemci = ", ".join(g.get("istemciler", [])) or "?"
    yedi = f" ({g.get('sayi_7', 0)} son 7 gün)"
    return f"`{g['imza']}` — {g['sayi']} kez / 30 gün{yedi}, son {g['son_tarih']}, {istemci}"


def defter_markdown(sonuc: dict) -> str:
    satirlar = [
        "# Hata Defteri",
        "",
        "> ⬆️ [[kontrol-paneli]] · tekrar eden hatalar ve onay bekleyen kalıcı çözümler",
        "",
        "Bu not `.beyin/scripts/hata_defteri.py analiz` tarafından üretilir; **elle düzenleme**, "
        "her analizde yeniden yazılır. Karar vermek için `hata-defteri` skill'ini kullan "
        "(\"hata defterine bak\"): onaylanan çözüm uygulanır ve `hata_defteri.py onayla IMZA "
        "--cozum ...` ile kapanır; istenmeyen `reddet` ile bir daha önerilmez.",
        "",
        f"Son analiz: {_tarih(sonuc['zaman'])} · 30 günde {sonuc['olay_sayisi']} olay, "
        f"{sonuc['gruplar']} imza, {sonuc['sinyal']} düzeltme sinyali.",
        "",
        "## Tekrarladı",
        "",
    ]
    if sonuc["tekrarladi"]:
        for g in sonuc["tekrarladi"]:
            satirlar += [f"- {_grup_satiri(g)}. **Çözümden sonra {g['sonra']} kez görüldü**; "
                         f"uygulanan çözüm ({_tarih(g['karar']['zaman'])}): {g['karar']['not']}"]
    else:
        satirlar.append("Yok. Uygulanan çözümlerin hiçbiri sonradan tekrarlamadı.")
    satirlar += ["", "## Onay bekleyen", ""]
    if sonuc["bekleyen"]:
        for g in sonuc["bekleyen"]:
            ornek = "; ".join(g["ozetler"][-2:]) or "—"
            satirlar += [f"### {g['imza']}", "",
                         f"- **Tür:** {g['tur']} · {_grup_satiri(g)}",
                         f"- **Örnek:** {ornek}",
                         f"- **Önerilen çözüm ({g['cozum_turu']}, hedef `{g['hedef']}`):** "
                         f"{g['oneri_metni']}", ""]
    else:
        satirlar += ["Yok.", ""]
    satirlar += ["## Uygulanan", ""]
    if sonuc["uygulanan"]:
        satirlar += [f"- `{g['imza']}` — {_tarih(g['karar']['zaman'])}: {g['karar']['not']}"
                     for g in sonuc["uygulanan"]]
    else:
        satirlar.append("Henüz yok.")
    satirlar += ["", "## Reddedilen", ""]
    if sonuc["reddedilen"]:
        satirlar += [f"- `{g['imza']}` — {g['karar']['not'] or 'gerekçe yok'}"
                     for g in sonuc["reddedilen"]]
    else:
        satirlar.append("Yok.")
    satirlar += [
        "", "## İlgili", "",
        "- [[davranis-kurallari]] — davranış hatasının kalıcı çözümü çoğu zaman orada bir kural.",
        "- [[araclar-ve-kaynaklar-indeksi]] — hook ve skill envanteri; yeni önleyici oraya da yazılır.",
        "",
    ]
    return "\n".join(satirlar)


def ozet_satiri(sonuc: dict) -> str:
    b, t = len(sonuc["bekleyen"]), len(sonuc["tekrarladi"])
    if not b and not t:
        return ""
    parca = [f"{b} onay bekleyen çözüm"] if b else []
    if t:
        parca.append(f"{t} çözümü tutmayan tekrar")
    return (f"{DEFTER}: {', '.join(parca)}. Uygun bir anda kullanıcıya kısaca söyle; "
            "\"hata defterine bak\" derse hata-defteri skill'ini kullan.")


def defteri_yaz(sonuc: dict, vault_root: Path = VAULT_ROOT, state_dir: Path = STATE_DIR) -> bool:
    """Notu ve açılış satırını yaz. Not değişmediyse dokunmaz."""
    import vault_write

    metin = defter_markdown(sonuc)
    yol = vault_root / DEFTER
    try:
        onceki = yol.read_text(encoding="utf-8")
    except OSError:
        onceki = None
    # "Son analiz" satırı her seferinde değişir; yalnız o fark ediyorsa yazma.
    def govde(t: str | None) -> str | None:
        return None if t is None else re.sub(r"(?m)^Son analiz: .*$", "", t)

    _atomik_yaz(state_dir / OZET_DOSYASI, ozet_satiri(sonuc) + "\n")
    if govde(onceki) == govde(metin):
        return False
    vault_write.write(vault_root, DEFTER, metin,
                      expected=vault_write.digest(onceki) if onceki is not None else "new")
    return True


def rapor(state_dir: Path = STATE_DIR, now: float | None = None) -> str:
    sonuc = analiz(state_dir, now)
    satirlar = [f"hata defteri: 30 günde {sonuc['olay_sayisi']} olay, {sonuc['gruplar']} imza, "
                f"{sonuc['sinyal']} düzeltme sinyali"]
    for baslik, anahtar in (("TEKRARLADI", "tekrarladi"), ("BEKLEYEN", "bekleyen"),
                            ("UYGULANAN", "uygulanan"), ("REDDEDILEN", "reddedilen")):
        for g in sonuc[anahtar]:
            satirlar.append(f"{baslik:<11} {g['sayi']:>3}  {g['imza']}")
    return "\n".join(satirlar)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = parser.add_subparsers(dest="komut", required=True)
    alt.add_parser("rapor")
    alt.add_parser("analiz")
    o = alt.add_parser("onayla")
    o.add_argument("imza")
    o.add_argument("--cozum", required=True)
    r = alt.add_parser("reddet")
    r.add_argument("imza")
    r.add_argument("--neden", default="")
    k = alt.add_parser("kaydet")
    k.add_argument("--tur", choices=TURLER, required=True)
    k.add_argument("--imza", required=True)
    k.add_argument("--ozet", default="")
    k.add_argument("--kategori", default="")
    k.add_argument("--istemci", default="elle")
    args = parser.parse_args(argv)

    if args.komut == "rapor":
        print(rapor())
    elif args.komut == "analiz":
        sonuc = analiz()
        yazildi = defteri_yaz(sonuc)
        print(f"{len(sonuc['bekleyen'])} bekleyen, {len(sonuc['tekrarladi'])} tekrarladı; "
              f"defter {'güncellendi' if yazildi else 'değişmedi'}")
    elif args.komut == "onayla":
        onayla(args.imza, args.cozum)
        print(f"uygulandı: {args.imza}")
    elif args.komut == "reddet":
        reddet(args.imza, args.neden)
        print(f"reddedildi: {args.imza}")
    elif args.komut == "kaydet":
        olay = kaydet(args.tur, args.imza, istemci=args.istemci, kategori=args.kategori,
                      ozet=args.ozet, kaynak="elle")
        print("kaydedildi" if olay else "kaydedilemedi")
        return 0 if olay else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

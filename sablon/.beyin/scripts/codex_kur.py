#!/usr/bin/env python3
"""Beyin hook'larını Codex'e bağlar (~/.codex/hooks.json).

Codex proje klasöründeki hook dosyasını okumaz; hook'lar CODEX_HOME altında globaldir. Bu
yüzden komutlar mutlak yol taşır ve hook'lar vault dışındaki oturumlarda kendiliğinden
susar (lib.sh ve Python hook'ları çalışma klasörüne bakar). Yalnız bu script'in daha önce
eklediği girdiler değiştirilir; kullanıcının diğer hook'ları korunur.

Kullanım:
  python3 .beyin/scripts/codex_kur.py            # vault = bu script'in iki üstü
  python3 .beyin/scripts/codex_kur.py --kuru     # yazmadan göster
  python3 .beyin/scripts/codex_kur.py --kaldir   # yalnız beyin girdilerini sil

Kurulumdan sonra Codex'i vault içinde açıp `/hooks` ile yeni hook'ları güvenilir işaretle;
işaretlenmeyen hook çalışmaz.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import tempfile
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
ISARET = "/.beyin/hooks/"

# olay -> [(dosya, zaman aşımı, durum mesajı, bağlam sınırı)]
# SessionStart argümansız çalışır ("hepsi"); Codex sınırı 23.000'lik iç bütçenin üstünde
# tutulur ki kırpma görünür notla script'te olsun. Codex SessionEnd'i 3 sn ile sınırlar;
# hook işi hemen arka plana attığı için yeterli. Codex'te PostToolUseFailure yok, hata
# yakalayıcı PostToolUse girdisinden okur.
HOOKS = {
    "SessionStart": [("session-start.sh", 15, "Beyin hafıza köprüsü", 24_000)],
    "UserPromptSubmit": [("prompt-counter.sh", 5, "Beyin mesaj sayacı", None),
                         ("baglam-bekcisi.py", 5, "Beyin bağlam bekçisi", None),
                         ("hata-yakalayici.py", 5, "Beyin hata defteri", None)],
    "PostToolUse": [("baglam-bekcisi.py", 5, "Beyin bağlam bekçisi", None),
                    ("hata-yakalayici.py", 5, "Beyin hata defteri", None)],
    "PreCompact": [("pre-compact.sh", 10, "Beyin sıkıştırma özeti", None)],
    "SessionEnd": [("session-end.sh", 3, "Beyin oturum özeti", None)],
}


def codex_home() -> Path:
    ozel = os.environ.get("CODEX_HOME")
    return Path(ozel).expanduser().resolve() if ozel else Path.home() / ".codex"


def komut(dosya: str) -> str:
    yol = VAULT / ".beyin" / "hooks" / dosya
    return ("python3 " if dosya.endswith(".py") else "") + shlex.quote(str(yol))


def bizim(girdi: object) -> bool:
    return isinstance(girdi, dict) and ISARET in str(girdi.get("command", "")).replace("\\", "/")


def temizle(hooks: dict) -> None:
    for olay, gruplar in list(hooks.items()):
        if not isinstance(gruplar, list):
            continue
        kalan = []
        for grup in gruplar:
            if isinstance(grup, dict) and isinstance(grup.get("hooks"), list):
                girdiler = [g for g in grup["hooks"] if not bizim(g)]
                if not girdiler:
                    continue
                grup = {**grup, "hooks": girdiler}
            kalan.append(grup)
        if kalan:
            hooks[olay] = kalan
        else:
            hooks.pop(olay)


def olustur(mevcut: dict, kaldir: bool) -> dict:
    hooks = mevcut.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("HATA: hooks.json içindeki 'hooks' bir nesne değil; elle bak.")
    temizle(hooks)
    if kaldir:
        return mevcut
    for olay, liste in HOOKS.items():
        for dosya, sure, mesaj, sinir in liste:
            girdi = {"type": "command", "command": komut(dosya), "timeout": sure, "statusMessage": mesaj}
            if sinir:
                girdi["additionalContextLimit"] = sinir
            hooks.setdefault(olay, []).append({"hooks": [girdi]})
    return mevcut


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kuru", action="store_true")
    ap.add_argument("--kaldir", action="store_true")
    args = ap.parse_args()

    hedef = codex_home() / "hooks.json"
    try:
        mevcut = json.loads(hedef.read_text(encoding="utf-8"))
    except FileNotFoundError:
        mevcut = {}
    if not isinstance(mevcut, dict):
        raise SystemExit("HATA: hooks.json kökü nesne değil; elle bak.")
    yeni = olustur(mevcut, args.kaldir)
    metin = json.dumps(yeni, indent=2, ensure_ascii=False) + "\n"
    if args.kuru:
        print(metin)
        return 0
    hedef.parent.mkdir(parents=True, exist_ok=True)
    if hedef.exists():
        yedek = hedef.with_name("hooks.json.beyin-oncesi")
        if not yedek.exists():
            yedek.write_bytes(hedef.read_bytes())
    fd, gecici = tempfile.mkstemp(dir=hedef.parent, prefix=".hooks.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(metin)
    os.replace(gecici, hedef)
    adet = sum(len(v) for v in HOOKS.values())
    print(f"{hedef}: " + ("beyin girdileri kaldırıldı" if args.kaldir else f"{adet} beyin hook'u yazıldı"))
    if not args.kaldir:
        print("Sonraki adım: vault içinde `codex` aç, `/hooks` yaz ve yeni hook'ları güvenilir işaretle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sessizce yutulan hook hatalarını sayan küçük yardımcı.

`flush.py` ve `compile.py` içindeki bazı `except Exception` blokları
kasıtlı olarak hatayı yutar: hook sınırı hiçbir zaman çağıranı düşürmemeli. Ama
sessiz yutma, arızanın hiç görünmemesi demek. Bu modül o noktalarda çağrılır,
kaynak başına bir sayaç ve son görülme zamanını diske yazar — istisna
**mesajını değil**, sadece sınıf adını tutar (mesaj sır/içerik taşıyabilir).

Bu modülün kendisi asla dışarı istisna fırlatmaz: sayaç bozulsa da hook akışı
etkilenmemeli.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    import _portalock
except Exception:  # pragma: no cover - portalock her zaman yanında durur
    _portalock = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = SCRIPT_DIR / ".state"
DOSYA_ADI = "hata-sayaclari.json"


def _dosya_yolu(state_dir: Path) -> Path:
    return state_dir / DOSYA_ADI


def _simdi() -> str:
    return time.strftime("%d.%m.%Y %H:%M")


def _yukle(hedef: Path) -> dict[str, Any]:
    try:
        yuklenen = json.loads(hedef.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return yuklenen if isinstance(yuklenen, dict) else {}


def _atomik_yaz(hedef: Path, payload: dict[str, Any]) -> None:
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.name}.{os.getpid()}.tmp")
    try:
        gecici.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(gecici, hedef)
    finally:
        try:
            gecici.unlink()
        except FileNotFoundError:
            pass


def _deftere_yaz(kaynak: str, exc: BaseException, state_dir: Path) -> None:
    """Aynı olayı hata defterine de düşür; tekrar ederse kod düzeltmesi önerilir."""
    try:
        import hata_defteri

        hata_defteri.kaydet("hook", f"hook:{kaynak}:{type(exc).__name__}", arac=kaynak,
                            kaynak="hata_sayaci", state_dir=state_dir)
    except Exception:
        pass


def kaydet(
    kaynak: str, exc: BaseException, state_dir: Path = STATE_DIR
) -> None:
    """Kaynak başına hata sayacını artır. Asla istisna fırlatmaz."""
    try:
        hedef = _dosya_yolu(state_dir)
        hedef.parent.mkdir(parents=True, exist_ok=True)

        def _guncelle() -> None:
            payload = _yukle(hedef)
            kayit = payload.get(kaynak)
            if not isinstance(kayit, dict):
                kayit = {"sayi": 0}
            kayit["sayi"] = int(kayit.get("sayi", 0) or 0) + 1
            kayit["son"] = _simdi()
            kayit["son_tur"] = type(exc).__name__
            payload[kaynak] = kayit
            _atomik_yaz(hedef, payload)

        _deftere_yaz(kaynak, exc, state_dir)
        if _portalock is not None:
            lock_path = hedef.with_suffix(hedef.suffix + ".lock")
            try:
                with lock_path.open("a", encoding="utf-8") as lock:
                    with _portalock.exclusive(lock):
                        _guncelle()
                return
            except Exception:
                pass  # kilit alinamadi; kilitsiz de olsa yine de dene
        _guncelle()
    except Exception:
        # Bu sayaç bir tanılama yardımcısıdır; kendi hatası hiçbir çağıranı
        # etkilememeli.
        pass


def oku(state_dir: Path = STATE_DIR) -> dict[str, Any]:
    return _yukle(_dosya_yolu(state_dir))


def sifirla(state_dir: Path = STATE_DIR) -> None:
    try:
        _dosya_yolu(state_dir).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _tablo_yazdir(state_dir: Path) -> None:
    payload = oku(state_dir)
    if not payload:
        print("hata sayaci: kayit yok")
        return
    print(f"{'kaynak':<24} {'sayi':>5}  {'son gorulme':<16}  son tur")
    for kaynak, kayit in sorted(
        payload.items(), key=lambda item: -int(item[1].get("sayi", 0) or 0)
    ):
        if not isinstance(kayit, dict):
            continue
        print(
            f"{kaynak:<24} {int(kayit.get('sayi', 0) or 0):>5}  "
            f"{str(kayit.get('son', '?')):<16}  {kayit.get('son_tur', '?')}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sessiz hook hatalarinin sayaci")
    parser.add_argument("--sifirla", action="store_true", help="Sayaclari sifirla")
    args = parser.parse_args()

    if args.sifirla:
        sifirla(STATE_DIR)
        print("hata sayaci: sifirlandi")
        return

    _tablo_yazdir(STATE_DIR)


if __name__ == "__main__":
    main()

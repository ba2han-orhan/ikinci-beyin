#!/usr/bin/env python3
"""Hata yakalayıcı: başarısız araç çağrısını ve düzeltme cümlesini hata defterine yazar.

Olaylar (stdin'de hook girdisi):
- PostToolUseFailure (Claude): `error` alanı; kullanıcı kesmesi (`is_interrupt`) sayılmaz.
- PostToolUse (Codex): `tool_response` içindeki çıkış kodu / hata alanı; yanıt düz metinse
  (Codex 0.155) kod transcript'ten `tool_use_id` ile okunur. Başarılı çağrı sessiz.
- UserPromptSubmit (ikisi): istem bir davranış düzeltmesine benziyorsa `davranis-sinyal`
  yazar ve kural yazımını hatırlatır. Asıl davranış kaydı oturum sonunda flush'tan gelir.

Hiçbir zaman bloklamaz, hata fırlatmaz, istem ya da çıktı metni saklamaz (imza + maskeli
kısa özet). Kayıt ve analiz: `.beyin/scripts/hata_defteri.py`.
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def emit(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                             "additionalContext": text}}, ensure_ascii=False))


def _yanit_hatasi(yanit) -> tuple[str, int | None] | None:
    """Codex tool_response'undan (hata metni, çıkış kodu); başarılıysa None."""
    if isinstance(yanit, str):
        try:
            yanit = json.loads(yanit)
        except ValueError:
            metin = yanit
            if "Exit code" in metin or "exit code" in metin.lower():
                import re

                m = re.search(r"(?i)exit code:?\s*(\d+)", metin)
                kod = int(m.group(1)) if m else None
                return (metin[-2000:], kod) if kod not in (None, 0) else None
            return None
    if not isinstance(yanit, dict):
        return None
    kod = None
    for alan in ("exit_code", "exitCode", "returncode", "status_code"):
        if isinstance(yanit.get(alan), int):
            kod = yanit[alan]
            break
    metadata = yanit.get("metadata")
    if kod is None and isinstance(metadata, dict) and isinstance(metadata.get("exit_code"), int):
        kod = metadata["exit_code"]
    hata = yanit.get("error") or yanit.get("stderr") or yanit.get("output") or ""
    if yanit.get("success") is False or yanit.get("is_error") is True or (kod not in (None, 0)):
        return str(hata)[-2000:], kod
    return None


def _transkript_hatasi(yol, kimlik, kuyruk: int = 262144) -> tuple[str, int | None] | None:
    """Codex 0.155 tool_response'u düz çıktı metnidir, çıkış kodu taşımaz. Kod, transcript'teki
    aynı kimlikli `item_completed` kaydında durur; dosyanın yalnız sonu okunur."""
    if not yol or not kimlik:
        return None
    try:
        with open(yol, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - kuyruk))
            satirlar = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for satir in reversed(satirlar):
        if kimlik not in satir or '"exit_code"' not in satir:
            continue
        try:
            oge = json.loads(satir)["payload"]["item"]
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(oge, dict) or oge.get("id") != kimlik:
            continue
        kod = oge.get("exit_code")
        if isinstance(kod, int) and kod != 0:
            metin = oge.get("aggregated_output") or oge.get("stderr") or oge.get("stdout") or ""
            return str(metin)[-2000:], kod
        return None
    return None


def main() -> int:
    if os.environ.get("BEYIN_INVOKED_BY"):
        return 0
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(d, dict):
        return 0
    sys.path.insert(0, str(SCRIPTS))
    try:
        import hata_defteri
    except Exception:
        return 0
    event = d.get("hook_event_name") or ""
    runner = os.environ.get("BEYIN_MODEL_RUNNER", "").strip().casefold()
    if runner in ("antigravity", "agy"):
        istemci = "antigravity"
    elif os.environ.get("CLAUDE_PROJECT_DIR") or runner == "claude":
        istemci = "claude"
    else:
        istemci = "codex"
    oturum = str(d.get("session_id") or "")
    kaynak = Path(d.get("cwd") or os.getcwd()).name

    if event == "UserPromptSubmit":
        anahtar = hata_defteri.duzeltme_sinyali(str(d.get("prompt") or ""))
        if anahtar:
            hata_defteri.kaydet("davranis-sinyal", f"sinyal:{anahtar}", istemci=istemci,
                                oturum=oturum, kaynak=kaynak)
            emit(event, "[Hata defteri] Bu mesaj bir davranış düzeltmesine benziyor. Öyleyse "
                 "düzeltmeyi uygula ve aynı oturumda 850-hafiza/davranis-kurallari.md "
                 "dosyasına kural olarak yaz (Nasıl büyür). Düzeltme değilse yok say.")
        return 0

    if event == "PostToolUseFailure":
        if d.get("is_interrupt"):
            return 0
        hata, kod = str(d.get("error") or ""), None
    elif event == "PostToolUse":
        sonuc = _yanit_hatasi(d.get("tool_response"))
        if sonuc is None and isinstance(d.get("tool_response"), str):
            sonuc = _transkript_hatasi(d.get("transcript_path"), d.get("tool_use_id"))
        if sonuc is None:
            return 0
        hata, kod = sonuc
    else:
        return 0
    arac = str(d.get("tool_name") or "bilinmiyor")
    imza = hata_defteri.arac_imzasi(arac, d.get("tool_input"), hata, kod)
    if imza:
        hata_defteri.kaydet("arac", imza, istemci=istemci, oturum=oturum, arac=arac,
                            ozet=hata_defteri.ozet_satiri_sec(hata), kaynak=kaynak)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)

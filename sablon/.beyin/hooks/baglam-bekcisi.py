#!/usr/bin/env python3
"""Bağlam bekçisi: oturum bağlamı eşiği geçince devir ister (200k uyarı, 250k devir).

Hook olarak (stdin'de hook girdisi):
- Etkileşimli oturumda: UserPromptSubmit ve PostToolUse'ta, her 50k'lık yeni bantta bir kez uyarır.

Ölçüm aracı olarak: `baglam-bekcisi.py --olc <transcript.jsonl>` son isteğin bağlamını
(girdi + önbellek yazma + önbellek okuma token'ı) yazar.

Neden son istek: işlenen token her istekte bütün bağlamın yeniden okunmasıdır; büyük
bağlamda her istek pahalılaşır.
"""
import json
import os
import sys
from pathlib import Path

ETKILESIMLI_ESIK = int(os.environ.get("BEYIN_BAGLAM_ETKILESIMLI_TOKEN", "200000"))  # hazırlık uyarısı
ETKILESIMLI_DEVIR = int(os.environ.get("BEYIN_BAGLAM_ETKILESIMLI_DEVIR_TOKEN", "250000"))
BANT = 50000
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "beyin" / "baglam"
TAIL_BYTES = 2_000_000
VAULT = Path(__file__).resolve().parents[2]


def codex_kaydi(session_id: str) -> Path | None:
    """Codex oturumunun rollout kaydı: ~/.codex/sessions/**/rollout-*<kimlik>.jsonl."""
    if not session_id or not all(c.isalnum() or c == "-" for c in session_id):
        return None
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    found = sorted((home / "sessions").glob(f"**/rollout-*{session_id}.jsonl"))
    return found[-1] if found else None


def son_baglam(transcript: Path) -> int:
    """Transcript'teki son ana-hat asistan isteğinin bağlam boyu; bulunamazsa 0."""
    try:
        with transcript.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            lines = f.read().splitlines()
    except OSError:
        return 0
    for raw in reversed(lines):
        if b'usage"' not in raw and b'input_tokens"' not in raw:  # Claude "usage", Codex "last_token_usage", AGY "input_tokens"
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("type") == "PLANNER_RESPONSE":
            tok = int(d.get("input_tokens") or 0) + int(d.get("cache_read_tokens") or 0)
            if tok:
                return tok
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        if p.get("type") == "token_count":
            last = (p.get("info") or {}).get("last_token_usage") or {}
            if last.get("input_tokens"):
                return int(last["input_tokens"])
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        u = (d.get("message") or {}).get("usage") or {}
        tok = sum(int(u.get(k) or 0) for k in
                  ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        if tok:
            return tok
    return 0


def emit(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                             "additionalContext": text}}, ensure_ascii=False))


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--olc":
        print(son_baglam(Path(sys.argv[2])))
        return 0
    if os.environ.get("BEYIN_INVOKED_BY"):
        return 0
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return 0
    event = d.get("hook_event_name") or ""
    transcript = d.get("transcript_path") or ""
    if not transcript:  # Claude her zaman verir; Codex vermeyebilir
        transcript = str(codex_kaydi(str(d.get("session_id") or "")) or "")
    if not transcript:
        return 0
    cwd = Path(d.get("cwd") or os.getcwd()).resolve()
    if cwd != VAULT and VAULT not in cwd.parents:
        return 0  # Codex hook'ları global; başka projede sessiz
    tok = son_baglam(Path(transcript))
    if tok < ETKILESIMLI_ESIK:
        return 0
    k = tok // 1000
    key = "".join(c for c in str(d.get("session_id") or "x") if c.isalnum() or c == "-")[:64]
    bant = tok // BANT
    iz = STATE / key
    try:
        onceki = int(iz.read_text().strip() or 0)
    except (OSError, ValueError):
        onceki = 0
    if bant <= onceki:
        return 0
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        iz.write_text(str(bant))
    except OSError:
        pass
    devir_notu = ("devir notunu yaz (son-oturum-ozetleri + ilgili proje notu: durum, son commit, "
                  "açık işler, tuzaklar, tam yollar) ve kullanıcıya yeni oturum öner")
    if tok < ETKILESIMLI_DEVIR:
        emit(event, f"[Bağlam] Oturum bağlamı {k}k; devir {ETKILESIMLI_DEVIR // 1000}k'da. Yeni büyük "
             f"adıma başlamadan iyi bir durma noktası ara; oraya gelince {devir_notu}.")
    else:
        emit(event, f"[Bağlam] Oturum bağlamı {k}k; {ETKILESIMLI_DEVIR // 1000}k eşik aşıldı. Yeni iş "
             f"başlatma: elindeki adımı bitir, {devir_notu}. 300k'yı geçme.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

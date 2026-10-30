#!/usr/bin/env python3
"""Beyin longitudinal output-quality events without transcript content."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import _portalock

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = SCRIPT_DIR / ".state"
FILE = "kalite-olaylari.jsonl"
WINDOWS = (7, 30)
FOLLOWUP_STATES = frozenset({"korundu", "duzeltildi", "geri-alindi", "izlenemedi"})
REPAIR_REASONS = frozenset(
    {"olgu", "baglam", "kisit", "test", "arac", "guvenlik", "eskime", "anlatim", "diger"}
)


def path(state_dir: Path = STATE_DIR) -> Path:
    return state_dir / FILE


def _key(*parts: object) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:24]


def _append(event: dict, state_dir: Path = STATE_DIR) -> dict:
    target = path(state_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock, _portalock.exclusive(lock):
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def _remember(rows: list[dict], client: str, model: Any, effort: Any = None) -> None:
    if not isinstance(model, str) or not model.strip():
        return
    item = {"istemci": client, "model": model.strip(),
            "efor": effort if isinstance(effort, str) else "bilinmiyor"}
    for current in rows:
        if current["istemci"] == item["istemci"] and current["model"] == item["model"]:
            if current["efor"] == "bilinmiyor" and item["efor"] != "bilinmiyor":
                current["efor"] = item["efor"]
                return
            if item["efor"] == "bilinmiyor" or current["efor"] == item["efor"]:
                return
    if item not in rows:
        rows.append(item)


def _roles_without_shadowed_unknown_effort(roles: Sequence[dict]) -> list[dict]:
    known = {(row.get("rol", "assistant"), row.get("istemci", "bilinmiyor"), row.get("model"))
             for row in roles if row.get("efor", "bilinmiyor") != "bilinmiyor"}
    return [row for row in roles
            if row.get("efor", "bilinmiyor") != "bilinmiyor"
            or (row.get("rol", "assistant"), row.get("istemci", "bilinmiyor"), row.get("model")) not in known]


def transcript_models(transcript_path: Path) -> list[dict]:
    """Return observed model settings in order; never infer a missing model."""
    import re
    models: list[dict] = []
    with transcript_path.open("r", encoding="utf-8") as stream:
        for raw in stream:
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            record_type = record.get("type")
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            if record_type == "turn_context":
                _remember(models, "codex", payload.get("model"), payload.get("reasoning_effort"))
            elif record_type == "event_msg" and payload.get("type") == "thread_settings_applied":
                settings = payload.get("thread_settings") if isinstance(payload.get("thread_settings"), dict) else {}
                _remember(models, "codex", settings.get("model"), settings.get("reasoning_effort"))
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            if record_type == "assistant" or message.get("role") == "assistant":
                _remember(models, "claude", message.get("model") or record.get("model"),
                          message.get("reasoning_effort") or record.get("reasoning_effort"))
            if record_type == "USER_INPUT":
                content = record.get("content")
                if isinstance(content, str) and "<USER_SETTINGS_CHANGE>" in content:
                    m_model = re.search(
                        r"Model Selection`?\s+from\s+.+?\s+to\s+(.+?)(?:\s+\(([^)]+)\)|\s+with thinking effort\s+([A-Za-z0-9._-]+))?\s*\.",
                        content,
                    )
                    if m_model:
                        effort = (m_model.group(2) or m_model.group(3) or "").strip().casefold() or None
                        _remember(models, "antigravity", m_model.group(1).strip(), effort)
            if record_type == "PLANNER_RESPONSE":
                _remember(models, "antigravity", record.get("model"), record.get("reasoning_effort"))
    return models


def transcript_usage(transcript_path: Path) -> dict:
    """Read reported session usage; missing readings stay explicit."""
    invalid_report = False

    def count(value: object) -> int:
        nonlocal invalid_report
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            invalid_report = True
            return 0
        if parsed < 0:
            invalid_report = True
            return 0
        return parsed

    codex_total: dict | None = None
    claude_rows: list[dict] = []
    agy_rows: list[dict] = []
    previous_claude_input: int | None = None
    with transcript_path.open("r", encoding="utf-8") as stream:
        for raw in stream:
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            if payload.get("type") == "token_count":
                info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                total = info.get("total_token_usage")
                if isinstance(total, dict):
                    codex_total = total
            if record.get("type") == "PLANNER_RESPONSE":
                cached = count(record.get("cache_read_tokens"))
                inp = count(record.get("input_tokens")) + cached
                out = count(record.get("output_tokens"))
                if inp or out or cached:
                    agy_rows.append({"girdi": inp, "onbellek": cached, "cikti": out, "dusunme": 0})
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            usage = message.get("usage") if record.get("type") == "assistant" else None
            if isinstance(usage, dict):
                cached = count(usage.get("cache_read_input_tokens"))
                created = count(usage.get("cache_creation_input_tokens"))
                current_input = count(usage.get("input_tokens")) + cached + created
                if current_input != previous_claude_input:
                    claude_rows.append({"girdi": current_input, "onbellek": cached,
                                        "cikti": count(usage.get("output_tokens")), "dusunme": 0})
                    previous_claude_input = current_input
    if codex_total is not None:
        return {
            "girdi": count(codex_total.get("input_tokens")),
            "onbellek": count(codex_total.get("cached_input_tokens")),
            "cikti": count(codex_total.get("output_tokens")),
            "dusunme": count(codex_total.get("reasoning_output_tokens")),
            "olculmedi": int(invalid_report),
        }
    if claude_rows:
        return {key: sum(row[key] for row in claude_rows)
                for key in ("girdi", "onbellek", "cikti", "dusunme")} | {
                    "olculmedi": int(invalid_report)}
    if agy_rows:
        return {key: sum(row[key] for row in agy_rows)
                for key in ("girdi", "onbellek", "cikti", "dusunme")} | {
                    "olculmedi": int(invalid_report)}
    return {"girdi": 0, "onbellek": 0, "cikti": 0, "dusunme": 0, "olculmedi": 1}


def session_event(session_id: str, reason: str, summary: str, transcript_path: Path,
                  *, now: float | None = None) -> dict:
    created = float(time.time() if now is None else now)
    summary_hash = hashlib.sha256(summary.encode()).hexdigest()
    output_id = f"beyin:{_key(session_id, reason, summary_hash)}"
    models = transcript_models(transcript_path)
    return {
        "surum": 1,
        "olay": "cikti",
        "olay_id": _key("cikti", output_id),
        "cikti_id": output_id,
        "sistem": "beyin",
        "zaman": created,
        "kaynak_id": session_id,
        "kaynak_olay": reason,
        "gorev_turu": "oturum-ozeti",
        "risk": "bilinmiyor",
        "sonuc": "bilinmiyor",
        "kanit": "kismi",
        "niyet_uyumu": "bilinmiyor",
        "kalibrasyon": "bilinmiyor",
        "devir": "bilinmiyor",
        "insan_yuku": {"zorunlu_onay": 0, "model_duzeltme": 0, "yeniden_aciklama": 0},
        "roller": [{"rol": "assistant", **model} for model in models],
        "model_kapsami": "coklu" if len(models) > 1 else ("tek" if models else "bilinmiyor"),
        "takim_token": transcript_usage(transcript_path),
        "icerik_saklandi": False,
        "ozet_hash": summary_hash,
        "etiket_surumu": 1,
    }


def record_session(session_id: str, reason: str, summary: str, transcript_path: Path,
                   *, state_dir: Path = STATE_DIR, now: float | None = None) -> dict:
    return _append(session_event(session_id, reason, summary, transcript_path, now=now), state_dir)


def observe(output_id: str, window: int, status: str, *, corrections: int = 0,
            repair_reason: str | None = None, evaluator: str = "insan",
            state_dir: Path = STATE_DIR, now: float | None = None) -> dict:
    source = next((event for event in events(state_dir)
                   if event.get("olay") == "cikti" and event.get("cikti_id") == output_id), None)
    if source is None:
        raise ValueError(f"bilinmeyen çıktı: {output_id}")
    if window not in WINDOWS:
        raise ValueError("takip penceresi 7 veya 30 olmalı")
    if status not in FOLLOWUP_STATES:
        raise ValueError(f"bilinmeyen takip durumu: {status}")
    if corrections < 0:
        raise ValueError("düzeltme sayısı negatif olamaz")
    if repair_reason is not None and repair_reason not in REPAIR_REASONS:
        raise ValueError(f"bilinmeyen düzeltme nedeni: {repair_reason}")
    created = float(time.time() if now is None else now)
    if created < float(source.get("zaman", created)) + window * 86_400:
        raise ValueError(f"{window} günlük takip penceresi henüz dolmadı")
    if status == "duzeltildi" and (corrections < 1 or repair_reason is None):
        raise ValueError("duzeltildi için pozitif --duzeltme ve --neden gerekli")
    if status != "duzeltildi" and (corrections or repair_reason is not None):
        raise ValueError("düzeltme sayısı ve nedeni yalnız duzeltildi durumunda kullanılır")
    return _append({
        "surum": 1, "olay": "gozlem",
        "olay_id": _key("gozlem", output_id, window, created),
        "cikti_id": output_id, "zaman": created, "pencere_gun": window,
        "durum": status, "duzeltme": corrections,
        "duzeltme_nedeni": repair_reason, "degerlendirici": evaluator,
        "etiket_surumu": 1,
    }, state_dir)


def events(state_dir: Path = STATE_DIR) -> list[dict]:
    try:
        lines = path(state_dir).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    latest: dict[str, dict] = {}
    for raw in lines:
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(event, dict) and event.get("surum") == 1 and event.get("olay_id"):
            latest[event["olay_id"]] = event
    return sorted(latest.values(), key=lambda row: row.get("zaman", 0))


def outputs(state_dir: Path = STATE_DIR, now: float | None = None) -> list[dict]:
    current = float(time.time() if now is None else now)
    base: dict[str, dict] = {}
    observations: dict[tuple[str, int], dict] = {}
    for event in events(state_dir):
        if event.get("olay") == "cikti":
            base[event["cikti_id"]] = event
        elif event.get("olay") == "gozlem" and event.get("pencere_gun") in WINDOWS:
            observations[(event.get("cikti_id"), event["pencere_gun"])] = event
    result = []
    for output_id, row in base.items():
        item = dict(row)
        item["takip"] = {}
        age = max(0.0, current - float(row.get("zaman", current)))
        for window in WINDOWS:
            observed = observations.get((output_id, window))
            if observed:
                item["takip"][str(window)] = observed["durum"]
            elif age < window * 86_400:
                item["takip"][str(window)] = "henuz-olgunlasmadi"
            else:
                item["takip"][str(window)] = "gozlem-bekliyor"
        result.append(item)
    return sorted(result, key=lambda row: row.get("zaman", 0))


def aggregate(rows: list[dict] | None = None, *, state_dir: Path = STATE_DIR,
              now: float | None = None) -> dict:
    rows = outputs(state_dir, now) if rows is None else rows
    followups = {str(window): Counter(row.get("takip", {}).get(str(window), "bilinmiyor") for row in rows)
                 for window in WINDOWS}
    models: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        for role in _roles_without_shadowed_unknown_effort(row.get("roller", [])):
            models[(role.get("rol", "assistant"), role.get("istemci", "bilinmiyor"),
                    role.get("model", "bilinmiyor"))] += 1
    return {
        "cikti": len(rows),
        "kanit": dict(Counter(row.get("kanit", "bilinmiyor") for row in rows)),
        "sonuc": dict(Counter(row.get("sonuc", "bilinmiyor") for row in rows)),
        "takip": {window: dict(counts) for window, counts in followups.items()},
        "modeller": [{"rol": role, "istemci": client, "model": model, "katki": count}
                     for (role, client, model), count in sorted(models.items())],
    }


def report(state_dir: Path = STATE_DIR, now: float | None = None) -> str:
    data = aggregate(state_dir=state_dir, now=now)
    lines = [f"BEYİN KALİTE GÜNLÜĞÜ: {data['cikti']} çıktı",
             f"Kanıt: {data['kanit'] or {'kayıt': 0}}",
             f"Sonuç: {data['sonuc'] or {'kayıt': 0}}"]
    for window in WINDOWS:
        lines.append(f"{window} gün takibi: {data['takip'][str(window)] or {'kayıt': 0}}")
    if data["modeller"]:
        lines += ["", "Model katılımı (oturum sonucu tek model başarısı değildir):"]
        lines += [f"  {row['istemci']} · {row['model']}: {row['katki']} çıktı"
                  for row in data["modeller"]]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rapor")
    follow = sub.add_parser("takip")
    follow.add_argument("cikti_id")
    follow.add_argument("--gun", type=int, choices=WINDOWS, required=True)
    follow.add_argument("--durum", choices=sorted(FOLLOWUP_STATES), required=True)
    follow.add_argument("--duzeltme", type=int, default=0)
    follow.add_argument("--neden", choices=sorted(REPAIR_REASONS))
    follow.add_argument("--degerlendirici", default="insan")
    args = parser.parse_args(argv)
    if args.command == "rapor":
        print(report())
        return 0
    try:
        event = observe(args.cikti_id, args.gun, args.durum, corrections=args.duzeltme,
                        repair_reason=args.neden, evaluator=args.degerlendirici)
    except ValueError as error:
        parser.error(str(error))
    print(f"Takip kaydedildi: {event['cikti_id']} · {event['pencere_gun']} gün · {event['durum']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

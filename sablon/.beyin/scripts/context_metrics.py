#!/usr/bin/env python3
"""Measure hook delivery without storing prompt content or guessing tokens."""

import argparse
import json
import os
import time
from pathlib import Path


def event(state, key, action, chars=0, trimmed=False, sections=None,
          budget_trimmed=False, part=None, rules_source=None, char_unit="unicode",
          selection_mode=None):
    folder = Path(state) / "context-metrics"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (key + ".json")
    record = json.loads(path.read_text()) if path.exists() else {"started": time.time()}
    record.update(event=action)
    if action == "delivered":
        if sections is not None:
            record.update(sections=sections, budget_trimmed=budget_trimmed,
                          schema_version=2, part=part, rules_source=rules_source,
                          char_unit=char_unit)
            if selection_mode:
                record["thread_selection"] = selection_mode
            trimmed = trimmed or budget_trimmed or any(s["trimmed"] for s in sections.values())
        record.update(finished=time.time(), chars=chars, trimmed=trimmed)
        record["seconds"] = round(record["finished"] - record["started"], 3)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)


def summary(state):
    files = sorted((Path(state) / "context-metrics").glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    rows = []
    for path in files:
        try:
            rows.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    done = [r for r in rows if r.get("event") == "delivered"]
    return {"attempts": len(rows), "delivered": len(done),
            "unfinished_over_30s": sum(r.get("event") != "delivered" and time.time()-r["started"] > 30 for r in rows),
            "empty": sum(r.get("chars", 0) == 0 for r in done),
            "trimmed": sum(bool(r.get("trimmed")) for r in done),
            "section_trimmed": sum(any(s.get("trimmed") for s in r.get("sections", {}).values()) for r in done),
            "budget_trimmed": sum(bool(r.get("budget_trimmed")) for r in done),
            "omitted_topics": sum(r.get("sections", {}).get("threads", {}).get("omitted_topics", 0) for r in done),
            "legacy_delivered": sum(r.get("schema_version", 1) < 2 for r in done),
            "chars": sum(r.get("chars", 0) for r in done),
            "note": "En son 200 deneme; Claude parçaları ayrı teslimdir. Eski kayıtlarda bölüm kırpılması bilinmiyor. Tamamlanmayan kayıt kesinti belirtisidir; kesin timeout kanıtı değildir."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--id")
    parser.add_argument("--event", choices=("started", "delivered"))
    parser.add_argument("--chars", type=int, default=0)
    parser.add_argument("--trimmed", action="store_true")
    parser.add_argument("--budget-trimmed", action="store_true")
    parser.add_argument("--part", choices=("hepsi", "kurallar", "hafiza"))
    parser.add_argument("--rules-source")
    parser.add_argument("--char-unit", choices=("unicode", "utf16"), default="unicode")
    parser.add_argument("--selection-mode", choices=("priority", "project", "query", "unavailable"))
    parser.add_argument("--section", action="append", nargs=6, default=[],
                        metavar=("NAME", "INPUT", "CAPPED", "EMITTED", "LIMIT", "OMITTED"))
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    try:
        if args.summary:
            print(json.dumps(summary(args.state), ensure_ascii=False))
        elif args.id and args.event:
            sections = {}
            for name, raw, capped, emitted, limit, omitted in args.section:
                raw, capped, emitted, limit, omitted = map(int, (raw, capped, emitted, limit, omitted))
                sections[name] = dict(input_chars=raw, capped_chars=capped,
                                      emitted_chars=emitted, limit=limit,
                                      trimmed=raw > limit if limit else False,
                                      budget_trimmed=emitted < capped,
                                      omitted_topics=omitted)
            event(args.state, args.id, args.event, args.chars, args.trimmed,
                  sections if args.event == "delivered" and args.part else None,
                  args.budget_trimmed, args.part, args.rules_source, args.char_unit,
                  args.selection_mode)
    except (OSError, ValueError):
        pass  # diagnostics cannot break memory delivery

#!/usr/bin/env python3
"""Read-only checks for the actual session-start sources and hook parts."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shlex

import context_metrics
import select_threads

SECTION_NAMES = {'last_session': 'LAST_SESSION', 'threads': 'THREADS', 'rules': 'RULES',
                 'journal': 'JOURNAL', 'reflection': 'REFLECTION'}


def rules_source(root):
    memory = Path(root) / '850-hafiza'
    core = memory / 'calisma-cekirdegi.md'
    return core if core.is_file() else memory / 'davranis-kurallari.md'


def rules_block(path):
    active, lines = False, []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('## Nasıl büyür'):
            break
        if line.startswith('## Kurallar'):
            active = True
        if active:
            lines.append(line)
    return '\n'.join(lines).rstrip('\n')


def section_caps(root):
    hooks = Path(root) / '.beyin/hooks'
    sh = (hooks / 'session-start.sh').read_text(encoding='utf-8')
    caps = {}
    for name, var in SECTION_NAMES.items():
        a = re.search(r'beyin_cap_section "\$BEYIN_' + var + r'" (\d+)', sh)
        caps[name] = {'sh': int(a[1]) if a else None}
    match = re.search(r'BEYIN_RULES}" -gt (\d+)', sh)
    caps['rules_part'] = {'sh': int(match[1]) if match else None}
    return caps


def hook_parts(root):
    counts = {e: Counter() for e in ('SessionStart', 'UserPromptSubmit', 'SessionEnd', 'PreCompact')}
    names = {'SessionStart': 'session-start', 'UserPromptSubmit': 'prompt-counter',
             'SessionEnd': 'session-end', 'PreCompact': 'pre-compact'}
    for name in ('settings.json', 'settings.local.json'):
        path = Path(root) / '.claude' / name
        if not path.exists():
            continue
        config = json.loads(path.read_text(encoding='utf-8'))
        for ev, stem in names.items():
            for matcher in config.get('hooks', {}).get(ev, []):
                for hook in matcher.get('hooks', []):
                    command = hook.get('command', '')
                    if not re.search(r'\b' + stem + r'\.sh\b', command):
                        continue
                    # Parse, never execute config commands; output contains only part labels.
                    tokens = shlex.split(command)
                    indices = [i for i, token in enumerate(tokens)
                               if re.search(r'(?:^|[/\\])' + stem + r'\.sh$', token)]
                    part = 'invalid'
                    if len(indices) == 1:
                        tail = tokens[indices[0] + 1:]
                        if ev != 'SessionStart':
                            part = 'hepsi' if not tail else 'invalid'
                        elif not tail:
                            part = 'hepsi'
                        elif len(tail) == 1 and tail[0] in ('kurallar', 'hafiza'):
                            part = tail[0]
                    counts[ev][part] += 1
    result = {}
    for ev, count in counts.items():
        valid = count == Counter(hepsi=1)
        if ev == 'SessionStart':
            valid = valid or count == Counter(kurallar=1, hafiza=1)
        result[ev] = {'ok': valid, 'parts': dict(count)}
    return result


def report(root, check):
    root = Path(root)
    healthy = True
    if check in ('all', 'hooks'):
        for ev, row in hook_parts(root).items():
            healthy = healthy and row['ok']
            print(f"{ev}: {'ok' if row['ok'] else 'BOZUK'} {json.dumps(row['parts'], ensure_ascii=False)}")
    if check in ('all', 'rules'):
        path = rules_source(root)
        if not path.is_file():
            raise ValueError('Seçilen kural kaynağı yok')
        block = rules_block(path)
        if not block:
            raise ValueError('Seçilen kaynakta kural bölümü yok')
        size = len(block)
        print(f'kurallar kaynagi: {path.relative_to(root)}, {size} karakter')
        for name, pair in section_caps(root).items():
            a = pair['sh']
            valid = a is not None
            healthy = healthy and valid
            print(f"{name} limit: sh={a}, {'ok' if valid else 'OKUNAMADI'}")
            if name in ('rules', 'rules_part') and a is not None:
                status = 'KIRMIZI' if size > a else 'SARI' if size >= a * .85 else 'YESIL'
                healthy = healthy and size <= a
                print(f'{name}: {size}/{a}, {status}')
    if check in ('all', 'index'):
        path = root / '550-derlenmis-bilgi-tabani/bilgi-tabani-indeksi.md'
        if not path.is_file():
            raise ValueError('Bilgi indeksi yok')
        count = sum(line.startswith('| [[') for line in path.read_text(encoding='utf-8').splitlines())
        print(f'index: {count} makale; kanca yalnız sayı ve kaynak işaretçisi enjekte ediyor')
    if check in ('all', 'topics'):
        path = root / '850-hafiza/aktif-konu-takibi.md'
        topics = select_threads.parse(path.read_text(encoding='utf-8'))
        missing = sum(not all(t['fields'].get(f) for f in ('status', 'decision', 'next', 'source')) for t in topics)
        duplicates = sum(bool(t.get('duplicates')) for t in topics)
        valid = bool(topics) and missing == 0 and duplicates == 0
        healthy = healthy and valid
        print(f"konu modeli: {'ok' if valid else 'BOZUK'}, {len(topics)} konu, {missing} eksik alan, {duplicates} yinelenmiş alan")
    if check in ('all', 'metrics'):
        data = context_metrics.summary(root / '.beyin/scripts/.state')
        print(json.dumps(data, ensure_ascii=False))
        files = sorted((root / '.beyin/scripts/.state/context-metrics').glob('*.json'),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        seen = set()
        for path in files[:200]:
            try:
                row = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if row.get('event') != 'delivered' or row.get('schema_version') != 2:
                continue
            part = row.get('part')
            if part in seen:
                continue
            seen.add(part)
            print(f"son {part}: kaynak={row.get('rules_source')}, birim={row.get('char_unit')}, secim={row.get('thread_selection')}, bolumler={json.dumps(row['sections'])}")
    return healthy


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--check', choices=('all', 'hooks', 'rules', 'index', 'topics', 'metrics'), default='all')
    args = parser.parse_args()
    try:
        healthy = report(args.root, args.check)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        # Do not echo config contents or exception messages that may contain credentials.
        print(f'BOZUK/OKUNAMADI: {type(error).__name__}')
        raise SystemExit(1)
    raise SystemExit(0 if healthy else 1)

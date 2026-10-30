#!/usr/bin/env python3
"""Select complete topic summaries; only cwd is consumed from native hook payloads."""

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import unicodedata

FIELDS = {'status': 'Status', 'decision': 'Karar', 'next': 'Sonraki adım',
          'source': 'Kaynak', 'aliases': 'Aliases', 'priority': 'Öncelik'}
POINTER = '[[aktif-konu-takibi|Tüm konular ve kaynakları]]'


def units(text):
    # Conservative on POSIX too: no PowerShell cap can cut a selected emoji.
    return len(text.encode('utf-16-le')) // 2


def normalize(text):
    text = text.casefold().replace('ı', 'i')
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def parse(text):
    active = False
    selected = []
    current = None
    field = None
    labels = {label: key for key, label in FIELDS.items()}
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('## Closed'):
            break
        if line.startswith('## Active'):
            active = True
            continue
        if not active:
            continue
        if line.startswith('### Thread: '):
            current = {'title': line[12:].strip(), 'line': number, 'fields': {}}
            selected.append(current)
            field = None
            continue
        if current is None:
            continue
        match = re.match(r'^\*\*([^*]+):\*\*\s*(.*)', line)
        if match:
            field = labels.get(match[1])
            if field:
                # Duplicate statuses are not silently overwritten.
                if field in current['fields']:
                    current.setdefault('duplicates', []).append(field)
                    field = None
                else:
                    current['fields'][field] = match[2]
        elif field and line.strip() and not line.startswith(('<!--', '^')):
            current['fields'][field] += ' ' + line.strip()
        elif not line.strip():
            field = None
    return selected


def concise(text, limit=190):
    text = ' '.join(text.split())
    if units(text) <= limit:
        return text
    # Keep a complete informative sentence, never half a URL, date or wikilink.
    for match in re.finditer(r'[.!?](?=\s|$)', text):
        prefix = text[:match.end()]
        content = re.sub(r'^[🟡🟢🔴\s]*\d{2}\.\d{2}\.\d{4}\.\s*', '', prefix)
        if units(prefix) > limit:
            break
        if len(content) >= 12 and prefix.count('[[') == prefix.count(']]'):
            return prefix
    return ''


def date_key(status):
    match = re.search(r'\b(\d{2})\.(\d{2})\.(\d{4})\b', status)
    if not match:
        return 0
    try:
        return dt.date(int(match[3]), int(match[2]), int(match[1])).toordinal()
    except ValueError:
        return 0


def rank(topic, query, cwd):
    fields = topic['fields']
    title = normalize(re.sub(r'\[\[([^]|]+)(?:\|([^]]+))?\]\]', lambda m: m[2] or m[1], topic['title']))
    aliases = [normalize(x) for x in fields.get('aliases', '').split('|') if x.strip()]
    aliases.append(title)
    normalized_query = normalize(query)
    project_segments = [normalize(s) for s in re.split(r'[/\\]', cwd) if s]
    exact_query = any(alias and f' {alias} ' in f' {normalized_query} ' for alias in aliases)
    project = any(alias and alias in project_segments for alias in aliases)
    words = set(title.split()) - {'thread', 've', 'bir', 'icin', 'proje', 'durum', 'ozeti'}
    overlap = len(words & set(normalized_query.split()))
    match = (8 if exact_query else 0) + (8 if project else 0) + min(overlap, 4)
    status = fields.get('status', '')
    priority = 3 if '🔴' in status else 2 if '🟡' in status else 0
    if fields.get('priority') in ('0', '1', '2', '3'):
        priority = int(fields['priority'])
    return match, priority, date_key(status), -topic['line']


def render(topic):
    fields = topic['fields']
    title = topic['title']
    # The heading is the stable source location, even for old records without metadata.
    source = f'[[aktif-konu-takibi#Thread: {title}|ayrıntı]]'
    status = concise(fields.get('status', '')) or 'Durum özeti uzun; ayrıntı kaynağını aç.'
    result = f'### Thread: {title}\n**Status:** {status}\n'
    next_step = concise(fields.get('next', ''), 120)
    if next_step:
        result += f'Sonraki: {next_step}\n'
    return result + source


def select(text, query='', cwd='', limit=2000, max_topics=6):
    topics = parse(text)
    ordered = sorted(topics, key=lambda t: rank(t, query, cwd), reverse=True)
    mode = 'query' if query.strip() else 'project' if cwd and any(rank(t, '', cwd)[0] for t in topics) else 'priority'
    rows = []
    chosen = []
    # Reserve the actual footer, using the longest possible omission count.
    footer = f'{len(topics)} konu yüklenmedi. {POINTER}'
    for topic in ordered:
        if len(chosen) >= max_topics:
            break
        row = render(topic)
        candidate = '\n\n'.join(rows + [row]) + '\n\n' + footer
        if units(candidate) <= limit:
            rows.append(row)
            chosen.append(topic)
    omitted = len(topics) - len(chosen)
    if topics:
        footer = f'{omitted} konu yüklenmedi. {POINTER}'
        output = '\n\n'.join(rows + [footer])
        if units(output) > limit:
            # Extremely small diagnostic budgets still never cut text.
            output = ''
    else:
        output = ''
    return {'text': output, 'total': len(topics), 'omitted': omitted, 'mode': mode,
            'selected': [t['title'] for t in chosen]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--query', default='', help='Explicit query for on-demand selection; not assumed in SessionStart')
    parser.add_argument('--cwd', default='')
    parser.add_argument('--payload', action='store_true', help='Read a native hook JSON from stdin; only cwd is used')
    parser.add_argument('--limit', type=int, default=2000)
    parser.add_argument('--max-topics', type=int, default=6)
    parser.add_argument('--format', choices=('json', 'hook'), default='json')
    args = parser.parse_args()
    cwd = args.cwd
    if args.payload:
        try:
            payload = json.load(sys.stdin)
            if isinstance(payload, dict) and isinstance(payload.get('cwd'), str):
                cwd = payload['cwd'][:4096]
        except (ValueError, OSError):
            pass
    try:
        text = args.source.read_text(encoding='utf-8')
    except OSError:
        text = ''
    result = select(text, args.query[:2048], cwd, args.limit, args.max_topics)
    if args.format == 'hook':
        print(f"{result['total']} {result['omitted']} {result['mode']}")
        print(result['text'], end='')
    else:
        print(json.dumps(result, ensure_ascii=False))

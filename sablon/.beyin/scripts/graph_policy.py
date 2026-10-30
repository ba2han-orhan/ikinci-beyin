"""Reviewed graph redirects and compiler staging reconciliation; no live note writes."""
import hashlib
import json
from pathlib import Path
import re

KB = '550-derlenmis-bilgi-tabani'
CONFIG = '.beyin/config/graph-policy.json'
SLUG = r'[a-z0-9]+(?:-[a-z0-9]+)*'


class GraphPolicyError(ValueError):
    pass


def safe(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != relative or '\\' in relative:
        raise GraphPolicyError('graph-path-invalid')
    target = Path(root) / path
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise GraphPolicyError('graph-path-outside-vault')
    return target


def snapshot(root):
    path = safe(root, CONFIG)
    if not path.exists():
        return {'redirects': {}, 'link_targets': {}, 'hashes': {}}
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('redirects'), list) or not isinstance(data.get('link_targets'), dict):
        raise GraphPolicyError('graph-policy-schema')
    redirects = {}
    hashes = {CONFIG: hashlib.sha256(raw).hexdigest()}
    resolved = {}
    for entry in data['redirects']:
        if not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) for k in ('from','to','basis')):
            raise GraphPolicyError('graph-redirect-invalid')
        old, new = entry['from'], entry['to']
        safe(root, old); safe(root, new)
        if old in redirects or old == new or not entry.get('basis'):
            raise GraphPolicyError('graph-redirect-invalid')
        redirects[old] = new
    for old in redirects:
        new, _chain = resolve_redirect(root, old, redirects)
        resolved[old] = new
        target = safe(root, new)
        hashes[new] = hashlib.sha256(target.read_bytes()).hexdigest()
    for slug, pair in data['link_targets'].items():
        if not re.fullmatch(SLUG, slug) or not isinstance(pair, dict) or set(pair) != {'human', 'generated'}:
            raise GraphPolicyError('graph-link-binding-invalid')
        for target in pair.values():
            if not isinstance(target, str):
                raise GraphPolicyError('graph-link-binding-invalid')
            path = safe(root, target + '.md')
            if not path.is_file():
                raise GraphPolicyError('graph-link-target-missing')
            hashes[target + '.md'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'redirects': redirects, 'resolved_redirects': resolved, 'link_targets': data['link_targets'], 'hashes': hashes}


def assert_unchanged(root, data):
    for relative, expected in data['hashes'].items():
        if hashlib.sha256(safe(root, relative).read_bytes()).hexdigest() != expected:
            raise GraphPolicyError('graph-policy-source-changed')


def resolve_redirect(root, target, redirects):
    chain = []
    while target in redirects:
        if target in chain:
            raise GraphPolicyError('graph-redirect-cycle')
        chain.append(target)
        target = redirects[target]
    path = safe(root, target)
    if not path.is_file():
        raise GraphPolicyError('graph-redirect-target-missing')
    return target, chain


def qualify_links(text, targets):
    """Preserve displayed names, anchors and aliases; skip code/comments exactly."""
    protected = re.compile(r'<!--[\s\S]*?-->|%%[\s\S]*?%%|(?m:^[ \t]*```[^\n]*\n[\s\S]*?^[ \t]*```[^\n]*$)|(?m:^[ \t]*~~~[^\n]*\n[\s\S]*?^[ \t]*~~~[^\n]*$)|`+[^`\n]*`+')
    def replace(chunk):
        def link(match):
            raw = match[1]
            first, pipe, label = raw.partition('|')
            escaped = first.endswith('\\') if pipe else False
            first = (first.rstrip('\\') if escaped else first).strip()
            base = re.split(r'[#^]', first, maxsplit=1)[0].strip()
            key = base[:-3] if base.endswith('.md') else base
            if key not in targets:
                return match[0]
            tail = first[len(base):]
            new = targets[key] + tail
            display = label if pipe else first
            return '[[' + new + ('\\|' if escaped else '|') + display + ']]'
        return re.sub(r'\[\[([^\]]+)\]\]', link, chunk)
    parts = []; pos = 0
    for match in protected.finditer(text):
        parts.extend((replace(text[pos:match.start()]), match[0])); pos = match.end()
    parts.append(replace(text[pos:]))
    return ''.join(parts)


def reconcile_stage(stage, data, timestamp):
    paths = [Path(stage) / KB / 'bilgi-tabani-indeksi.md', Path(stage) / KB / 'bilgi-derleme-gunlugu.md']
    for folder in ('concepts', 'connections'):
        paths.extend(sorted((Path(stage) / KB / folder).glob('*.md')))
    targets = {slug: pair['generated'] for slug, pair in data['link_targets'].items()}
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        before = text
        header_end = text.find('\n---', 4) + 4 if text.startswith('---\n') else 0
        prefix, body = text[:header_end], text[header_end:]
        old_body = body
        for old in data['redirects']:
            new = data.get('resolved_redirects', {}).get(old, data['redirects'][old])
            body = body.replace(old, new)
        text = prefix + body
        import authority
        prior = authority.fields(text).get('redirected_references', '[]')
        existing = json.loads(prior)
        terminal_targets = set(data.get('resolved_redirects', data['redirects']).values())
        origins = [p for p in existing if p not in terminal_targets]
        if text.startswith('---\n') and (body != old_body or origins != existing):
            import authority
            origins.extend(old for old in data['redirects'] if old in old_body and old not in origins)
            text = authority._metadata(text, {'redirected_references': json.dumps(origins, ensure_ascii=False), 'updated': timestamp[:10]})
            if '> Kaynak yolu uzlaştırması:' not in text:
                heading = re.search(r'(?m)^# [^\n]+\n', text)
                if heading:
                    explanation = '\n> Kaynak yolu uzlaştırması: eski raporun güncel birleşik başvuru yolu kullanılıyor; aşağıdaki tarihsel karar ve ölçüm iddiaları korunmuştur.\n'
                    text = text[:heading.end()] + explanation + text[heading.end():]
        text = qualify_links(text, targets)
        if text != before:
            path.write_text(text, encoding='utf-8')


def validate_connections(stage, changed):
    for relative in changed:
        path = Path(relative)
        if path.parent != Path(KB) / 'connections':
            continue
        pair = path.stem.split('--')
        if len(pair) != 2 or pair[0] == pair[1] or any(not re.fullmatch(SLUG, s) for s in pair):
            raise GraphPolicyError('connection-name-invalid')
        import authority
        value = authority.fields((Path(stage) / path).read_text()).get('connects', '')
        if not value.startswith('[') or not value.endswith(']'):
            raise GraphPolicyError('connection-connects-invalid')
        items = [s.strip().strip('\"\'') for s in value[1:-1].split(',')]
        if items != pair:
            raise GraphPolicyError('connection-name-connects-mismatch')
        for slug in pair:
            if not (Path(stage) / KB / 'concepts' / (slug + '.md')).is_file():
                raise GraphPolicyError('connection-concept-missing')

"""Two audited policy pilots and authority-aware resolution; no general search claim."""

import datetime as dt
import hashlib
import json
from pathlib import Path
import re

from select_threads import normalize

KB = '550-derlenmis-bilgi-tabani'
POLICIES = {
    'session-context-handoff': {
        'source': '850-hafiza/davranis-kurallari.md',
        'anchor': 'Bağlamı küçük tut:',
        'slug': 'oturum-baglam-devir-kurali',
        'title': 'Oturum Bağlamı ve Devir Kuralı',
        'aliases': ['150k', '150k sınırı', '250k', '400k', 'bağlam sınırı', 'devir kuralı'],
        'legacy': 'oturum-150k-token-devir-siniri',
    },
    'generated-knowledge-ownership': {
        'source': '850-hafiza/vault-not-baglanti-standardi.md',
        'anchor': '**`550-derlenmis-bilgi-tabani/` elle düzenlenmez.**',
        'slug': 'makine-bilgi-tabani-yazim-kurali',
        'title': 'Makine Bilgi Tabanı Yazım Kuralı',
        'aliases': ['bilgi indeksi', 'indeks', 'elle düzenleme', '550 düzenleme'],
    },
}


class AuthorityError(ValueError):
    pass


def fields(text):
    if not text.startswith('---\n'):
        return {}
    end = text.find('\n---', 4)
    if end < 0:
        raise AuthorityError('frontmatter-unclosed')
    result = {}
    for line in text[4:end].splitlines():
        match = re.fullmatch(r'([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)', line)
        if match:
            key, value = match.groups()
            if key in result:
                raise AuthorityError('duplicate-frontmatter-field')
            result[key] = value.strip('"\'')
    return result


def snapshot(root, policy_ids=None):
    root = Path(root).resolve()
    data = {}
    for key, policy in POLICIES.items():
        if policy_ids is not None and key not in policy_ids:
            continue
        path = root / policy['source']
        if not path.exists():
            continue  # Small test/seed vaults may lack these optional sources.
        if not path.resolve().is_relative_to(root):
            raise AuthorityError('authority-source-outside-vault')
        raw = path.read_bytes()
        lines = raw.decode('utf-8').splitlines()
        start = next((i for i, line in enumerate(lines) if policy['anchor'] in line), None)
        if start is None:
            continue  # Kullanıcı kuralı silmiş ya da yeniden yazmış olabilir; pilot isteğe bağlı.
        end = start + 1
        while end < len(lines) and lines[end].strip():
            end += 1
        data[key] = {'source': policy['source'], 'line': start + 1,
                     'excerpt': '\n'.join(lines[start:end]),
                     'sha256': hashlib.sha256(raw).hexdigest()}
    return data


def assert_unchanged(root, data):
    for policy in data.values():
        path = Path(root) / policy['source']
        if hashlib.sha256(path.read_bytes()).hexdigest() != policy['sha256']:
            raise AuthorityError('authority-source-changed')


def resolve(concepts, slug):
    concepts = Path(concepts)
    chain = []
    while True:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise AuthorityError('invalid-superseded-by')
        if slug in chain:
            raise AuthorityError('superseded-cycle')
        path = concepts / f'{slug}.md'
        if not path.is_file() or path.is_symlink():
            raise AuthorityError('missing-superseded-target')
        chain.append(slug)
        marker = fields(path.read_text(encoding='utf-8')).get('superseded_by')
        if not marker:
            return slug, chain
        slug = marker


def source_kind(relative):
    # Origin wins over claims made in generated metadata; dates never grant authority.
    if relative in {p['source'] for p in POLICIES.values()} or relative in ('CLAUDE.md', 'AGENTS.md'):
        return 'authoritative_rule', 5
    if relative.startswith('300-projeler/') and relative.endswith('-proje-durum-ozeti.md'):
        return 'project_state', 4
    if relative.startswith(('600-araclar-ve-kaynaklar/', '500-kalici-bilgi/', '850-hafiza/')):
        return 'dated_source', 3
    if relative.startswith(KB + '/'):
        return 'derived_concept', 2
    if relative.startswith('800-gunluk-oturum-kayitlari/'):
        return 'daily_log', 1
    return 'unknown', 0


def _metadata(text, updates):
    fields(text)
    if not text.startswith('---\n'):
        raise AuthorityError('historical-frontmatter-missing')
    end = text.find('\n---', 4)
    rows = text[4:end].splitlines()
    keys = set(updates)
    rows = [line for line in rows if not any(line.startswith(key + ':') for key in keys)]
    for key, value in updates.items():
        rows.append(f'{key}: {value}')
    return '---\n' + '\n'.join(rows) + text[end:]


def reconcile_stage(stage, data, timestamp, history_text=None):
    """Deterministic compiler output. Only called within validated compiler staging."""
    if not data:
        return
    knowledge = Path(stage) / KB
    concepts = knowledge / 'concepts'
    concepts.mkdir(exist_ok=True)
    day = timestamp[:10]
    entries = {}
    for key, evidence in data.items():
        policy = POLICIES[key]
        legacy = policy.get('legacy')
        path = concepts / f"{policy['slug']}.md"
        links = [f"- [[{Path(evidence['source']).stem}]] — bu kararın yetkili, güncel kaynağı."]
        if legacy and (concepts / f'{legacy}.md').exists():
            links.append(f'- [[{legacy}]] — önceki kararın tarihsel kaydı; güncel kuralın yerine geçmez.')
        if (concepts / 'hafiza-sistemi.md').exists():
            links.append('- [[hafiza-sistemi]] — yazım ve kaynak kurallarının uygulandığı hafıza mimarisini açıklar.')
        text = ('---\n' + '\n'.join([
            'title: ' + policy['title'], 'aliases: ' + json.dumps(policy['aliases'], ensure_ascii=False),
            'tags: [beyin, kural, kaynak]', 'sources: []', f'created: {day}', f'updated: {day}',
            f'decision_id: {key}', 'authoritative_source: ' + evidence['source'],
            'authoritative_source_sha256: ' + evidence['sha256'],
            'verified_at: ' + json.dumps(timestamp), 'verification_method: direct-source-read',
        ]) + '\n---\n\n' + '# ' + policy['title'] + '\n\n'
            + '> ⬆️ [[bilgi-tabani-indeksi]] · Yetkili kaynakla doğrulanmış, makine üretimi karar özeti.\n\n'
            + 'Güncel uygulama aşağıdaki yetkili kaynaktan doğrulanır. Kaynak tarihi tek başına doğruluk kanıtı değildir.\n\n'
            + '## Önemli Noktalar\n\n' + evidence['excerpt'] + '\n\n'
            + '## Detaylar\n\nBu metin üretim anındaki kaynak görüntüsüdür; retrieval yetkili kaynağı yeniden okur.\n\n'
            + '## İlgili Kavramlar\n\n' + '\n'.join(links) + '\n\n'
            + '## Kaynaklar\n\n' + f"- [[{Path(evidence['source']).stem}]] — doğrulanan paragraf, satır {evidence['line']}.\n")
        if path.exists():
            created = fields(path.read_text()).get('created')
            if created:
                text = text.replace(f'created: {day}', f'created: {created}', 1)
        path.write_text(text, encoding='utf-8')
        entries[policy['slug']] = f"| [[{policy['slug']}]] | Yetkili kaynak: [[{Path(evidence['source']).stem}]]; güncel karar | {Path(evidence['source']).name} | {day[8:10]}.{day[5:7]}.{day[:4]} |"
        if legacy and (concepts / f'{legacy}.md').is_file():
            old = history_text if history_text is not None else (concepts / f'{legacy}.md').read_text(encoding='utf-8')
            old = _metadata(old, {'superseded_by': policy['slug'], 'decision_id': 'session-context-handoff-2026-09-26', 'updated': day})
            warning = f"> Tarihsel karar: yerini [[{policy['slug']}]] aldı. Aşağıdaki metin önceki kararın korunmuş kaydıdır."
            old = re.sub(r'(?m)^> Tarihsel karar:.*\n\n?', '', old)
            title = re.search(r'(?m)^# [^\n]+\n', old)
            if title is None:
                raise AuthorityError('historical-title-missing')
            old = old[:title.end()] + '\n' + warning + '\n' + old[title.end():]
            (concepts / f'{legacy}.md').write_text(old, encoding='utf-8')
            entries[legacy] = f"| [[{legacy}]] | Yerini [[{policy['slug']}]] aldı; 26.09.2026 tarihsel karar | 26.09.2026.md | {day[8:10]}.{day[5:7]}.{day[:4]} |"
    index = knowledge / 'bilgi-tabani-indeksi.md'
    text = index.read_text(encoding='utf-8')
    if 'generated-knowledge-ownership' in data:
        header = re.search(r'(?m)^\|\s*Makale\s*\|', text)
        if header is None:
            raise AuthorityError('index-table-header-missing')
        text = ('# Bilgi Tabanı İndeksi\n\n> ⬆️ [[kontrol-paneli]] · Derlenmiş bilgilerin makine üretimi erişim noktası.\n\n'
                'Bu dosya `.beyin/scripts/compile.py` tarafından üretilir; elle düzenlenmez.\n'
                'Düzeltme üretici üzerinden yapılır. Yetkili kaynak: [[vault-not-baglanti-standardi]].\n'
                'Her satır concepts/ altındaki bir makaleye karşılık gelir.\n\n' + text[header.start():])
    rows = text.splitlines()
    for slug, row in entries.items():
        # The model may write the path-qualified link form; both name the same
        # article. Authority rows are fully generated, so extra copies are dropped.
        pattern = r'^\|\s*\[\[(?:' + re.escape(KB) + r'/concepts/)?' + re.escape(slug) + r'(?:\|[^\]]+)?\]\]'
        positions = [i for i, line in enumerate(rows) if re.match(pattern, line)]
        if positions:
            rows[positions[0]] = row
            for i in reversed(positions[1:]):
                del rows[i]
        else:
            rows.append(row)
    index.write_text('\n'.join(rows) + '\n', encoding='utf-8')


def lookup(root, query, historical=False):
    root = Path(root)
    concepts = root / KB / 'concepts'
    normalized = normalize(query)
    matches = []
    for path in concepts.glob('*.md'):
        meta = fields(path.read_text(encoding='utf-8'))
        haystack = normalize(path.stem + ' ' + meta.get('title', '') + ' ' + meta.get('aliases', ''))
        words = set(normalized.split()) & set(haystack.split())
        if normalized == normalize(path.stem) or words:
            matches.append((len(words), path.stem))
    resolved = []
    seen = set()
    evidence = None
    for score, slug in sorted(matches, reverse=True):
        target, chain = (slug, [slug]) if historical else resolve(concepts, slug)
        if target in seen:
            continue
        seen.add(target)
        path = concepts / f'{target}.md'
        text = path.read_text(encoding='utf-8')
        meta = fields(text)
        key = meta.get('decision_id')
        kind, priority = source_kind(f'{KB}/concepts/{target}.md')
        if historical and meta.get('superseded_by'):
            priority = 3
        row = {'concept': target, 'matched': slug, 'replacement_chain': chain,
               'source': f'{KB}/concepts/{target}.md', 'kind': kind, 'priority': priority,
               'historical': historical, 'text': text, 'score': score}
        if not historical and key in POLICIES and target == POLICIES[key]['slug']:
            if meta.get('authoritative_source') != POLICIES[key]['source']:
                raise AuthorityError('authority-source-mismatch')
            if evidence is None:
                evidence = {}
            if key not in evidence:
                evidence.update(snapshot(root, (key,)))
            if key not in evidence:
                raise AuthorityError('authority-source-unavailable')
            current = evidence[key]
            row.update(source=current['source'], line=current['line'], text=current['excerpt'],
                       kind='authoritative_rule', priority=5, decision_id=key,
                       source_changed_since_generation=current['sha256'] != meta.get('authoritative_source_sha256'),
                       source_sha256=current['sha256'], metadata_verified_at=meta.get('verified_at'))
            row.update(verified_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                       verification_method='direct-source-read')
        resolved.append(row)
    return sorted(resolved, key=lambda row: (row['priority'], row['score']), reverse=True)[:3]

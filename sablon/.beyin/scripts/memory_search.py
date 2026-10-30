"""Local lexical source search; no evaluation labels, network, index writes or models."""
import collections
import hashlib
import json
import math
from pathlib import Path
import re

import authority
from select_threads import normalize

ROOTS = ('300-projeler', '500-kalici-bilgi', '550-derlenmis-bilgi-tabani/concepts',
         '600-araclar-ve-kaynaklar', '800-gunluk-oturum-kayitlari', '850-hafiza', '900-arsiv')
# Grammar/question words, not topic synonyms or benchmark query patterns.
STOP = set(normalize('ve veya ile bir bu şu o mı mi mu mü ne nasıl nerede hangi için de da '
                     'hâlâ artık şu an şimdi bugün güncel eski son ilk olarak kadar '
                     'var yok en daha her aynı ben sen biz göre sonra önce').split())
SUFFIXES = ('larindan', 'lerinden', 'larinin', 'lerinin', 'larinda', 'lerinde', 'larin', 'lerin',
            'sinin', 'sindan', 'sinde', 'sinda', 'inin', 'unun', 'dan', 'den', 'nda', 'nde',
            'lari', 'leri', 'lar', 'ler', 'ini', 'unu', 'nin', 'nda', 'nde', 'yla', 'yle')


def tokens(text):
    # CamelCase boundaries also make ProjectWarehouse / Project Warehouse equivalent.
    text = re.sub(r'([a-zçğıöşü])([A-ZÇĞİÖŞÜ])', r'\1 \2', text)
    words = normalize(text).split()
    out = []
    for word in words:
        if word in STOP:
            continue
        for suffix in SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 5:
                word = word[:-len(suffix)]
                break
        out.append(word)
    return out


def phrase_match(name, query_phrase):
    phrase = ' '.join(tokens(name))
    return bool(phrase and ' ' + phrase + ' ' in ' ' + query_phrase + ' ')


def aliases(meta):
    value = meta.get('aliases') or '[]'
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        if not value.startswith('[') or not value.endswith(']'):
            raise ValueError('aliases-must-be-inline-list')
        parsed = [s.strip().strip('\"\'') for s in value[1:-1].split(',') if s.strip()]
    if not isinstance(parsed, list) or any(not isinstance(s, str) or not s.strip() for s in parsed):
        raise ValueError('aliases-must-be-string-list')
    return parsed


def metadata(text):
    meta = authority.fields(text)
    if text.startswith('---\n') and meta.get('aliases') == '':
        header = text[4:text.index('\n---', 4)]
        match = re.search(r'(?m)^aliases:\s*\n((?:[ \t]*- [^\n]+\n?)+)', header)
        if match:
            names = [line.strip()[2:].strip().strip('\"\'') for line in match[1].splitlines()]
            meta['aliases'] = json.dumps(names, ensure_ascii=False)
    return meta


def source_paths(root, roots=ROOTS):
    root = Path(root).resolve()
    paths = []
    for prefix in roots:
        for p in sorted((root / prefix).rglob('*.md')):
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                continue
            # Evaluation reports are explicitly outside the search corpus (label leakage).
            meta = metadata(p.read_text(encoding='utf-8'))
            if meta.get('search_exclude', '').casefold() == 'true':
                continue
            paths.append(p.relative_to(root).as_posix())
    # The router belongs to the full corpus only; a narrowed search (e.g. concepts) skips it.
    if roots == ROOTS and (root / 'CLAUDE.md').is_file() and (root / 'CLAUDE.md').resolve().is_relative_to(root):
        paths.append('CLAUDE.md')
    return sorted(set(paths))


def blocks(text):
    """Paragraphs with original one-based source lines and containing headings."""
    lines = text.splitlines()
    begin = 0
    if lines and lines[0] == '---':
        try:
            begin = lines.index('---', 1) + 1
        except ValueError:
            raise ValueError('frontmatter-unclosed')
    section = ''
    pending = []
    start = begin + 1
    for i in range(begin, len(lines) + 1):
        line = lines[i] if i < len(lines) else ''
        if line.startswith('#') or not line.strip() or len(pending) >= 18:
            if pending:
                yield start, section, '\n'.join(pending)
                pending = []
            if line.startswith('#'):
                section = line.lstrip('#').strip()
                continue
            if not line.strip():
                continue
        if not pending:
            start = i + 1
        pending.append(line)


class SearchIndex:
    def __init__(self, root, roots=ROOTS):
        self.root = Path(root).resolve()
        # Policy routing needs the authoritative source in the corpus; narrowed indexes skip it.
        self.full = roots == ROOTS
        self.documents = {}
        self.blocks = []
        self.identities = {}
        for relative in source_paths(self.root, roots):
            path = self.root / relative
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            meta = metadata(text)
            identity = meta.get('id') or 'path:' + relative
            if meta.get('id'):
                if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', identity):
                    raise ValueError('invalid-source-id')
                if identity in self.identities:
                    raise ValueError('duplicate-source-id')
                self.identities[identity] = relative
            names = [meta.get('title', path.stem), *aliases(meta)]
            name_tokens = set(tokens(' '.join(names)))
            kind, priority = authority.source_kind(relative)
            if relative.startswith('900-arsiv/'):
                kind, priority = 'archive', 1
            self.documents[relative] = {'id': identity, 'title': names[0], 'aliases': names[1:],
                'project': meta.get('project'), 'status': meta.get('status'), 'kind': kind,
                'priority': priority, 'source': relative, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                'names': name_tokens, 'meta': meta}
            for line, section, excerpt in blocks(text):
                if normalize(section) in ('ilgili', 'ilgili kavramlar', 'kaynaklar'):
                    continue  # Link lists locate notes but are not answer evidence.
                freq = collections.Counter(tokens(excerpt + ' ' + section))
                if freq:
                    self.blocks.append({'source': relative, 'line': line, 'section': section,
                                        'text': excerpt, 'freq': freq, 'length': sum(freq.values())})
        self.df = collections.Counter()
        for block in self.blocks:
            self.df.update(block['freq'].keys())
        self.average_length = sum(b['length'] for b in self.blocks) / max(1, len(self.blocks))

    def lookup(self, query, historical=False, limit=3):
        terms = set(tokens(query))
        if not terms:
            return []
        total = len(self.blocks)
        idf = {t: math.log(1 + (total - self.df[t] + .5) / (self.df[t] + .5)) for t in terms}
        scored = []
        query_phrase = ' '.join(tokens(query))
        for block in self.blocks:
            doc = self.documents[block['source']]
            matched = terms & (block['freq'].keys() | doc['names'])
            if not matched:
                continue
            # Require a meaningful lexical connection before authority can affect ranking.
            score = 0.0
            for term in matched:
                freq = block['freq'][term]
                if freq:
                    score += idf[term] * freq * 2.2 / (freq + 1.2 * (.25 + .75 * block['length'] / self.average_length))
                if term in doc['names']:
                    score += idf[term] * 1.5
            phrase = any(phrase_match(name, query_phrase) for name in [doc['title'], *doc['aliases']])
            if phrase:
                score *= 1.3
            # Authority is a bounded relevance multiplier, never a global priority sort.
            if not historical:
                score *= 1 + .12 * doc['priority']
                if doc['kind'] in ('daily_log', 'archive'):
                    score *= .65
                if doc['meta'].get('superseded_by'):
                    score *= .4
            elif doc['meta'].get('superseded_by'):
                score *= 1.5  # Explicit historical mode preserves the preceding decision.
            scored.append((score, block))
        scored.sort(key=lambda item: (-item[0], item[1]['source'], item[1]['line']))
        project_matches = set()
        if not historical:
            for doc in self.documents.values():
                if doc['kind'] == 'project_state' and any(
                        phrase_match(name, query_phrase) for name in [doc['title'], *doc['aliases']]):
                    project_matches.add(doc['source'])
            # A named project has an explicit current state owner; route to that source.
            # No date/title claims in generated concepts can assign this ownership.
            scored.sort(key=lambda item: (item[1]['source'] not in project_matches,
                                         -item[0], item[1]['source'], item[1]['line']))
        rows = []
        seen = set()
        for score, block in scored:
            source = block['source']
            if source in seen:
                continue
            doc = self.documents[source]
            chain = []
            if not historical and doc['meta'].get('superseded_by') and source.startswith(authority.KB + '/concepts/'):
                target, chain = authority.resolve(self.root / authority.KB / 'concepts', Path(source).stem)
                source = authority.KB + '/concepts/' + target + '.md'
                doc = self.documents[source]
                # A replacement must be searched on its own terms; it cannot inherit an unrelated excerpt.
                candidates = [b for _, b in scored if b['source'] == source]
                if not candidates:
                    continue
                block = candidates[0]
            if source in seen:
                continue
            key = doc['meta'].get('decision_id')
            policy_evidence = None
            if (self.full and not historical and key in authority.POLICIES
                    and Path(source).stem == authority.POLICIES[key]['slug']):
                if doc['meta'].get('authoritative_source') != authority.POLICIES[key]['source']:
                    raise authority.AuthorityError('authority-source-mismatch')
                policy_evidence = authority.snapshot(self.root, (key,)).get(key)
                if policy_evidence is None:
                    raise authority.AuthorityError('authority-source-unavailable')
                # Check the real paragraph too; a title-only match cannot invent relevance.
                if not terms.intersection(tokens(policy_evidence['excerpt'])):
                    continue
                source = policy_evidence['source']
                if source not in self.documents:
                    raise authority.AuthorityError('authority-source-not-indexed')
                doc = self.documents[source]
                if source in seen:
                    continue
            seen.add(source)
            rows.append({k: doc[k] for k in ('id', 'title', 'aliases', 'project', 'status', 'source',
                                             'kind', 'priority', 'source_sha256')})
            rows[-1].update(line=block['line'], section=block['section'], text=block['text'][:1600],
                            score=round(score, 6), historical=historical,
                            replacement_chain=chain, verification_method='direct-source-read')
            if policy_evidence:
                rows[-1].update(line=policy_evidence['line'], section='Yetkili karar paragrafı',
                                text=policy_evidence['excerpt'], source_sha256=policy_evidence['sha256'])
            if len(rows) >= limit:
                break
        return rows


def lookup(root, query, historical=False, limit=3):
    return SearchIndex(root).lookup(query, historical, limit)

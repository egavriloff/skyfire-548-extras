"""Conservative corpus terminology and review diagnostics for offline AI requests.

Whole short fields are atomic terms; this is not bilingual word alignment.
No fuzzy spelling, source-name trust, or donor decision changes are allowed.
"""
from collections import defaultdict
import copy
import json
import re

TERM_FIELDS = {'creature': ('name', 'subname'), 'item': ('name',),
               'gameobject': ('name',), 'points_of_interest': ('icon_name',)}
INSTRUCTIONS = (
    'Use exact terminology translations where the English term occurs. '
    'Do not invent transliterations or repair source English. '
    'Preserve every runtime token and its case. '
    'If needs_review is true, withhold the translation for human review. '
    'Glossary absence does not establish a canonical name; flag uncertain names.'
)


def contains(text, term):
    return bool(re.search(r'(?<![\w])' + re.escape(term) + r'(?![\w])', text))


def suspicious(text):
    reasons = []
    if re.search(r'^(?:out|DEBUG|UNUSED|DELETE|OBSOLETE|TEST)\b', text):
        reasons.append('debug_or_garbage_prefix')
    if re.search(r'\b(?:DEBUG|UNUSED|DELETE|OBSOLETE)\s*$', text):
        reasons.append('debug_or_garbage_suffix')
    if re.search(r'^Morph\s|Only GM can see|\bQuest Credit\b', text):
        reasons.append('internal_or_debug_label')
    if '\ufffd' in text or any(ord(c) < 32 and c not in '\n\t' for c in text):
        reasons.append('broken_source_characters')
    if not text.strip() or re.search(r'^\s*\.\.\.|\.\.\.\s*$', text):
        reasons.append('possibly_truncated_fragment')
    return {'source_suspicious': bool(reasons), 'needs_review': bool(reasons), 'reasons': reasons}


def relevant_text(row):
    base = row['context'].get('target_base', {})
    return '\n'.join([row['english']] + [v for v in base.values() if isinstance(v, str)])


def glossary(api, conn, rows, locale):
    """Read existing index; confirm candidate terms through the unchanged engine."""
    texts = sorted(set(relevant_text(r) for r in rows))
    text_index = defaultdict(set)
    for i, text in enumerate(texts):
        for word in set(re.findall(r'\w+', text)):
            text_index[word].add(i)
    def relevant(term):
        words = re.findall(r'\w+', term)
        if not words:
            return False
        anchor = min(words, key=lambda w: len(text_index.get(w, ())))
        return any(contains(texts[i], term) for i in text_index.get(anchor, ()))
    candidates = []
    # Stream base rows; only relevant short fields trigger a decision lookup.
    for kind, fields in sorted(TERM_FIELDS.items()):
        if kind not in api.SPECS:
            continue
        for key, raw in conn.execute("SELECT entity,fields FROM main.entities WHERE source='target' AND kind=? ORDER BY entity", (kind,)):
            base = json.loads(raw)
            selected = {f: base.get(f) for f in fields if isinstance(base.get(f), str)
                        and 2 <= len(base[f]) <= 100 and not suspicious(base[f])['needs_review']
                        and relevant(base[f])}
            if selected:
                candidates.append((kind, key, selected))
    terms = defaultdict(lambda: defaultdict(list))
    with api.analytics.engine_scope(api, conn) as (view, metadata):
        for kind, key, fields in candidates:
            view.reset_row()
            entry = api.bulk_decision(view, kind, key, locale)[0]
            if entry['status'] in ('CONFLICT', 'UNSUPPORTED', 'AMBIGUOUS') or entry.get('identity_failed'):
                continue
            exported = api.analytics.state(entry)[1]
            for field, english in sorted(fields.items()):
                detail = entry['fields'].get(field, {})
                if detail.get('status') not in ('MATCH', 'SOURCE_ONLY', 'TARGET_IDENTICAL'):
                    continue
                evidence = []
                if field in exported:
                    for source, value in sorted(detail.get('upstream', {}).items()):
                        proof, origin, target = api.evidence_roles.field_english_proof(api, view, source, kind, key, field)
                        if proof:
                            evidence.append((source, value, detail.get('provenance', {}).get(source, {}), origin))
                target_value = detail.get('target')
                if target_value and detail.get('status') == 'TARGET_IDENTICAL':
                    evidence.append(('target', target_value, {}, api.english_field_evidence(view, 'target', kind, key, field)))
                for source, value, provenance, origin in evidence:
                    if not isinstance(value, str) or not value.strip() or api.looks_mojibake(value):
                        continue
                    normalized = api.translation_comparison_text(value, locale)
                    if normalized == api.translation_comparison_text(english, locale):
                        continue
                    terms[english][normalized].append({'translation': value, 'source': source,
                        'entity': kind, 'key': json.loads(key), 'field': field,
                        'provenance': provenance, 'english_proof': origin})
    result, ambiguous = [], []
    for english, variants in sorted(terms.items()):
        if len(variants) != 1:
            ambiguous.append(english)
            continue
        evidence = next(iter(variants.values()))
        evidence.sort(key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))
        result.append({'english': english, 'ruRU': evidence[0]['translation'],
                       'source': evidence[0]['source'], 'evidence': evidence})
    return result, ambiguous


def enrich(api, conn, rows, locale):
    catalog, ambiguous = glossary(api, conn, rows, locale)
    output = copy.deepcopy(rows)
    for row in output:
        text = relevant_text(row)
        matches = [t for t in catalog if contains(text, t['english'])
                   and (' ' in t['english'] or t['english'] == row['english']
                        or t['english'] in row['context'].get('target_base', {}).values())]
        # A shorter overlapping term can have a different sense (Tank vs Battle Tank).
        row['context']['terminology'] = [t for t in matches if not any(
            len(other['english']) > len(t['english']) and contains(other['english'], t['english'])
            for other in matches)]
        row['context']['terminology_ambiguous'] = [t for t in ambiguous if contains(text, t)]
        row['context']['translation_instructions'] = INSTRUCTIONS
        row['context']['quality'] = suspicious(row['english'])
    return output


def semantic_qa(request, translation):
    """Review hints only; these diagnostics are not semantic equivalence proof."""
    findings = []
    if suspicious(request['english'])['needs_review']:
        findings.append({'reason': 'source_suspicious'})
    glossary = request['context'].get('terminology', [])
    for term in glossary:
        if contains(request['english'], term['english']) and not contains(translation.casefold(), term['ruRU'].casefold()):
            # Missing a surface form is not proof of a changed term: Russian
            # inflection and compound translations need linguistic judgment.
            # Keep this diagnostic advisory; never infer equivalence by stemming.
            findings.append({'reason': 'terminology_form_unverified', 'severity': 'advisory',
                             'blocking': False, 'needs_review': False,
                             'english': term['english'], 'expected': term['ruRU']})
    # Ignore runtime tokens; Latin words are a review signal, never language proof.
    clean = re.sub(r'\$(?:[A-Za-z]|[0-9]+)|%[-+0-9.]*[a-zA-Z]', '', translation)
    latin = sorted(set(re.findall(r'[A-Za-z]{3,}', clean)))
    if latin:
        findings.append({'reason': 'latin_fragment_review', 'fragments': latin})
    covered = ' '.join(t['english'] for t in glossary)
    names = sorted(set(w for w in re.findall(r"\b[A-Z][a-z]+(?:['’][A-Za-z]+)?\b", request['english']) if not contains(covered, w)))
    if names:
        findings.append({'reason': 'capitalized_terms_without_glossary', 'terms': names})
    return findings


def batch_qa(requests, responses):
    lookup = {(r['entity'], json.dumps(r['key']), r['field']): r for r in requests}
    diagnostics, variants = [], defaultdict(set)
    for row in responses:
        request = lookup[(row['entity'], json.dumps(row['key']), row['field'])]
        diagnostics.append({'entity': row['entity'], 'key': row['key'], 'field': row['field'],
                            'diagnostics': semantic_qa(request, row['translation'])})
        variants[request['english']].add(row['translation'])
    return {'rows': diagnostics, 'inconsistent_exact_terms': [
        {'english': text, 'translations': sorted(values)} for text, values in sorted(variants.items()) if len(values) > 1]}

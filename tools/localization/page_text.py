"""Schema-based page adapters and fail-closed linked-page identity proof."""
import json


def canonical(row):
    row = dict(row)
    for alias, field in (('id', 'entry'), ('nextpage', 'next_page'), ('nextpageid', 'next_page')):
        if alias in row:
            if field in row and row[field] != row[alias]:
                row['_evidence_incomplete'] = 1
            else:
                row[field] = row[alias]
    return row


def finalize(api, conn):
    """Validate complete source-local chains after all active base updates."""
    sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM entities WHERE kind='page_text'")]
    for source in sources:
        pages = {json.loads(key): (json.loads(fields), file) for key, fields, file in conn.execute(
            "SELECT entity,fields,file FROM entities WHERE source=? AND kind='page_text'", (source,))}
        for entry, (fields, file) in pages.items():
            current, seen, chain, reason = entry, set(), [], None
            while current:
                if current in seen:
                    reason = 'cyclic next_page chain'; break
                seen.add(current)
                if current not in pages:
                    reason = 'missing next_page entity: ' + str(current); break
                base, basefile = pages[current]
                next_page = base.get('next_page')
                if (base.get('_evidence_incomplete') or not isinstance(base.get('text'), str)
                        or not base['text'].strip() or type(next_page) is not int or next_page < 0):
                    reason = 'incomplete page base/next_page: ' + str(current); break
                chain.append({'entry': current, 'text': base['text'], 'next_page': next_page,
                              'file': basefile, 'table': 'page_text'})
                current = next_page
            fields['_page_chain_valid'] = reason is None
            fields['_page_chain'] = chain
            relationships = [{k: v for k, v in node.items() if k != 'text'} for node in chain]
            fields.setdefault('_english_provenance', {})['text'] = {'relationship_chain': relationships}
            if reason:
                fields['_page_chain_reason'] = reason
                api.schema_warning(conn, source, file, 'page_text', 'page_text', reason, entry,
                                   {'visited': sorted(seen)})
            else:
                fields.pop('_page_chain_reason', None)
            conn.execute("UPDATE entities SET fields=? WHERE source=? AND kind='page_text' AND entity=?",
                         (json.dumps(fields, ensure_ascii=False), source, json.dumps(entry)))
            for locale, encoded, localefile in conn.execute(
                    "SELECT locale,fields,file FROM records WHERE source=? AND kind='page_text' AND entity=?",
                    (source, json.dumps(entry))).fetchall():
                values = json.loads(encoded)
                values.setdefault('_provenance', {})['text'] = {
                    'file': localefile, 'table': api.record_table(conn, source, 'page_text', json.dumps(entry), locale),
                    'adapter': 'direct', 'relationship_chain': relationships}
                conn.execute("UPDATE records SET fields=? WHERE source=? AND kind='page_text' AND entity=? AND locale=?",
                             (json.dumps(values, ensure_ascii=False), source, json.dumps(entry), locale))


def match(api, source, target):
    if not source or not target or not source.get('_page_chain_valid') or not target.get('_page_chain_valid'):
        return False
    a, b = source.get('_page_chain', []), target.get('_page_chain', [])
    return bool(a and b and len(a) == len(b) and all(
        x['entry'] == y['entry'] and x['next_page'] == y['next_page']
        and api.quest_identity_text(x['text']) == api.quest_identity_text(y['text'])
        for x, y in zip(a, b)))

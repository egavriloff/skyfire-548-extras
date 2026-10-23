"""Quest analysis candidates only: no translation evidence or acceptance rules.

Candidate detection is deliberately heuristic. Capitalization alone is insufficient
for an isolated word. Corpus English labels are lexical clues, not ruRU proof.
"""
import re

WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
COMMON = frozenset("""a an the and or but nor so yet if although though because since unless until while
when whenever where wherever why how what whatever which who whom whose whether
were was is are am be been being do does did done have has had having can could
will would shall should may might must need ought i me my mine myself you your yours
yourself yourselves he him his himself she her hers herself it its itself we us our
ours ourselves they them their theirs themselves this that these those there here
then than as at by for from in into of off on onto out over through to under up with
without about after before between during within across again all any both each
either every everyone everything few many more most much neither no none not nothing
one once only other others same some someone something such two three four five six
seven eight nine ten first second third next last now never ever always already still
also just even really quite rather very too almost enough anyhow anyway otherwise
instead perhaps maybe probably certainly surely indeed unfortunately fortunately
well yes yeah yep nay okay ok bah ah aha ahh oh ooh hmm hm hey ho ha hah haha ahoy
hello greetings welcome congratulations perfect excellent great good fine splendid
wonderful beautiful amazing interesting impressive superb fantastic magnificent
look listen see tell ask give take bring get go come return find found use let keep
make made recover remember hope hopefully please thank thanks sorry pardon excuse careful
ready quick quickly soon right true wrong foolish silly old new young little big
small large long short happy back dear friend friends pal matey mon ya ye yer yeh dey dem
rememba captain general lord lady mister master brother sister chief fellow boy girl
""".split())
CONTRACTION = re.compile(r"(?:i|you|he|she|it|we|they|what|who|where|when|why|how|that|there|here|let|ain|don|doesn|didn|isn|aren|wasn|weren|haven|hasn|hadn|won|wouldn|can|couldn|shouldn|mustn)['’](?:s|t|ve|re|ll|d|m)$", re.I)
CONNECTORS = frozenset(('of','the','in','at','and'))
NAME_CUE = re.compile(r"(?:\b(?:named|called|against|defeat|kill|slay|from|to|with|of|the)|speak to|speak with)\s+$",re.I)


def _noise(word):
    return word.casefold() in COMMON or bool(CONTRACTION.fullmatch(word))


def english_entity_lexicon(conn):
    """Read authoritative base labels, not translations or source trust roles."""
    fields = {'creature':('name','subname'), 'gameobject':('name',), 'item':('name',),
              'points_of_interest':('icon_name',),
              'quest':('questgivertargetname','questturntargetname')}
    import json
    result=set()
    for kind, names in sorted(fields.items()):
        for (raw,) in conn.execute("SELECT fields FROM main.entities WHERE source='target' AND kind=?",(kind,)):
            base=json.loads(raw)
            for field in names:
                text=base.get(field)
                if not isinstance(text,str) or not text.strip():
                    continue
                if not text.islower():
                    result.add(text)
                # Name components help recognize unknown translations (e.g. a
                # surname in a longer NPC label); they never create glossary pairs.
                for word in WORD.findall(text):
                    if len(word) > 1 and word[:1].isupper() and not _noise(word):
                        result.add(word)
    return frozenset(result)


def candidates(english, *, exact_terms=(), entity_terms=(), known_terms=()):
    """Return literal English spans with independent entity-like clues.

    Exact accepted hints always survive. Other isolated capitalized words need
    lexical or syntactic name evidence. No spelling repair or English fuzzy match.
    """
    from ai_context import contains
    result={term for term in (*exact_terms, *known_terms) if term and contains(english,term)}
    # Mask tokens, preserving offsets so neighboring words are not concatenated.
    text=re.sub(r'\$[A-Za-z0-9]+|%[-+0-9.]*[A-Za-z]',lambda m:' '*len(m.group()),english)
    words=list(WORD.finditer(text))
    for i,match in enumerate(words):
        word=match.group()
        if _noise(word):
            continue
        if word[:1].isupper() and word in entity_terms:
            result.add(word)
        possessive=word.endswith(("'s",'’s'))
        root=word[:-2] if possessive else word
        if "'" in root or '’' in root:
            if root[:1].isupper():
                result.add(root)
        elif possessive and root[:1].isupper() and not _noise(root):
            result.add(root)
        if word[:1].isupper() and NAME_CUE.search(text[:match.start()]):
            result.add(root)
        if not word[:1].isupper():
            continue
        # Consecutive title words (with internal connectors) are phrase evidence.
        last=i;count=1
        for j in range(i+1,min(i+10,len(words))):
            previous=words[j-1]
            following=words[j]
            if text[previous.end():following.start()] not in (' ','-'):
                break
            token=following.group()
            if token in CONNECTORS:
                continue
            if not token[:1].isupper() or _noise(token):
                break
            count+=1;last=j
        if count>=2:
            result.add(text[match.start():words[last].end()])
    for acronym in re.findall(r'\b(?:[A-Z]\.){2,}[A-Z]?(?:\.)?',text):
        result.add(acronym)
    # Keep the most informative phrase, retaining a short term only if it also
    # occurs outside its longer phrase elsewhere in this request.
    selected=[]
    for term in sorted(result):
        remainders=text
        for longer in sorted(result,key=lambda t:(-len(t),t)):
            if len(longer)>len(term) and contains(longer,term):
                remainders=remainders.replace(longer,' ' * len(longer))
        if contains(remainders,term) or term in exact_terms:
            selected.append(term)
    return selected

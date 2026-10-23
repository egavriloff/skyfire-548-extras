"""Conservative object-label context enrichment; no donor/acceptance changes."""
import copy
import re
import ai_context
import quest_ai_review

ORDINARY = frozenset("""open closed door doors gate gates chest chests use warning exit entrance welcome
opening breaking collecting grabbing activation deactivating rotation hefting
house hut tent tower small big large medium lower mid upper first second
bench dining guard watch wall walls piece part segment post with stairs wooden
stone rock iron brass bronze gold silver red green blue white black purple
snow snowy ice icy warm hot cold swamp desert jungle mountain volcanic water
cave den dens tunnel tunnels bridge arch fountain well basin monument statue
fire campfire pyre brazier coffin lid tomb grave frame crypt simple building
cage room hall great townhall barn barracks shop store counter shopping centre center
market trade library cathedral chapel abbey altar shrine longhouse lodge kennel
inn tavern stable farm mill wagon cart wheel platform pad landing dock boat ship
forge anvil blacksmith mine goldmine signs sign fences fence portcullis active
ore gem lava plug rail balloon zeppelin transport mailbox elevator street path
weapon sword spear mace bow rifle sniper shield arrows arrow ballista catapult
mortar shell spear spearman paladin priest mage shaman druid warrior hunter
human orc troll undead dwarf dwarven gnome goblin draenei night elf elves
burnt people hanging body cracked giant turtle sea spider mushroom bamboo
hay stack wheat animal furbolg naga pagoda tepee igloo ziggurat outpost
slaughter ruined covered rack pick axe firework launcher fishing hole tree
spinning flower fountain catchers roots owl banner captain crusader gun guns
ammo bag bags supplies pass valley forest ruins district cavern cavernous
barricade barrels barrel crate crates mechanism lever button portal instance
barrow burrow standing chasm corrupted crimson starting dam deactivate mesa
rooted world auction gnomes melting pot griffon aviary hearse hive hoofprints
vendor industrial maiden walk mini albino machine monster balcony observatory
facade city pest repeller plagued player housing prison headquarters sarcophagus
scarecrow shack sprinkler shoulderpads hotel mall underwater vault teeth
waterfall wrought exterior particles crusader
""".split())


def quality(text, existing=None):
    result=copy.deepcopy(existing) if existing is not None else ai_context.suspicious(text)
    reasons=list(result.get('reasons',[]))
    if text.strip() in ('unk name','unk','0'):
        reasons.append('placeholder_object_label')
    if re.match(r'^(?:Doodad_|TEMP\b|OUT OF ORDER!)',text):
        reasons.append('internal_or_debug_object_label')
    if re.search(r'\b(?:CavernDoor\d+|WallPost|Intance|Plataform|Aliancce|Monestary|Cementery|Scarley)\b',text):
        reasons.append('malformed_or_internal_source_label')
    if reasons:
        result.update(needs_review=True,source_suspicious=True,reasons=sorted(set(reasons)))
    return result


def candidates(text, terms, entity_terms):
    exact=[t['english'] for t in terms if ai_context.contains(text,t['english'])]
    raw=quest_ai_review.candidates(text,exact_terms=exact,entity_terms=entity_terms)
    selected=set(exact)
    for phrase in raw:
        if phrase in exact:
            continue
        # Ordinary label vocabulary is not a canonical-name blocker. Preserve
        # unknown/name-like components verbatim; never infer their ruRU spelling.
        for word in quest_ai_review.WORD.findall(phrase):
            if word.casefold() not in ORDINARY and not quest_ai_review._noise(word):
                selected.add(word)
    return sorted(selected)


def enrich(api,conn,rows,locale):
    catalog,ambiguous=ai_context.glossary(api,conn,rows,locale,quest_context=True,
                                       additional_fields={'npc_text':api.npc_text.TEXT_FIELDS})
    lexicon=quest_ai_review.english_entity_lexicon(conn)
    result=copy.deepcopy(rows)
    for row in result:
        context=row['context']
        text=ai_context.relevant_text(row)
        context['terminology']=[t for t in catalog if ai_context.contains(text,t['english'])]
        context['terminology_ambiguous']=[t for t in ambiguous if ai_context.contains(text,t)]
        context['quality']=quality(row['english'],context.get('quality'))
        context['translation_instructions']=ai_context.INSTRUCTIONS
        review=candidates(row['english'],context['terminology'],lexicon)
        context['terminology_review_candidates']=review
        context['terminology_unproven']=[term for term in review if not any(
            ai_context.contains(t['english'],term) and ai_context.contains(row['english'],t['english'])
            for t in context['terminology'])]
    return result

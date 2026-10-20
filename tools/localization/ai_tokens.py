"""Strict, entity-specific token contracts for external translation staging."""
import re

# Preserve exact case. These operations are already recognized by the toolkit;
# this layer does not equate quest identity tokens with translation tokens.
WOW = re.compile(r'\$(?:[nNcCrRbB]|[0-9]+W?)')


def validate(api, kind, english, translation):
    if kind == 'creature_text':
        proof = api.creature_text_tokens.validate(english, translation)
        return {'valid': proof['status'] == 'SAFE', 'validator': 'creature_text_semantic_v1', **proof}
    if kind in ('skyfire_string', 'db_script_string'):
        return {'validator': 'runtime_printf_wow_v1', **api.skyfire_string.validate(english, translation)}
    # NPC and quest use an exact token contract, not chat semantic rewrites.
    # Unproved pipe/declension constructs require manual handling.
    proof = api.skyfire_string.validate(english, translation, wow_pattern=WOW)
    if proof['valid'] and proof['target_contract']['printf_forms'] != proof['translation_contract']['printf_forms']:
        proof = {**proof, 'valid': False, 'reason': 'printf representation changed'}
    # Preserve lexical escaping without assuming a new client escape grammar.
    escaped = re.compile(r'(\\+)(\$[A-Za-z0-9]|%)')
    if proof['valid'] and escaped.findall(english) != escaped.findall(translation):
        proof = {**proof, 'valid': False, 'reason': 'placeholder escaping changed'}
    if proof['valid'] and ('|' in english.replace('||', '') or '|' in translation.replace('||', '')):
        proof = {**proof, 'valid': False, 'reason': 'unproved pipe/declension contract'}
    if proof['valid'] and (english.count('%%') != translation.count('%%') or
                           english.count('||') != translation.count('||') or
                           english.count('\n') != translation.count('\n')):
        proof = {**proof, 'valid': False, 'reason': 'escaped literal or linebreak contract mismatch'}
    return {'validator': ('npc_text_exact_v1' if kind == 'npc_text' else 'quest_exact_v1' if kind == 'quest' else 'entity_exact_v1'), **proof}

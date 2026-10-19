#!/usr/bin/env python3
"""Offline indexing, comparison and safe localization SQL for SkyFire 5.4.8."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from contextvars import ContextVar
from contextlib import closing
from collections import deque
from pathlib import Path
from typing import Iterator, TextIO

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
import publishing
import reporting
import evidence_roles
import npc_text
import creature_text
import creature_text_tokens
import page_text
import points_of_interest
import skyfire_string
import db_script_string
import achievement_reward
import source_setup
import analytics
import sql_schema
import explicit_updates
WORKSPACE = ROOT / ".tmp" / "localization"
INDEX = WORKSPACE / "index" / "localization-index.sqlite3"
LOCALES = {
    "enUS": 0, "koKR": 1, "frFR": 2, "deDE": 3, "zhCN": 4, "zhTW": 5,
    "esES": 6, "esMX": 7, "ruRU": 8, "itIT": 9, "ptBR": 10, "ptPT": 11,
}
SKIP_DIRS = {"old", "pending", "archive", "archives", "deprecated", "legacy"}
SCAN_CONTEXT = ContextVar("localization_scan_context", default=None)

SPECS = {
    "item": {
        "source_table": "item_template_locale", "target_table": "locales_item",
        "target_entity": "item_template", "entity_fields": ("entry",),
        "identity": ("name",), "text_fields": {"name": "name", "description": "description"},
        "source_id": "id", "target_id": "entry", "source_locale": "locale",
        "source_target_fields": {"name": "name", "description": "description"},
        "wide_fields": {"name": "name_loc{n}", "description": "description_loc{n}"},
    },
    "gameobject": {
        "source_table": "gameobject_template_locale", "target_table": "locales_gameobject",
        "target_entity": "gameobject_template", "entity_fields": ("entry",),
        "identity": ("name", "type"), "text_fields": {"name": "name", "castbarcaption": "castbarcaption"},
        "source_id": "entry", "target_id": "entry", "source_locale": "locale",
        "source_target_fields": {"name": "name", "castbarcaption": "castbarcaption"},
        "wide_fields": {"name": "name_loc{n}", "castbarcaption": "castbarcaption_loc{n}"},
    },
    "gossip_menu_option": {
        "source_table": "gossip_menu_option_locale", "target_table": "gossip_menu_option_locale",
        "target_entity": "gossip_menu_option", "entity_fields": ("menuid", "optionid"),
        "identity": ("optionbroadcasttextid", "optiontext"),
        "text_fields": {"optiontext": "optiontext", "boxtext": "boxtext"},
        "source_id": ("menuid", "optionid"), "target_id": ("menuid", "optionid"), "source_locale": "locale",
        "source_target_fields": {"optiontext": "optiontext", "boxtext": "boxtext"},
        "wide_fields": {},
    },
}

# Fields verified against ObjectMgr loaders and GossipDef packets in SkyFire 5.4.8.
QUEST_TEXT = tuple('title details objectives offerrewardtext requestitemstext endtext completedtext questgivertextwindow questgivertargetname questturntextwindow questturntargetname'.split())
QUEST_ALIASES = dict(zip('logtitle questdescription logdescription areadescription questcompletionlog portraitgivertext portraitgivername portraitturnintext portraitturninname'.split(),
                         'title details objectives endtext completedtext questgivertextwindow questgivertargetname questturntextwindow questturntargetname'.split()))
CREATURE_STRUCT = ('type', 'unit_class', 'family', 'rank')
QUEST_STRUCT_ALIASES = {'questtype': 'method', 'questsortid': 'zoneorsort', 'questinfoid': 'type'}
for kind, entity, target, idcol, fields in (
        ('creature', 'creature_template', 'locales_creature', 'entry', ('name', 'subname')),
        ('quest', 'quest_template', 'locales_quest', 'id', QUEST_TEXT)):
    SPECS[kind] = {'source_table': entity + '_locale', 'target_table': target, 'target_entity': entity,
                   'entity_fields': (idcol,), 'source_id': idcol, 'target_id': idcol, 'source_locale': 'locale',
                   'text_fields': {f: f for f in fields}, 'source_target_fields': {f: f for f in fields},
                   'wide_fields': {f: f + '_loc{n}' for f in fields}}

SPECS['npc_text'] = {'source_table':'npc_text_locale', 'target_table':'locales_npc_text',
    'target_entity':'npc_text', 'entity_fields':('id',), 'source_id':'id', 'target_id':'id',
    'source_locale':'locale', 'text_fields':{f:f for f in npc_text.TEXT_FIELDS},
    'source_target_fields':{f:f for f in npc_text.TEXT_FIELDS},
    'wide_fields':{f:f+'_loc{n}' for f in npc_text.TEXT_FIELDS}}

SPECS['creature_text'] = {'source_table':'creature_text_locale', 'target_table':'locales_creature_text',
    'target_entity':'creature_text', 'entity_fields':creature_text.KEYS, 'source_id':creature_text.KEYS,
    'target_id':creature_text.KEYS, 'source_locale':'locale', 'text_fields':{'text':'text'},
    'source_target_fields':{'text':'text'}, 'wide_fields':{'text':'text_loc{n}'}}

SPECS['page_text'] = {'source_table':'page_text_locale', 'target_table':'locales_page_text',
    'target_entity':'page_text', 'entity_fields':('entry',), 'source_id':'entry', 'target_id':'entry',
    'source_locale':'locale', 'text_fields':{'text':'text'}, 'source_target_fields':{'text':'text'},
    'wide_fields':{'text':'Text_loc{n}'}}

SPECS['points_of_interest'] = {'source_table':'points_of_interest_locale', 'target_table':'locales_points_of_interest',
    'target_entity':'points_of_interest', 'entity_fields':('entry',), 'source_id':'entry', 'target_id':'entry',
    'source_locale':'locale', 'text_fields':{'icon_name':'icon_name'}, 'source_target_fields':{'icon_name':'icon_name'},
    'wide_fields':{'icon_name':'icon_name_loc{n}'}}

SPECS['skyfire_string'] = {'source_table':'trinity_string', 'target_table':'skyfire_string',
    'target_entity':'skyfire_string', 'entity_fields':('entry',), 'source_id':'entry', 'target_id':'entry',
    'source_locale':'locale', 'text_fields':{'content':'content'}, 'source_target_fields':{'content':'content'},
    'wide_fields':{'content':'content_loc{n}'}}

SPECS['db_script_string'] = {**SPECS['skyfire_string'], 'source_table':'db_script_string',
    'target_table':'db_script_string', 'target_entity':'db_script_string'}
SPECS['achievement_reward'] = {'source_table':'achievement_reward_locale', 'target_table':'locales_achievement_reward',
    'target_entity':'achievement_reward', 'entity_fields':('entry',), 'source_id':'id', 'target_id':'entry',
    'source_locale':'locale', 'text_fields':{'subject':'subject','text':'text'},
    'source_target_fields':{'subject':'subject','text':'text'},
    'wide_fields':{'subject':'subject_loc{n}','text':'text_loc{n}'}}
INLINE_STRING_TABLES = (*skyfire_string.TABLES, *db_script_string.TABLES)

# Internal quest parts; these are not separate CLI entity types.
QUEST_PARTS = {
    'quest_offer_reward': ('quest_offer_reward_locale', 'offerrewardtext', 'rewardtext'),
    'quest_request_items': ('quest_request_items_locale', 'requestitemstext', 'completiontext'),
    'quest_objective': ('quest_objective_locale', 'description', 'description'),
}
INTERNAL_SPECS = {kind: {'source_table': table, 'target_table': 'locales_quest_objective' if kind == 'quest_objective' else table,
                       'target_entity': kind, 'entity_fields': ('id',), 'source_id': 'id', 'target_id': 'id',
                       'source_locale': 'locale', 'text_fields': {field: field}, 'source_target_fields': {field: col}, 'wide_fields': {}}
                  for kind, (table, field, col) in QUEST_PARTS.items()}
INTERNAL_SPECS[npc_text.BROADCAST_KIND] = {'source_table':'broadcast_text_locale','target_table':'broadcast_text_locale',
    'target_entity':'broadcast_text','entity_fields':('id',),'source_id':'id','target_id':'id','source_locale':'locale',
    'text_fields':{'text':'text','text1':'text1'},'source_target_fields':{'text':'text','text1':'text1'},'wide_fields':{}}
ALL_SPECS = {**SPECS, **INTERNAL_SPECS}
REFERENCE_LOCALE_TABLES = {s['target_table']: k for k, s in ALL_SPECS.items()
                          if s['wide_fields'] or k == 'quest_objective'}
REFERENCE_LOCALE_TABLES['locales_gossip_menu_option'] = 'gossip_menu_option'


def locale_table_kind(table: str) -> str | None:
    if table in db_script_string.TABLES:
        return 'db_script_string'
    if table in skyfire_string.TABLES:
        return 'skyfire_string'
    if table in REFERENCE_LOCALE_TABLES:
        return REFERENCE_LOCALE_TABLES[table]
    if table == 'creature_template_wdb_locale':
        return 'creature'
    if table == 'quest_objectives_locale':
        return 'quest_objective'
    return next((k for k, s in ALL_SPECS.items() if table in (s['source_table'], s['target_table'])), None)


def canonical_row(kind: str, row: dict) -> dict:
    row = dict(row)
    if kind == 'achievement_reward':
        row = achievement_reward.canonical(row)
    if kind == 'points_of_interest':
        row = points_of_interest.canonical(row)
    if kind == 'page_text':
        row = page_text.canonical(row)
    if kind == 'creature_text':
        row = creature_text.canonical(row)
    if kind == 'npc_text':
        row = npc_text.canonical(row)
    if kind == npc_text.BROADCAST_KIND:
        row = npc_text.broadcast_canonical(row)
    if kind == 'creature' and 'title' in row:
        row['subname'] = row['title']
    if kind == 'creature' and 'npc_rank' in row:
        row['rank'] = row['npc_rank']
    if kind == 'quest':
        for alias, field in {**QUEST_ALIASES, **QUEST_STRUCT_ALIASES}.items():
            if alias in row:
                row[field] = row[alias]
    if kind == 'quest_objective' and 'storageindex' in row:
        row['index'] = row['storageindex']
    if kind == 'quest_offer_reward' and 'offerrewardtext' in row:
        row['rewardtext'] = row['offerrewardtext']
    if kind == 'quest_request_items' and 'requestitemstext' in row:
        row['completiontext'] = row['requestitemstext']
    return row

GOSSIP_FIELDS = {
    "optionbroadcasttextid": ("optionbroadcasttextid", "option_broadcast_text_id"),
    "boxbroadcasttextid": ("boxbroadcasttextid", "box_broadcast_text_id"),
    "optiontext": ("optiontext", "option_text"), "boxtext": ("boxtext", "box_text"),
    "optiontype": ("optiontype", "option_id"), "optionicon": ("optionicon", "option_icon"),
    "optionnpcflag": ("optionnpcflag", "npc_option_npcflag"),
    "actionmenuid": ("actionmenuid", "action_menu_id"), "actionpoiid": ("actionpoiid", "action_poi_id"),
    "boxcoded": ("boxcoded", "box_coded"), "boxmoney": ("boxmoney", "box_money"),
}
GO_FIELDS = {"type", "displayid", "name", "castbarcaption", "iconname", "unk1", "size", "faction", "flags", "ainame", "scriptname"} | {f"data{n}" for n in range(32)} | {f"questitem{n}" for n in range(1, 7)}
GO_ALIAS_RULES = {57708: ("lamp-post-57708", "Lamp Post", "Lamppost", 8),
                  170524: ("bench-bracket-170524", "Bench", "Bench]", 7)}
GOSSIP_ALIAS_RULES = {
    (0, 1): ("vendor-terminal-period", "I want to browse your goods.", "I want to browse your goods", 3370),
    (0, 3): ("trainer-terminal-punctuation", "Train me.", "Train me!", 3266),
    (0, 9): ("guild-crest-terminal-period", "I want to create a guild crest.", "I want to create a guild crest", 3415),
    (125, 0): ("astor-apostrophes-125", "You've got something I need, Astor. And I'll be taking it now.", "You''ve got something I need, Astor. And I''ll be taking it now.", 2591),
    (126, 0): ("astor-apostrophe-126", "You're Astor Hadren, right?", "You''re Astor Hadren, right?", 2589),
}


class Tokens:
    """Small-buffer SQL lexer; strings are tokenized one at a time from a stream."""
    def __init__(self, stream: TextIO):
        self.stream = stream
        self.variables: dict[str, object] = {}
        self.buf = ""
        self.pos = 0
        self.eof = False
        self.pushback: deque[tuple[str, str]] = deque()
        self.context_head = []
        self.context_tail = deque(maxlen=12)
        self.capture_context = False

    def _char(self) -> str:
        if self.pos >= len(self.buf):
            self.buf = self.stream.read(65536)
            self.pos = 0
            if not self.buf:
                self.eof = True
                return ""
        c = self.buf[self.pos]
        self.pos += 1
        return c

    def _peek(self) -> str:
        if self.pos >= len(self.buf):
            self.buf = self.stream.read(65536)
            self.pos = 0
            if not self.buf:
                self.eof = True
                return ""
        return self.buf[self.pos]

    def get(self) -> tuple[str, str]:
        token = self._next_token()
        if self.capture_context:
            value = repr(token[1][:96]) if token[0] == 'string' else token[1][:96]
            if len(self.context_head) < 6:
                self.context_head.append(value)
            self.context_tail.append(value)
        return token

    def statement_context(self) -> str:
        return ' '.join(self.context_head) + ' ... ' + ' '.join(self.context_tail)

    def _next_token(self) -> tuple[str, str]:
        if self.pushback:
            return self.pushback.popleft()
        while True:
            c = self._char()
            if not c:
                return ("eof", "")
            if c.isspace():
                continue
            if c == "#":
                while (c := self._char()) and c != "\n":
                    pass
                continue
            if c == "-" and self._peek() == "-":
                self._char()
                while (c := self._char()) and c != "\n":
                    pass
                continue
            if c == "/" and self._peek() == "*":
                self._char()
                prev = ""
                while (n := self._char()):
                    if prev == "*" and n == "/":
                        break
                    prev = n
                continue
            break
        if c in "'\"`":
            quote = c
            value = []
            raw = [quote]
            while True:
                n = self._char()
                raw.append(n)
                if not n:
                    break
                if n == "\\" and quote != "`":
                    esc = self._char()
                    raw.append(esc)
                    if not esc:
                        break
                    value.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}.get(esc, esc))
                elif n == quote:
                    if self._peek() == quote:
                        self._char()
                        raw.append(quote)
                        value.append(quote)
                    else:
                        break
                else:
                    value.append(n)
            decoded = "".join(value)
            return ("string", sql_schema.QuotedLiteral(decoded, "".join(raw))) if quote != "`" else ("word", decoded)
        if c in "<>!":
            operator = c
            if self._peek() == "=" or (c == "<" and self._peek() == ">"):
                operator += self._char()
            return ("word", operator)
        if c in "(),.;=":
            return (c, c)
        value = [c]
        while self._peek() and not self._peek().isspace() and self._peek() not in "(),.;=<>!'\"`#":
            value.append(self._char())
        return ("word", "".join(value))

    def unget(self, token: tuple[str, str]) -> None:
        self.pushback.appendleft(token)

    def skip_raw_statement(self) -> None:
        """Skip an unrelated SQL statement without allocating tokens for its rows."""
        self.pushback.clear()
        # mysqldump emits statement terminators at line ends. A C-level search
        # avoids Python per-character work across hundreds of MB of irrelevant rows.
        search = self.pos
        while True:
            end = self.buf.find(";\n", search)
            width = 2
            if end < 0:
                end = self.buf.find(";\r\n", search)
                width = 3
            if end >= 0:
                following = self.buf[end + width:]
                if not following and not self.eof:
                    more = self.stream.read(4096)
                    self.buf = self.buf[end + width:] + more
                    self.pos = 0
                    self.eof = not bool(more)
                    search = 0
                    continue
                if re.match(r"\s*(?:INSERT|REPLACE|UPDATE|DELETE|CREATE|DROP|ALTER|LOCK|UNLOCK|SET|START|COMMIT|--|#|/\*|$)", following, re.I):
                    self.buf = self.buf[end + width:]
                    self.pos = 0
                    return
                search = end + 1
                continue
            # Keep a short overlap so a terminator split across chunk boundaries is found.
            overlap = self.buf[max(self.pos, len(self.buf) - 4):]
            more = self.stream.read(65536)
            if not more:
                self.eof = True
                break
            self.buf = overlap + more
            self.pos = 0
            search = 0
        quote = ""
        while True:
            if self.pos >= len(self.buf):
                self.buf = self.stream.read(65536)
                self.pos = 0
                if not self.buf:
                    self.eof = True
                    return
            if quote:
                end = self.buf.find(quote, self.pos)
                if end < 0:
                    self.pos = len(self.buf)
                    continue
                slashes = 0
                j = end - 1
                while j >= self.pos and self.buf[j] == "\\":
                    slashes += 1
                    j -= 1
                if quote != "`" and slashes % 2:
                    self.pos = end + 1
                    continue
                if end + 1 < len(self.buf) and self.buf[end + 1] == quote:
                    self.pos = end + 2
                    continue
                self.pos = end + 1
                quote = ""
                continue
            if not quote:
                positions = [p for p in (self.buf.find(";", self.pos), self.buf.find("'", self.pos), self.buf.find('"', self.pos), self.buf.find("`", self.pos), self.buf.find("#", self.pos), self.buf.find("/", self.pos), self.buf.find("-", self.pos)) if p >= 0]
                if not positions:
                    self.pos = len(self.buf)
                    continue
                self.pos = min(positions)
            c = self._char()
            if c in ("'", '"', "`"):
                quote = c
            elif c == "#":
                while (n := self._char()) and n != "\n":
                    pass
            elif c == "/" and self._peek() == "*":
                self._char()
                prev = ""
                while (n := self._char()):
                    if prev == "*" and n == "/":
                        break
                    prev = n
            elif c == "-" and self._peek() == "-":
                self._char()
                while (n := self._char()) and n != "\n":
                    pass
            elif c == ";":
                return

    def skip_raw_tuple(self) -> None:
        """Skip remaining values of a tuple after its identity prefix was read."""
        self.pushback.clear()
        quote = ""
        depth = 0
        while True:
            if self.pos >= len(self.buf):
                self.buf = self.stream.read(65536)
                self.pos = 0
                if not self.buf:
                    self.eof = True
                    return
            if quote:
                end = self.buf.find(quote, self.pos)
                if end < 0:
                    self.pos = len(self.buf)
                    continue
                slashes = 0
                j = end - 1
                while j >= self.pos and self.buf[j] == "\\":
                    slashes += 1
                    j -= 1
                if quote != "`" and slashes % 2:
                    self.pos = end + 1
                    continue
                if end + 1 < len(self.buf) and self.buf[end + 1] == quote:
                    self.pos = end + 2
                    continue
                self.pos = end + 1
                quote = ""
                continue
            if not quote:
                positions = [p for p in (self.buf.find("'", self.pos), self.buf.find('"', self.pos), self.buf.find("`", self.pos), self.buf.find("(", self.pos), self.buf.find(")", self.pos), self.buf.find("#", self.pos), self.buf.find("/", self.pos), self.buf.find("-", self.pos)) if p >= 0]
                if not positions:
                    self.pos = len(self.buf)
                    continue
                self.pos = min(positions)
            c = self._char()
            if c in ("'", '"', "`"):
                quote = c
            elif c == "#":
                while (n := self._char()) and n != "\n":
                    pass
            elif c == "/" and self._peek() == "*":
                self._char()
                prev = ""
                while (n := self._char()):
                    if prev == "*" and n == "/":
                        break
                    prev = n
            elif c == "-" and self._peek() == "-":
                self._char()
                while (n := self._char()) and n != "\n":
                    pass
            elif c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    return
                depth -= 1


def source_definitions() -> dict[str, dict]:
    """Discover inputs and explicit local evidence roles; names never imply trust."""
    result = {}
    core = ROOT / 'externals/core'
    if any((core / part).is_dir() for part in ('repo', 'db')):
        result['target'] = {'path': core, 'role': 'target', 'alias_role': None}
    references = ROOT / 'externals/references'
    if references.is_dir():
        for directory in sorted(references.iterdir(), key=lambda p: p.name):
            if not directory.is_dir() or directory.is_symlink() or directory.name.casefold() in SKIP_DIRS or directory.name.startswith('.'):
                continue
            source = directory.name
            if source.casefold() == 'target' or any(ord(c) < 32 for c in source):
                raise RuntimeError(f'Invalid or reserved reference source ID: {source!r}')
            if not any((directory / part).is_dir() for part in ('repo', 'db')):
                continue
            config_file = directory / 'source.json'
            config = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
            if not isinstance(config, dict) or set(config) - {'alias_role', 'evidence_role', 'evidence_family', 'inputs', 'exclude'} or config.get('alias_role') not in (None, 'origin', 'corroborator'):
                raise RuntimeError(f'Invalid optional evidence role configuration: {config_file}')
            source_setup.validate_family(config)
            if not isinstance(config.get('evidence_role'), str) or config['evidence_role'] not in evidence_roles.ROLES:
                raise RuntimeError(f'{source}: source.json requires explicit evidence_role (primary, supplemental, code_schema): {config_file}')
            if config.get('alias_role') and config['evidence_role'] != 'primary':
                raise RuntimeError(f'{source}: alias_role requires PRIMARY evidence')
            if 'inputs' in config or 'exclude' in config:
                source_setup.resolve_config(directory, config, SKIP_DIRS)
            result[source] = {'path': directory, 'role': 'reference', 'alias_role': config.get('alias_role'),
                              'evidence_role': config['evidence_role'], 'config_fingerprint': evidence_roles.fingerprint(config), 'config':config}
    roles = [value['alias_role'] for value in result.values() if value['alias_role']]
    if len(roles) != len(set(roles)):
        raise RuntimeError('Duplicate alias evidence roles; require at most one origin and one corroborator')
    return result


def register_sources(conn: sqlite3.Connection) -> None:
    for source, definition in source_definitions().items():
        conn.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?)', (source, definition['role'], definition['alias_role']))
        if source != 'target':
            evidence_roles.register(conn, source, definition['evidence_role'], definition['config_fingerprint'])


def all_reference_sources(conn: sqlite3.Connection) -> tuple[str, ...]:
    registered = conn.execute("SELECT source FROM sources WHERE role='reference' ORDER BY source").fetchall()
    if registered:
        return tuple(row[0] for row in registered)
    rows = conn.execute("SELECT DISTINCT source FROM entities WHERE source<>'target' UNION SELECT DISTINCT source FROM records WHERE source<>'target' UNION SELECT DISTINCT source FROM files WHERE source<>'target' ORDER BY source")
    return tuple(row[0] for row in rows)


def reference_sources(conn: sqlite3.Connection) -> tuple[str, ...]:
    return evidence_roles.sources(conn, 'primary')


def data_reference_sources(conn):
    return tuple(s for s, info in evidence_roles.profile(conn).items()
                 if info['evidence_role'] in ('primary', 'supplemental'))


def alias_reference_pair(conn: sqlite3.Connection) -> tuple[str, str] | None:
    refs = reference_sources(conn)
    rows = [(source, role) for source, role in conn.execute(
        "SELECT source,alias_role FROM sources WHERE role='reference' AND alias_role IS NOT NULL") if source in refs]
    roles = {role: source for source, role in rows}
    if len(rows) != 2 or set(roles) != {'origin', 'corroborator'}:
        return None
    return roles['origin'], roles['corroborator']


def excluded_sql_input(path: Path, member: str | None = None) -> bool:
    """Reject excluded path segments, including physical aliases and ZIP members."""
    for candidate, root in ((path.absolute(), ROOT.absolute()), (path.resolve(), ROOT.resolve())):
        try:
            parts = candidate.relative_to(root).parts
        except ValueError:
            return True  # Inputs must remain within the local external workspace.
        if any(part.casefold() in SKIP_DIRS for part in parts):
            return True
    return bool(member and any(part.casefold() in SKIP_DIRS
                               for part in member.replace('\\', '/').split('/')[:-1]))


def active_files() -> list[tuple[str, Path, str | None]]:
    result = []
    for source, definition in source_definitions().items():
        if definition.get('evidence_role') == 'code_schema':
            continue
        root=definition['path']
        config=definition.get('config')
        try:
            rows=(source_setup.resolve_config(root,config,SKIP_DIRS) if config
                  else source_setup.discover(root,SKIP_DIRS)['inputs'])
        except (OSError,zipfile.BadZipFile,ValueError) as exc:
            raise RuntimeError(f"Source inputs invalid: source={source} path={root}: {exc}") from exc
        for row in rows:
            path=root/row['path'];member=row.get('member')
            if not excluded_sql_input(path,member):
                result.append((source,path,member))
    # Source base snapshots, then full/release db dumps, then ordered updates.
    def order(entry: tuple[str, Path, str | None]) -> tuple[str, int, str, str]:
        original = entry[1].relative_to(ROOT).as_posix()
        rel = original.casefold()
        if "/repo/sql/base/" in rel:
            rank = 0
        elif "/db/" in rel:
            rank = 1
        else:
            rank = 2
        ref = original + ("!" + entry[2] if entry[2] else "")
        return entry[0], rank, ref.casefold(), ref
    return sorted(result, key=order)


def source_revision(source: str) -> str | None:
    # Do not report the parent workspace SHA as an upstream source revision.
    source_repo = ROOT / 'externals' / ('core' if source == 'target' else 'references/' + source) / 'repo'
    if not (source_repo / ".git").exists():
        return None
    try:
        result = subprocess.run(["git", "-C", str(source_repo), "rev-parse", "--verify", "HEAD"],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", revision) else None


def open_sql(path: Path, member: str | None) -> TextIO:
    if member is not None:
        zf = zipfile.ZipFile(path)
        # Attach the archive lifetime to the returned wrapper.
        raw = zf.open(member)
        import io
        wrapper = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        wrapper._localize_zip = zf  # type: ignore[attr-defined]
        return wrapper
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")


def db_connect(path: Path = INDEX) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS records (
        source TEXT NOT NULL, kind TEXT NOT NULL, entity TEXT NOT NULL, locale TEXT NOT NULL,
        fields TEXT NOT NULL, file TEXT NOT NULL, rank INTEGER NOT NULL,
        PRIMARY KEY(source, kind, entity, locale))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS entities (
        source TEXT NOT NULL, kind TEXT NOT NULL, entity TEXT NOT NULL,
        fields TEXT NOT NULL, file TEXT NOT NULL, rank INTEGER NOT NULL,
        PRIMARY KEY(source, kind, entity))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS files (
        source TEXT NOT NULL, file TEXT NOT NULL, bytes INTEGER NOT NULL,
        status TEXT NOT NULL, PRIMARY KEY(source,file))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS warnings (
        source TEXT NOT NULL, file TEXT NOT NULL, message TEXT NOT NULL)""")
    conn.execute("CREATE TABLE IF NOT EXISTS gossip_boxes(source TEXT,entity TEXT,boxtext TEXT,file TEXT,PRIMARY KEY(source,entity))")
    conn.execute("CREATE TABLE IF NOT EXISTS gossip_aux(source TEXT,entity TEXT,table_name TEXT,fields TEXT,file TEXT,PRIMARY KEY(source,entity,table_name))")
    conn.execute('CREATE TABLE IF NOT EXISTS sources(source TEXT PRIMARY KEY,role TEXT NOT NULL,alias_role TEXT)')
    evidence_roles.create_schema(conn)
    sql_schema.create_schema(conn)
    skyfire_string.create_schema(conn)
    db_script_string.create_schema(conn)
    points_of_interest.create_schema(conn)
    conn.execute('CREATE TABLE IF NOT EXISTS record_origins(source TEXT,kind TEXT,entity TEXT,locale TEXT,table_name TEXT,PRIMARY KEY(source,kind,entity,locale))')
    conn.execute('CREATE TABLE IF NOT EXISTS invalid_values(source TEXT,kind TEXT,entity TEXT,locale TEXT,field TEXT,value TEXT,file TEXT,table_name TEXT,reason TEXT,rank INTEGER,PRIMARY KEY(source,kind,entity,locale,field))')
    conn.execute('CREATE INDEX IF NOT EXISTS invalid_values_entity_idx ON invalid_values(kind,entity,locale)')
    conn.execute("CREATE INDEX IF NOT EXISTS entities_name_idx ON entities(source,kind,json_extract(fields,'$.name'))")
    conn.execute("CREATE INDEX IF NOT EXISTS quest_objectives_parent_idx ON entities(kind,source,json_extract(fields,'$.questid'))")
    conn.execute("CREATE INDEX IF NOT EXISTS quest_objectives_all_parents_idx ON entities(kind,json_extract(fields,'$.questid'))")
    conn.execute('CREATE TABLE IF NOT EXISTS source_schemas(source TEXT,table_name TEXT,columns TEXT,primary_key TEXT,file TEXT,PRIMARY KEY(source,table_name))')
    conn.execute('CREATE TABLE IF NOT EXISTS creature_parts(source TEXT,table_name TEXT,entity TEXT,fields TEXT,file TEXT,rank INTEGER,PRIMARY KEY(source,table_name,entity))')
    conn.execute('CREATE INDEX IF NOT EXISTS creature_parts_entity_idx ON creature_parts(source,entity)')
    conn.execute('CREATE TABLE IF NOT EXISTS parser_diagnostics(source TEXT,file TEXT,table_name TEXT,entity TEXT,reason TEXT,affected_row TEXT)')
    conn.execute('CREATE INDEX IF NOT EXISTS warnings_dedup_idx ON warnings(source,file,message)')
    conn.execute('CREATE INDEX IF NOT EXISTS diagnostics_dedup_idx ON parser_diagnostics(source,file,table_name,entity,reason,affected_row)')
    return conn


def qid(t: Tokens) -> str:
    token = t.get()
    if token[0] not in ("word", "string"):
        return ""
    name = token[1]
    if t.get()[0] == ".":
        return t.get()[1].lower()
    # The token after a bare identifier wasn't a dot.
    # Caller needs this helper to preserve non-dot lookahead.
    return name.lower()


def next_name(t: Tokens) -> str:
    # Consume identifier with optional database qualifier.
    a = t.get()
    while a[0] in ("word", "string") and a[1].upper() in {"IF", "NOT", "EXISTS", "TEMPORARY"}:
        a = t.get()
    if a[0] not in ("word", "string"):
        return ""
    name = a[1].lower()
    p = t.get()
    if p[0] == ".":
        name = t.get()[1].lower()
    else:
        t.unget(p)
    return name


def skip_statement(t: Tokens) -> None:
    while True:
        x = t.get()
        if x[0] in (";", "eof"):
            return


def parse_create(t: Tokens, source: str, file: str, schemas: dict[tuple[str, str], list[str]], conn=None) -> None:
    # CREATE [TEMPORARY] TABLE [IF NOT EXISTS] name (...)
    tok = t.get()
    if tok[1].upper() == "TEMPORARY":
        tok = t.get()
    if tok[1].upper() != "TABLE":
        t.unget(tok)
        return
    name = next_name(t)
    if not name:
        skip_statement(t)
        return
    if name not in TARGET_TABLES:
        t.skip_raw_statement()
        return
    if conn is not None:
        # CREATE LIKE/AS SELECT must not inherit an unrelated earlier column proof.
        conn.execute("DELETE FROM source_column_types WHERE source=? AND table_name=?", (source, name))
        current = SCAN_CONTEXT.get()
        if current:
            getattr(current[1], "integer_plans", {}).pop(name, None)
    if t.get()[0] != "(":
        skip_statement(t)
        return
    depth, cols, segment, segments = 1, [], [], []
    def is_column(segment):
        first = segment[0][1].lower()
        if first == 'index' and len(segment) > 1 and segment[1][1].lower() in ('tinyint', 'smallint', 'mediumint', 'int', 'bigint'):
            return True  # `index` is a real quest_objective column, not an INDEX definition.
        return segment[0][0] == 'word' and first not in {'primary', 'unique', 'key', 'index', 'constraint', 'foreign', 'fulltext', 'spatial'}
    while depth:
        x = t.get()
        if x[0] == "eof":
            break
        if x[0] == "(":
            depth += 1
        elif x[0] == ")":
            depth -= 1
            if depth == 0:
                if segment:
                    segments.append(segment)
                    first = segment[0][1].lower()
                    if is_column(segment):
                        cols.append(first)
                break
        if x[0] == "," and depth == 1:
            if segment:
                segments.append(segment)
                first = segment[0][1].lower()
                if is_column(segment):
                    cols.append(first)
            segment = []
        else:
            segment.append(x)
    schemas[(source, name)] = cols
    if conn is not None:
        for segment in segments:
            context = sql_schema.column_type(segment) if is_column(segment) else None
            if context:
                conn.execute("INSERT INTO source_column_types VALUES(?,?,?,?,?)",
                             (source, name, segment[0][1].lower(), json.dumps(context, sort_keys=True), file))
        primary = []
        for part in segments:
            if [x[1].upper() for x in part[:2]] == ['PRIMARY', 'KEY']:
                primary = [x[1].lower() for x in part[2:] if x[0] == 'word']
        conn.execute('INSERT OR REPLACE INTO source_schemas VALUES(?,?,?,?,?)',
                     (source, name, json.dumps(cols), json.dumps(primary), file))
    skip_statement(t)


def literal_tuple(t: Tokens, *, defer_unresolved=False) -> list[object]:
    # Deferred cells are never persisted; INSERT dependency classification owns them.
    def value(expression):
        try:
            value = sql_value(expression,t.variables)
            if len(expression) == 1 and expression[0][0] == "string":
                return sql_schema.QuotedLiteral(value, getattr(expression[0][1], "literal", None))
            return value
        except UnresolvedVariableError as exc:
            if not defer_unresolved:raise
            return UnresolvedCell(tuple(expression),str(exc))
    values: list[object] = []
    expr: list[tuple[str, str]] = []
    depth = 0
    while True:
        x = t.get()
        if x[0] == "eof":
            break
        if x[0] == "(" :
            depth += 1
            expr.append(x)
        elif x[0] == ")":
            if depth:
                depth -= 1
                expr.append(x)
            else:
                values.append(value(expr))
                break
        elif x[0] == "," and depth == 0:
            values.append(value(expr))
            expr = []
        else:
            expr.append(x)
    return values


@dataclass(frozen=True)
class UnresolvedVariable:
    """Known assignment whose expression is never executed or guessed."""
    variable: str
    expression: str
    reason: str
    assignment: str
    source: str = ""
    file: str = ""
    pass_name: str = ""
    status: str = "UNRESOLVED"


@dataclass(frozen=True)
class UnresolvedCell:
    expression: tuple
    diagnostic: str


class UnresolvedVariableError(ValueError):
    """A relevant key/value requires an unavailable variable value."""


def sql_value(expr: list[tuple[str, str]], variables: dict[str, object] | None = None) -> object:
    # Even unsupported compound values must not hide an unresolved dependency.
    # Quoted strings are literal content, never variable references.
    if len(expr) != 1:
        for token_kind, token_value in expr:
            if token_kind != 'string':
                for name in re.findall(r'(?<!@)@[A-Za-z_][A-Za-z_0-9]*', token_value):
                    if variables and isinstance(variables.get(name.casefold()), UnresolvedVariable):
                        sql_value([('word', name)], variables)
    if len(expr) == 1:
        kind, val = expr[0]
        if kind == "string":
            return str(val)
        if val.startswith("@"):
            if re.fullmatch(r"@[A-Za-z_][A-Za-z_0-9]*[+*\-].+",val):
                return integer_expression(val,variables or {})
            if variables is None or val.casefold() not in variables:
                raise ValueError(f"неопределённая SQL-переменная: {val}")
            value = variables[val.casefold()]
            if isinstance(value, UnresolvedVariable):
                raise UnresolvedVariableError(
                    f"unresolved SQL variable={val} assignment_source={value.source} "
                    f"assignment_file={value.file} assignment_pass={value.pass_name} "
                    f"assignment={value.assignment} expression={value.expression}: {value.reason}")
            return value
        up = val.upper()
        if up == "NULL":
            return None
        if up in ("TRUE", "FALSE"):
            return 1 if up == "TRUE" else 0
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val
    combined = "".join(x[1] for x in expr)
    if re.fullmatch(r"[-+]?\d+\.\d+", combined):
        return float(combined)
    return combined


def normalized_row(source: str, table: str, cols: list[str], vals: list[object]) -> tuple[str, str, str, dict[str, object]] | None:
    kind = locale_table_kind(table)
    if not kind:
        return None
    spec = ALL_SPECS[kind]
    if not cols or len(cols) != len(vals):
        return None
    row = canonical_row(kind, {str(c).lower(): v for c, v in zip(cols, vals)})
    # Source row-style localization.
    if table == spec["source_table"] or table in ('quest_objectives_locale', 'creature_template_wdb_locale') or kind == 'quest_objective':
        if kind == "gossip_menu_option":
            entity = (row.get("menuid"), row.get("optionid", row.get("optionindex", row.get("id"))))
        elif kind == "creature_text":
            entity = creature_text.key(row)
        else:
            entity = row.get("id" if table == "creature_template_wdb_locale" else spec["source_id"])
        locale = row.get(spec["source_locale"])
        if kind == 'quest_objective' and isinstance(locale, int):
            locale = next((code for code, n in LOCALES.items() if n == locale), None)
        if not valid_entity_key(kind, entity) or locale not in LOCALES:
            return None
        fields = {key: row.get(col) for key, col in spec["source_target_fields"].items()}
        if kind == 'achievement_reward' and row.get('_evidence_incomplete'):
            fields['_schema_unsupported'] = True
        if table == 'creature_template_wdb_locale':
            entity = row.get('id')
            if not valid_entity_key(kind, entity):
                return None
            fields = {'name': row.get('name1'), 'subname': row.get('title')}
        return kind, json.dumps(entity, ensure_ascii=False), str(locale), fields
    # SkyFire wide table: only non-enUS localized slots are represented here.
    if kind == "gossip_menu_option":
        return None
    entity = creature_text.key(row) if kind == "creature_text" else row.get(spec["target_id"])
    if entity is None:
        return None
    for locale, index in LOCALES.items():
        if index == 0:
            continue
        fields = {}
        for canonical, pattern in spec["wide_fields"].items():
            col = pattern.format(n=index).lower()
            value = row.get(col)
            if value not in (None, ""):
                fields[canonical] = value
        if fields:
            # One INSERT row can populate multiple locales; caller expands below.
            pass
    return kind, json.dumps(entity, ensure_ascii=False), "__wide__", row


def identity_fields(kind: str, row: dict[str, object]) -> dict[str, object]:
    row = canonical_row(kind, row)
    if kind == 'achievement_reward':
        return {k:row[k] for k in ('entry', *achievement_reward.STRUCT, *achievement_reward.FIELDS, *achievement_reward.EXTRA_DEFAULTS, '_evidence_incomplete') if k in row}
    if kind == 'points_of_interest':
        return {k:row[k] for k in (*points_of_interest.BASE_FIELDS, '_evidence_incomplete') if k in row}
    if kind in ('skyfire_string','db_script_string'):
        return {'content':row['content_default']} if 'content_default' in row else {}
    if kind == 'page_text':
        return {k:row[k] for k in ('text', 'next_page', '_evidence_incomplete') if k in row}
    if kind == 'creature_text':
        return {k:row[k] for k in ('text', *creature_text.STRUCT, 'textrange','broadcasttextid','soundtype','mintimer','maxtimer','spellid') if k in row}
    if kind == 'npc_text':
        return {k:v for k,v in row.items() if k != 'id'}
    if kind == npc_text.BROADCAST_KIND:
        return {k:row[k] for k in ('text','text1','languageid') if k in row}
    if kind == 'creature':
        return {k: row[k] for k in ('name', 'subname', *CREATURE_STRUCT) if k in row}
    if kind == 'quest':
        return {k: row[k] for k in (*QUEST_TEXT, 'minlevel', 'method', 'zoneorsort', 'type') if k in row}
    if kind == 'quest_objective':
        return {k: row[k] for k in ('questid', 'type', 'objectid', 'amount', 'flags', 'description', 'index') if k in row}
    if kind in QUEST_PARTS:
        field, col = QUEST_PARTS[kind][1:]
        return {field: row[col]} if col in row else {}
    if kind == "gossip_menu_option":
        fields = {}
        for canonical, aliases in GOSSIP_FIELDS.items():
            for alias in aliases:
                if alias in row:
                    fields[canonical] = row[alias]
                    break
        return fields
    if kind == "item":
        return {k: row.get(k) for k in ("name", "class", "subclass", "description") if k in row}
    return {k: row[k] for k in sorted(GO_FIELDS) if k in row}


def valid_entity_key(kind, key):
    if kind == 'db_script_string':
        return type(key) is int and db_script_string.MIN_ENTRY <= key < db_script_string.MAX_ENTRY
    if kind in ('skyfire_string','db_script_string'):
        return type(key) is int and 1 <= key < 2000000000
    if kind == 'points_of_interest':
        return type(key) is int and key > 0
    if kind == 'page_text':
        return type(key) is int and key > 0
    if kind == 'npc_text' and key == 0:
        return False  # LoadGossipText reserves zero.
    if kind == 'creature_text':
        return isinstance(key,(tuple,list)) and len(key)==3 and all(type(v) is int and v>=0 for v in key) and key[0]>0 and key[1]<=255 and key[2]<=255
    parts = key if kind == 'gossip_menu_option' and isinstance(key, (tuple, list)) else (key,)
    return (kind != 'gossip_menu_option' or len(parts) == 2) and all(type(v) is int and v >= 0 for v in parts)


def schema_warning(conn, source, file, table, kind, reason, key=None, row=None, *, emit_warning=True):
    affected = json.dumps({'key': key, 'row': row}, ensure_ascii=False, sort_keys=True)
    message = f'SCHEMA {table} entity={kind} key={json.dumps(key)}: {reason}'
    if emit_warning:
        parser_warning(conn, source, file, message)
    conn.execute('INSERT INTO parser_diagnostics SELECT ?,?,?,?,?,? WHERE NOT EXISTS '
                 '(SELECT 1 FROM parser_diagnostics WHERE source=? AND file=? AND table_name=? AND entity=? AND reason=? AND affected_row=?)',
                 (source, file, table, kind, reason, affected, source, file, table, kind, reason, affected))


def persist_entity(conn: sqlite3.Connection, source: str, kind: str, row: dict[str, object], file: str, rank: int, table_name: str | None = None) -> None:
    if kind == 'achievement_reward':
        row = achievement_reward.canonical(row)
    if kind == 'points_of_interest':
        row = points_of_interest.canonical(row)
    if kind == 'page_text':
        row = page_text.canonical(row)
    spec = ALL_SPECS[kind]
    if kind == "gossip_menu_option":
        ident = (row.get("menuid", row.get("menu_id")), row.get("optionid", row.get("optionindex", row.get("id"))))
    elif kind == "creature_text":
        ident = creature_text.key(row)
    else:
        ident = row.get(spec["entity_fields"][0])
    if not valid_entity_key(kind, ident):
        schema_warning(conn, source, file, table_name or spec['target_entity'], kind, 'incomplete or invalid entity key; row rejected', ident, row)
        return
    fields = identity_fields(kind, row)
    if not fields:
        schema_warning(conn, source, file, table_name or spec['target_entity'], kind, 'missing base identity fields; row rejected', ident, row)
        return
    required = {'creature': {'name', 'type', 'unit_class'}, 'quest': {'title', 'objectives', 'details', 'minlevel'}, 'creature_text': {'text', *creature_text.STRUCT}, 'page_text': {'text', 'next_page'}, 'points_of_interest': set(points_of_interest.BASE_FIELDS), 'achievement_reward': {'entry', *achievement_reward.STRUCT}}.get(kind, set())
    if kind == 'achievement_reward':
        fields['_english_provenance'] = {f:{'file':file,'table':table_name or spec['target_entity'],
            'field':'body' if f=='text' and 'body' in row else f} for f in achievement_reward.FIELDS if f in fields}
    if kind in ('skyfire_string','db_script_string'):
        fields['_english_provenance'] = {'content':{'file':file,'table':table_name or SPECS[kind]['target_entity'],'field':'content_default'}}
    missing = sorted(required - set(fields))
    if missing:
        fields['_evidence_incomplete'] = 1
        schema_warning(conn, source, file, table_name or spec['target_entity'], kind, 'incomplete base identity: missing ' + ', '.join(missing), ident, row)
    conn.execute("INSERT INTO entities VALUES(?,?,?,?,?,?) ON CONFLICT(source,kind,entity) DO UPDATE SET fields=excluded.fields,file=excluded.file,rank=excluded.rank WHERE excluded.rank>=entities.rank",
                 (source, kind, json.dumps(ident, ensure_ascii=False), json.dumps(fields, ensure_ascii=False), file, rank))


def persist_locale(conn: sqlite3.Connection, source: str, kind: str, entity: str, locale: str, fields: dict[str, object], file: str, rank: int, table_name: str | None = None) -> None:
    if not valid_entity_key(kind, json.loads(entity)):
        schema_warning(conn, source, file, table_name or ALL_SPECS[kind]['source_table'], kind, 'incomplete or invalid entity key; row rejected', json.loads(entity), fields)
        return
    if source != 'target' and locale == 'ruRU':
        existing_rank = conn.execute('SELECT max(rank) FROM (SELECT rank FROM records WHERE source=? AND kind=? AND entity=? AND locale=? UNION ALL SELECT rank FROM invalid_values WHERE source=? AND kind=? AND entity=? AND locale=?)',
                                     (source, kind, entity, locale, source, kind, entity, locale)).fetchone()[0]
        if existing_rank is not None and existing_rank > rank:
            return
    clean = {k: v for k, v in fields.items() if v not in (None, "")}
    for field, value in fields.items():
        if source != 'target' and locale == 'ruRU' and isinstance(value, str) and looks_mojibake(value):
            reason = 'suspected mojibake; source value excluded without repair'
            conn.execute('INSERT INTO invalid_values VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,kind,entity,locale,field) DO UPDATE SET value=excluded.value,file=excluded.file,table_name=excluded.table_name,reason=excluded.reason,rank=excluded.rank WHERE excluded.rank>=invalid_values.rank',
                         (source, kind, entity, locale, field, value, file, table_name or ALL_SPECS[kind]['source_table'], reason, rank))
            parser_warning(conn, source, file, f'INVALID LOCALE {kind} {entity} {locale} {field}: {reason}', table_name=table_name)
            clean.pop(field, None)
        elif source != 'target' and locale == 'ruRU':
            conn.execute('DELETE FROM invalid_values WHERE source=? AND kind=? AND entity=? AND locale=? AND field=? AND rank<=?',
                         (source, kind, entity, locale, field, rank))
    if kind == 'points_of_interest':
        points_of_interest.persist_variant(conn,source,entity,locale,clean,file,rank,table_name or ALL_SPECS[kind]['source_table'])
    if not clean:
        conn.execute("DELETE FROM records WHERE source=? AND kind=? AND entity=? AND locale=? AND rank<=?",
                     (source, kind, entity, locale, rank))
        return
    conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,kind,entity,locale) DO UPDATE SET fields=excluded.fields,file=excluded.file,rank=excluded.rank WHERE excluded.rank>=records.rank",
                 (source, kind, entity, locale, json.dumps(clean, ensure_ascii=False), file, rank))
    if table_name:
        conn.execute('INSERT OR REPLACE INTO record_origins VALUES(?,?,?,?,?)', (source,kind,entity,locale,table_name))


def looks_mojibake(value: str) -> bool:
    # Repeated UTF-8-as-Western-byte lead characters and replacement characters
    # are invalid evidence, not candidates for automatic reverse decoding.
    return '\ufffd' in value or len(re.findall(r'[\u00d0\u00d1][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2010-\u203a\u20ac\u2122]', value)) >= 2


def invalid_locale_values(conn, kind, entity, locale, *, all_sources=False):
    kinds = (kind, 'quest_offer_reward', 'quest_request_items') if kind == 'quest' else (kind,)
    try:
        rows = list(conn.execute('SELECT source,kind,entity,field,value,file,table_name,reason FROM invalid_values WHERE kind IN (' + ','.join('?' for _ in kinds) + ') AND entity=? AND locale=? ORDER BY source,kind,field', (*kinds, entity, locale)))
        if kind == 'quest':
            rows += list(conn.execute("SELECT i.source,i.kind,i.entity,i.field,i.value,i.file,i.table_name,i.reason FROM entities e CROSS JOIN invalid_values i WHERE e.kind='quest_objective' AND json_extract(e.fields,'$.questid')=? AND i.source=e.source AND i.kind=e.kind AND i.entity=e.entity AND i.locale=? ORDER BY i.source,i.entity", (json.loads(entity), locale)))
    except sqlite3.OperationalError as exc:
        if 'no such table: invalid_values' in str(exc):
            return []  # Older local indexes remain readable until rebuilt.
        raise
    allowed = {"target", *(data_reference_sources(conn) if all_sources else reference_sources(conn))}
    return [{'source': s, 'kind': k, 'entity_key': json.loads(key), 'field': 'objective:' + key if k == 'quest_objective' and kind == 'quest' else field,
             'value': value, 'file': file, 'table': table, 'reason': reason, 'status': 'UNSUPPORTED'}
            for s, k, key, field, value, file, table, reason in rows if s in allowed]


def reference_locale_plan(table: str, cols: list[str]) -> tuple[str, tuple[str, ...], dict[str, tuple[str, str]]] :
    """Validate a supported schema and explicit locale slots before importing rows."""
    kind = REFERENCE_LOCALE_TABLES[table]
    keys = ('menu_id', 'id') if kind == 'gossip_menu_option' else tuple(next((col for col in cols if creature_text.ALIASES.get(col,col)==key),key) for key in creature_text.KEYS) if kind == 'creature_text' else (ALL_SPECS[kind]['target_id'],)
    if kind == 'points_of_interest':
        keys=(next((k for k in ('entry','id') if k in cols),'entry'),)
    if not cols or len(cols) != len(set(cols)) or not set(keys).issubset(cols):
        raise ValueError('missing/duplicate entity key columns')
    if kind == 'quest_objective':
        if set(cols) - {'verifiedbuild'} != {'id', 'locale', 'description'}:
            raise ValueError('expected id, locale, description schema')
        return kind, keys, {'description': ('description', 'row')}
    patterns = ({'optiontext': 'option_text_loc{n}', 'boxtext': 'box_text_loc{n}'}
                if kind == 'gossip_menu_option' else ALL_SPECS[kind]['wide_fields'])
    if kind == 'points_of_interest' and any(c.startswith('name_loc') for c in cols):
        patterns={**patterns,'icon_name':'name_loc{n}'}
    known = {pattern.format(n=n).lower(): (field, locale) for field, pattern in patterns.items()
             for locale, n in LOCALES.items() if n > 0}
    female = {prefix + '_female_loc' + str(n) for prefix in ('option_text', 'box_text') for n in range(1, 12)} if kind == 'gossip_menu_option' else {f'text_female_loc{n}' for n in range(1,12)} if kind == 'creature_text' else set()
    unknown = set(cols) - set(keys) - set(known) - female - {"verifiedbuild"}
    mapped = {col: known[col] for col in cols if col in known}
    if unknown or not mapped:
        raise ValueError('unsupported locale columns: ' + ', '.join(sorted(unknown)) if unknown else 'no supported locale columns')
    return kind, keys, mapped


def persist_reference_locale(conn, source, table, plan, row, file, rank):
    kind, keys, mapped = plan
    parts = [row.get(key) for key in keys]
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in parts):
        raise ValueError('invalid entity key')
    entity = json.dumps(parts if kind in ('gossip_menu_option','creature_text') else parts[0])
    if kind == "creature_text" and not valid_entity_key(kind,parts):
        raise ValueError('incomplete or invalid composite key; row rejected')
    if kind == 'quest_objective':
        value = row.get('locale')
        locale = next((code for code, n in LOCALES.items() if type(value) is int and n == value), value)
        if locale not in LOCALES or locale == 'enUS':
            raise ValueError('unsupported objective locale')
        if row.get('description') not in (None, '') and not isinstance(row['description'], str):
            raise ValueError('non-text description')
        persist_locale(conn, source, kind, entity, locale, {'description': row.get('description')}, file, rank, table)
        return
    values = {}
    unsupported_locales = set()
    for col, (field, locale) in mapped.items():
        value = row.get(col)
        if value not in (None, '') and not isinstance(value, str):
            raise ValueError('non-text locale column: ' + col)
        if kind == 'gossip_menu_option':
            female = row.get(col.replace('_loc', '_female_loc'))
            if female not in (None, '', value):
                parser_warning(conn, source, file, f'REFERENCE LOCALE {table}: unsupported differing female text: {col}')
                unsupported_locales.add(locale)
        values.setdefault(locale, {})[field] = value
    for locale, fields in values.items():
        if locale in unsupported_locales:
            continue
        # A legacy compatibility table must not overwrite the source's canonical
        # row-based translation. Wide-only sources remain fully supported.
        canonical = conn.execute('SELECT 1 FROM records r JOIN record_origins o USING(source,kind,entity,locale) '
                                 'WHERE r.source=? AND r.kind=? AND r.entity=? AND r.locale=? AND o.table_name=?',
                                 (source, kind, entity, locale, ALL_SPECS[kind]['source_table'])).fetchone()
        if canonical and kind != 'points_of_interest':
            continue
        persist_locale(conn, source, kind, entity, locale, fields, file, rank, table)


def assert_resolved_dependencies(tokens,variables):
    for kind,text in tokens:
        if kind=='string':continue
        for name in re.findall(r'(?<!@)@[A-Za-z_][A-Za-z_0-9]*',text):
            if isinstance(variables.get(name.casefold()),UnresolvedVariable):sql_value([('word',name)],variables)


def dependency_warning(conn,source,file,phase,t,table,decision,detail):
    info=table_info(table,source)
    entity=info[0] if info else locale_table_kind(table) or '-'
    message=(f'exception_type=UnresolvedVariableError source={source} file={file} pass={phase} '
             f'table={table} adapter/entity={entity} decision={decision} statement={t.statement_context()}: {detail}')
    parser_warning(conn,source,file,message)
    schema_warning(conn,source,file,table,entity,decision,
                   row={'pass':phase,'statement':t.statement_context(),'dependency':detail},emit_warning=False)


def skip_irrelevant(t,conn,source,file,phase,table):
    unresolved={name:value for name,value in t.variables.items() if isinstance(value,UnresolvedVariable)}
    if not unresolved:
        t.skip_raw_statement();return
    found=set();tail=''
    def observe(text):
        nonlocal tail
        text=tail+text
        partial=re.search(r'@[A-Za-z_][A-Za-z_0-9]*$',text)
        tail=partial[0] if partial else ''
        for name in re.findall(r'(?<!@)@[A-Za-z_][A-Za-z_0-9]*',text):
            if name.casefold() in unresolved:found.add(name.casefold())
    source_setup.skip_payload(t,observe=observe)
    for name in sorted(found):
        value=unresolved[name]
        dependency_warning(conn,source,file,phase,t,table,'skipped_unresolved_irrelevant',
                           f'variable={value.variable} assignment={value.assignment} expression={value.expression}')


def classify_unresolved_insert(t,source,table,row):
    unknown={c for c,v in row.items() if isinstance(v,UnresolvedCell)}
    info=table_info(table,source)
    kind=info[0] if info else locale_table_kind(table)
    if not kind:return 'skipped_unresolved_irrelevant'
    spec=ALL_SPECS[kind]
    base=table==spec['target_entity'] or table in INLINE_STRING_TABLES
    if not base and unknown-{'verifiedbuild'}:return 'hard_error_relevant_state'
    keys=set(spec['entity_fields']) if base else set(spec['source_id'] if isinstance(spec['source_id'],tuple) else (spec['source_id'],))|{spec['source_locale']}
    key_unknown={c for c in unknown if keys & set(canonical_row(kind,{c:0}))}
    if kind=='gossip_menu_option':key_unknown.update(unknown & {'menu_id','optionindex','id'})
    localized=[c for c in row if any(re.fullmatch(re.escape(pattern.split('{n}')[0].lower())+r'[0-9]+',c) for pattern in spec['wide_fields'].values())]
    has_locale_values=any(row[c] not in (None,'') for c in localized)
    generated_key=bool(key_unknown) and all(any(
        isinstance(t.variables.get(name.casefold()),UnresolvedVariable)
        and re.search(r'\bSELECT\s+MAX\s*\(',t.variables[name.casefold()].expression,re.I)
        for token_kind,text in row[column].expression if token_kind!='string'
        for name in re.findall(r'(?<!@)@[A-Za-z_][A-Za-z_0-9]*',text)) for column in key_unknown)
    if (base and source!='target' and len(keys)==1 and key_unknown and generated_key
            and not has_locale_values and t.context_head and t.context_head[0].upper()=='INSERT'):
        remaining=unknown-keys
        if all(not identity_fields(kind,{c:0}) for c in remaining):return 'skipped_unprovable_row'
    if key_unknown:return 'hard_error_relevant_state'
    for column in unknown:
        if base:
            if identity_fields(kind,{column:0}) or column in localized:return 'hard_error_relevant_state'
        elif column in spec['source_target_fields'].values() or column in localized:return 'hard_error_relevant_state'
    return 'skipped_unresolved_irrelevant'


def parse_insert(t: Tokens, source: str, file: str, schemas: dict[tuple[str, str], list[str]], conn: sqlite3.Connection, rank: int,
                 phase: str, candidates: set[str]) -> None:
    first = t.get()
    if first[1].upper() == "IGNORE":
        first = t.get()
    if first[1].upper() != "INTO":
        t.unget(first)
        return
    table = next_name(t)
    t.current_table=table
    if not table:
        skip_statement(t)
        return
    locale_tables = {spec["target_table"] if source == "target" else spec["source_table"] for spec in ALL_SPECS.values()}
    if source == 'target':
        locale_tables.difference_update(('quest_offer_reward_locale', 'quest_request_items_locale','broadcast_text_locale'))
    if source != 'target':
        locale_tables.update(('quest_objectives_locale', 'creature_template_wdb_locale'))
        locale_tables.update(REFERENCE_LOCALE_TABLES)
    entity_tables = {spec["target_entity"] for spec in ALL_SPECS.values()} | {"gossip_menu_option_box", "gossip_menu_option_action"}
    if source != "target":
        entity_tables.update(("creature_template_wdb", "quest_objectives"))
    if source == 'target':
        entity_tables.discard('broadcast_text')
    locale_tables.update(INLINE_STRING_TABLES)
    entity_tables.update(INLINE_STRING_TABLES)
    relevant = locale_tables if phase == "locales" else entity_tables
    if table not in relevant:
        skip_irrelevant(t,conn,source,file,phase,table)
        return
    cols: list[str] | None = None
    x = t.get()
    if x[0] == "(":
        cols = []
        while True:
            c = t.get()
            if c[0] in (",", ")"):
                if c[0] == ")":
                    break
                continue
            if c[0] in ("word", "string"):
                cols.append(c[1].lower())
    else:
        t.unget(x)
    while True:
        x = t.get()
        if x[0] in (";", "eof"):
            return
        if x[1].upper() == 'SELECT' and table in ('creature_template', 'quest_template', *QUEST_PARTS, 'creature_template_locale', 'quest_template_locale', 'quest_objective_locale', 'quest_objectives_locale'):
            tokens = statement_tokens(t)
            actual_cols = cols or schemas.get((source, table), [])
            try:
                marker = next(i for i, token in enumerate(tokens) if token[1].upper() == 'WHERE')
                values = [sql_value(part, t.variables) for part in split_tokens(tokens[:marker], ',')]
                guard = ''.join(token[1].lower() for token in tokens[marker:])
                match = re.fullmatch(r'wherenotexists\(select1fromquest_objectivewhereid=(\d+)\)', guard)
                row = dict(zip(actual_cols, values))
                if table != 'quest_objective' or len(actual_cols) != len(values) or not match or row.get('id') != int(match[1]):
                    raise ValueError('неподдерживаемый INSERT SELECT')
                if not base_entity(conn, source, 'quest_objective', str(row['id'])):
                    persist_entity(conn, source, 'quest_objective', row, file, rank)
            except (ValueError, StopIteration) as exc:
                parser_warning(conn, source, file, f'INSERT SELECT {table}: {exc}')
            return
        if x[1].upper() == "VALUES" or (x[1].upper() == "VALUE"):
            break
    if cols is None:
        cols = schemas.get((source, table))
    if not cols:
        if source != 'target' and table in REFERENCE_LOCALE_TABLES:
            parser_warning(conn, source, file, f'REFERENCE LOCALE {table}: missing schema/columns')
        skip_statement(t)
        return
    integer_plans = getattr(t, "integer_plans", None)
    if integer_plans is None:
        t.integer_plans = integer_plans = {}
    if table not in integer_plans:
        integer_plans[table] = sql_schema.plan(conn, source, table)
    integer_types = integer_plans[table]
    reference_plan = None
    if source != 'target' and table in REFERENCE_LOCALE_TABLES and table not in INLINE_STRING_TABLES:
        try:
            reference_plan = reference_locale_plan(table, cols)
        except ValueError as exc:
            parser_warning(conn, source, file, f'REFERENCE LOCALE {table}: {exc}')
            t.skip_raw_statement()
            return
    while True:
        x = t.get()
        if x[0] == "(":
            if phase == "entities" and cols and table not in ('creature_template', 'creature_template_wdb', 'quest_template', 'quest_objectives', 'npc_text', 'creature_text', 'page_text', 'skyfire_string', 'trinity_string', 'db_script_string', 'achievement_reward', 'broadcast_text', 'points_of_interest', *points_of_interest.GOSSIP, *QUEST_PARTS):
                first_index = next((cols.index(c) for c in ("entry", "menuid", "menu_id", "id") if c in cols), -1)
                if table in ('gossip_menu_option', 'gossip_menu_option_box', 'gossip_menu_option_action') and (len(cols) < 2 or cols[0] not in ('menuid', 'menu_id') or cols[1] not in ('optionid', 'optionindex', 'id')):
                    first_index = -1  # Sparse composite reads require proven column order.
                if first_index == 0:
                    # Read the integer entity key before paying to tokenize every non-candidate row.
                    prefix = t.get()
                    unresolved_prefix = None
                    try:
                        prefix_value = (sql_schema.QuotedLiteral(prefix[1], getattr(prefix[1], 'literal', None))
                                        if prefix[0] == 'string' else sql_value([prefix], t.variables))
                        prefix_value, _ = sql_schema.literal(prefix_value, integer_types.get(cols[0]))
                        key_value = prefix_value if type(prefix_value) is int else None
                    except UnresolvedVariableError as exc:
                        unresolved_prefix=UnresolvedCell((prefix,),str(exc));key_value=None
                    except (ValueError, TypeError):
                        key_value = None
                    if unresolved_prefix is not None:
                        comma=t.get()
                        if comma[0]!=',':raise UnresolvedVariableError(unresolved_prefix.diagnostic)
                        vals=[unresolved_prefix]+literal_tuple(t,defer_unresolved=True)
                    elif table in ("gossip_menu_option", "gossip_menu_option_box", "gossip_menu_option_action"):
                        comma = t.get()
                        second = t.get()
                        comma2 = t.get()
                        second_value = None
                        try:
                            second_value = (sql_schema.QuotedLiteral(second[1], getattr(second[1], 'literal', None))
                                            if second[0] == 'string' else sql_value([second], t.variables))
                            second_value, _ = sql_schema.literal(second_value, integer_types.get(cols[1]))
                            if type(second_value) is not int:
                                raise ValueError('composite key has no integer schema proof')
                            candidate_key = json.dumps((key_value, second_value))
                        except UnresolvedVariableError:
                            raise
                        except (ValueError, TypeError):
                            candidate_key = ""
                        if key_value is None or second_value is None:
                            schema_warning(conn, source, file, table, 'gossip_menu_option', 'incomplete composite key; row rejected',
                                           (key_value, second_value), dict(zip(cols[:2], (key_value, second_value))))
                        if comma[0] != "," or comma2[0] != "," or candidate_key not in candidates:
                            t.skip_raw_tuple()
                            sep = t.get()
                            if sep[0] == ",":
                                continue
                            if sep[0] in (";", "eof"):
                                return
                            t.unget(sep)
                            t.skip_raw_statement()
                            return
                        vals_prefix = [(prefix[0], prefix[1]), (second[0], second[1])]
                        # Reconstruct values by parsing the remaining tuple and prepend key columns.
                        rest = literal_tuple(t,defer_unresolved=True)
                        vals = [sql_schema.QuotedLiteral(x[1], getattr(x[1], "literal", None)) if x[0] == "string" else sql_value([x], t.variables) for x in vals_prefix] + rest
                    elif key_value is None or json.dumps(key_value) not in candidates:
                        t.skip_raw_tuple()
                        sep = t.get()
                        if sep[0] == ",":
                            continue
                        if sep[0] in (";", "eof"):
                            return
                        t.unget(sep)
                        t.skip_raw_statement()
                        return
                    else:
                        comma = t.get()
                        rest = literal_tuple(t,defer_unresolved=True)
                        vals = [sql_schema.QuotedLiteral(prefix[1], getattr(prefix[1], "literal", None)) if prefix[0] == "string" else sql_value([prefix], t.variables)] + rest
                else:
                    vals = literal_tuple(t,defer_unresolved=True)
            else:
                vals = literal_tuple(t,defer_unresolved=True)
            if len(cols) == len(vals):
                row = {c: v for c, v in zip(cols, vals)}
                if any(isinstance(v,UnresolvedCell) for v in vals):
                    decision=classify_unresolved_insert(t,source,table,row)
                    if decision=='hard_error_relevant_state':
                        raise UnresolvedVariableError(next(v.diagnostic for v in vals if isinstance(v,UnresolvedCell)))
                    for cell in vals:
                        if isinstance(cell,UnresolvedCell):dependency_warning(conn,source,file,phase,t,table,decision,cell.diagnostic)
                    if decision=='skipped_unprovable_row':
                        t.skipped_unprovable_insert=True
                        sep=t.get()
                        if sep[0]==',':continue
                        if sep[0] in (';','eof'):return
                        raise UnresolvedVariableError('Unknown-key INSERT has unsupported state-changing suffix: '+sep[1])
                    row={c:v for c,v in row.items() if not isinstance(v,UnresolvedCell)}
                try:
                    vals, integer_changes = sql_schema.normalize_row(cols, vals, integer_types)
                except sql_schema.InvalidIntegerLiteral as exc:
                    schema_warning(conn, source, file, table, (table_info(table, source) or (locale_table_kind(table) or "base", None))[0],
                                   str(exc) + "; row rejected", row=[repr(v) if isinstance(v, UnresolvedCell) else v for v in vals])
                    sep = t.get()
                    if sep[0] == ",":
                        continue
                    return
                row = {c: v for c, v in zip(cols, vals) if not isinstance(v, UnresolvedCell)}
                sql_schema.save(conn, source, table, row, file, phase, integer_changes)
                if phase == 'entities' and table in points_of_interest.GOSSIP:
                    points_of_interest.persist_relationship(sys.modules[__name__],conn,source,table,row,file,rank)
                if table in INLINE_STRING_TABLES:
                    adapter=db_script_string if table in db_script_string.TABLES else skyfire_string
                    adapter.persist_row(sys.modules[__name__],conn,source,table,row,file,rank,phase)
                    sep = t.get()
                    if sep[0] == ',':continue
                    return
                spec_kind = locale_table_kind(table)
                if spec_kind == 'creature_text' and not valid_entity_key(spec_kind,creature_text.key(row)):
                    schema_warning(conn,source,file,table,spec_kind,'incomplete or invalid composite key; row rejected',creature_text.key(row),row)
                if spec_kind == 'gossip_menu_option':
                    key = (row.get('menuid', row.get('menu_id')), row.get('optionid', row.get('optionindex', row.get('id'))))
                    if not valid_entity_key(spec_kind, key):
                        schema_warning(conn, source, file, table, spec_kind, 'incomplete composite key; row rejected', key, row)
                if reference_plan:
                    try:
                        persist_reference_locale(conn, source, table, reference_plan, row, file, rank)
                    except ValueError as exc:
                        parser_warning(conn, source, file, f'REFERENCE LOCALE {table}: {exc}')
                        parts = [row.get(key) for key in reference_plan[1]]
                        schema_warning(conn, source, file, table, reference_plan[0], str(exc), parts if len(parts) > 1 else parts[0], row, emit_warning=False)
                elif spec_kind:
                    if table == ALL_SPECS[spec_kind]["target_table"] and ALL_SPECS[spec_kind]['wide_fields']:
                        entity = creature_text.key(row) if spec_kind == "creature_text" else row.get(ALL_SPECS[spec_kind]["target_id"])
                        if valid_entity_key(spec_kind,entity) if spec_kind == "creature_text" else entity is not None:
                            for locale, n in LOCALES.items():
                                if n == 0:
                                    continue
                                fields = {key: row.get(pattern.format(n=n).lower()) for key, pattern in ALL_SPECS[spec_kind]["wide_fields"].items()}
                                persist_locale(conn, source, spec_kind, json.dumps(entity), locale, fields, file, rank, table)
                    else:
                        normalized = normalized_row(source, table, cols, vals)
                        if normalized:
                            kind, entity, locale, fields = normalized
                            persist_locale(conn, source, kind, entity, locale, fields, file, rank, table_name=table)
                gossip_sparse = len(cols)>=2 and cols[0] in ("menuid","menu_id") and cols[1] in ("optionid","optionindex","id")
                if table in ("gossip_menu_option_box", "gossip_menu_option_action") and (not gossip_sparse or json.dumps((row.get("menuid"), row.get("optionindex", row.get("optionid")))) in candidates):
                    menu, option = row.get("menuid"), row.get("optionindex", row.get("optionid"))
                    if isinstance(menu, int) and isinstance(option, int):
                        if table == "gossip_menu_option_box":
                            conn.execute("INSERT OR REPLACE INTO gossip_boxes VALUES(?,?,?,?)",
                                         (source, json.dumps((menu, option)), row.get("boxtext"), file))
                        conn.execute("INSERT OR REPLACE INTO gossip_aux VALUES(?,?,?,?,?)",
                                     (source, json.dumps((menu, option)), table, json.dumps(identity_fields("gossip_menu_option", row), ensure_ascii=False), file))
                # Base entity identity records.
                if table in points_of_interest.GOSSIP:
                    key = (row.get('menuid',row.get('menu_id')),row.get('optionid',row.get('optionindex',row.get('id'))))
                    if gossip_sparse and json.dumps(key) not in candidates:
                        sep=t.get()
                        if sep[0]==',':continue
                        return
                base_map = {s['target_entity']: k for k, s in ALL_SPECS.items()}
                if source != 'target':
                    base_map['quest_objectives'] = 'quest_objective'
                if source != 'target' and table in ('creature_template', 'creature_template_wdb') and (source, 'creature_template_wdb') in schemas:
                    persist_split_creature(conn, source, table, row, file, rank)
                elif table == 'quest_objectives' and not {'id', 'questid', 'type', 'objectid', 'amount', 'flags', 'storageindex'}.issubset(row):
                    schema_warning(conn, source, file, table, 'quest_objective', 'incomplete plural objective structural identity; row rejected', row.get('id'), row)
                elif table in base_map:
                    persist_entity(conn, source, base_map[table], row, file, rank, table)
                if conn.total_changes - parse_insert.last_commit >= 20000:
                    conn.commit()
                    parse_insert.last_commit = conn.total_changes
            else:
                schema_warning(conn, source, file, table, locale_table_kind(table) or 'base', 'column/value count mismatch; row rejected', row=vals)
            sep = t.get()
            if sep[0] == ",":
                continue
            if sep[0] == ";" or sep[0] == "eof":
                return
            if getattr(t,'skipped_unprovable_insert',False):
                raise UnresolvedVariableError('Unknown-key INSERT has unsupported state-changing suffix: '+sep[1])
            t.unget(sep)
            t.skip_raw_statement()
            return
        if x[0] in (";", "eof"):
            return


parse_insert.last_commit = 0


TARGET_TABLES = {
    "item_template_locale", "locales_item", "item_template",
    "gameobject_template_locale", "locales_gameobject", "gameobject_template",
    "gossip_menu_option_locale", "gossip_menu_option", "gossip_menu_option_box", "gossip_menu_option_action",
}
TARGET_TABLES.update(table for spec in ALL_SPECS.values() for table in (spec['source_table'], spec['target_table'], spec['target_entity']))
TARGET_TABLES.update(('quest_objectives_locale', 'quest_objectives', 'creature_template_wdb', 'creature_template_wdb_locale'))
TARGET_TABLES.update(REFERENCE_LOCALE_TABLES)


def rank_for(file: str) -> int:
    p = file.lower()
    if "/repo/sql/base/" in p:
        return 10
    if "/db/" in p:
        return 20
    return 30


def scan_file(conn: sqlite3.Connection, source: str, path: Path, member: str | None, schemas: dict[tuple[str, str], list[str]], phase: str,
              candidates: set[str]) -> None:
    if excluded_sql_input(path, member):
        raise ValueError(f"Excluded SQL input rejected: source={source} file={path} member={member} pass={phase}")
    file = path.relative_to(ROOT).as_posix() + (("!" + member) if member else "")
    rank = rank_for(file)
    size = path.stat().st_size
    conn.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (source, file, size, "indexed"))
    if size >= 50_000_000:
        print(f"[{source}] потоковая обработка {file} ({size:,} bytes)", flush=True)
    with open_sql(path, member) as stream:
        t = Tokens(stream)
        t.assignment_context = (conn, source, file, phase)
        context_token = SCAN_CONTEXT.set((phase, t))
        try:
            while True:
                token = t.get()
                if token[0] == "eof":
                    break
                t.current_table = None
                t.integer_statement_changes = {}
                t.skipped_unprovable_insert = False
                t.capture_context = True
                t.context_head = [token[1][:96]]
                t.context_tail.clear()
                word = token[1].upper()
                if word in ("CREATE", "INSERT", "REPLACE", "DELETE", "UPDATE", "SET", "ALTER", "DROP", "RENAME"):
                    t.statement_index = getattr(t, "statement_index", 0) + 1
                if word == "CREATE":
                    parse_create(t, source, file, schemas, conn)
                elif word in ("INSERT", "REPLACE"):
                    parse_insert(t, source, file, schemas, conn, rank, phase, candidates)
                elif word == "DELETE":
                    parse_delete(t, source, file, conn, phase)
                elif word == "UPDATE":
                    parse_update(t, source, file, conn, phase)
                elif word == "SET":
                    parse_set(t)
                elif word in ('ALTER', 'DROP', 'RENAME'):
                    # Unsupported DDL invalidates type proof rather than guessing the new layout.
                    ddl = statement_tokens(t)
                    if ddl and ddl[0][1].upper() in ('TABLE', 'TEMPORARY'):
                        names = {value.lower() for kind, value in ddl if kind == 'word'}
                        for name in names:
                            conn.execute('DELETE FROM source_column_types WHERE source=? AND table_name=?', (source, name))
                            getattr(t, 'integer_plans', {}).pop(name, None)
                if t.integer_statement_changes:
                    sql_schema.save(conn, source, t.current_table,
                                    {col: notes[0]['normalized_integer'] if len(notes) == 1 else [note['normalized_integer'] for note in notes]
                                     for col, notes in t.integer_statement_changes.items()},
                                    file, phase, {col: notes[0] if len(notes) == 1 else notes
                                                  for col, notes in t.integer_statement_changes.items()})
                # Index commits in manageable batches.
                if conn.total_changes and conn.total_changes % 50000 < 500:
                    conn.commit()
        except (ValueError,KeyError,IndexError,TypeError,sqlite3.Error) as exc:
            table=getattr(t,'current_table',None) or '-'
            info=table_info(table,source)
            entity=info[0] if info else locale_table_kind(table) or '-'
            decision='hard_error_relevant_state' if isinstance(exc,UnresolvedVariableError) else 'parser_error'
            raise ValueError(f"exception_type={type(exc).__name__} source={source} file={file} pass={phase} table={table} adapter/entity={entity} decision={decision} statement={t.statement_context()}: {exc}") from exc
        finally:
            t.capture_context = False
            SCAN_CONTEXT.reset(context_token)


def statement_tokens(t: Tokens) -> list[tuple[str, str]]:
    # UPDATE/DELETE/SET are small; INSERT tuples remain streamed separately.
    result = []
    while True:
        token = t.get()
        if token[0] in (";", "eof"):
            return result
        result.append(token)
        if len(result) > 100000:
            skip_statement(t)
            raise ValueError("слишком сложный SQL statement")


SQL_INT_MIN = -(1 << 63)
SQL_INT_MAX = (1 << 63) - 1


def checked_sql_integer(value: int) -> int:
    if type(value) is not int or not SQL_INT_MIN <= value <= SQL_INT_MAX:
        raise ValueError('SQL integer overflow or non-integer operand (signed 64-bit)')
    return value


def integer_expression(text: str, variables: dict[str, object]) -> int:
    """Bounded recursive descent; only integer operands, unary signs, +, -, *."""
    if len(text) > 4096:
        raise ValueError('SQL integer expression exceeds size limit')
    pattern = re.compile(r'\s*(@[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[+*()\-])')
    tokens=[];offset=0
    while offset < len(text):
        match=pattern.match(text,offset)
        if not match:
            if text[offset:].isspace():break
            raise ValueError('unsupported SQL integer expression token: '+text[offset:offset+80])
        tokens.append(match[1]);offset=match.end()
        if len(tokens)>256:raise ValueError('SQL integer expression exceeds token limit')
    position=0
    def take():
        nonlocal position
        if position >= len(tokens):raise ValueError('incomplete SQL integer expression')
        value=tokens[position];position+=1;return value
    def atom(depth=0):
        nonlocal position
        if depth>32:raise ValueError('SQL integer expression nesting limit')
        value=take()
        if value in ('+','-'):
            # Handle the minimum signed integer as a negative literal, not an overflowing positive intermediate.
            if value=='-' and position<len(tokens) and tokens[position].isdigit():
                digits=take()
                if len(digits.lstrip('0'))>19:raise ValueError('SQL integer overflow')
                return checked_sql_integer(-int(digits))
            return checked_sql_integer((1 if value=='+' else -1)*atom(depth+1))
        if value=='(':
            result=addition(depth+1)
            if take()!=')':raise ValueError('unbalanced SQL integer expression')
            return result
        if value.startswith('@'):
            return checked_sql_integer(sql_value([('word',value)],variables))
        if value.isdigit():
            if len(value.lstrip('0'))>19:raise ValueError('SQL integer overflow')
            return checked_sql_integer(int(value))
        raise ValueError('invalid SQL integer operand: '+value)
    def multiplication(depth):
        nonlocal position
        result=atom(depth)
        while position<len(tokens) and tokens[position]=='*':
            position+=1;result=checked_sql_integer(result*atom(depth))
        return result
    def addition(depth):
        nonlocal position
        result=multiplication(depth)
        while position<len(tokens) and tokens[position] in ('+','-'):
            operator=take();right=multiplication(depth)
            result=checked_sql_integer(result+right if operator=='+' else result-right)
        return result
    result=addition(0)
    if position!=len(tokens):raise ValueError('unexpected SQL integer expression suffix: '+tokens[position])
    return result


def assignment_value(expr: list[tuple[str, str]], variables: dict[str, object]) -> object:
    """Evaluate typed literals/copies or bounded deterministic integer arithmetic."""
    if len(expr) == 1 and expr[0][0] == 'string':
        return str(expr[0][1])
    if any(token[0] == 'string' for token in expr):
        raise ValueError('unsupported string expression in SQL variable assignment')
    combined = ' '.join(token[1] for token in expr)
    # The lexer splits a decimal point, but separate numeric words are not literals.
    combined = re.sub(r'^([-+]?\d+)\s+\.\s+(\d+(?:[eE][-+]?\d+)?)$', r'\1.\2', combined)
    if re.fullmatch(r'@[A-Za-z_][A-Za-z_0-9]*', combined):
        value=sql_value([('word', combined)], variables)
        return checked_sql_integer(value) if type(value) is int else value
    if combined.upper() in ('NULL', 'TRUE', 'FALSE'):
        return sql_value([('word', combined)], variables)
    if re.fullmatch(r'[-+]?\d+', combined):
        return integer_expression(combined,variables)
    if re.fullmatch(r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?', combined):
        import math
        value = float(combined)
        if math.isfinite(value):
            return value
    return integer_expression(combined,variables)


def parse_set(t: Tokens) -> None:
    tokens = statement_tokens(t)
    # Session/system settings are irrelevant. User assignments are file-local.
    for part in split_tokens(tokens, ','):
        if not part or not part[0][1].startswith('@') or part[0][1].startswith('@@'):
            continue
        name = part[0][1].rstrip(':').casefold()
        if not re.fullmatch(r'@[A-Za-z_][A-Za-z_0-9]*', name):
            raise ValueError('unsupported SQL user variable name')
        pos = 1
        # Lexer splits := into ':' and '='; compact @name:= keeps ':' on name.
        if pos < len(part) and part[pos][1] == ':':
            pos += 1
        if pos >= len(part) or part[pos][0] != '=' or not part[pos + 1:]:
            raise ValueError('unsupported SQL variable assignment syntax')
        try:
            value = assignment_value(part[pos + 1:], t.variables)
        except ValueError as exc:
            context = getattr(t, 'assignment_context', None)
            source, file, phase = context[1:] if context else ('', '', '')
            expression = ' '.join(v for _, v in part[pos + 1:])[:512]
            assignment = 'SET ' + ' '.join(repr(v) if k == 'string' else v for k, v in part)[:1024]
            value = UnresolvedVariable(name, expression, str(exc), assignment, source, file, phase)
            if context:
                conn = context[0]
                message = (f"UNRESOLVED SET source={source} file={file} pass={phase} "
                           f"variable={name} assignment={assignment}: {exc}")
                parser_warning(conn, source, file, message)
                affected = json.dumps(value.__dict__, ensure_ascii=False, sort_keys=True)
                conn.execute('INSERT INTO parser_diagnostics SELECT ?,?,?,?,?,? WHERE NOT EXISTS '
                             '(SELECT 1 FROM parser_diagnostics WHERE source=? AND file=? AND table_name=? AND entity=? AND reason=? AND affected_row=?)',
                             (source, file, 'SET', 'sql_user_variable', str(exc), affected,
                              source, file, 'SET', 'sql_user_variable', str(exc), affected))
        # Reassignment replaces stale scalars as well as unresolved expressions.
        t.variables[name] = value


def split_tokens(tokens: list[tuple[str, str]], separator: str) -> list[list[tuple[str, str]]]:
    result, current, depth = [], [], 0
    for tok in tokens:
        if tok[0] == "(":
            depth += 1
        elif tok[0] == ")":
            depth -= 1
        if depth == 0 and tok[0] == separator:
            result.append(current)
            current = []
        else:
            current.append(tok)
    return result + [current]


def table_info(table: str, source: str | None = None) -> tuple[str, str] | None:
    if source and source != 'target' and table in ('quest_objectives', 'creature_template_wdb'):
        return ('quest_objective' if table == 'quest_objectives' else 'creature'), 'entities'
    if source and source != 'target' and table == 'creature_template_wdb_locale':
        return 'creature', 'records'
    if source and source != 'target' and table in REFERENCE_LOCALE_TABLES:
        return REFERENCE_LOCALE_TABLES[table], 'records'
    if source == 'target' and table in ('quest_offer_reward_locale', 'quest_request_items_locale'):
        return None  # The SkyFire loader reads these texts only from locales_quest.
    if table == 'quest_objectives_locale' and source != 'target':
        return 'quest_objective', 'records'
    for kind, spec in ALL_SPECS.items():
        if table == spec["target_entity"]:
            return kind, "entities"
        if table in (spec["source_table"], spec["target_table"]):
            if source and table != (spec["target_table"] if source == "target" else spec["source_table"]):
                return None
            return kind, "records"
    return None


def schema_sql_value(expression, variables, column):
    """Use the active statement's proven column type, never a key-name heuristic."""
    value = sql_value(expression, variables)
    current = SCAN_CONTEXT.get()
    if not current or len(expression) != 1 or expression[0][0] != 'string':
        return value
    t = current[1]
    conn, source, file, phase = t.assignment_context
    table = getattr(t, 'current_table', None)
    plans = getattr(t, 'integer_plans', None)
    if plans is None:
        t.integer_plans = plans = {}
    if table not in plans:
        plans[table] = sql_schema.plan(conn, source, table)
    value, detail = sql_schema.literal(
        sql_schema.QuotedLiteral(value, getattr(expression[0][1], 'literal', None)),
        plans[table].get(column))
    if detail:
        t.integer_statement_changes.setdefault(column, []).append(detail)
    return value


def predicate_sql(tokens: list[tuple[str, str]], kind: str, storage: str, variables: dict[str, object]) -> tuple[str, list[object]]:
    # Deliberately restricted, parameterized subset: equality, IN, BETWEEN, AND.
    depth = 0
    for i, token in enumerate(tokens):
        depth += int(token[0] == '(') - int(token[0] == ')')
        if token[1].upper() == 'OR' and depth == 0:
            left, lp = predicate_sql(tokens[:i], kind, storage, variables)
            right, rp = predicate_sql(tokens[i + 1:], kind, storage, variables)
            return '(' + left + ' OR ' + right + ')', lp + rp
    pos, fragments, params = 0, [], []
    while pos < len(tokens):
        col = tokens[pos][1].lower()
        if tokens[pos][0] == "(":
            level, end = 1, pos
            while level:
                end += 1
                level += int(tokens[end][0] == '(') - int(tokens[end][0] == ')')
            if end == len(tokens) - 1 or tokens[end + 1][1].upper() == 'AND':
                condition, values = predicate_sql(tokens[pos + 1:end], kind, storage, variables)
                fragments.append('(' + condition + ')')
                params.extend(values)
                pos = end + 1
                if pos < len(tokens):
                    pos += 1
                continue
            columns = [token for token in tokens[pos + 1:end] if token[0] != ","]
            expressions = []
            for column in columns:
                expression, _ = predicate_sql([column, ("=", "="), ("word", "0")], kind, storage, variables)
                expressions.append(expression[:-2])
            if tokens[end + 1][1].upper() != "IN" or tokens[end + 2][0] != "(":
                raise ValueError("неподдерживаемое tuple condition")
            pos = end + 3
            tuples = []
            while tokens[pos][0] != ")":
                if tokens[pos][0] != "(":
                    raise ValueError("ожидается literal tuple")
                pos += 1
                values = []
                while tokens[pos][0] != ")":
                    if tokens[pos][0] != ",":
                        values.append(schema_sql_value([tokens[pos]], variables, columns[len(values)][1].lower()))
                    pos += 1
                if len(values) != len(columns):
                    raise ValueError("неполный tuple")
                tuples.append("(" + ",".join("?" for _ in values) + ")")
                params.extend(values)
                pos += 1
                if tokens[pos][0] == ",":
                    pos += 1
            fragments.append("(" + ",".join(expressions) + ") IN (" + ",".join(tuples) + ")")
            pos += 1
            if pos < len(tokens):
                if tokens[pos][1].upper() != "AND":
                    raise ValueError("ожидается AND")
                pos += 1
            continue
        pos += 1
        if kind == "creature_text" and creature_text.ALIASES.get(col,col) in creature_text.KEYS:
            expression = "json_extract(entity,'$[%d]')" % creature_text.KEYS.index(creature_text.ALIASES.get(col,col))
        elif kind == "gossip_menu_option" and col in ("menuid", "menu_id", "optionid", "optionindex", "id"):
            expression = "json_extract(entity,'$[%d]')" % (0 if col in ("menuid", "menu_id") else 1)
        elif col in ("entry", "id") and kind != "gossip_menu_option":
            expression = "json_extract(entity,'$')"
        elif col == "locale" and storage == "records":
            expression = "locale"
        else:
            table = ALL_SPECS[kind]["target_entity"] if storage == "entities" else ALL_SPECS[kind]["source_table"]
            mapped = normalized_update_field(kind, table, col)
            if not mapped:
                raise ValueError(f"неподдерживаемое поле WHERE: {col}")
            expression = "json_extract(fields,'$.%s')" % mapped[0]
        if pos >= len(tokens):
            raise ValueError("неполный WHERE")
        op = tokens[pos][1].upper()
        pos += 1
        if op == 'IS':
            negate = tokens[pos][1].upper() == 'NOT'
            pos += int(negate)
            if tokens[pos][1].upper() != 'NULL':
                raise ValueError('IS поддерживает только NULL/NOT NULL')
            fragments.append(expression + (' IS NOT NULL' if negate else ' IS NULL'))
            pos += 1
        elif op in ("=", "<>", "!=", "<", ">", "<=", ">="):
            fragments.append(expression + op + "?")
            value = schema_sql_value([tokens[pos]], variables, col)
            if kind == 'quest_objective' and col == 'locale' and isinstance(value, int):
                value = next((code for code, n in LOCALES.items() if n == value), value)
            params.append(value)
            pos += 1
        elif op == "BETWEEN":
            low = schema_sql_value([tokens[pos]], variables, col)
            if tokens[pos + 1][1].upper() != "AND":
                raise ValueError("неполный BETWEEN")
            high = schema_sql_value([tokens[pos + 2]], variables, col)
            fragments.append(expression + " BETWEEN ? AND ?")
            params.extend([low, high])
            pos += 3
        elif op == "IN":
            if tokens[pos][0] != "(":
                raise ValueError("ожидается IN (...)")
            pos += 1
            values = []
            while tokens[pos][0] != ")":
                values.append(schema_sql_value([tokens[pos]], variables, col))
                pos += 1
                if tokens[pos][0] == ",":
                    pos += 1
                elif tokens[pos][0] != ")":
                    raise ValueError("неподдерживаемый IN")
            pos += 1
            fragments.append(expression + " IN (" + ",".join("?" for _ in values) + ")")
            params.extend(values)
        else:
            raise ValueError(f"неподдерживаемый оператор: {op}")
        if pos < len(tokens):
            if tokens[pos][1].upper() != "AND":
                raise ValueError("ожидается AND")
            pos += 1
    if not fragments:
        raise ValueError("пустой WHERE")
    return " AND ".join(fragments), params


def parser_warning(conn: sqlite3.Connection, source: str, file: str, message: str, *, table_name: str | None = None) -> None:
    diagnostic_message = message
    context = SCAN_CONTEXT.get()
    if context and 'SQL-переменная' in message:
        phase, tokens = context
        message = f"source={source} file={file} pass={phase} statement={tokens.statement_context()}: {message}"
    conn.execute("INSERT INTO warnings SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM warnings WHERE source=? AND file=? AND message=?)",
                 (source, file, message, source, file, message))
    match = re.match(r'(?:REFERENCE LOCALE|INSERT SELECT|UPDATE|DELETE) ([a-z_]+):', diagnostic_message)
    invalid = re.match(r'INVALID LOCALE ([a-z_]+) (.+?) (\w+) ([a-z_]+): (.*)', diagnostic_message)
    if match or invalid:
        table = table_name or (match[1] if match else ALL_SPECS[invalid[1]]['source_table'])
        info = table_info(table, source)
        kind = info[0] if info else (invalid[1] if invalid else 'unknown')
        affected = {'scope': 'statement; affected keys not decoded'} if not invalid else {'key': json.loads(invalid[2]), 'locale': invalid[3], 'field': invalid[4]}
        reason = diagnostic_message.split(': ', 1)[-1]
        if context and 'SQL-переменная' in diagnostic_message:
            phase, tokens = context
            affected.update(pass_name=phase, statement=tokens.statement_context())
        serialized = json.dumps(affected, ensure_ascii=False, sort_keys=True)
        conn.execute('INSERT INTO parser_diagnostics SELECT ?,?,?,?,?,? WHERE NOT EXISTS '
                     '(SELECT 1 FROM parser_diagnostics WHERE source=? AND file=? AND table_name=? AND entity=? AND reason=? AND affected_row=?)',
                     (source, file, table, kind, reason, serialized, source, file, table, kind, reason, serialized))


def reference_wide_filter(source, table, kind, condition, params):
    if source != 'target' and table in REFERENCE_LOCALE_TABLES:
        condition = '(' + condition + ') AND NOT EXISTS (SELECT 1 FROM record_origins o '
        condition += 'WHERE o.source=records.source AND o.kind=records.kind AND o.entity=records.entity '
        condition += 'AND o.locale=records.locale AND o.table_name=?)'
        params = [*params, ALL_SPECS[kind]['source_table']]
    return condition, params


def parse_delete(t: Tokens, source: str, file: str, conn: sqlite3.Connection, phase: str | None = None) -> None:
    if t.get()[1].upper() != "FROM":
        skip_statement(t)
        return
    table = next_name(t)
    t.current_table=table
    if table not in TARGET_TABLES:
        skip_irrelevant(t,conn,source,file,phase,table)
        return
    tokens = statement_tokens(t)
    assert_resolved_dependencies(tokens,t.variables)
    points_of_interest.replay_mutation(sys.modules[__name__],conn,source,file,table,tokens,t.variables,'DELETE',phase)
    if table in ('points_of_interest_locale','locales_points_of_interest') and phase != 'entities':
        points_of_interest.delete_locales(sys.modules[__name__],conn,source,table,tokens,t.variables)
        return
    if table in INLINE_STRING_TABLES:
        inline_kind='db_script_string' if table in db_script_string.TABLES else 'skyfire_string'
        key_table=db_script_string.KEY_TABLE if inline_kind=='db_script_string' else 'inline_string_keys'
        storage = 'entities' if phase == 'entities' else 'records'
        if not tokens or tokens[0][1].upper() != 'WHERE':raise ValueError('inline string DELETE requires WHERE')
        english_predicate=any(token[1].lower()=='content_default' for token in tokens[1:] if token[0]=='word')
        if english_predicate:
            # Locale pass has no complete English base snapshot yet. Replay in entities.
            for token in tokens[1:]:
                if token[1].startswith('@'):sql_value([token],t.variables)
            if phase!='entities':return
            condition,params=predicate_sql(tokens[1:],inline_kind,'entities',t.variables)
            keys=[r[0] for r in conn.execute('SELECT entity FROM entities WHERE source=? AND kind=? AND '+condition,[source,inline_kind,*params])]
            for key in keys:
                conn.execute('DELETE FROM records WHERE source=? AND kind=? AND entity=?',(source,inline_kind,key))
                conn.execute('DELETE FROM entities WHERE source=? AND kind=? AND entity=?',(source,inline_kind,key))
                conn.execute('DELETE FROM '+key_table+' WHERE source=? AND entity=?',(source,key))
            return
        condition,params = predicate_sql(tokens[1:],inline_kind,storage,t.variables)
        conn.execute(f'DELETE FROM {storage} WHERE source=? AND kind=? AND '+condition,[source,inline_kind,*params])
        if phase != 'entities':
            conn.execute('DELETE FROM '+key_table+' WHERE source=? AND '+condition,[source,*params])
        return
    if table in ("gossip_menu_option_box", "gossip_menu_option_action"):
        if phase and phase != "entities":
            return
        try:
            if not tokens or tokens[0][1].upper() != "WHERE":
                raise ValueError("DELETE без WHERE запрещён")
            condition, params = predicate_sql(tokens[1:], "gossip_menu_option", "entities", t.variables)
            conn.execute("DELETE FROM gossip_aux WHERE source=? AND table_name=? AND " + condition, [source, table] + params)
            if table == "gossip_menu_option_box":
                # This compatibility table contains only the same composite key.
                conn.execute("DELETE FROM gossip_boxes WHERE source=? AND entity NOT IN (SELECT entity FROM gossip_aux WHERE source=? AND table_name=?)", (source, source, table))
        except UnresolvedVariableError:
            raise
        except (ValueError, IndexError) as exc:
            parser_warning(conn, source, file, f"DELETE {table}: {exc}")
        return
    info = table_info(table, source)
    if not info:
        return
    kind, storage = info
    if phase and phase != ("entities" if storage == "entities" else "locales"):
        return
    try:
        if not tokens or tokens[0][1].upper() != "WHERE":
            raise ValueError("DELETE без WHERE запрещён")
        condition, params = predicate_sql(tokens[1:], kind, storage, t.variables)
        if storage == 'records':
            condition, params = reference_wide_filter(source, table, kind, condition, params)
        if storage == 'entities' and kind == 'creature':
            affected = [r[0] for r in conn.execute('SELECT entity FROM entities WHERE source=? AND kind=? AND ' + condition, [source, kind] + params)]
            conn.executemany('DELETE FROM creature_parts WHERE source=? AND table_name=? AND entity=?', [(source, table, key) for key in affected])
        conn.execute(f"DELETE FROM {storage} WHERE source=? AND kind=? AND " + condition, [source, kind] + params)
    except UnresolvedVariableError:
        raise
    except (ValueError, IndexError) as exc:
        parser_warning(conn, source, file, f"DELETE {table}: {exc}")


def normalized_update_field(kind: str, table: str, column: str) -> tuple[str, str] | None:
    if table == 'locales_gossip_menu_option':
        for field, prefix in (('optiontext', 'option_text_loc'), ('boxtext', 'box_text_loc')):
            match = re.fullmatch(prefix + r'(\d+)', column)
            if match:
                locale = next((code for code, n in LOCALES.items() if n > 0 and n == int(match[1])), None)
                return (field, locale) if locale else None
        return None
    spec = ALL_SPECS[kind]
    if kind in ('skyfire_string','db_script_string') and table in INLINE_STRING_TABLES:
        if column=='content_default':return ('content','entity')
        match=re.fullmatch(r'content_loc([1-9]|10|11)',column)
        if match:return ('content',next(code for code,n in LOCALES.items() if n==int(match[1])))
        return None
    if table == 'creature_template_wdb':
        column = {'name1': 'name', 'title': 'subname', 'classification': 'rank'}.get(column, column)
        return (column, 'entity') if column in ('name', 'subname', *CREATURE_STRUCT) else None
    if table == 'creature_template_wdb_locale':
        return ({'name1': 'name', 'title': 'subname'}[column], 'locale') if column in ('name1', 'title') else None
    if table == 'quest_objectives':
        mapped = identity_fields(kind, {column: 0})
        return (next(iter(mapped)), 'entity') if mapped else None
    if kind == 'npc_text' and table == 'npc_text':
        column = re.sub(r'^probability', 'prob', column)
        return (column, 'entity') if column in (*npc_text.TEXT_FIELDS, *(f'{prefix}{i}' for prefix in ('prob','lang','broadcasttextid') for i in range(npc_text.OPTIONS))) else None
    if kind in ('creature', 'quest', 'npc_text', 'creature_text', 'page_text', 'points_of_interest', 'achievement_reward', npc_text.BROADCAST_KIND, *QUEST_PARTS):
        if table == spec['target_entity']:
            mapped = identity_fields(kind, {column: 0})
            return (next(iter(mapped)), 'entity') if mapped else None
        if kind in QUEST_PARTS:
            field, col = QUEST_PARTS[kind][1:]
            return (field, 'locale') if col in canonical_row(kind, {column: 0}) else None
        mapped = canonical_row(kind, {column: 0})
        for field in spec['text_fields']:
            if field in mapped:
                return field, 'locale'
        for field, pattern in spec['wide_fields'].items():
            match = re.fullmatch(re.escape(pattern.split('{n}')[0].lower()) + r'(\d+)', column)
            if match:
                code = next((code for code, n in LOCALES.items() if n == int(match[1])), None)
                return (field, code) if code else None
        return None
    if table == spec["target_entity"]:
        aliases = {
            "item": {"name": "name", "description": "description", "class": "class", "subclass": "subclass"},
            "gameobject": {"name": "name", "type": "type", "castbarcaption": "castbarcaption"},
            "gossip_menu_option": {"optiontext": "optiontext", "option_text": "optiontext", "boxtext": "boxtext", "box_text": "boxtext",
                                   "optionbroadcasttextid": "optionbroadcasttextid", "option_broadcast_text_id": "optionbroadcasttextid"},
        }[kind]
        if kind == "gameobject":
            aliases.update({field: field for field in GO_FIELDS})
        elif kind == "gossip_menu_option":
            aliases.update({alias: field for field, names in GOSSIP_FIELDS.items() for alias in names})
        return (aliases[column], "entity") if column in aliases else None
    if table in (spec["source_table"], spec["target_table"]):
        source_aliases = {"item": {"name": "name", "description": "description"},
                          "gameobject": {"name": "name", "castbarcaption": "castbarcaption"},
                          "gossip_menu_option": {"optiontext": "optiontext", "boxtext": "boxtext"}}[kind]
        if column in source_aliases:
            return source_aliases[column], "locale"
        if kind != "gossip_menu_option":
            for field, pattern in spec["wide_fields"].items():
                match = re.fullmatch(re.escape(pattern.split("{n}")[0].lower()) + r"(\d+)", column)
                if match:
                    index = int(match.group(1))
                    locale = next((code for code, value in LOCALES.items() if value == index), None)
                    return (field, locale) if locale else None
    return None


def apply_simple_update(conn: sqlite3.Connection, source: str, table: str, assignments: dict[str, object], where: dict[str, object], file: str, rank: int) -> bool:
    info = table_info(table, source)
    kind = info[0] if info else None
    if not kind:
        return False
    spec = ALL_SPECS[kind]
    if info[1] == "entities":
        if kind == "creature_text":
            ident=creature_text.key(where)
            if not valid_entity_key(kind,ident):
                return False
            entity=json.dumps(ident)
            row=conn.execute("SELECT entity,fields FROM entities WHERE source=? AND kind=? AND entity=?",(source,kind,entity)).fetchone()
            rows=[row] if row else []
        elif kind == "gossip_menu_option":
            menu = where.get("menuid", where.get("menu_id"))
            option = where.get("optionid", where.get("id"))
            if menu is None or option is None:
                return False
            entity = json.dumps((menu, option))
            row = conn.execute("SELECT entity,fields FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
            rows = [row] if row else []
        else:
            entity_id = where.get("entry", where.get("id"))
            if entity_id is not None:
                entity = json.dumps(entity_id)
                row = conn.execute("SELECT entity,fields FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
                rows = [row] if row else []
            elif kind == "gameobject" and "name" in where:
                rows = conn.execute("SELECT entity,fields FROM entities WHERE source=? AND kind=? AND json_extract(fields,'$.name')=?",
                                    (source, kind, where["name"])).fetchall()
            else:
                return False
        for entity, serialized in rows:
            fields = json.loads(serialized)
            for column, value in assignments.items():
                normalized = normalized_update_field(kind, table, column)
                if normalized and normalized[1] == "entity":
                    fields[normalized[0]] = value
            conn.execute("UPDATE entities SET fields=?,file=?,rank=? WHERE source=? AND kind=? AND entity=?",
                         (json.dumps(fields, ensure_ascii=False), file, rank, source, kind, entity))
            part = conn.execute('SELECT fields FROM creature_parts WHERE source=? AND table_name=? AND entity=?', (source, table, entity)).fetchone()
            if part:
                raw = json.loads(part[0]); raw.update(assignments)
                conn.execute('UPDATE creature_parts SET fields=?,file=?,rank=? WHERE source=? AND table_name=? AND entity=?',
                             (json.dumps(raw, ensure_ascii=False), file, rank, source, table, entity))
        return True
    # Locale row updates require an entity key and locale. Wide target rows derive locale from _locN.
    if kind == "creature_text":
        ident=creature_text.key(where)
        entity=json.dumps(ident) if valid_entity_key(kind,ident) else None
        locale=where.get("locale")
    elif kind == "gossip_menu_option":
        menu, option = where.get("menuid", where.get("menu_id")), where.get("optionid", where.get("id"))
        entity = json.dumps((menu, option)) if menu is not None and option is not None else None
        locale = where.get("locale")
    else:
        idcol = spec['target_id'] if table == spec['target_table'] else spec['source_id']
        entity_id = where.get(idcol)
        entity = json.dumps(entity_id) if entity_id is not None else None
        locale = where.get("locale")
    if not entity:
        return False
    if kind == 'quest_objective' and isinstance(locale, int):
        locale = next((code for code, n in LOCALES.items() if n == locale), None)
    updates: dict[str, dict[str, object]] = {}
    for column, value in assignments.items():
        normalized = normalized_update_field(kind, table, column)
        if normalized is None:
            continue
        field, loc_or_mode = normalized
        loc = str(locale) if loc_or_mode == "locale" and locale is not None else loc_or_mode
        if loc not in LOCALES:
            return False
        updates.setdefault(loc, {})[field] = value
    if not updates:
        return False
    for loc, fields_update in updates.items():
        current = conn.execute("SELECT fields FROM records WHERE source=? AND kind=? AND entity=? AND locale=?", (source, kind, entity, loc)).fetchone()
        fields = json.loads(current[0]) if current else {}
        fields.update(fields_update)
        persist_locale(conn, source, kind, entity, loc, fields, file, rank, table)
    return True


def apply_gossip_box_join(conn: sqlite3.Connection, source: str, file: str, tokens: list[tuple[str, str]]) -> bool:
    # Recognize the verified split-table migration, not arbitrary JOIN execution.
    compact = "".join(x[1].lower() for x in tokens)
    required = ("leftjoingossip_menu_option_boxgmobongmo.menuid=gmob.menuidandgmo.optionid=gmob.optionindex",
                "gmo.boxtext=gmob.boxtext")
    if not all(fragment in compact for fragment in required) or "where" in compact:
        return False
    for entity, serialized, boxtext in conn.execute("SELECT e.entity,e.fields,b.boxtext FROM entities e LEFT JOIN gossip_boxes b ON b.source=e.source AND b.entity=e.entity WHERE e.source=? AND e.kind='gossip_menu_option'", (source,)).fetchall():
        fields = json.loads(serialized)
        fields["boxtext"] = boxtext
        for table, defaults in (("gossip_menu_option_action", {"actionmenuid": 0, "actionpoiid": 0}),
                                ("gossip_menu_option_box", {"boxcoded": 0, "boxmoney": 0, "boxbroadcasttextid": 0})):
            row = conn.execute("SELECT fields,file FROM gossip_aux WHERE source=? AND entity=? AND table_name=?", (source, entity, table)).fetchone()
            extra = json.loads(row[0]) if row else {}
            fields.update({key: extra.get(key) if extra.get(key) is not None else value for key, value in defaults.items()})
            if row:
                fields.setdefault("_structural_provenance", {})[table] = row[1]
        conn.execute("UPDATE entities SET fields=?,file=?,rank=? WHERE source=? AND kind='gossip_menu_option' AND entity=?",
                     (json.dumps(fields, ensure_ascii=False), file, rank_for(file), source, entity))
    return True


def persist_split_creature(conn, source, table, row, file, rank):
    key = row.get('entry')
    if not valid_entity_key('creature', key):
        schema_warning(conn, source, file, table, 'creature', 'invalid WDB join key; row rejected', key, row)
        return
    entity = json.dumps(key)
    conn.execute('INSERT INTO creature_parts VALUES(?,?,?,?,?,?) ON CONFLICT(source,table_name,entity) DO UPDATE '
                 'SET fields=excluded.fields,file=excluded.file,rank=excluded.rank WHERE excluded.rank>=creature_parts.rank',
                 (source, table, entity, json.dumps(row, ensure_ascii=False), file, rank))
    parts = {t: (json.loads(data), path, priority) for t, data, path, priority in conn.execute(
        'SELECT table_name,fields,file,rank FROM creature_parts WHERE source=? AND entity=?', (source, entity))}
    reason = None
    primary_keys = {}
    for name, required in (('creature_template', {'entry', 'unit_class'}),
                           ('creature_template_wdb', {'entry', 'name1', 'type', 'family', 'classification'})):
        schema = conn.execute('SELECT columns,primary_key FROM source_schemas WHERE source=? AND table_name=?', (source, name)).fetchone()
        primary_keys[name] = json.loads(schema[1]) if schema else []
        if not schema or primary_keys[name] != ['entry'] or not required.issubset(json.loads(schema[0])):
            reason = 'unproven split identity join: expected single PRIMARY KEY(entry) and structural columns'
    if reason is None and len(parts) < 2:
        reason = 'incomplete split identity: missing matching creature_template or creature_template_wdb row'
    merged = {}
    if reason is None:
        for name in ('creature_template', 'creature_template_wdb'):
            raw = parts[name][0]
            mapped = dict(raw)
            if name.endswith('_wdb'):
                mapped.update(name=raw.get('name1'), subname=raw.get('title'), rank=raw.get('classification'))
            fields = identity_fields('creature', mapped)
            if any(k in merged and merged[k] != v for k, v in fields.items() if k != 'subname'):
                reason = 'conflicting split structural identity fields'
            merged.update(fields)
        if any(merged.get(k) is None for k in ('name', *CREATURE_STRUCT)):
            reason = 'incomplete split identity: missing name or strict structural field'
    previous = conn.execute("SELECT fields FROM entities WHERE source=? AND kind='creature' AND entity=?", (source, entity)).fetchone()
    # Unsupported updates remain blocked, even if another part is subsequently inserted.
    if previous and json.loads(previous[0]).get('_evidence_incomplete') and not json.loads(previous[0]).get('_split_pending'):
        reason = 'split identity has unresolved UPDATE evidence'
    if reason:
        merged.update(_evidence_incomplete=1)
        if reason != 'split identity has unresolved UPDATE evidence':
            merged['_split_pending'] = 1
    merged['_structural_provenance'] = {name: {'file': value[1], 'key': key, 'primary_key': primary_keys.get(name, [])} for name, value in parts.items()}
    conn.execute("INSERT INTO entities VALUES(?,?,?,?,?,?) ON CONFLICT(source,kind,entity) DO UPDATE SET fields=excluded.fields,file=excluded.file,rank=excluded.rank",
                 (source, 'creature', entity, json.dumps(merged, ensure_ascii=False), file, max(v[2] for v in parts.values())))
    if reason and not reason.startswith('incomplete split identity: missing matching'):
        schema_warning(conn, source, file, table, 'creature', reason, key)


def finalize_schema_evidence(conn):
    for source, entity, data, file in conn.execute("SELECT source,entity,fields,file FROM entities WHERE kind='creature' AND json_extract(fields,'$._split_pending')=1").fetchall():
        schema_warning(conn, source, file, 'creature_template_wdb', 'creature', 'incomplete/unproven split identity; evidence unusable', json.loads(entity), json.loads(data))




def ignored_metadata_join(tokens, kind, table):
    """Ignore a JOIN only when every assignment targets known non-identity columns."""
    marker = next((i for i, tok in enumerate(tokens) if tok[1].upper() == 'SET'), None)
    if marker is None:
        return False
    prefix = tokens[:marker]
    alias = None
    if prefix and prefix[0][1].upper() == 'AS' and len(prefix) > 1:
        alias = prefix[1][1].lower()
    elif prefix and prefix[0][1].upper() not in ('JOIN', 'LEFT', 'RIGHT', 'INNER'):
        alias = prefix[0][1].lower()
    allowed = {'creature_template': {'gossip_menu_id'}}.get(table, set())
    end = next((i for i in range(marker + 1, len(tokens)) if tokens[i][1].upper() == 'WHERE'), len(tokens))
    assignments = split_tokens(tokens[marker + 1:end], ',')
    if not assignments or not allowed:
        return False
    for part in assignments:
        if len(part) < 5 or part[1][0] != '.' or part[3][0] != '=':
            return False
        if part[0][1].lower() not in (alias, table) or part[2][1].lower() not in allowed:
            return False
        if normalized_update_field(kind, table, part[2][1].lower()):
            return False
    return True


def parse_update(t: Tokens, source: str, file: str, conn: sqlite3.Connection, phase: str | None = None) -> None:
    table = next_name(t)
    t.current_table=table
    if table not in TARGET_TABLES:
        skip_irrelevant(t,conn,source,file,phase,table)
        return
    if table in INLINE_STRING_TABLES:
        t.inline_string_table = table
        adapter=db_script_string if table in db_script_string.TABLES else skyfire_string
        adapter.update(sys.modules[__name__],t,source,file,conn,phase)
        return
    tokens = statement_tokens(t)  # Consume exactly once, including ignored metadata updates.
    points_of_interest.replay_mutation(sys.modules[__name__],conn,source,file,table,tokens,t.variables,'UPDATE',phase)
    info = table_info(table, source)
    if not info:
        return
    kind, storage = info
    if phase and phase != ("entities" if storage == "entities" else "locales"):
        return
    if storage == "records" and explicit_updates.observe(sys.modules[__name__], conn, source, file, table, tokens, t):
        return
    try:
        if not tokens or tokens[0][1].upper() != "SET":
            if ignored_metadata_join(tokens, kind, table):
                return
            if table == "gossip_menu_option" and apply_gossip_box_join(conn, source, file, tokens):
                return
            raise ValueError("неподдерживаемый JOIN UPDATE")
        where_pos = next((i for i, token in enumerate(tokens) if token[1].upper() == "WHERE"), len(tokens))
        assignments = {}
        relevant = False
        for part in split_tokens(tokens[1:where_pos], ","):
            if part and normalized_update_field(kind, table, part[0][1].lower()):
                relevant = True
                if len(part) < 3 or part[1][0] != "=":
                    raise ValueError("неподдерживаемое выражение SET")
                expression = part[2:]
                assert_resolved_dependencies(expression,t.variables)
                if len(expression) != 1 and not re.fullmatch(r"[-+]?\d+\.\d+", "".join(token[1] for token in expression)):
                    raise ValueError("неподдерживаемое выражение SET")
                assignments[part[0][1].lower()] = schema_sql_value(expression, t.variables, part[0][1].lower())
        if not relevant:
            return  # Gameplay metadata is intentionally outside this index.
        assert_resolved_dependencies(tokens[where_pos+1:],t.variables)
        condition, params = predicate_sql(tokens[where_pos + 1:], kind, storage, t.variables)
        if storage == 'records':
            condition, params = reference_wide_filter(source, table, kind, condition, params)
        rows = conn.execute(f"SELECT entity" + (",locale" if storage == "records" else "") + f" FROM {storage} WHERE source=? AND kind=? AND " + condition, [source, kind] + params).fetchall()
        for row in rows:
            key = json.loads(row[0])
            spec = ALL_SPECS[kind]
            idcol = spec['entity_fields'][0] if storage == 'entities' else spec['target_id'] if table == spec['target_table'] else spec['source_id']
            where = {"menuid": key[0], "optionid": key[1]} if kind == "gossip_menu_option" else dict(zip(creature_text.KEYS,key)) if kind == "creature_text" else {idcol: key}
            if storage == "records":
                where["locale"] = row[1]
            if not apply_simple_update(conn, source, table, assignments, where, file, rank_for(file)):
                raise ValueError("UPDATE не применён")
    except UnresolvedVariableError:
        raise
    except (ValueError, IndexError) as exc:
        parser_warning(conn, source, file, f"UPDATE {table}: {exc}")
        if storage == "entities" and kind in ("gameobject", "gossip_menu_option", "creature", "quest", "quest_objective", "npc_text", "creature_text", "page_text", "points_of_interest", "achievement_reward", npc_text.BROADCAST_KIND):
            condition, params = "1", []
            try:
                marker = next(i for i, token in enumerate(tokens) if token[1].upper() == "WHERE")
                condition, params = predicate_sql(tokens[marker + 1:], kind, storage, t.variables)
            except (ValueError, IndexError, StopIteration):
                pass
            affected = [json.loads(r[0]) for r in conn.execute('SELECT entity FROM entities WHERE source=? AND kind=? AND ' + condition, [source, kind] + params)]
            schema_warning(conn, source, file, table, kind, 'unsupported identity UPDATE; evidence marked incomplete', row={'keys': affected, 'predicate': condition, 'parameters': params, 'sql_tokens': tokens}, emit_warning=False)
            conn.execute("UPDATE entities SET fields=json_set(json_remove(fields,'$._split_pending'),'$._evidence_incomplete',1) WHERE source=? AND kind=? AND " + condition, [source, kind] + params)


def build_index(_: argparse.Namespace) -> int:
    sources = tuple(active_files())  # One immutable snapshot for both streaming passes.
    for source, path, member in sources:
        if excluded_sql_input(path, member):
            raise RuntimeError(f"Excluded discovery input: source={source} file={path} member={member}; index untouched")
    if not sources:
        raise RuntimeError("SQL-источники не найдены. Подготовьте externals/core/ and externals/references/<source-id>/repo/ or db/.")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    if INDEX.exists():
        INDEX.unlink()
    conn = db_connect(INDEX)
    register_sources(conn)
    schemas: dict[tuple[str, str], list[str]] = {}
    counts = {s: 0 for s in (*all_reference_sources(conn), "target")}
    # First pass indexes localized rows, avoiding the cost of decoding every base entity row.
    for source, path, member in sources:
        if not path.exists():
            print(f"Пропуск отсутствующего файла: {path}", file=sys.stderr)
            continue
        try:
            scan_file(conn, source, path, member, schemas, "locales", set())
            counts[source] += 1
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            conn.execute("INSERT INTO warnings VALUES(?,?,?)", (source, str(path), str(exc)))
            print(f"Ошибка индексации source={source} file={path} pass=locales exception_type={type(exc).__name__}: {exc}", file=sys.stderr)
        conn.commit()
    conn.commit()
    # Base entity indexing is sparse: only IDs with candidate translations are decoded in detail.
    candidates_by_source = {}
    for source in (*all_reference_sources(conn), "target"):
        ids = {row[0] for row in conn.execute("SELECT DISTINCT entity FROM records WHERE source=? AND kind IN ('item','gameobject','gossip_menu_option')", (source,))}
        ids.update(row[0] for row in conn.execute("SELECT DISTINCT entity FROM records WHERE kind='gossip_menu_option'"))
        if source == "target":
            for upstream in all_reference_sources(conn):
                ids.update(row[0] for row in conn.execute("SELECT DISTINCT entity FROM records WHERE source=? AND kind IN ('item','gameobject','gossip_menu_option')", (upstream,)))
        candidates_by_source[source] = ids
    for source, path, member in sources:
        if not path.exists():
            continue
        try:
            scan_file(conn, source, path, member, schemas, "entities", candidates_by_source[source])
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            conn.execute("INSERT INTO warnings VALUES(?,?,?)", (source, str(path), "entity pass: " + str(exc)))
            print(f"Ошибка entity-pass source={source} file={path} pass=entities exception_type={type(exc).__name__}: {exc}", file=sys.stderr)
        conn.commit()
    finalize_schema_evidence(conn)
    npc_text.finalize(sys.modules[__name__],conn)
    creature_text.finalize(sys.modules[__name__],conn)
    page_text.finalize(sys.modules[__name__],conn)
    points_of_interest.finalize(sys.modules[__name__],conn)
    conn.commit()
    print("Индекс построен:", INDEX)
    for source, count in counts.items():
        nrec = conn.execute("SELECT count(*) FROM records WHERE source=?", (source,)).fetchone()[0]
        nent = conn.execute("SELECT count(*) FROM entities WHERE source=?", (source,)).fetchone()[0]
        nwarn = conn.execute("SELECT count(*) FROM warnings WHERE source=?", (source,)).fetchone()[0]
        print(f"{source}: SQL-потоков (включая SQL из ZIP) {count}, localization records {nrec}, entities {nent}, warnings {nwarn}")
    conn.close()
    return 0


def open_index() -> sqlite3.Connection:
    if not INDEX.exists():
        raise RuntimeError("Индекс не найден. Сначала выполните команду index.")
    return sqlite3.connect(INDEX)


def raw_record(conn: sqlite3.Connection, source: str, kind: str, entity: str, locale: str) -> tuple[dict, str, str] | None:
    row = conn.execute("SELECT fields,file,kind FROM records WHERE source=? AND kind=? AND entity=? AND locale=?", (source, kind, entity, locale)).fetchone()
    return (json.loads(row[0]), row[1], record_table(conn, source, kind, entity, locale)) if row else None


def record_table(conn: sqlite3.Connection, source: str, kind: str, entity: str, locale: str) -> str:
    origin = conn.execute('SELECT table_name FROM record_origins WHERE source=? AND kind=? AND entity=? AND locale=?', (source,kind,entity,locale)).fetchone()
    spec = ALL_SPECS[kind]
    return origin[0] if origin else spec['target_table'] if source == 'target' else spec['source_table']


def get_record(conn: sqlite3.Connection, source: str, kind: str, entity: str, locale: str) -> tuple[dict, str, str] | None:
    base = raw_record(conn, source, kind, entity, locale)
    if kind != 'quest':
        return base
    fields, origins, files = {}, {}, []
    for part in (('quest',) if source == 'target' else ('quest', 'quest_offer_reward', 'quest_request_items')):
        rec = base if part == 'quest' else raw_record(conn, source, part, entity, locale)
        if rec:
            spec = ALL_SPECS[part]
            table = record_table(conn, source, part, entity, locale)
            for field, value in rec[0].items():
                fields[field] = value
                origins[field] = {'file': rec[1], 'table': table}
            files.append(rec[1])
    for objective, texts, file in conn.execute(
            "SELECT e.entity,r.fields,r.file FROM entities e JOIN records r ON r.source=e.source AND r.kind=e.kind AND r.entity=e.entity "
            "WHERE e.source=? AND e.kind='quest_objective' AND json_extract(e.fields,'$.questid')=? AND r.locale=? ORDER BY CAST(e.entity AS INTEGER)",
            (source, json.loads(entity), locale)):
        text = json.loads(texts).get('description')
        if text not in (None, ''):
            field = 'objective:' + objective
            fields[field] = text
            table = record_table(conn, source, 'quest_objective', objective, locale)
            origins[field] = {'file': file, 'table': table, 'objective_id': int(objective)}
            files.append(file)
    if not fields:
        return None
    fields['_provenance'] = origins
    return fields, ' | '.join(sorted(set(files))), record_table(conn, source, kind, entity, locale)


def text_fields_for(conn: sqlite3.Connection, kind: str, entity: str, *, all_sources=False) -> tuple[str, ...]:
    fields = tuple(SPECS[kind]['text_fields'])
    if kind == 'quest':
        selected = ('target', *(data_reference_sources(conn) if all_sources else reference_sources(conn)))
        objectives = conn.execute("SELECT DISTINCT entity FROM entities WHERE kind='quest_objective' AND json_extract(fields,'$.questid')=? AND source IN (" + ','.join('?' for _ in selected) + ") ORDER BY CAST(entity AS INTEGER)", (json.loads(entity), *selected))
        fields += tuple('objective:' + row[0] for row in objectives)
    return fields


def objective_identity_ok(conn: sqlite3.Connection, entity: str, source: str) -> bool:
    target = base_entity(conn, 'target', 'quest_objective', entity)
    upstream = base_entity(conn, source, 'quest_objective', entity)
    required = ('questid', 'type', 'objectid', 'amount', 'flags', 'description')
    return bool(target and upstream and not target.get('_evidence_incomplete') and not upstream.get('_evidence_incomplete')
                and all(field in target and field in upstream and target[field] == upstream[field] for field in required)
                and ('index' not in target or 'index' not in upstream or target['index'] == upstream['index']))


def entity_key(kind: str, entity_arg: str) -> str:
    if kind == "creature_text":
        parts = tuple(int(v) for v in entity_arg.split(","))
        if not valid_entity_key(kind,parts):
            raise ValueError("creature_text key must be Entry,GroupID,ID (uint8 group/line)")
        return json.dumps(parts)
    if kind == "gossip_menu_option":
        values = entity_arg.split(",")
        if len(values) != 2:
            raise ValueError("Для gossip_menu_option укажите MenuID,OptionID через запятую")
        return json.dumps(tuple(int(v) for v in values))
    return json.dumps(int(entity_arg))


def target_locale_record(conn: sqlite3.Connection, kind: str, entity: str, locale: str) -> dict | None:
    return get_record(conn, "target", kind, entity, locale)[0] if get_record(conn, "target", kind, entity, locale) else None


def base_entity(conn: sqlite3.Connection, source: str, kind: str, entity: str) -> dict | None:
    row = conn.execute("SELECT fields FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
    return json.loads(row[0]) if row else None


def norm_identity(kind: str, fields: dict) -> tuple:
    if kind == 'npc_text':
        return (kind,)
    if kind in ('creature', 'quest'):
        return (kind, fields.get('name' if kind == 'creature' else 'title'))
    if kind == "gossip_menu_option":
        bt = fields.get("optionbroadcasttextid")
        if bt not in (None, "", 0, "0"):
            return ("broadcast", str(bt))
        text = fields.get("optiontext")
        return ("text", " ".join(str(text or "").split()).casefold())
    if kind == "item":
        return ("name", " ".join(str(fields.get("name") or "").split()).casefold())
    return ("name-type", " ".join(str(fields.get("name") or "").split()).casefold(), str(fields.get("type")))


def quest_identity_text(value, *, field: str | None = None):
    if value is None:
        return ''
    if not isinstance(value, str):
        return None
    protected = re.compile(r'(\$g[^;]*;|\|\d[^()]*\([^)]*\)|\$[A-Za-z])')
    parts = protected.split(value)
    text = ''.join(part if i % 2 else re.sub(r'\s+', ' ', part) for i, part in enumerate(parts)).strip()
    if field == 'details':
        # Name tokens have the same referent; only their display case differs.
        # Keep escaped dollars and longer token-like expressions exact.
        parts = re.split(r'(\$[gG][^;]*;|\|\d[^()]*\([^)]*\))', text)
        text = ''.join(part if i % 2 else re.sub(r'(?<![$\\])\$N(?![A-Za-z0-9_])', '$n', part)
                       for i, part in enumerate(parts))
    return text


def identities_match(kind: str, source: dict, target: dict) -> bool:
    if kind == 'achievement_reward':
        return achievement_reward.structure(source,target)[0]
    if kind == 'db_script_string':
        return db_script_string.match(sys.modules[__name__],source,target)
    if kind in ('skyfire_string','db_script_string'):
        return skyfire_string.match(sys.modules[__name__],source,target)
    if kind == 'page_text':
        return page_text.match(sys.modules[__name__], source, target)
    if kind == 'creature_text':
        return creature_text.match(sys.modules[__name__],source,target)
    if kind == 'npc_text':
        return any(npc_text.field_match(sys.modules[__name__],source,target,field) for field in npc_text.TEXT_FIELDS)
    if kind in ('creature', 'quest'):
        required = ('name', 'type', 'unit_class') if kind == 'creature' else ('title', 'objectives', 'details', 'minlevel')
        structural = CREATURE_STRUCT if kind == 'creature' else ('minlevel', 'method', 'zoneorsort', 'type')
        name = 'name' if kind == 'creature' else 'title'
        return bool(isinstance(source.get(name), str) and isinstance(target.get(name), str)
                    and str(source.get(name) or '').strip() and str(target.get(name) or '').strip()
                    and not source.get('_evidence_incomplete') and not target.get('_evidence_incomplete')
                    and all(field in source and field in target and
                            (quest_identity_text(source[field], field=field) is not None and quest_identity_text(source[field], field=field) == quest_identity_text(target[field], field=field)
                             if kind == 'quest' and field in ('title', 'details', 'objectives') else source[field] == target[field]) for field in required)
                    and all(isinstance(value, int) and not isinstance(value, bool) for value in
                            (source.get('type' if kind == 'creature' else 'minlevel'), target.get('type' if kind == 'creature' else 'minlevel')))
                    and all(source[field] == target[field] for field in structural if field in source and field in target))
    if kind == "gossip_menu_option":
        source_bt = source.get("optionbroadcasttextid")
        target_bt = target.get("optionbroadcasttextid")
        if source_bt not in (None, "", 0, "0") and target_bt not in (None, "", 0, "0"):
            return str(source_bt) == str(target_bt)
        source_text = " ".join(str(source.get("optiontext") or "").split()).casefold()
        target_text = " ".join(str(target.get("optiontext") or "").split()).casefold()
        return bool(source_text and target_text and source_text == target_text)
    if kind == "item":
        return bool(str(source.get("name") or "").strip() and str(target.get("name") or "").strip()) and norm_identity(kind, source) == norm_identity(kind, target)
    if kind == "gameobject":
        return bool(str(source.get("name") or "").strip() and str(target.get("name") or "").strip()
                    and source.get("type") is not None and target.get("type") is not None) and norm_identity(kind, source) == norm_identity(kind, target)
    return norm_identity(kind, source) == norm_identity(kind, target)


def identity_ok(conn: sqlite3.Connection, kind: str, entity: str, sources: tuple[str, ...] | None = None) -> tuple[bool, str]:
    target = base_entity(conn, "target", kind, entity)
    if not target:
        return False, "target entity missing"
    if kind == 'npc_text':
        donors = sources if sources is not None else reference_sources(conn)
        return (True, 'field-level npc_text identity') if any(base_entity(conn,s,kind,entity) is not None for s in donors) else (False,'no upstream base identity')
    tid = norm_identity(kind, target)
    seen = False
    for src in (sources if sources is not None else reference_sources(conn)):
        candidate = base_entity(conn, src, kind, entity)
        if candidate:
            seen = True
            if not identities_match(kind, candidate, target):
                return False, f"{src} identity mismatch"
    return (True, "identity verified") if seen else (False, "no upstream base identity")


def translation_comparison_text(value: str, locale: str) -> str:
    """Compare spacing and narrow glyph variants; never rewrite source values."""
    if locale != 'ruRU':
        return value
    protected = re.compile(r'(\$[gG][^;]*;|\|\d[^()]*\([^)]*\)|\$[A-Za-z]|\|H[^|]*\|h[^|]*\|h|\|T[^|]*\|t|\|A[^|]*\|a|\|c[0-9A-Fa-f]{8}|\|r)')
    parts = protected.split(value)
    result = []
    for i, part in enumerate(parts):
        if not i % 2:
            part = re.sub(r'[^\S\r\n\v\f\u0085\u2028\u2029]+', ' ', part.replace('\r\n', '\n'))
            part = re.sub(r'(?<![\d.…])…(?![\d.…])', '...', part)
            part = re.sub(r"(?<=[А-Яа-яЁё])’(?=[А-Яа-яЁё])", "'", part)
        result.append(part)
    return ''.join(result).strip()


def _primary_compare_value(conn: sqlite3.Connection, kind: str, entity: str, locale: str, field: str, *, indexed_provenance: bool = False,
                  identity_sources: tuple[str, ...] | None = None, invalid_evidence: list | None = None,
                  _allow_english_fallback: bool = True) -> tuple[str, dict[str, object]]:
    if locale not in LOCALES:
        return "UNSUPPORTED", {"reason": "unknown locale"}
    identity, reason = identity_ok(conn, kind, entity, identity_sources)
    if not identity:
        return ("MISSING" if reason == "target entity missing" else "UNSUPPORTED"), {"reason": reason}
    if locale == "enUS":
        upstream, provenance = {}, {}
        for source in reference_sources(conn):
            row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
            if row:
                text = json.loads(row[0]).get(field)
                if text not in (None, ""):
                    upstream[source] = str(text)
                    revision = None if indexed_provenance else source_revision(source)
                    provenance[source] = {"repository_revision": revision, "revision_verified": revision is not None,
                                          "file": row[1], "table": SPECS[kind]["target_entity"]}
        target_row = conn.execute("SELECT fields FROM entities WHERE source='target' AND kind=? AND entity=?", (kind, entity)).fetchone()
        target_fields = json.loads(target_row[0]) if target_row else {}
        target_val = target_fields.get(field)
        details = {"upstream": upstream, "provenance": provenance, "target": target_val}
        if len(set(upstream.values())) > 1:
            return "CONFLICT", details
        if not upstream:
            return ("MISSING" if not target_val else "TARGET_IDENTICAL"), details
        value = next(iter(upstream.values()))
        if target_val not in (None, ""):
            return ("TARGET_IDENTICAL" if str(target_val) == value else "CONFLICT"), details
        return ("MATCH" if len(upstream) >= 2 else "SOURCE_ONLY"), details
    upstream = {}
    provenance = {}
    npc_rejections = []
    npc_proofs = {}
    for source in reference_sources(conn):
        item = get_record(conn, source, kind, entity, locale)
        if item and item[0].get(field) not in (None, ""):
            if kind in ('skyfire_string','db_script_string'):
                base = base_entity(conn,source,kind,entity)
                target_base = base_entity(conn,'target',kind,entity)
                adapter=db_script_string if kind=='db_script_string' else skyfire_string
                if not adapter.match(sys.modules[__name__],base,target_base):
                    return 'UNSUPPORTED', {'reason':source+' string English identity unproven','source_english':base,'target_english':target_base}
                proof = skyfire_string.validate(target_base['content'],item[0][field])
                if not proof['valid']:
                    return 'UNSUPPORTED', {'reason':'FORMAT_CONTRACT_FAILURE','format_contract_failures':[{
                        'source':source,'value':item[0][field],'format_contract':proof,
                        'provenance':{**item[0].get('_provenance',{}).get(field,{'file':item[1],'table':item[2]}),
                                      **evidence_roles.profile(conn).get(source,{})}}]}
            if kind == 'page_text' and not page_text.match(sys.modules[__name__],
                    base_entity(conn, source, kind, entity), base_entity(conn, 'target', kind, entity)):
                return 'UNSUPPORTED', {'reason': source + ' page_text chain identity unproven',
                                       'source_page': base_entity(conn, source, kind, entity),
                                       'target_page': base_entity(conn, 'target', kind, entity)}
            if kind in ('creature_text', 'page_text', 'skyfire_string', 'db_script_string'):
                if field in item[0].get('_adapter_conflicts',{}):
                    return 'CONFLICT', {'reason':'direct/broadcast translation conflict','adapter_conflict':item[0]['_adapter_conflicts'][field]}
                english = english_field_evidence(conn,'target',kind,entity,field)
                if locale == 'ruRU' and english and translation_comparison_text(item[0][field],locale) == translation_comparison_text(english['value'],locale):
                    npc_rejections.append({'source':source,'value':item[0][field],'reason':'CONFIRMED_ENGLISH_FALLBACK','provenance':item[0].get('_provenance',{}).get(field,{'file':item[1],'table':item[2]}),'target_english':english})
            if kind == 'npc_text':
                if not npc_text.field_match(sys.modules[__name__],base_entity(conn,source,kind,entity),base_entity(conn,'target',kind,entity),field):
                    return 'UNSUPPORTED', {'reason':source+' npc_text field identity mismatch','field':field,
                                           'source_option':npc_text.option_evidence(base_entity(conn,source,kind,entity),field),
                                           'target_option':npc_text.option_evidence(base_entity(conn,'target',kind,entity),field),
                                           'source':source,'source_english':english_field_evidence(conn,source,kind,entity,field),
                                           'target_english':english_field_evidence(conn,'target',kind,entity,field),
                                           'provenance':{source:item[0].get('_provenance',{}).get(field,{'file':item[1],'table':item[2]})}}
                if field in item[0].get('_adapter_conflicts',{}):
                    return 'CONFLICT', {'reason':'direct/broadcast translation conflict','source':source,
                                        'provenance':{source:item[0].get('_provenance',{}).get(field,{'file':item[1],'table':item[2]})},
                                        'adapter_conflict':item[0]['_adapter_conflicts'][field]}
                npc_proofs[source] = {'source':english_field_evidence(conn,source,kind,entity,field),
                                      'target':english_field_evidence(conn,'target',kind,entity,field),
                                      'source_option':npc_text.option_evidence(base_entity(conn,source,kind,entity),field),
                                      'target_option':npc_text.option_evidence(base_entity(conn,'target',kind,entity),field)}
                english = npc_proofs[source]['target']
                if locale == 'ruRU' and english and translation_comparison_text(item[0][field],locale) == translation_comparison_text(english['value'],locale):
                    npc_rejections.append({'source':source,'value':item[0][field],'reason':'CONFIRMED_ENGLISH_FALLBACK',
                                          'provenance':item[0].get('_provenance',{}).get(field,{'file':item[1],'table':item[2]}),'target_english':english})
            if kind == 'quest' and field.startswith('objective:') and not objective_identity_ok(conn, field.split(':')[1], source):
                return 'UNSUPPORTED', {'reason': f'{source} quest objective identity mismatch', 'objective_id': int(field.split(':')[1])}
            upstream[source] = str(item[0][field])
            revision = None if indexed_provenance else source_revision(source)
            provenance[source] = {"repository_revision": revision, "revision_verified": revision is not None,
                                  **item[0].get('_provenance', {}).get(field, {"file": item[1], "table": item[2]})}
    # English-only NPC candidates are not useful ruRU data. Mixed evidence
    # retains the existing PRIMARY quorum/conflict policy.
    if npc_rejections and set(upstream) == {r['source'] for r in npc_rejections}:
        upstream = {}
        provenance = {}
    else:
        npc_rejections = []
    target_record = target_locale_record(conn, kind, entity, locale)
    target_val = target_record.get(field) if target_record else None
    details: dict[str, object] = {"upstream": upstream, "provenance": provenance, "target": target_val}
    if npc_proofs:
        details['npc_text_identity_proof'] = npc_proofs
    if npc_rejections:
        details["rejected_english_fallbacks"] = npc_rejections
    invalid = [value for value in (invalid_locale_values(conn, kind, entity, locale) if invalid_evidence is None else invalid_evidence) if value['field'] == field]
    if invalid:
        details['invalid_values'] = invalid
    compared = {source: translation_comparison_text(value, locale) for source, value in upstream.items()}
    if len(set(compared.values())) > 1:
        if _allow_english_fallback and locale == 'ruRU' and len(upstream) >= 3:
            resolved = confirmed_english_fallback_comparisons(conn, kind, entity, locale, indexed_provenance=indexed_provenance)
            if resolved:
                detail = resolved[field]
                return detail['status'], {k: v for k, v in detail.items() if k != 'status'}
        return "CONFLICT", details
    if not upstream:
        if invalid:
            return 'UNSUPPORTED', {**details, 'reason': 'Only invalid localization evidence available'}
        return ("MISSING" if not target_val else "TARGET_IDENTICAL"), details
    value = next(iter(upstream.values()))
    if target_val not in (None, ""):
        return ("TARGET_IDENTICAL" if translation_comparison_text(str(target_val), locale) == translation_comparison_text(value, locale) else "CONFLICT"), details
    if len(upstream) >= 2:
        return "MATCH", details
    return "SOURCE_ONLY", details


def english_field_evidence(conn: sqlite3.Connection, source: str, kind: str, entity: str, field: str) -> dict | None:
    """Read the actual base field, including split quest text and objectives."""
    part, key, column = kind, entity, field
    if kind == 'quest' and field.startswith('objective:'):
        part, key, column = 'quest_objective', field.split(':', 1)[1], 'description'
    elif kind == 'quest' and field in ('offerrewardtext', 'requestitemstext') and source != 'target':
        part = 'quest_offer_reward' if field == 'offerrewardtext' else 'quest_request_items'
    row = conn.execute('SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?', (source, part, key)).fetchone()
    if not row and part != kind and part != 'quest_objective':
        part, key = kind, entity
        row = conn.execute('SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?', (source, part, key)).fetchone()
    if not row:
        return None
    fields = json.loads(row[0])
    value = fields.get(column)
    if fields.get('_evidence_incomplete') or not isinstance(value, str) or not value.strip():
        return None
    if part == 'quest_objective' and fields.get('questid') != json.loads(entity):
        return None
    return {'value': value, 'file': row[1], 'table': ALL_SPECS[part]['target_entity'],
            'field': column, 'entity_key': json.loads(key), **fields.get('_english_provenance',{}).get(column,{})}


def confirmed_english_fallback_comparisons(conn: sqlite3.Connection, kind: str, entity: str, locale: str, *,
                                          indexed_provenance: bool = False, comparisons: dict | None = None) -> dict | None:
    """Exclude confirmed reference fallback only if the whole entity is safe."""
    if locale != 'ruRU' or not identity_ok(conn, kind, entity)[0]:
        return None
    for source in reference_sources(conn):
        if get_record(conn, source, kind, entity, locale) and base_entity(conn, source, kind, entity) is None:
            return None
    if comparisons is None:
        comparisons = {}
        for field in text_fields_for(conn, kind, entity):
            status, detail = _primary_compare_value(conn, kind, entity, locale, field, indexed_provenance=indexed_provenance,
                                           _allow_english_fallback=False)
            comparisons[field] = {'status': status, **detail}
    if any(d['status'] == 'UNSUPPORTED' for d in comparisons.values()):
        return None
    resolved = dict(comparisons)
    rejected_any = False
    for field, detail in comparisons.items():
        if detail['status'] != 'CONFLICT':
            continue
        upstream = detail.get('upstream', {})
        if len(upstream) < 3:
            return None
        target_base = english_field_evidence(conn, 'target', kind, entity, field)
        if not target_base:
            return None
        target_text = translation_comparison_text(target_base['value'], locale)
        bases = {source: english_field_evidence(conn, source, kind, entity, field) for source in upstream}
        if any(not base or translation_comparison_text(base['value'], locale) != target_text for base in bases.values()):
            return None
        rejected = {s: v for s, v in upstream.items() if translation_comparison_text(v, locale) == target_text}
        accepted = {s: v for s, v in upstream.items() if s not in rejected}
        # This content guard does not identify English. Fallback proof above is
        # exclusively same-field base equality; near matches are never accepted.
        if not rejected or len(accepted) < 2 or not all(re.search('[А-Яа-яЁё]', v) for v in accepted.values()):
            return None
        accepted_texts = {translation_comparison_text(v, locale) for v in accepted.values()}
        if len(accepted_texts) != 1:
            return None
        target_value = detail.get('target')
        if target_value not in (None, '') and translation_comparison_text(str(target_value), locale) not in accepted_texts:
            return None
        rejections = [{'source': s, 'field': field, 'value': v, 'reason': 'confirmed_english_base_fallback',
                       'provenance': detail.get('provenance', {}).get(s, {}), 'source_english_base': bases[s],
                       'target_english_base': target_base, 'confirmed_donors': {a: {'value': text, 'english_base': bases[a],
                       'provenance': detail.get('provenance', {}).get(a, {})} for a, text in accepted.items()}}
                      for s, v in rejected.items()]
        resolved[field] = {**detail, 'status': 'TARGET_IDENTICAL' if target_value not in (None, '') else 'MATCH',
                           'upstream': accepted, 'provenance': {s: detail.get('provenance', {}).get(s, {}) for s in accepted},
                           'original_upstream': upstream, 'rejected_english_fallbacks': rejections}
        rejected_any = True
    return resolved if rejected_any else None


def values_for_kind(conn: sqlite3.Connection, kind: str, entity: str, locales: list[str] | None = None) -> list[tuple[str, str, str, dict]]:
    result = []
    locs = locales or list(LOCALES)
    for locale in locs:
        for field in text_fields_for(conn, kind, entity, all_sources=True):
            status, detail = compare_value(conn, kind, entity, locale, field)
            result.append((locale, field, status, detail))
    return result


def command_inspect(args: argparse.Namespace) -> int:
    kind = args.entity_type
    key = entity_key(kind, args.entity_id)
    locales = [args.locale] if args.locale else list(LOCALES)
    with open_index() as conn:
        if kind == 'points_of_interest':
            for locale in locales:
                entry,_ = points_of_interest.decide(sys.modules[__name__],conn,key,locale)
                print(json.dumps(entry,ensure_ascii=False,sort_keys=True,indent=2))
            return 0
        print(f"{kind} {args.entity_id}")
        print(json.dumps(evidence_roles.profile(conn), ensure_ascii=False, sort_keys=True))
        for source in ("target", *all_reference_sources(conn)):
            base = base_entity(conn, source, kind, key)
            print(f"  {source} base: {json.dumps(base, ensure_ascii=False) if base else 'нет'}")
            tables = {ALL_SPECS[kind]['target_entity']}
            tables.update(row[0] for row in conn.execute('SELECT DISTINCT table_name FROM record_origins WHERE source=? AND kind=? AND entity=?', (source, kind, key)))
            for table in sorted(tables):
                normalizations = sql_schema.inspect_provenance(conn, source, table, key)
                if normalizations:
                    print(f"  {source} integer_literal_provenance [{table}]: {json.dumps(normalizations, ensure_ascii=False, sort_keys=True)}")
        for locale in locales:
            if locale not in LOCALES:
                print(f"  {locale}: UNSUPPORTED (неизвестная локаль)")
                continue
            for source in ("target", *all_reference_sources(conn)):
                rec = get_record(conn, source, kind, key, locale)
                if rec:
                    fields, file, table = rec
                    actual_table = table
                    print(f"  {source} {locale} [{actual_table}] {file}: {json.dumps(fields, ensure_ascii=False)}")
                elif locale == "enUS":
                    base_row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, key)).fetchone()
                    if base_row:
                        base_fields = json.loads(base_row[0])
                        values = {field: base_fields.get(field) for field in SPECS[kind]["text_fields"] if base_fields.get(field) not in (None, "")}
                        print(f"  {source} enUS [{SPECS[kind]['target_entity']}] {base_row[1]}: {json.dumps(values, ensure_ascii=False)}")
                    else:
                        print(f"  {source} enUS: нет индексированной базовой сущности")
                else:
                    print(f"  {source} {locale}: нет данных")
            if kind == 'creature_text' and locale != 'enUS':
                entry, _ = bulk_decision(conn, kind, key, locale)
                if 'token_validation' in entry:
                    print('  token_validation: ' + json.dumps(entry['token_validation'], ensure_ascii=False, sort_keys=True))
    return 0


def command_compare(args: argparse.Namespace) -> int:
    key = entity_key(args.entity_type, args.entity_id)
    with open_index() as conn:
        rows = values_for_kind(conn, args.entity_type, key, [args.locale] if args.locale else None)
        for locale, field, status, detail in rows:
            print(f"{locale}\t{field}\t{status}\t{json.dumps(detail, ensure_ascii=False, sort_keys=True)}")
    return 0


def sql_quote(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace("'", "\\'").replace("\0", "\\0").replace("\n", "\\n").replace("\r", "\\r").replace("\x1a", "\\Z")
    return "'" + text + "'"


def _primary_export_rows(conn: sqlite3.Connection, kind: str, entity: str, locales: list[str] | None = None, *, comparisons: dict | None = None,
                allow_single_identity: bool = False, allow_verified_aliases: bool = False,
                _identity_sources: tuple[str, ...] | None = None, _fields: tuple[str, ...] | None = None) -> list[str]:
    ok, reason = identity_ok(conn, kind, entity, _identity_sources)
    single_identity_mode = not ok and kind == "item" and allow_single_identity
    alias_mode = not ok and kind in ("gameobject", "gossip_menu_option") and allow_verified_aliases
    if not ok and not single_identity_mode and not alias_mode:
        raise ValueError(f"Экспорт запрещён: {reason}")
    sql: list[str] = []
    if kind == "gossip_menu_option":
        menu, option = json.loads(entity)
    else:
        numeric_id = json.loads(entity)
    for locale in sorted(set(locales or [x for x in LOCALES if x != "enUS"]), key=lambda x: LOCALES[x]):
        if locale == "enUS":
            continue
        proof = single_item_identity(conn, entity, locale) if single_identity_mode else None
        alias = verified_alias(conn, kind, entity, locale) if alias_mode else None
        if alias_mode and not alias:
            raise ValueError("Экспорт запрещён: условия VERIFIED_ALIAS не выполнены")
        if single_identity_mode and not proof:
            raise ValueError("Экспорт запрещён: условия SAFE_SINGLE_IDENTITY не выполнены")
        fields_out = {}
        provenance = []
        statuses = []
        for field in (_fields if _fields is not None else text_fields_for(conn, kind, entity)):
            status, details = comparisons[(locale, field)] if comparisons is not None else _primary_compare_value(
                conn, kind, entity, locale, field, identity_sources=tuple(alias["identity_sources"]) if alias else (proof["confirmed_upstream"],) if proof else reference_sources(conn))
            statuses.append(status)
            ups = details.get("upstream", {})
            if status in ("MATCH", "SOURCE_ONLY", "SAFE_SINGLE_IDENTITY", "VERIFIED_ALIAS") and ups:
                fields_out[field] = next(iter(ups.values()))
                for src, p in details.get("provenance", {}).items():
                    revision = p.get("repository_revision") or "revision-unverified"
                    provenance.append(f"{src}@{revision}:{p['file']}:{p['table']}")
        if not fields_out:
            continue
        if kind == 'creature' and any(status in ('CONFLICT', 'UNSUPPORTED') for status in statuses):
            continue
        if proof:
            sql.append(f"-- SAFE_SINGLE_IDENTITY; confirmed={proof['confirmed_upstream']}; rejected={proof['rejected_upstream']}; --allow-single-identity")
        if alias:
            sql.append(f"-- VERIFIED_ALIAS; rule={alias['rule_name']}; --allow-verified-aliases")
        comment = " | ".join(sorted(set(provenance)))
        if kind == "gossip_menu_option":
            option_text = fields_out.get("optiontext", "")
            box_text = fields_out.get("boxtext", "")
            sql.append(f"-- {locale}; source: {comment}")
            sql.append("INSERT INTO `gossip_menu_option_locale` (`MenuID`,`OptionID`,`Locale`,`OptionText`,`BoxText`) VALUES "
                       f"({int(menu)},{int(option)},{sql_quote(locale)},{sql_quote(option_text)},{sql_quote(box_text)}) "
                       "ON DUPLICATE KEY UPDATE `OptionText`=IF(`OptionText` IS NULL OR `OptionText`='',VALUES(`OptionText`),`OptionText`), "
                       "`BoxText`=IF(`BoxText` IS NULL OR `BoxText`='',VALUES(`BoxText`),`BoxText`);")
        else:
            n = LOCALES[locale]
            table = SPECS[kind]["target_table"]
            assignments = []
            columns = list(creature_text.KEYS) if kind == 'creature_text' else [SPECS[kind]['target_id']]
            values = [str(int(v)) for v in numeric_id] if kind == 'creature_text' else [str(int(numeric_id))]
            for field, value in fields_out.items():
                if field.startswith('objective:'):
                    continue
                col = SPECS[kind]["wide_fields"][field].format(n=n)
                columns.append(col)
                values.append(sql_quote(value))
                assignments.append(f"`{col}`=IF(`{col}` IS NULL OR `{col}`='',{sql_quote(value)},`{col}`)")
            if assignments:
                sql.append(f"-- {locale}; source: {comment}")
                sql.append(f"INSERT INTO `{table}` ({','.join('`' + c + '`' for c in columns)}) VALUES ({','.join(values)}) "
                           f"ON DUPLICATE KEY UPDATE {', '.join(assignments)};")
            if kind == 'quest':
                for field, value in fields_out.items():
                    if field.startswith('objective:'):
                        objective = int(field.split(':')[1])
                        sql.append(f'-- quest {numeric_id}; {locale}; source: {comment}')
                        sql.append(f"INSERT INTO `locales_quest_objective` (`id`,`locale`,`description`) VALUES ({objective},{n},{sql_quote(value)}) ON DUPLICATE KEY UPDATE `description`=IF(`description` IS NULL OR `description`='',VALUES(`description`),`description`);")
    return sql


def command_export(args: argparse.Namespace) -> int:
    key = entity_key(args.entity_type, args.entity_id)
    locales = args.locale or [x for x in LOCALES if x != "enUS"]
    try:
        with open_index() as conn:
            out = export_rows(conn, args.entity_type, key, locales)
        target = Path(args.output) if args.output else None
        content = "\n".join(out) + ("\n" if out else "-- Нет безопасных строк для экспорта.\n")
        if target:
            if WORKSPACE.resolve() not in target.resolve().parents:
                raise ValueError('Generated SQL must stay under .tmp/localization/; use publish for final output')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            print(f"SQL сохранён для review (не выполнен): {target}")
        else:
            print(content, end="")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def command_manifest(args: argparse.Namespace) -> int:
    kind = args.entity_type
    key = entity_key(kind, args.entity_id)
    try:
        with open_index() as conn:
            results = []
            for locale, field, status, details in values_for_kind(conn, kind, key, args.locale or list(LOCALES)):
                results.append({"locale": locale, "field": field, "status": status, **details})
            identity, reason = identity_ok(conn, kind, key)
            source_evidence = evidence_roles.profile(conn)
        manifest = {
            "target": "SkyFire 5.4.8",
            "entity_type": kind,
            "entity_id": json.loads(key),
            "identity_verified": identity,
            "identity_reason": reason,
            "source_evidence": source_evidence,
            "locale_mapping": LOCALES,
            "results": results,
        }
        content = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            output = Path(args.output)
            if WORKSPACE.resolve() not in output.resolve().parents:
                raise ValueError('Generated reports must stay under .tmp/localization/')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8", newline="\n")
            print(f"Manifest сохранён для review (данные не применены): {output}")
        else:
            print(content, end="")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def single_item_identity(conn: sqlite3.Connection, entity: str, locale: str) -> dict | None:
    """A renamed upstream may corroborate text, never structural identity."""
    refs = reference_sources(conn)
    if len(refs) != 2:
        return None  # Preserve the two-reference exception; never discard other evidence.
    bases = {}
    for source in (*reference_sources(conn), "target"):
        row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind='item' AND entity=?", (source, entity)).fetchone()
        if not row:
            return None
        bases[source] = {"fields": json.loads(row[0]), "file": row[1], "table": SPECS["item"]["target_entity"]}
    fields = {source: base["fields"] for source, base in bases.items()}
    if not all(isinstance(base.get("name"), str) and base["name"].strip() for base in fields.values()):
        return None
    confirmed = [source for source in refs if identities_match("item", fields[source], fields["target"])]
    if len(confirmed) != 1:
        return None
    # All indexed non-text fields must be present and equal in all three bases.
    # class/subclass are mandatory; a partial/unknown structural field fails closed.
    structural = sorted(set().union(*(base.keys() for base in fields.values())) - {"name", "description"})
    if not {"class", "subclass"}.issubset(structural):
        return None
    for field in structural:
        values = [base.get(field) for base in fields.values()]
        if any(value is None for value in values) or not all(type(value) is type(values[0]) and value == values[0] for value in values):
            return None
        if field in ("class", "subclass") and (not isinstance(values[0], int) or isinstance(values[0], bool) or values[0] < 0):
            return None
    records = {source: get_record(conn, source, "item", entity, locale) for source in refs}
    if not all(records.values()):
        return None
    texts = {}
    for field in SPECS["item"]["text_fields"]:
        a, b = (records[source][0].get(field) for source in refs)
        a, b = (None if value in (None, "") else value for value in (a, b))
        if a != b or (a is not None and not isinstance(a, str)):
            return None
        if a is not None:
            texts[field] = a
    if not texts:
        return None
    rejected = next(source for source in refs if source != confirmed[0])
    return {"confirmed_upstream": confirmed[0], "rejected_upstream": rejected,
            "base_entities": bases, "structural_fields_checked": structural, "localization_text": texts,
            "provenance": {source: {"file": row[1], "table": SPECS["item"]["source_table"]} for source, row in records.items()},
            "reason": "Один upstream подтвердил identity SkyFire; оба upstream дают одинаковый текст; class/subclass и все индексированные структурные поля совпадают"}


def verified_alias(conn: sqlite3.Connection, kind: str, entity: str, locale: str) -> dict | None:
    if locale != "ruRU":
        return None
    key = json.loads(entity)
    if kind == "gameobject" and (not isinstance(key, int) or isinstance(key, bool)):
        return None
    if kind == "gossip_menu_option" and (not isinstance(key, list) or len(key) != 2 or not all(isinstance(part, int) and not isinstance(part, bool) for part in key)):
        return None
    lookup = tuple(key) if kind == "gossip_menu_option" and isinstance(key, list) else key
    rule = (GO_ALIAS_RULES if kind == "gameobject" else GOSSIP_ALIAS_RULES if kind == "gossip_menu_option" else {}).get(lookup)
    if rule is None:
        return None
    pair = alias_reference_pair(conn)
    if pair is None:
        return None
    origin, corroborator = pair
    required_sources = {origin, corroborator, 'target'}
    bases = {}
    for source in (*reference_sources(conn), "target"):
        row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
        if not row:
            if source in required_sources:
                return None
            continue
        bases[source] = {"fields": json.loads(row[0]), "file": row[1], "table": SPECS[kind]["target_entity"]}
    fields = {source: base["fields"] for source, base in bases.items()}
    if any(base.get("_evidence_incomplete") for base in fields.values()):
        return None
    text_field = "name" if kind == "gameobject" else "optiontext"
    rule_name, old, target_text, expected = rule
    if fields[origin].get(text_field) != old or fields["target"].get(text_field) != target_text:
        return None
    if fields[corroborator].get(text_field) != (target_text if kind == "gameobject" else old):
        return None
    for source in set(fields) - required_sources:
        # Missing evidence is neutral; available evidence must match an exact
        # established spelling, never a new normalization or inferred alias.
        for field in SPECS[kind]['text_fields']:
            value = fields[source].get(field)
            established = {fields[role].get(field) for role in required_sources}
            if value not in (None, '') and value not in established:
                return None
    if kind == "gameobject":
        required = {"type", "displayid", "size"} | {f"data{n}" for n in range(32)}
        if any(base.get("type") != expected for source, base in fields.items()
               if source in required_sources or 'type' in base):
            return None
        structural = sorted(set().union(*(base.keys() for base in fields.values())) - {"name", "castbarcaption"})
    else:
        required = {"optiontype", "optionicon", "optionnpcflag", "actionmenuid", "actionpoiid", "boxcoded", "boxmoney"}
        structural = sorted(required | {"optionbroadcasttextid", "boxbroadcasttextid"})
        if fields[corroborator].get("optionbroadcasttextid") != expected or fields["target"].get("optionbroadcasttextid") != expected:
            return None
    evidence = {}
    for field in structural:
        if field.startswith("_"):
            continue
        present = {source: base[field] for source, base in fields.items() if field in base}
        if field in required and (not required_sources.issubset(present) or any(value is None for value in present.values())):
            return None
        if field in required:
            types = (int, float) if field == "size" else (int,)
            if any(not isinstance(value, types) or isinstance(value, bool) for value in present.values()):
                return None
        if len(present) > 1 and not all(value == next(iter(present.values())) for value in present.values()):
            return None
        evidence[field] = present
    records = {source: get_record(conn, source, kind, entity, locale) for source in (*reference_sources(conn), "target")}
    texts = {source: {field: None if not row or row[0].get(field) in (None, "") else row[0][field] for field in SPECS[kind]["text_fields"]}
             for source, row in records.items()}
    if any(value is not None for value in texts["target"].values()):
        return None
    if not isinstance(texts[origin][text_field], str) or not texts[origin][text_field]:
        return None
    if any(value is not None and not isinstance(value, str) for source in texts for value in texts[source].values()):
        return None
    if kind == "gameobject":
        if not records[corroborator] or texts[origin] != texts[corroborator]:
            return None
    elif records[corroborator]:
        if any(texts[origin][field] != texts[corroborator][field] for field in SPECS[kind]["text_fields"]):
            return None
    for source in set(texts) - required_sources:
        if any(value is not None and value != texts[origin][field] for field, value in texts[source].items()):
            return None
    return {"rule_name": rule_name, "identity_sources": [corroborator], "evidence_roles": {'origin':origin,'corroborator':corroborator}, "reason": "Fixed key and exact English aliases verified; structure consistent; ruRU candidate agreed; target locale empty",
            "source_target_text": {source: base.get(text_field) for source, base in fields.items()},
            "structural_evidence": evidence, "base_entities": bases, "localization_text": texts,
            "broadcast_evidence": evidence.get("optionbroadcasttextid") if kind == "gossip_menu_option" else None,
            "provenance": {source: {"file": row[1], "table": SPECS[kind]["source_table"]} for source, row in records.items() if row}}


def _primary_bulk_decision(conn: sqlite3.Connection, kind: str, entity: str, locale: str, *, allow_single_identity: bool = False,
                  allow_verified_aliases: bool = False) -> tuple[dict, list[str]]:
    key = json.loads(entity)
    key_parts = key if kind in ("gossip_menu_option","creature_text") and isinstance(key, list) else [key]
    valid_key = (len(key_parts) == (3 if kind == "creature_text" else 2 if kind == "gossip_menu_option" else 1)
                 and all(isinstance(part, int) and not isinstance(part, bool) and part >= 0 for part in key_parts))
    if kind == "creature_text":
        valid_key = valid_key and valid_entity_key(kind,key)
    records = {source: get_record(conn, source, kind, entity, locale) for source in (*reference_sources(conn), "target")}
    fields = text_fields_for(conn, kind, entity)
    values = {source: {field: record[0].get(field) if record else None for field in fields}
              for source, record in records.items()}
    provenance = {source: {"file": record[1], "table": record[2]}
                  for source, record in records.items() if record}
    if kind == 'quest':
        for source, record in records.items():
            if record:
                provenance[source]['fields'] = record[0].get('_provenance', {})
    invalid_evidence = invalid_locale_values(conn, kind, entity, locale)
    invalid_sources = {value['source'] for value in invalid_evidence}
    candidates = [source for source in reference_sources(conn) if source in invalid_sources or any(value not in (None, "") for value in values[source].values())]
    identity, identity_reason = identity_ok(conn, kind, entity) if candidates else (False, "no candidates")
    proof = single_item_identity(conn, entity, locale) if kind == "item" and candidates and not identity and valid_key else None
    alias = verified_alias(conn, kind, entity, locale) if kind in ("gameobject", "gossip_menu_option") and valid_key and candidates else None
    # A translation donor must have its own verified identity; another upstream's
    # matching base row cannot establish identity for a SOURCE_ONLY donor.
    if identity and kind != 'npc_text':
        for source in candidates:
            if base_entity(conn, source, kind, entity) is None:
                identity, identity_reason = False, f"{source} no upstream base identity"
                break
    comparisons = {}
    for field in fields:
        if candidates and not identity and not proof and not alias:
            status, detail = "UNSUPPORTED", {"reason": identity_reason}
        elif not candidates:
            status, detail = ("TARGET_IDENTICAL" if values["target"][field] not in (None, "") else "MISSING"), {}
        else:
            # The index does not store upstream revisions. Do not let live Git
            # HEAD alter output from an otherwise unchanged index.
            status, detail = _primary_compare_value(conn, kind, entity, locale, field, indexed_provenance=True,
                                          identity_sources=tuple(alias["identity_sources"]) if alias else (proof["confirmed_upstream"],) if proof else reference_sources(conn), invalid_evidence=invalid_evidence,
                                          _allow_english_fallback=False)
            if alias and status in ("MATCH", "SOURCE_ONLY"):
                status = "VERIFIED_ALIAS"
            if proof and status == "MATCH":
                status = "SAFE_SINGLE_IDENTITY"
        if not valid_key:
            status, detail = "UNSUPPORTED", {"reason": "Неподдерживаемый entity key"}
        if any(value not in (None, "") and not isinstance(value, str) for value in (values[source][field] for source in values)):
            status, detail = "UNSUPPORTED", {"reason": "non-text localization value"}
        comparisons[field] = {"status": status, **detail}
    if identity and valid_key and not proof and not alias and any(d['status'] == 'CONFLICT' and len(d.get('upstream', {})) >= 3 for d in comparisons.values()):
        comparisons = confirmed_english_fallback_comparisons(conn, kind, entity, locale, indexed_provenance=True,
                                                             comparisons=comparisons) or comparisons
    statuses = {value["status"] for value in comparisons.values()}
    sql = []
    if (kind in ("quest", "npc_text") and identity and valid_key
            and statuses & {"MATCH", "SOURCE_ONLY"}
            and statuses & {"CONFLICT", "UNSUPPORTED"}):
        status, reason = "PARTIAL", "Экспорт только согласованных полей; заблокированные поля не изменяются"
        prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
        sql = _primary_export_rows(conn, kind, entity, [locale], comparisons=prepared)
    elif "UNSUPPORTED" in statuses:
        status = "UNSUPPORTED"
        reason = "Identity не подтверждена: " + identity_reason if candidates and not identity else "Неподдерживаемые localization data"
    elif "CONFLICT" in statuses:
        status, reason = "CONFLICT", "Переводы upstream расходятся или отличаются от непустого SkyFire translation"
    elif "VERIFIED_ALIAS" in statuses:
        status = "VERIFIED_ALIAS"
        reason = alias["reason"] + ("; экспорт разрешён --allow-verified-aliases" if allow_verified_aliases else "; экспорт требует --allow-verified-aliases")
        if allow_verified_aliases:
            prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
            sql = _primary_export_rows(conn, kind, entity, [locale], comparisons=prepared, allow_verified_aliases=True)
    elif "SAFE_SINGLE_IDENTITY" in statuses:
        status = "SAFE_SINGLE_IDENTITY"
        reason = proof["reason"] + ("; экспорт разрешён --allow-single-identity" if allow_single_identity else "; экспорт требует --allow-single-identity")
        if allow_single_identity:
            prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
            sql = _primary_export_rows(conn, kind, entity, [locale], comparisons=prepared, allow_single_identity=True)
    elif statuses & {"MATCH", "SOURCE_ONLY"}:
        status = "SOURCE_ONLY" if "SOURCE_ONLY" in statuses else "MATCH"
        prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
        sql = _primary_export_rows(conn, kind, entity, [locale], comparisons=prepared)
        reason = "Безопасный перевод"
    elif "TARGET_IDENTICAL" in statuses:
        status, reason = "TARGET_IDENTICAL", "SkyFire уже содержит совпадающий перевод; SQL не требуется"
    else:
        status, reason = "MISSING", "Нет upstream translation для выбранной locale"
    # Keep human-facing report reasons in Russian; raw identity details remain
    # inspectable through the existing single-entity commands.
    reason = reason.replace("target entity missing", "target entity отсутствует").replace("identity mismatch", "identity не совпадает").replace("no upstream base identity", "нет upstream base identity")
    for detail in comparisons.values():
        if kind == "db_script_string":
            continue  # Keep precise formatting diagnostics for this entity.
        if "reason" in detail:
            detail["reason"] = detail['reason'].replace('identity mismatch', 'identity не совпадает') if kind == 'quest' else reason
    entry = {"entity_type": kind, "entity_key": key, "locale": locale,
             "status": status, "reason": reason, "candidates_found": bool(candidates),
             "exported": bool(sql), "identity_failed": bool(candidates and not identity and not proof and not alias),
             "values": values, "provenance": provenance, "fields": comparisons}
    if kind in ('quest','npc_text','creature_text','page_text','skyfire_string','db_script_string'):
        for field, detail in comparisons.items():
            detail['exported'] = bool(sql) and detail['status'] in ('MATCH', 'SOURCE_ONLY')
        entry['exported_fields'] = sorted(field for field, detail in comparisons.items() if detail['exported'])
        entry['blocked_fields'] = sorted(field for field, detail in comparisons.items() if detail['status'] in ('CONFLICT', 'UNSUPPORTED'))
    invalid = invalid_evidence
    if invalid:
        entry['invalid_values'] = invalid
    rejections = [rejection for detail in comparisons.values() for rejection in detail.get('rejected_english_fallbacks', [])]
    if rejections:
        entry['rejected_english_fallbacks'] = rejections
    if proof:
        entry["single_identity"] = proof
    if alias:
        entry["verified_alias"] = alias
    if not sql or proof or alias or rejections or status == "PARTIAL":
        entry["base_entities"] = {}
        for source in (*reference_sources(conn), "target"):
            row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
            if row:
                entry["base_entities"][source] = {"fields": json.loads(row[0]), "file": row[1], "table": SPECS[kind]["target_entity"]}
    return entry, sql



def bulk_decision(conn: sqlite3.Connection, kind: str, entity: str, locale: str, *, allow_single_identity=False, allow_verified_aliases=False):
    if kind == 'achievement_reward':
        return achievement_reward.decide(sys.modules[__name__],conn,entity,locale)
    if kind == 'points_of_interest':
        return points_of_interest.decide(sys.modules[__name__],conn,entity,locale)
    entry, sql = evidence_roles.decide(sys.modules[__name__], conn, kind, entity, locale,
                                       allow_single_identity=allow_single_identity, allow_verified_aliases=allow_verified_aliases)
    if kind == 'creature_text' and locale != 'enUS':
        return creature_text_tokens.apply(sys.modules[__name__], conn, entity, entry, sql)
    return entry, sql


def compare_value(conn, kind, entity, locale, field, **kwargs):
    if kind == 'points_of_interest':
        entry,_ = points_of_interest.decide(sys.modules[__name__],conn,entity,locale)
        detail=entry['fields']['icon_name']
        return detail['status'], {k:v for k,v in detail.items() if k!='status'}
    if kwargs:
        # Explicit proof scopes are internal PRIMARY policy calls.
        metadata = evidence_roles.validate(conn)
        status, detail = _primary_compare_value(conn, kind, entity, locale, field, **kwargs)
        evidence_roles._annotate(detail, metadata)
        return status, detail
    if locale == 'enUS' or (kind != 'creature_text' and not evidence_roles.sources(conn, 'supplemental')):
        metadata = evidence_roles.validate(conn)
        status, detail = _primary_compare_value(conn, kind, entity, locale, field)
        evidence_roles._annotate(detail, metadata)
        return status, detail
    entry, _ = bulk_decision(conn, kind, entity, locale)
    detail = dict(entry['fields'].get(field, {'status': 'MISSING'}))
    observations = [r for r in entry.get('supplemental_observations', []) if r['field'] == field]
    if observations:
        detail['supplemental_observations'] = observations
    return detail['status'], {k: v for k, v in detail.items() if k != 'status'}


def export_rows(conn, kind, entity, locales=None, *, allow_single_identity=False, allow_verified_aliases=False, **kwargs):
    if kwargs:
        evidence_roles.validate(conn)
        return _primary_export_rows(conn, kind, entity, locales, allow_single_identity=allow_single_identity,
                                    allow_verified_aliases=allow_verified_aliases, **kwargs)
    evidence_roles.validate(conn)
    if not base_entity(conn, 'target', kind, entity):
        raise ValueError('Target entity отсутствует')
    result = []
    for locale in sorted(set(locales or [x for x in LOCALES if x != 'enUS']), key=lambda x: LOCALES.get(x, -1)):
        if locale == 'enUS':
            continue
        entry, sql = bulk_decision(conn, kind, entity, locale, allow_single_identity=allow_single_identity,
                                   allow_verified_aliases=allow_verified_aliases)
        result.extend(sql)
    return result


def bulk_export(conn: sqlite3.Connection, kinds: list[str], locale: str, directory: Path, *, allow_single_identity: bool = False,
                allow_verified_aliases: bool = False) -> dict:
    if locale not in LOCALES or locale == "enUS":
        raise ValueError("export-all поддерживает locale translations; enUS хранится в base entity tables")
    evidence_roles.validate(conn)
    kinds = sorted(set(kinds))
    if any(kind not in SPECS for kind in kinds):
        raise ValueError("Неподдерживаемый entity type")
    directory.mkdir(parents=True, exist_ok=True)
    summary = {}
    report_path = directory / f"report-{locale}.json"
    # Both the selection and output are streamed; only one entity's details are
    # held in Python memory. A transaction keeps all queries on one snapshot.
    with conn:
        conn.execute("BEGIN")
        with report_path.open("w", encoding="utf-8", newline="\n") as report:
            header = {"target": "SkyFire 5.4.8", "locale": locale, "selection": "indexed_target_entities",
                      "allow_single_identity": allow_single_identity,
                      "allow_verified_aliases": allow_verified_aliases,
                      "counter_units": "entity/locale statuses are mutually exclusive; PARTIAL includes blocked fields; *_fields count field values; identity_failed is included in unsupported; skipped = total_target_entities - exported",
                      "source_evidence": evidence_roles.profile(conn),
                      "sql_files": {kind: f"{kind}-{locale}.sql" for kind in kinds}}
            report.write(json.dumps(header, ensure_ascii=False, sort_keys=True, indent=2)[:-2] + ',\n  "entries": [\n')
            first_entry = True
            for kind in kinds:
                counts = {name: 0 for name in ("total_target_entities", "candidates_found", "exported", "MATCH", "SOURCE_ONLY", "SAFE_SINGLE_IDENTITY", "VERIFIED_ALIAS", "TARGET_IDENTICAL", "CONFLICT", "MISSING", "UNSUPPORTED", "identity_failed", "unsupported", "skipped", "PARTIAL", "exported_fields", "quest_row_fields", "objective_fields", "conflict_fields")}
                if kind in ('npc_text','creature_text'):
                    counts.update(npc_text_fields=0, creature_text_fields=0, primary_fields=0, supplemental_fields=0, direct_evidence=0, broadcast_backed_evidence=0, unsupported_fields=0)
                if kind in ('page_text','skyfire_string','db_script_string'):
                    counts.update(page_text_fields=0, primary_fields=0, supplemental_fields=0, unsupported_fields=0)
                if kind == 'achievement_reward':
                    counts.update(structural_mismatch=0, full_structural_identity=0, subject_fields=0, text_fields=0, achievement_reward_fields=0, primary_fields=0, supplemental_fields=0, unsupported_fields=0, placeholder_failures=0, confirmed_english_fallback=0, existing_target_protected=0)
                if kind == 'points_of_interest':
                    counts.update(AMBIGUOUS=0, exact_identity_matches=0, relationship_remapped_matches=0, primary_fields=0, supplemental_fields=0, existing_target_protected=0, confirmed_english_fallback=0, coordinate_mismatch=0, structural_mismatch=0, ambiguous_mapping=0, relationship_proof_failure=0)
                if kind in ('skyfire_string','db_script_string'):
                    counts.update({kind+'_fields':0, 'existing_target_protected':0,
                                   'confirmed_english_fallback':0, 'placeholder_failures':0})
                summary[kind] = counts
                order = "json_extract(entity,'$[0]'),json_extract(entity,'$[1]'),json_extract(entity,'$[2]'),entity" if kind == "creature_text" else "json_extract(entity,'$[0]'),json_extract(entity,'$[1]'),entity" if kind == "gossip_menu_option" else "json_extract(entity,'$'),entity"
                rows = conn.execute("SELECT entity FROM entities WHERE source='target' AND kind=? ORDER BY " + order, (kind,))
                with (directory / f"{kind}-{locale}.sql").open("w", encoding="utf-8", newline="\n") as sql_file:
                    sql_file.write(f"-- SkyFire 5.4.8; {kind}; {locale}; review SQL, not applied automatically.\n")
                    for (entity,) in rows:
                        entry, statements = bulk_decision(conn, kind, entity, locale, allow_single_identity=allow_single_identity,
                                                          allow_verified_aliases=allow_verified_aliases)
                        counts["total_target_entities"] += 1
                        counts["candidates_found"] += int(entry["candidates_found"])
                        counts[entry["status"]] += 1
                        if kind == 'achievement_reward':
                            achievement_reward.count_entry(counts,entry)
                        if kind in ('quest','npc_text','creature_text'):
                            selected = entry['exported_fields']
                            counts['exported_fields'] += len(selected)
                            if kind == 'quest':
                                counts['quest_row_fields'] += sum(not field.startswith('objective:') for field in selected)
                            else:
                                counts['creature_text_fields' if kind == 'creature_text' else 'npc_text_fields'] += len(selected)
                                for field in selected:
                                    detail = entry['fields'][field]
                                    counts['supplemental_fields' if detail.get('decision_origin') == 'supplemental' else 'primary_fields'] += 1
                                    for proof in detail.get('provenance',{}).values():
                                        counts['broadcast_backed_evidence' if proof.get('adapter') == 'broadcast-backed' else 'direct_evidence'] += 1
                                counts['unsupported_fields'] += sum(d['status'] == 'UNSUPPORTED' for d in entry['fields'].values())
                            counts['objective_fields'] += sum(field.startswith('objective:') for field in selected)
                            counts['conflict_fields'] += sum(detail['status'] == 'CONFLICT' for detail in entry['fields'].values())
                        if kind in ('page_text','skyfire_string','db_script_string'):
                            selected = entry['exported_fields']
                            counts['exported_fields'] += len(selected)
                            counts[kind+'_fields' if kind in ('skyfire_string','db_script_string') else 'page_text_fields'] += len(selected)
                            counts['conflict_fields'] += sum(d['status'] == 'CONFLICT' for d in entry['fields'].values())
                            counts['unsupported_fields'] += sum(d['status'] == 'UNSUPPORTED' for d in entry['fields'].values())
                            for field in selected:
                                detail = entry['fields'][field]
                                counts['supplemental_fields' if detail.get('decision_origin') == 'supplemental' else 'primary_fields'] += 1
                        if kind in ('skyfire_string','db_script_string'):
                            counts['existing_target_protected'] += int(bool((target_locale_record(conn,kind,entity,locale) or {}).get('content')))
                            counts['confirmed_english_fallback'] += len(entry.get('rejected_english_fallbacks',[])) + sum(
                                r.get('reason') == 'CONFIRMED_ENGLISH_FALLBACK' for r in entry.get('supplemental_observations',[]))
                            counts['placeholder_failures'] += sum(len(d.get('format_contract_failures',[])) for d in entry['fields'].values()) + sum(
                                r.get('reason') == 'FORMAT_CONTRACT_FAILURE' for r in entry.get('supplemental_observations',[]))
                        if kind == 'points_of_interest':
                            selected=entry['exported_fields']
                            counts['exported_fields']+=len(selected)
                            counts['supplemental_fields' if entry['fields']['icon_name']['decision_origin']=='supplemental' else 'primary_fields']+=len(selected)
                            counts['exact_identity_matches']+=int('EXACT_IDENTITY' in entry['identity_modes'])
                            counts['relationship_remapped_matches']+=int('STRONG_RELATIONSHIP_MATCH' in entry['identity_modes'])
                            counts['existing_target_protected']+=int(entry['existing_target_protected'])
                            for counter,reason in (('confirmed_english_fallback','CONFIRMED_ENGLISH_FALLBACK'),('coordinate_mismatch','COORDINATE_MISMATCH'),('structural_mismatch','STRUCTURAL_MISMATCH'),('ambiguous_mapping','AMBIGUOUS_MAPPING'),('relationship_proof_failure','RELATIONSHIP_PROOF_FAILURE')):
                                counts[counter]+=int(any(o.get('reason')==reason for o in entry['observations']))
                        counts["identity_failed"] += int(entry["identity_failed"])
                        counts["unsupported"] += int(entry["status"] == "UNSUPPORTED" or (kind == "points_of_interest" and entry["status"] == "AMBIGUOUS"))
                        if statements:
                            counts["exported"] += 1
                            sql_file.write("\n".join(statements) + "\n")
                        else:
                            counts["skipped"] += 1
                        if kind in ('quest','npc_text','creature_text','page_text','skyfire_string','db_script_string','points_of_interest','achievement_reward') or entry.get('supplemental_observations') or not statements or entry.get('invalid_values') or entry.get('rejected_english_fallbacks') or entry["status"] in ("SAFE_SINGLE_IDENTITY", "VERIFIED_ALIAS"):
                            if not first_entry:
                                report.write(",\n")
                            first_entry = False
                            report.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=2))
                print(f"{kind}: target {counts['total_target_entities']}, candidates {counts['candidates_found']}, exported {counts['exported']}, conflicts {counts['CONFLICT']}, skipped {counts['skipped']}", flush=True)
            totals = {key: sum(counts.get(key,0) for counts in summary.values()) for key in sorted({key for counts in summary.values() for key in counts})}
            report.write('\n  ],\n  "summary": ' + json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
            report.write(',\n  "totals": ' + json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2) + "\n}\n")
    publishing.create_bundle(directory, locale, summary)
    return summary


def command_export_all(args: argparse.Namespace) -> int:
    directory = Path(args.output_dir) if args.output_dir else WORKSPACE / "review" / args.locale
    if WORKSPACE.resolve() not in directory.resolve().parents:
        raise ValueError('Review output must stay under .tmp/localization/')
    with closing(open_index()) as conn:
        bulk_export(conn, [args.entity_type] if args.entity_type else list(SPECS), args.locale, directory,
                    allow_single_identity=args.allow_single_identity, allow_verified_aliases=args.allow_verified_aliases)
    print(f"SQL и report сохранены для review: {directory}")
    return 0


def command_publish(args: argparse.Namespace) -> int:
    directory = Path(args.input_dir) if args.input_dir else WORKSPACE / 'review' / args.locale
    if WORKSPACE.resolve() not in directory.resolve().parents:
        raise ValueError('Reviewed inputs must be under .tmp/localization/')
    if args.command == 'approve-review':
        result = publishing.approve(directory, args.locale, args.acknowledge_skipped)
    else:
        output = ROOT / 'localizations' / args.locale
        if ROOT.resolve() not in output.resolve().parents:
            raise ValueError('Publication output must stay inside this repository')
        result = publishing.publish(directory, output, args.locale, args.entity_types, SPECS, LOCALES)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ('coverage','report'):
        q=sub.add_parser(command,help='Read existing review coverage' if command=='coverage' else 'Read existing review metadata')
        q.add_argument('--locale',required=True,choices=tuple(code for code in LOCALES if code!='enUS'))
        if command=='coverage':
            q.add_argument('--verbose',action='store_true',help='Show all diagnostic and entity-specific counters')
            q.add_argument('--json',action='store_true',help='Print deterministic JSON to stdout only')
    for command in ('source-contribution','gaps'):
        q=sub.add_parser(command,help='Read-only decision analytics over the existing index')
        q.add_argument('--locale',required=True,choices=tuple(code for code in LOCALES if code!='enUS'))
        q.add_argument('--json',action='store_true',help='Print deterministic JSON')
        if command=='source-contribution':q.add_argument('--verbose',action='store_true')
        else:q.add_argument('--entity',choices=tuple(sorted(set(SPECS)|{'quest_objective'})))
    sub.add_parser("index", help="Build the local streaming SQLite index")
    q=sub.add_parser("sources",help="Read-only reference summary")
    q.add_argument("--json",action="store_true",help="Print deterministic JSON")
    for command in ("source-scan","source-init","source-validate"):
        q=sub.add_parser(command,help="Inspect, configure or validate local reference inputs")
        q.add_argument("source_path",nargs=None if command=="source-init" else "?",help="Source directory containing repo/ and/or db/")
        if command!="source-init":
            q.add_argument("--all",action="store_true",help="Process all reference directories")
            q.add_argument("--json",action="store_true",help="Print deterministic JSON")
    for command in ('approve-review', 'publish'):
        q = sub.add_parser(command, help='Record review approval' if command == 'approve-review' else 'Publish hash-bound reviewed SQL, offline')
        q.add_argument('--locale', required=True, choices=tuple(code for code in LOCALES if code != 'enUS'))
        q.add_argument('--input-dir', help='Reviewed input directory under .tmp/localization/')
        if command == 'approve-review':
            q.add_argument('--acknowledge-skipped', action='store_true', help='Explicitly acknowledge conflicts/skips in the reviewed report')
        else:
            q.add_argument('entity_types', nargs='*', choices=tuple(SPECS))
    q = sub.add_parser("export-all", help="Export safe target translations and a review report")
    q.add_argument("entity_type", nargs="?", choices=tuple(SPECS))
    q.add_argument("--locale", required=True, choices=tuple(code for code in LOCALES if code != "enUS"))
    q.add_argument("--output-dir", help="Review directory under .tmp/localization/; default review/<locale>")
    q.add_argument("--allow-single-identity", action="store_true", help="Enable item SAFE_SINGLE_IDENTITY after text and structure verification")
    q.add_argument("--allow-verified-aliases", action="store_true", help="Enable only fixed gameobject/gossip aliases with complete evidence")
    for cmd in ("inspect", "compare", "export"):
        q = sub.add_parser(cmd)
        q.add_argument("entity_type", choices=tuple(SPECS))
        q.add_argument("entity_id", help="ID; gossip_menu_option: MenuID,OptionID; creature_text: Entry,GroupID,ID")
        if cmd != "export":
            q.add_argument("--locale", choices=tuple(LOCALES))
        else:
            q.add_argument("--locale", action="append", choices=tuple(LOCALES))
            q.add_argument("--output", help="путь для review SQL; по умолчанию stdout")
    q = sub.add_parser("export-manifest", help="создать provenance manifest для review")
    q.add_argument("entity_type", choices=tuple(SPECS))
    q.add_argument("entity_id", help="ID; gossip_menu_option: MenuID,OptionID; creature_text: Entry,GroupID,ID")
    q.add_argument("--locale", action="append", choices=tuple(LOCALES))
    q.add_argument("--output", help="JSON path under .tmp/localization/; default stdout")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command in ('source-contribution','gaps'):
            return analytics.command(sys.modules[__name__],args)
        if args.command in ('coverage','report'):
            return reporting.command(sys.modules[__name__],args)
        if args.command in ("sources","source-scan","source-init","source-validate"):
            return source_setup.command(sys.modules[__name__],args)
        if args.command == "index":
            return build_index(args)
        if args.command == "export-all":
            return command_export_all(args)
        if args.command in ('approve-review','publish'):
            return command_publish(args)
        if args.command == "inspect":
            return command_inspect(args)
        if args.command == "compare":
            return command_compare(args)
        if args.command == "export-manifest":
            return command_manifest(args)
        return command_export(args)
    except (RuntimeError, ValueError, sqlite3.Error, OSError, zipfile.BadZipFile) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

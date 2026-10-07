#!/usr/bin/env python3
"""Офлайн-индекс, сравнение и безопасная подготовка SQL локализаций для SkyFire 5.4.8."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from collections import deque
from pathlib import Path
from typing import Iterator, TextIO

ROOT = Path(__file__).resolve().parents[2]
PORTING = ROOT / ".porting" / "localization"
INDEX = PORTING / "localization-index.sqlite3"
LOCALES = {
    "enUS": 0, "koKR": 1, "frFR": 2, "deDE": 3, "zhCN": 4, "zhTW": 5,
    "esES": 6, "esMX": 7, "ruRU": 8, "itIT": 9, "ptBR": 10, "ptPT": 11,
}
SKIP_DIRS = {"old", "pending", "archive", "archives", "deprecated", "legacy"}

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
            while True:
                n = self._char()
                if not n:
                    break
                if n == "\\" and quote != "`":
                    esc = self._char()
                    if not esc:
                        break
                    value.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}.get(esc, esc))
                elif n == quote:
                    if self._peek() == quote:
                        self._char()
                        value.append(quote)
                    else:
                        break
                else:
                    value.append(n)
            return ("string" if quote != "`" else "word", "".join(value))
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


def active_files() -> list[tuple[str, Path, str | None]]:
    result = []
    def walk_error(error: OSError) -> None:
        raise RuntimeError(f"Не удалось прочитать каталог источников: {error}") from error

    for source in ("alexkulya", "loap", "skyfire"):
        for location in ("repo", "db"):
            base = ROOT / ".porting" / "sources" / source / location
            if not base.exists():
                continue
            for directory, dirs, files in os.walk(base, onerror=walk_error, followlinks=False):
                dirs[:] = sorted(name for name in dirs if name.casefold() not in SKIP_DIRS | {".git"})
                for name in sorted(files):
                    path = Path(directory) / name
                    if path.suffix.casefold() == ".sql":
                        result.append((source, path, None))
                    elif path.suffix.casefold() == ".zip":
                        try:
                            # Read archive metadata only; SQL members are streamed later.
                            with zipfile.ZipFile(path) as archive:
                                for info in archive.infolist():
                                    member = info.filename.replace("\\", "/")
                                    if (not info.is_dir() and member.casefold().endswith(".sql")
                                            and not any(part.casefold() in SKIP_DIRS for part in member.split("/")[:-1])):
                                        result.append((source, path, info.filename))
                        except (OSError, zipfile.BadZipFile) as exc:
                            raise RuntimeError(f"Не удалось прочитать SQL-архив {path}: {exc}") from exc
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
    source_repo = ROOT / ".porting" / "sources" / source / "repo"
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
    conn.execute("CREATE INDEX IF NOT EXISTS entities_name_idx ON entities(source,kind,json_extract(fields,'$.name'))")
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


def parse_create(t: Tokens, source: str, file: str, schemas: dict[tuple[str, str], list[str]]) -> None:
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
    if t.get()[0] != "(":
        skip_statement(t)
        return
    depth, cols, segment = 1, [], []
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
                    first = segment[0][1].lower()
                    if segment[0][0] == "word" and first not in {"primary", "unique", "key", "index", "constraint", "foreign", "fulltext", "spatial"}:
                        cols.append(first)
                break
        if x[0] == "," and depth == 1:
            if segment:
                first = segment[0][1].lower()
                if segment[0][0] == "word" and first not in {"primary", "unique", "key", "index", "constraint", "foreign", "fulltext", "spatial"}:
                    cols.append(first)
            segment = []
        else:
            segment.append(x)
    schemas[(source, name)] = cols
    skip_statement(t)


def literal_tuple(t: Tokens) -> list[object]:
    # Called after opening parenthesis. Consume expressions conservatively.
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
                values.append(sql_value(expr, t.variables))
                break
        elif x[0] == "," and depth == 0:
            values.append(sql_value(expr, t.variables))
            expr = []
        else:
            expr.append(x)
    return values


def sql_value(expr: list[tuple[str, str]], variables: dict[str, object] | None = None) -> object:
    if len(expr) == 1:
        kind, val = expr[0]
        if kind == "string":
            return val
        if val.startswith("@"):
            if variables is None or val.casefold() not in variables:
                raise ValueError(f"неопределённая SQL-переменная: {val}")
            return variables[val.casefold()]
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
    kind = next((k for k, spec in SPECS.items() if table == spec["source_table"] or table == spec["target_table"]), None)
    if not kind:
        return None
    spec = SPECS[kind]
    if not cols or len(cols) != len(vals):
        return None
    row = {str(c).lower(): v for c, v in zip(cols, vals)}
    # Source row-style localization.
    if table == spec["source_table"]:
        if kind == "gossip_menu_option":
            entity = (row.get("menuid"), row.get("optionid", row.get("optionindex")))
        else:
            entity = row.get(spec["source_id"])
        locale = row.get(spec["source_locale"])
        if entity is None or locale not in LOCALES:
            return None
        fields = {key: row.get(col) for key, col in spec["source_target_fields"].items()}
        return kind, json.dumps(entity, ensure_ascii=False), str(locale), fields
    # SkyFire wide table: only non-enUS localized slots are represented here.
    if kind == "gossip_menu_option":
        return None
    entity = row.get(spec["target_id"])
    if entity is None:
        return None
    for locale, index in LOCALES.items():
        if index == 0:
            continue
        fields = {}
        for canonical, pattern in spec["wide_fields"].items():
            col = pattern.format(n=index)
            value = row.get(col)
            if value not in (None, ""):
                fields[canonical] = value
        if fields:
            # One INSERT row can populate multiple locales; caller expands below.
            pass
    return kind, json.dumps(entity, ensure_ascii=False), "__wide__", row


def identity_fields(kind: str, row: dict[str, object]) -> dict[str, object]:
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


def persist_entity(conn: sqlite3.Connection, source: str, kind: str, row: dict[str, object], file: str, rank: int) -> None:
    spec = SPECS[kind]
    if kind == "gossip_menu_option":
        ident = (row.get("menuid", row.get("menu_id")), row.get("optionid", row.get("optionindex", row.get("id"))))
    else:
        ident = row.get(spec["entity_fields"][0])
    if ident is None:
        return
    fields = identity_fields(kind, row)
    if not fields:
        return
    conn.execute("INSERT INTO entities VALUES(?,?,?,?,?,?) ON CONFLICT(source,kind,entity) DO UPDATE SET fields=excluded.fields,file=excluded.file,rank=excluded.rank WHERE excluded.rank>=entities.rank",
                 (source, kind, json.dumps(ident, ensure_ascii=False), json.dumps(fields, ensure_ascii=False), file, rank))


def persist_locale(conn: sqlite3.Connection, source: str, kind: str, entity: str, locale: str, fields: dict[str, object], file: str, rank: int) -> None:
    clean = {k: v for k, v in fields.items() if v not in (None, "")}
    if not clean:
        conn.execute("DELETE FROM records WHERE source=? AND kind=? AND entity=? AND locale=? AND rank<=?",
                     (source, kind, entity, locale, rank))
        return
    conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,kind,entity,locale) DO UPDATE SET fields=excluded.fields,file=excluded.file,rank=excluded.rank WHERE excluded.rank>=records.rank",
                 (source, kind, entity, locale, json.dumps(clean, ensure_ascii=False), file, rank))


def parse_insert(t: Tokens, source: str, file: str, schemas: dict[tuple[str, str], list[str]], conn: sqlite3.Connection, rank: int,
                 phase: str, candidates: set[str]) -> None:
    first = t.get()
    if first[1].upper() == "IGNORE":
        first = t.get()
    if first[1].upper() != "INTO":
        t.unget(first)
        return
    table = next_name(t)
    if not table:
        skip_statement(t)
        return
    locale_tables = {spec["target_table"] if source == "skyfire" else spec["source_table"] for spec in SPECS.values()}
    entity_tables = {spec["target_entity"] for spec in SPECS.values()} | {"gossip_menu_option_box", "gossip_menu_option_action"}
    relevant = locale_tables if phase == "locales" else entity_tables
    if table not in relevant:
        t.skip_raw_statement()
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
        if x[1].upper() == "VALUES" or (x[1].upper() == "VALUE"):
            break
    if cols is None:
        cols = schemas.get((source, table))
    if not cols:
        skip_statement(t)
        return
    while True:
        x = t.get()
        if x[0] == "(":
            if phase == "entities" and cols:
                first_index = next((cols.index(c) for c in ("entry", "menuid", "menu_id") if c in cols), -1)
                if first_index == 0:
                    # Read the integer entity key before paying to tokenize every non-candidate row.
                    prefix = t.get()
                    try:
                        key_value = int(sql_value([prefix], t.variables))
                    except (ValueError, TypeError):
                        key_value = None
                    if table in ("gossip_menu_option", "gossip_menu_option_box", "gossip_menu_option_action"):
                        comma = t.get()
                        second = t.get()
                        comma2 = t.get()
                        try:
                            second_value = int(sql_value([second], t.variables))
                            candidate_key = json.dumps((key_value, second_value))
                        except (ValueError, TypeError):
                            candidate_key = ""
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
                        rest = literal_tuple(t)
                        vals = [sql_value([vals_prefix[0]], t.variables), sql_value([vals_prefix[1]], t.variables)] + rest
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
                        rest = literal_tuple(t)
                        vals = [sql_value([prefix], t.variables)] + rest
                else:
                    vals = literal_tuple(t)
            else:
                vals = literal_tuple(t)
            if len(cols) == len(vals):
                row = {c: v for c, v in zip(cols, vals)}
                spec_kind = next((k for k, s in SPECS.items() if table == s["source_table"] or table == s["target_table"]), None)
                if spec_kind:
                    if table == SPECS[spec_kind]["target_table"] and spec_kind != "gossip_menu_option":
                        entity = row.get(SPECS[spec_kind]["target_id"])
                        if entity is not None:
                            for locale, n in LOCALES.items():
                                if n == 0:
                                    continue
                                fields = {key: row.get(pattern.format(n=n)) for key, pattern in SPECS[spec_kind]["wide_fields"].items()}
                                persist_locale(conn, source, spec_kind, json.dumps(entity), locale, fields, file, rank)
                    else:
                        normalized = normalized_row(source, table, cols, vals)
                        if normalized:
                            kind, entity, locale, fields = normalized
                            persist_locale(conn, source, kind, entity, locale, fields, file, rank)
                if table in ("gossip_menu_option_box", "gossip_menu_option_action"):
                    menu, option = row.get("menuid"), row.get("optionindex", row.get("optionid"))
                    if isinstance(menu, int) and isinstance(option, int):
                        if table == "gossip_menu_option_box":
                            conn.execute("INSERT OR REPLACE INTO gossip_boxes VALUES(?,?,?,?)",
                                         (source, json.dumps((menu, option)), row.get("boxtext"), file))
                        conn.execute("INSERT OR REPLACE INTO gossip_aux VALUES(?,?,?,?,?)",
                                     (source, json.dumps((menu, option)), table, json.dumps(identity_fields("gossip_menu_option", row), ensure_ascii=False), file))
                # Base entity identity records.
                base_map = {"item_template": "item", "gameobject_template": "gameobject", "gossip_menu_option": "gossip_menu_option"}
                if table in base_map:
                    persist_entity(conn, source, base_map[table], row, file, rank)
                if conn.total_changes - parse_insert.last_commit >= 20000:
                    conn.commit()
                    parse_insert.last_commit = conn.total_changes
            sep = t.get()
            if sep[0] == ",":
                continue
            if sep[0] == ";" or sep[0] == "eof":
                return
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


def rank_for(file: str) -> int:
    p = file.lower()
    if "/repo/sql/base/" in p:
        return 10
    if "/db/" in p:
        return 20
    return 30


def scan_file(conn: sqlite3.Connection, source: str, path: Path, member: str | None, schemas: dict[tuple[str, str], list[str]], phase: str,
              candidates: set[str]) -> None:
    file = path.relative_to(ROOT).as_posix() + (("!" + member) if member else "")
    rank = rank_for(file)
    size = path.stat().st_size
    conn.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (source, file, size, "indexed"))
    if size >= 50_000_000:
        print(f"[{source}] потоковая обработка {file} ({size:,} bytes)", flush=True)
    with open_sql(path, member) as stream:
        t = Tokens(stream)
        while True:
            token = t.get()
            if token[0] == "eof":
                break
            word = token[1].upper()
            if word == "CREATE":
                parse_create(t, source, file, schemas)
            elif word in ("INSERT", "REPLACE"):
                parse_insert(t, source, file, schemas, conn, rank, phase, candidates)
            elif word == "DELETE":
                parse_delete(t, source, file, conn, phase)
            elif word == "UPDATE":
                parse_update(t, source, file, conn, phase)
            elif word == "SET":
                parse_set(t)
            # Index commits in manageable batches.
            if conn.total_changes and conn.total_changes % 50000 < 500:
                conn.commit()


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


def parse_set(t: Tokens) -> None:
    tokens = statement_tokens(t)
    # Only literal user variables. Session/system SETs are irrelevant here.
    for part in split_tokens(tokens, ","):
        if len(part) == 3 and part[0][1].startswith("@") and not part[0][1].startswith("@@") and part[1][0] == "=":
            name = part[0][1].rstrip(":").casefold()
            try:
                t.variables[name] = sql_value([part[2]], t.variables)
            except ValueError:
                t.variables.pop(name, None)


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
    for kind, spec in SPECS.items():
        if table == spec["target_entity"]:
            return kind, "entities"
        if table in (spec["source_table"], spec["target_table"]):
            if source and table != (spec["target_table"] if source == "skyfire" else spec["source_table"]):
                return None
            return kind, "records"
    return None


def predicate_sql(tokens: list[tuple[str, str]], kind: str, storage: str, variables: dict[str, object]) -> tuple[str, list[object]]:
    # Deliberately restricted, parameterized subset: equality, IN, BETWEEN, AND.
    pos, fragments, params = 0, [], []
    while pos < len(tokens):
        col = tokens[pos][1].lower()
        if tokens[pos][0] == "(":
            end = next(i for i in range(pos + 1, len(tokens)) if tokens[i][0] == ")")
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
                        values.append(sql_value([tokens[pos]], variables))
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
        if kind == "gossip_menu_option" and col in ("menuid", "menu_id", "optionid", "optionindex", "id"):
            expression = "json_extract(entity,'$[%d]')" % (0 if col in ("menuid", "menu_id") else 1)
        elif col in ("entry", "id") and kind != "gossip_menu_option":
            expression = "json_extract(entity,'$')"
        elif col == "locale" and storage == "records":
            expression = "locale"
        else:
            table = SPECS[kind]["target_entity"] if storage == "entities" else SPECS[kind]["source_table"]
            mapped = normalized_update_field(kind, table, col)
            if not mapped:
                raise ValueError(f"неподдерживаемое поле WHERE: {col}")
            expression = "json_extract(fields,'$.%s')" % mapped[0]
        if pos >= len(tokens):
            raise ValueError("неполный WHERE")
        op = tokens[pos][1].upper()
        pos += 1
        if op in ("=", "<>", "!=", "<", ">", "<=", ">="):
            fragments.append(expression + op + "?")
            params.append(sql_value([tokens[pos]], variables))
            pos += 1
        elif op == "BETWEEN":
            low = sql_value([tokens[pos]], variables)
            if tokens[pos + 1][1].upper() != "AND":
                raise ValueError("неполный BETWEEN")
            high = sql_value([tokens[pos + 2]], variables)
            fragments.append(expression + " BETWEEN ? AND ?")
            params.extend([low, high])
            pos += 3
        elif op == "IN":
            if tokens[pos][0] != "(":
                raise ValueError("ожидается IN (...)")
            pos += 1
            values = []
            while tokens[pos][0] != ")":
                values.append(sql_value([tokens[pos]], variables))
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


def parser_warning(conn: sqlite3.Connection, source: str, file: str, message: str) -> None:
    conn.execute("INSERT INTO warnings SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM warnings WHERE source=? AND file=? AND message=?)",
                 (source, file, message, source, file, message))


def parse_delete(t: Tokens, source: str, file: str, conn: sqlite3.Connection, phase: str | None = None) -> None:
    if t.get()[1].upper() != "FROM":
        skip_statement(t)
        return
    table = next_name(t)
    if table not in TARGET_TABLES:
        t.skip_raw_statement()
        return
    tokens = statement_tokens(t)
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
        conn.execute(f"DELETE FROM {storage} WHERE source=? AND kind=? AND " + condition, [source, kind] + params)
    except (ValueError, IndexError) as exc:
        parser_warning(conn, source, file, f"DELETE {table}: {exc}")


def normalized_update_field(kind: str, table: str, column: str) -> tuple[str, str] | None:
    spec = SPECS[kind]
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
                match = re.fullmatch(re.escape(pattern.split("{n}")[0]) + r"(\d+)", column)
                if match:
                    index = int(match.group(1))
                    locale = next((code for code, value in LOCALES.items() if value == index), None)
                    return (field, locale) if locale else None
    return None


def apply_simple_update(conn: sqlite3.Connection, source: str, table: str, assignments: dict[str, object], where: dict[str, object], file: str, rank: int) -> bool:
    kind = next((k for k, spec in SPECS.items() if table in (spec["target_entity"], spec["source_table"], spec["target_table"])), None)
    if not kind:
        return False
    spec = SPECS[kind]
    if table == spec["target_entity"]:
        if kind == "gossip_menu_option":
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
        return True
    # Locale row updates require an entity key and locale. Wide target rows derive locale from _locN.
    if kind == "gossip_menu_option":
        menu, option = where.get("menuid", where.get("menu_id")), where.get("optionid", where.get("id"))
        entity = json.dumps((menu, option)) if menu is not None and option is not None else None
        locale = where.get("locale")
    else:
        idcol = "id" if table == spec["source_table"] and kind == "item" else "entry"
        entity_id = where.get(idcol)
        entity = json.dumps(entity_id) if entity_id is not None else None
        locale = where.get("locale")
    if not entity:
        return False
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
        persist_locale(conn, source, kind, entity, loc, fields, file, rank)
    return True


def apply_gossip_box_join(conn: sqlite3.Connection, source: str, file: str, tokens: list[tuple[str, str]]) -> bool:
    # Recognize LOAP's specific schema migration, not arbitrary JOIN execution.
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


def parse_update(t: Tokens, source: str, file: str, conn: sqlite3.Connection, phase: str | None = None) -> None:
    table = next_name(t)
    if table not in TARGET_TABLES:
        t.skip_raw_statement()
        return
    tokens = statement_tokens(t)  # Consume exactly once, including ignored metadata updates.
    info = table_info(table, source)
    if not info:
        return
    kind, storage = info
    if phase and phase != ("entities" if storage == "entities" else "locales"):
        return
    try:
        if not tokens or tokens[0][1].upper() != "SET":
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
                if len(expression) != 1 and not re.fullmatch(r"[-+]?\d+\.\d+", "".join(token[1] for token in expression)):
                    raise ValueError("неподдерживаемое выражение SET")
                assignments[part[0][1].lower()] = sql_value(expression, t.variables)
        if not relevant:
            return  # Gameplay metadata is intentionally outside this index.
        condition, params = predicate_sql(tokens[where_pos + 1:], kind, storage, t.variables)
        rows = conn.execute(f"SELECT entity" + (",locale" if storage == "records" else "") + f" FROM {storage} WHERE source=? AND kind=? AND " + condition, [source, kind] + params).fetchall()
        for row in rows:
            key = json.loads(row[0])
            where = {"menuid": key[0], "optionid": key[1]} if kind == "gossip_menu_option" else {"id" if table == SPECS[kind]["source_table"] and kind == "item" else "entry": key}
            if storage == "records":
                where["locale"] = row[1]
            if not apply_simple_update(conn, source, table, assignments, where, file, rank_for(file)):
                raise ValueError("UPDATE не применён")
    except (ValueError, IndexError) as exc:
        parser_warning(conn, source, file, f"UPDATE {table}: {exc}")
        if storage == "entities" and kind in ("gameobject", "gossip_menu_option"):
            condition, params = "1", []
            try:
                marker = next(i for i, token in enumerate(tokens) if token[1].upper() == "WHERE")
                condition, params = predicate_sql(tokens[marker + 1:], kind, storage, t.variables)
            except (ValueError, IndexError, StopIteration):
                pass
            conn.execute("UPDATE entities SET fields=json_set(fields,'$._evidence_incomplete',1) WHERE source=? AND kind=? AND " + condition, [source, kind] + params)


def build_index(_: argparse.Namespace) -> int:
    sources = active_files()
    if not sources:
        raise RuntimeError("SQL-источники не найдены. Подготовьте .porting/sources/<source>/repo/ и/или db/.")
    PORTING.mkdir(parents=True, exist_ok=True)
    if INDEX.exists():
        INDEX.unlink()
    conn = db_connect(INDEX)
    schemas: dict[tuple[str, str], list[str]] = {}
    counts = {s: 0 for s in ("alexkulya", "loap", "skyfire")}
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
            print(f"Ошибка индексации {path}: {exc}", file=sys.stderr)
        conn.commit()
    conn.commit()
    # Base entity indexing is sparse: only IDs with candidate translations are decoded in detail.
    candidates_by_source = {}
    for source in ("alexkulya", "loap", "skyfire"):
        ids = {row[0] for row in conn.execute("SELECT DISTINCT entity FROM records WHERE source=?", (source,))}
        ids.update(row[0] for row in conn.execute("SELECT DISTINCT entity FROM records WHERE kind='gossip_menu_option'"))
        if source == "skyfire":
            for upstream in ("alexkulya", "loap"):
                ids.update(row[0] for row in conn.execute("SELECT DISTINCT entity FROM records WHERE source=?", (upstream,)))
        candidates_by_source[source] = ids
    for source, path, member in sources:
        if not path.exists():
            continue
        try:
            scan_file(conn, source, path, member, schemas, "entities", candidates_by_source[source])
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            conn.execute("INSERT INTO warnings VALUES(?,?,?)", (source, str(path), "entity pass: " + str(exc)))
            print(f"Ошибка entity-pass {path}: {exc}", file=sys.stderr)
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


def get_record(conn: sqlite3.Connection, source: str, kind: str, entity: str, locale: str) -> tuple[dict, str, str] | None:
    row = conn.execute("SELECT fields,file,kind FROM records WHERE source=? AND kind=? AND entity=? AND locale=?", (source, kind, entity, locale)).fetchone()
    return (json.loads(row[0]), row[1], row[2]) if row else None


def entity_key(kind: str, entity_arg: str) -> str:
    if kind == "gossip_menu_option":
        values = entity_arg.split(",")
        if len(values) != 2:
            raise ValueError("Для gossip_menu_option укажите MenuID,OptionID через запятую")
        return json.dumps(tuple(int(v) for v in values))
    return json.dumps(int(entity_arg))


def target_locale_record(conn: sqlite3.Connection, kind: str, entity: str, locale: str) -> dict | None:
    return get_record(conn, "skyfire", kind, entity, locale)[0] if get_record(conn, "skyfire", kind, entity, locale) else None


def base_entity(conn: sqlite3.Connection, source: str, kind: str, entity: str) -> dict | None:
    row = conn.execute("SELECT fields FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
    return json.loads(row[0]) if row else None


def norm_identity(kind: str, fields: dict) -> tuple:
    if kind == "gossip_menu_option":
        bt = fields.get("optionbroadcasttextid")
        if bt not in (None, "", 0, "0"):
            return ("broadcast", str(bt))
        text = fields.get("optiontext")
        return ("text", " ".join(str(text or "").split()).casefold())
    if kind == "item":
        return ("name", " ".join(str(fields.get("name") or "").split()).casefold())
    return ("name-type", " ".join(str(fields.get("name") or "").split()).casefold(), str(fields.get("type")))


def identities_match(kind: str, source: dict, target: dict) -> bool:
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


def identity_ok(conn: sqlite3.Connection, kind: str, entity: str, sources: tuple[str, ...] = ("alexkulya", "loap")) -> tuple[bool, str]:
    target = base_entity(conn, "skyfire", kind, entity)
    if not target:
        return False, "target entity missing"
    tid = norm_identity(kind, target)
    seen = False
    for src in sources:
        candidate = base_entity(conn, src, kind, entity)
        if candidate:
            seen = True
            if not identities_match(kind, candidate, target):
                return False, f"{src} identity mismatch"
    return (True, "identity verified") if seen else (False, "no upstream base identity")


def compare_value(conn: sqlite3.Connection, kind: str, entity: str, locale: str, field: str, *, indexed_provenance: bool = False,
                  identity_sources: tuple[str, ...] = ("alexkulya", "loap")) -> tuple[str, dict[str, object]]:
    if locale not in LOCALES:
        return "UNSUPPORTED", {"reason": "unknown locale"}
    identity, reason = identity_ok(conn, kind, entity, identity_sources)
    if not identity:
        return ("MISSING" if reason == "target entity missing" else "UNSUPPORTED"), {"reason": reason}
    if locale == "enUS":
        upstream, provenance = {}, {}
        for source in ("alexkulya", "loap"):
            row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
            if row:
                text = json.loads(row[0]).get(field)
                if text not in (None, ""):
                    upstream[source] = str(text)
                    revision = None if indexed_provenance else source_revision(source)
                    provenance[source] = {"repository_revision": revision, "revision_verified": revision is not None,
                                          "file": row[1], "table": SPECS[kind]["target_entity"]}
        target_row = conn.execute("SELECT fields FROM entities WHERE source='skyfire' AND kind=? AND entity=?", (kind, entity)).fetchone()
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
        return ("MATCH" if len(upstream) == 2 else "SOURCE_ONLY"), details
    upstream = {}
    provenance = {}
    for source in ("alexkulya", "loap"):
        item = get_record(conn, source, kind, entity, locale)
        if item and item[0].get(field) not in (None, ""):
            upstream[source] = str(item[0][field])
            revision = None if indexed_provenance else source_revision(source)
            provenance[source] = {"repository_revision": revision, "revision_verified": revision is not None,
                                  "file": item[1], "table": SPECS[kind]["source_table"]}
    target_record = target_locale_record(conn, kind, entity, locale)
    target_val = target_record.get(field) if target_record else None
    details: dict[str, object] = {"upstream": upstream, "provenance": provenance, "target": target_val}
    if len(set(upstream.values())) > 1:
        return "CONFLICT", details
    if not upstream:
        return ("MISSING" if not target_val else "TARGET_IDENTICAL"), details
    value = next(iter(upstream.values()))
    if target_val not in (None, ""):
        return ("TARGET_IDENTICAL" if str(target_val) == value else "CONFLICT"), details
    if len(upstream) == 2:
        return "MATCH", details
    return "SOURCE_ONLY", details


def values_for_kind(conn: sqlite3.Connection, kind: str, entity: str, locales: list[str] | None = None) -> list[tuple[str, str, str, dict]]:
    result = []
    locs = locales or list(LOCALES)
    for locale in locs:
        for field in SPECS[kind]["text_fields"]:
            status, detail = compare_value(conn, kind, entity, locale, field)
            result.append((locale, field, status, detail))
    return result


def command_inspect(args: argparse.Namespace) -> int:
    kind = args.entity_type
    key = entity_key(kind, args.entity_id)
    locales = [args.locale] if args.locale else list(LOCALES)
    with open_index() as conn:
        print(f"{kind} {args.entity_id}")
        for source in ("skyfire", "alexkulya", "loap"):
            base = base_entity(conn, source, kind, key)
            print(f"  {source} base: {json.dumps(base, ensure_ascii=False) if base else 'нет'}")
        for locale in locales:
            if locale not in LOCALES:
                print(f"  {locale}: UNSUPPORTED (неизвестная локаль)")
                continue
            for source in ("skyfire", "alexkulya", "loap"):
                rec = get_record(conn, source, kind, key, locale)
                if rec:
                    fields, file, table = rec
                    actual_table = (SPECS[kind]["target_table"] if source == "skyfire" else SPECS[kind]["source_table"])
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


def export_rows(conn: sqlite3.Connection, kind: str, entity: str, locales: list[str] | None = None, *, comparisons: dict | None = None,
                allow_single_identity: bool = False, allow_verified_aliases: bool = False) -> list[str]:
    ok, reason = identity_ok(conn, kind, entity)
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
        for field in SPECS[kind]["text_fields"]:
            status, details = comparisons[(locale, field)] if comparisons is not None else compare_value(
                conn, kind, entity, locale, field, identity_sources=("loap",) if alias else (proof["confirmed_upstream"],) if proof else ("alexkulya", "loap"))
            statuses.append(status)
            ups = details.get("upstream", {})
            if status in ("MATCH", "SOURCE_ONLY", "SAFE_SINGLE_IDENTITY", "VERIFIED_ALIAS") and ups:
                fields_out[field] = next(iter(ups.values()))
                for src, p in details.get("provenance", {}).items():
                    revision = p.get("repository_revision") or "revision-unverified"
                    provenance.append(f"{src}@{revision}:{p['file']}:{p['table']}")
        if not fields_out:
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
            columns = ["entry"]
            values = [str(int(numeric_id))]
            for field, value in fields_out.items():
                col = SPECS[kind]["wide_fields"][field].format(n=n)
                columns.append(col)
                values.append(sql_quote(value))
                assignments.append(f"`{col}`=IF(`{col}` IS NULL OR `{col}`='',{sql_quote(value)},`{col}`)")
            sql.append(f"-- {locale}; source: {comment}")
            sql.append(f"INSERT INTO `{table}` ({','.join('`' + c + '`' for c in columns)}) VALUES ({','.join(values)}) "
                       f"ON DUPLICATE KEY UPDATE {', '.join(assignments)};")
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
        manifest = {
            "target": "SkyFire 5.4.8",
            "entity_type": kind,
            "entity_id": json.loads(key),
            "identity_verified": identity,
            "identity_reason": reason,
            "locale_mapping": LOCALES,
            "results": results,
        }
        content = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            output = Path(args.output)
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
    bases = {}
    for source in ("alexkulya", "loap", "skyfire"):
        row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind='item' AND entity=?", (source, entity)).fetchone()
        if not row:
            return None
        bases[source] = {"fields": json.loads(row[0]), "file": row[1], "table": SPECS["item"]["target_entity"]}
    fields = {source: base["fields"] for source, base in bases.items()}
    if not all(isinstance(base.get("name"), str) and base["name"].strip() for base in fields.values()):
        return None
    confirmed = [source for source in ("alexkulya", "loap") if identities_match("item", fields[source], fields["skyfire"])]
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
    records = {source: get_record(conn, source, "item", entity, locale) for source in ("alexkulya", "loap")}
    if not all(records.values()):
        return None
    texts = {}
    for field in SPECS["item"]["text_fields"]:
        a, b = (records[source][0].get(field) for source in ("alexkulya", "loap"))
        a, b = (None if value in (None, "") else value for value in (a, b))
        if a != b or (a is not None and not isinstance(a, str)):
            return None
        if a is not None:
            texts[field] = a
    if not texts:
        return None
    rejected = next(source for source in ("alexkulya", "loap") if source != confirmed[0])
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
    bases = {}
    for source in ("alexkulya", "loap", "skyfire"):
        row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
        if not row:
            return None
        bases[source] = {"fields": json.loads(row[0]), "file": row[1], "table": SPECS[kind]["target_entity"]}
    fields = {source: base["fields"] for source, base in bases.items()}
    if any(base.get("_evidence_incomplete") for base in fields.values()):
        return None
    text_field = "name" if kind == "gameobject" else "optiontext"
    rule_name, old, target_text, expected = rule
    if fields["alexkulya"].get(text_field) != old or fields["skyfire"].get(text_field) != target_text:
        return None
    if fields["loap"].get(text_field) != (target_text if kind == "gameobject" else old):
        return None
    if kind == "gameobject":
        required = {"type", "displayid", "size"} | {f"data{n}" for n in range(32)}
        if any(base.get("type") != expected for base in fields.values()):
            return None
        structural = sorted(set().union(*(base.keys() for base in fields.values())) - {"name", "castbarcaption"})
    else:
        required = {"optiontype", "optionicon", "optionnpcflag", "actionmenuid", "actionpoiid", "boxcoded", "boxmoney"}
        structural = sorted(required | {"optionbroadcasttextid", "boxbroadcasttextid"})
        if fields["loap"].get("optionbroadcasttextid") != expected or fields["skyfire"].get("optionbroadcasttextid") != expected:
            return None
    evidence = {}
    for field in structural:
        if field.startswith("_"):
            continue
        present = {source: base[field] for source, base in fields.items() if field in base}
        if field in required and (len(present) != 3 or any(value is None for value in present.values())):
            return None
        if field in required:
            types = (int, float) if field == "size" else (int,)
            if any(not isinstance(value, types) or isinstance(value, bool) for value in present.values()):
                return None
        if len(present) > 1 and not all(value == next(iter(present.values())) for value in present.values()):
            return None
        evidence[field] = present
    records = {source: get_record(conn, source, kind, entity, locale) for source in ("alexkulya", "loap", "skyfire")}
    texts = {source: {field: None if not row or row[0].get(field) in (None, "") else row[0][field] for field in SPECS[kind]["text_fields"]}
             for source, row in records.items()}
    if any(value is not None for value in texts["skyfire"].values()):
        return None
    if not isinstance(texts["alexkulya"][text_field], str) or not texts["alexkulya"][text_field]:
        return None
    if any(value is not None and not isinstance(value, str) for source in texts for value in texts[source].values()):
        return None
    if kind == "gameobject":
        if not records["loap"] or texts["alexkulya"] != texts["loap"]:
            return None
    elif records["loap"]:
        if any(texts["alexkulya"][field] != texts["loap"][field] for field in SPECS[kind]["text_fields"]):
            return None
    return {"rule_name": rule_name, "reason": "Фиксированный key и точные English aliases подтверждены; доступная структура не противоречит; ruRU candidate согласован; target locale пустой",
            "source_target_text": {source: base[text_field] for source, base in fields.items()},
            "structural_evidence": evidence, "base_entities": bases, "localization_text": texts,
            "broadcast_evidence": evidence.get("optionbroadcasttextid") if kind == "gossip_menu_option" else None,
            "provenance": {source: {"file": row[1], "table": SPECS[kind]["source_table"]} for source, row in records.items() if row}}


def bulk_decision(conn: sqlite3.Connection, kind: str, entity: str, locale: str, *, allow_single_identity: bool = False,
                  allow_verified_aliases: bool = False) -> tuple[dict, list[str]]:
    key = json.loads(entity)
    key_parts = key if kind == "gossip_menu_option" and isinstance(key, list) else [key]
    valid_key = (len(key_parts) == (2 if kind == "gossip_menu_option" else 1)
                 and all(isinstance(part, int) and not isinstance(part, bool) and part >= 0 for part in key_parts))
    records = {source: get_record(conn, source, kind, entity, locale) for source in ("alexkulya", "loap", "skyfire")}
    values = {source: {field: record[0].get(field) if record else None for field in SPECS[kind]["text_fields"]}
              for source, record in records.items()}
    provenance = {source: {"file": record[1], "table": SPECS[kind]["target_table"] if source == "skyfire" else SPECS[kind]["source_table"]}
                  for source, record in records.items() if record}
    candidates = [source for source in ("alexkulya", "loap") if any(value not in (None, "") for value in values[source].values())]
    identity, identity_reason = identity_ok(conn, kind, entity) if candidates else (False, "no candidates")
    proof = single_item_identity(conn, entity, locale) if kind == "item" and candidates and not identity and valid_key else None
    alias = verified_alias(conn, kind, entity, locale) if kind in ("gameobject", "gossip_menu_option") and valid_key and candidates else None
    # A translation donor must have its own verified identity; another upstream's
    # matching base row cannot establish identity for a SOURCE_ONLY donor.
    if identity:
        for source in candidates:
            if base_entity(conn, source, kind, entity) is None:
                identity, identity_reason = False, f"{source} no upstream base identity"
                break
    comparisons = {}
    for field in SPECS[kind]["text_fields"]:
        if candidates and not identity and not proof and not alias:
            status, detail = "UNSUPPORTED", {"reason": identity_reason}
        elif not candidates:
            status, detail = ("TARGET_IDENTICAL" if values["skyfire"][field] not in (None, "") else "MISSING"), {}
        else:
            # The index does not store upstream revisions. Do not let live Git
            # HEAD alter output from an otherwise unchanged index.
            status, detail = compare_value(conn, kind, entity, locale, field, indexed_provenance=True,
                                          identity_sources=("loap",) if alias else (proof["confirmed_upstream"],) if proof else ("alexkulya", "loap"))
            if alias and status in ("MATCH", "SOURCE_ONLY"):
                status = "VERIFIED_ALIAS"
            if proof and status == "MATCH":
                status = "SAFE_SINGLE_IDENTITY"
        if not valid_key:
            status, detail = "UNSUPPORTED", {"reason": "Неподдерживаемый entity key"}
        if any(value not in (None, "") and not isinstance(value, str) for value in (values[source][field] for source in values)):
            status, detail = "UNSUPPORTED", {"reason": "non-text localization value"}
        comparisons[field] = {"status": status, **detail}
    statuses = {value["status"] for value in comparisons.values()}
    sql = []
    if "UNSUPPORTED" in statuses:
        status = "UNSUPPORTED"
        reason = "Identity не подтверждена: " + identity_reason if candidates and not identity else "Неподдерживаемые localization data"
    elif "CONFLICT" in statuses:
        status, reason = "CONFLICT", "Переводы upstream расходятся или отличаются от непустого SkyFire translation"
    elif "VERIFIED_ALIAS" in statuses:
        status = "VERIFIED_ALIAS"
        reason = alias["reason"] + ("; экспорт разрешён --allow-verified-aliases" if allow_verified_aliases else "; экспорт требует --allow-verified-aliases")
        if allow_verified_aliases:
            prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
            sql = export_rows(conn, kind, entity, [locale], comparisons=prepared, allow_verified_aliases=True)
    elif "SAFE_SINGLE_IDENTITY" in statuses:
        status = "SAFE_SINGLE_IDENTITY"
        reason = proof["reason"] + ("; экспорт разрешён --allow-single-identity" if allow_single_identity else "; экспорт требует --allow-single-identity")
        if allow_single_identity:
            prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
            sql = export_rows(conn, kind, entity, [locale], comparisons=prepared, allow_single_identity=True)
    elif statuses & {"MATCH", "SOURCE_ONLY"}:
        status = "SOURCE_ONLY" if "SOURCE_ONLY" in statuses else "MATCH"
        prepared = {(locale, field): (detail["status"], {k: v for k, v in detail.items() if k != "status"}) for field, detail in comparisons.items()}
        sql = export_rows(conn, kind, entity, [locale], comparisons=prepared)
        reason = "Безопасный перевод"
    elif "TARGET_IDENTICAL" in statuses:
        status, reason = "TARGET_IDENTICAL", "SkyFire уже содержит совпадающий перевод; SQL не требуется"
    else:
        status, reason = "MISSING", "Нет upstream translation для выбранной locale"
    # Keep human-facing report reasons in Russian; raw identity details remain
    # inspectable through the existing single-entity commands.
    reason = reason.replace("target entity missing", "target entity отсутствует").replace("identity mismatch", "identity не совпадает").replace("no upstream base identity", "нет upstream base identity")
    for detail in comparisons.values():
        if "reason" in detail:
            detail["reason"] = reason
    entry = {"entity_type": kind, "entity_key": key, "locale": locale,
             "status": status, "reason": reason, "candidates_found": bool(candidates),
             "exported": bool(sql), "identity_failed": bool(candidates and not identity and not proof and not alias),
             "values": values, "provenance": provenance, "fields": comparisons}
    if proof:
        entry["single_identity"] = proof
    if alias:
        entry["verified_alias"] = alias
    if not sql or proof or alias:
        entry["base_entities"] = {}
        for source in ("alexkulya", "loap", "skyfire"):
            row = conn.execute("SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?", (source, kind, entity)).fetchone()
            if row:
                entry["base_entities"][source] = {"fields": json.loads(row[0]), "file": row[1], "table": SPECS[kind]["target_entity"]}
    return entry, sql


def bulk_export(conn: sqlite3.Connection, kinds: list[str], locale: str, directory: Path, *, allow_single_identity: bool = False,
                allow_verified_aliases: bool = False) -> dict:
    if locale not in LOCALES or locale == "enUS":
        raise ValueError("export-all поддерживает locale translations; enUS хранится в base entity tables")
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
                      "counter_units": "entity/locale; статусы взаимоисключающие; identity_failed входит в unsupported; skipped = total_target_entities - exported",
                      "sql_files": {kind: f"{kind}-{locale}.sql" for kind in kinds}}
            report.write(json.dumps(header, ensure_ascii=False, sort_keys=True, indent=2)[:-2] + ',\n  "entries": [\n')
            first_entry = True
            for kind in kinds:
                counts = {name: 0 for name in ("total_target_entities", "candidates_found", "exported", "MATCH", "SOURCE_ONLY", "SAFE_SINGLE_IDENTITY", "VERIFIED_ALIAS", "TARGET_IDENTICAL", "CONFLICT", "MISSING", "UNSUPPORTED", "identity_failed", "unsupported", "skipped")}
                summary[kind] = counts
                order = "json_extract(entity,'$[0]'),json_extract(entity,'$[1]'),entity" if kind == "gossip_menu_option" else "json_extract(entity,'$'),entity"
                rows = conn.execute("SELECT entity FROM entities WHERE source='skyfire' AND kind=? ORDER BY " + order, (kind,))
                with (directory / f"{kind}-{locale}.sql").open("w", encoding="utf-8", newline="\n") as sql_file:
                    sql_file.write(f"-- SkyFire 5.4.8; {kind}; {locale}; review SQL, не применён автоматически.\n")
                    for (entity,) in rows:
                        entry, statements = bulk_decision(conn, kind, entity, locale, allow_single_identity=allow_single_identity,
                                                          allow_verified_aliases=allow_verified_aliases)
                        counts["total_target_entities"] += 1
                        counts["candidates_found"] += int(entry["candidates_found"])
                        counts[entry["status"]] += 1
                        counts["identity_failed"] += int(entry["identity_failed"])
                        counts["unsupported"] += int(entry["status"] == "UNSUPPORTED")
                        if statements:
                            counts["exported"] += 1
                            sql_file.write("\n".join(statements) + "\n")
                        else:
                            counts["skipped"] += 1
                        if not statements or entry["status"] in ("SAFE_SINGLE_IDENTITY", "VERIFIED_ALIAS"):
                            if not first_entry:
                                report.write(",\n")
                            first_entry = False
                            report.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=2))
                print(f"{kind}: target {counts['total_target_entities']}, candidates {counts['candidates_found']}, exported {counts['exported']}, conflicts {counts['CONFLICT']}, skipped {counts['skipped']}", flush=True)
            totals = {key: sum(counts[key] for counts in summary.values()) for key in next(iter(summary.values()), {})}
            report.write('\n  ],\n  "summary": ' + json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
            report.write(',\n  "totals": ' + json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2) + "\n}\n")
    return summary


def command_export_all(args: argparse.Namespace) -> int:
    directory = PORTING / "review"
    with closing(open_index()) as conn:
        bulk_export(conn, [args.entity_type] if args.entity_type else list(SPECS), args.locale, directory,
                    allow_single_identity=args.allow_single_identity, allow_verified_aliases=args.allow_verified_aliases)
    print(f"SQL и report сохранены для review: {directory}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("index", help="построить локальный потоковый SQLite-индекс")
    q = sub.add_parser("export-all", help="экспортировать безопасные переводы target entities и общий report")
    q.add_argument("entity_type", nargs="?", choices=tuple(SPECS))
    q.add_argument("--locale", required=True, choices=tuple(code for code in LOCALES if code != "enUS"))
    q.add_argument("--allow-single-identity", action="store_true", help="разрешить item SAFE_SINGLE_IDENTITY после проверки одинаковых текстов и структуры")
    q.add_argument("--allow-verified-aliases", action="store_true", help="разрешить только фиксированные gameobject/gossip aliases с полным evidence")
    for cmd in ("inspect", "compare", "export"):
        q = sub.add_parser(cmd)
        q.add_argument("entity_type", choices=tuple(SPECS))
        q.add_argument("entity_id", help="ID; для gossip_menu_option: MenuID,OptionID")
        if cmd != "export":
            q.add_argument("--locale", choices=tuple(LOCALES))
        else:
            q.add_argument("--locale", action="append", choices=tuple(LOCALES))
            q.add_argument("--output", help="путь для review SQL; по умолчанию stdout")
    q = sub.add_parser("export-manifest", help="создать provenance manifest для review")
    q.add_argument("entity_type", choices=tuple(SPECS))
    q.add_argument("entity_id", help="ID; для gossip_menu_option: MenuID,OptionID")
    q.add_argument("--locale", action="append", choices=tuple(LOCALES))
    q.add_argument("--output", help="путь JSON; по умолчанию stdout")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "index":
            return build_index(args)
        if args.command == "export-all":
            return command_export_all(args)
        if args.command == "inspect":
            return command_inspect(args)
        if args.command == "compare":
            return command_compare(args)
        if args.command == "export-manifest":
            return command_manifest(args)
        return command_export(args)
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

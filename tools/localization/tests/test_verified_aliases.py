from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize

JOIN = "UPDATE gossip_menu_option gmo LEFT JOIN gossip_menu_option_action gmoa ON gmo.MenuID=gmoa.MenuId AND gmo.OptionID=gmoa.OptionIndex LEFT JOIN gossip_menu_option_box gmob ON gmo.MenuId=gmob.MenuId AND gmo.OptionID=gmob.OptionIndex SET gmo.ActionMenuID=COALESCE(gmoa.ActionMenuId,0),gmo.BoxText=gmob.BoxText;"


class VerifiedAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = localize.db_connect(self.root / "index.sqlite")
        self.fixtures = json.loads((Path(__file__).parent / "fixtures/verified-aliases.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def fixture(self, kind, key):
        self.conn.execute("DELETE FROM entities")
        self.conn.execute("DELETE FROM records")
        self.conn.execute("DELETE FROM gossip_aux")
        self.conn.execute("DELETE FROM gossip_boxes")
        fixture = self.fixtures[kind][json.dumps(key)]
        for source, base in fixture["bases"].items():
            localize.persist_entity(self.conn, source, kind, base["row"], base["file"], 20)
        if kind == "gossip_menu_option":
            if key == [126, 0]:
                # world_548_20240722.sql:568354, legacy action row (126,0,125,0).
                tokens = localize.Tokens(StringIO("INSERT INTO gossip_menu_option_action(MenuId,OptionIndex,ActionMenuId,ActionPoiId) VALUES(126,0,125,0);"))
                tokens.get()
                localize.parse_insert(tokens,"loap","action-base.sql",{},self.conn,20,"entities",{json.dumps(key)})
            tokens = localize.Tokens(StringIO(JOIN))
            tokens.get()
            localize.parse_update(tokens, "loap", "migration.sql", self.conn, "entities")
        for source, values in fixture["translations"].items():
            localize.persist_locale(self.conn, source, kind, json.dumps(key), "ruRU", values, source + "-locale.sql", 20)

    def run_export(self, kind, allow, name="review"):
        self.conn.commit()
        path = self.root / name
        with redirect_stdout(StringIO()):
            summary = localize.bulk_export(self.conn, [kind], "ruRU", path, allow_verified_aliases=allow)
        report = json.loads((path / "report-ruRU.json").read_text(encoding="utf-8"))
        return summary[kind], report, path

    def mutate(self, source, kind, key, **changes):
        fields = localize.base_entity(self.conn, source, kind, json.dumps(key))
        fields.update(changes)
        self.conn.execute("UPDATE entities SET fields=? WHERE source=? AND kind=? AND entity=?", (json.dumps(fields), source, kind, json.dumps(key)))

    def test_seven_positive_regressions_require_opt_in_and_keep_proof(self):
        cases = [("gameobject", 57708), ("gameobject", 170524)] + [("gossip_menu_option", key) for key in ([0,1],[0,3],[0,9],[125,0],[126,0])]
        for kind, key in cases:
            with self.subTest(kind=kind, key=key):
                self.fixture(kind, key)
                counts, report, _ = self.run_export(kind, False)
                self.assertEqual(counts["VERIFIED_ALIAS"], 1)
                self.assertEqual(counts["exported"], 0)
                counts, report, path = self.run_export(kind, True)
                self.assertEqual(counts["exported"], 1)
                self.assertEqual(counts["MATCH"], 0)
                entry = report["entries"][0]
                self.assertTrue(entry["exported"])
                proof = entry["verified_alias"]
                self.assertIn("rule_name", proof)
                self.assertEqual(set(proof["base_entities"]), {"alexkulya", "loap", "skyfire"})
                self.assertTrue(proof["structural_evidence"])
                if kind == "gossip_menu_option":
                    self.assertEqual(proof["broadcast_evidence"]["loap"], proof["broadcast_evidence"]["skyfire"])
                self.assertIn("VERIFIED_ALIAS", (path / f"{kind}-ruRU.sql").read_text(encoding="utf-8"))

    def test_3642_and_0_12_never_approved(self):
        for kind, key in (("gameobject",3642),("gossip_menu_option",[0,12])):
            with self.subTest(key=key):
                self.fixture(kind,key)
                counts, report, _ = self.run_export(kind,True)
                self.assertEqual(counts["exported"],0)
                self.assertEqual(counts["VERIFIED_ALIAS"],0)

    def test_structural_conflict_missing_fields_and_incomplete_evidence(self):
        for changes in ({"data1":999},{"type":3},{"size":2},{"_evidence_incomplete":1},{"displayid":None}):
            with self.subTest(changes=changes):
                self.fixture("gameobject",57708)
                self.mutate("alexkulya","gameobject",57708,**changes)
                self.assertEqual(self.run_export("gameobject",True)[0]["exported"],0)

    def test_broadcast_and_gossip_action_mismatch(self):
        for changes in ({"optionbroadcasttextid":999},{"actionmenuid":123},{"boxmoney":1},{"optionicon":7}):
            with self.subTest(changes=changes):
                self.fixture("gossip_menu_option",[0,1])
                self.mutate("loap","gossip_menu_option",[0,1],**changes)
                self.assertEqual(self.run_export("gossip_menu_option",True)[0]["exported"],0)

    def test_matching_but_unsupported_structural_values(self):
        self.fixture("gameobject",57708)
        for source in ("alexkulya","loap","skyfire"):
            self.mutate(source,"gameobject",57708,data1="0")
        self.assertEqual(self.run_export("gameobject",True)[0]["exported"],0)

    def test_exact_pattern_no_whitespace_normalization(self):
        self.fixture("gameobject",57708)
        self.mutate("alexkulya","gameobject",57708,name="Lamp  Post")
        self.assertEqual(self.run_export("gameobject",True)[0]["exported"],0)

    def test_translation_conflict_and_nonempty_target(self):
        for source,value in (("loap","Другой перевод"),("skyfire","Фонарный столб"),("skyfire","Иное")):
            with self.subTest(source=source,value=value):
                self.fixture("gameobject",57708)
                localize.persist_locale(self.conn,source,"gameobject","57708","ruRU",{"name":value},"test.sql",30)
                self.assertEqual(self.run_export("gameobject",True)[0]["exported"],0)

    def test_missing_target_and_deterministic_outputs(self):
        self.fixture("gameobject",57708)
        _, _, first = self.run_export("gameobject",True,"first")
        _, _, second = self.run_export("gameobject",True,"second")
        for name in ("gameobject-ruRU.sql","report-ruRU.json"):
            self.assertEqual((first/name).read_bytes(),(second/name).read_bytes())
        self.conn.execute("DELETE FROM entities WHERE source='skyfire'")
        self.assertEqual(self.run_export("gameobject",True)[0]["total_target_entities"],0)

    def test_global_gossip_candidates_index_base_without_locale(self):
        sql = {
            "alexkulya": "INSERT INTO gossip_menu_option_locale(MenuID,OptionID,Locale,OptionText) VALUES(0,1,'ruRU','Товары');\nINSERT INTO gossip_menu_option(menu_id,id,option_text,option_id,npc_option_npcflag) VALUES(0,1,'Talk',3,128);\n",
            "loap": "INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag,OptionBroadcastTextID) VALUES(0,1,'Talk',3,1,128,3370);\n",
            "skyfire": "INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType) VALUES(0,1,'Talk',3);\n",
        }
        for source, contents in sql.items():
            path=self.root/f".porting/sources/{source}/db/world.sql"
            path.parent.mkdir(parents=True)
            path.write_text(contents,encoding="utf-8")
        index=self.root/"bootstrap.sqlite"
        with patch.object(localize,"ROOT",self.root), patch.object(localize,"PORTING",self.root/".porting/localization"), patch.object(localize,"INDEX",index), redirect_stdout(StringIO()):
            self.assertEqual(localize.build_index(None),0)
        conn=localize.db_connect(index)
        try:
            base=localize.base_entity(conn,"loap","gossip_menu_option",json.dumps([0,1]))
            self.assertEqual(base["optiontype"],3)
            self.assertEqual(base["optionbroadcasttextid"],3370)
            self.assertIsNone(localize.get_record(conn,"loap","gossip_menu_option",json.dumps([0,1]),"ruRU"))
        finally:
            conn.close()

    def test_structural_updates_tuple_predicate_and_failed_expression(self):
        self.fixture("gossip_menu_option",[0,1])
        sql="UPDATE gossip_menu_option SET OptionType=5 WHERE OptionType<>5 AND (MenuID,OptionID) IN ((0,1),(0,3));"
        tokens=localize.Tokens(StringIO(sql)); tokens.get()
        localize.parse_update(tokens,"loap","update.sql",self.conn,"entities")
        self.assertEqual(localize.base_entity(self.conn,"loap","gossip_menu_option",json.dumps([0,1]))["optiontype"],5)
        self.fixture("gameobject",57708)
        sql="UPDATE gameobject_template SET data1=data1+1 WHERE entry=57708;"
        tokens=localize.Tokens(StringIO(sql)); tokens.get()
        localize.parse_update(tokens,"alexkulya","update.sql",self.conn,"entities")
        self.assertIsNone(localize.verified_alias(self.conn,"gameobject","57708","ruRU"))


if __name__ == "__main__":
    unittest.main()

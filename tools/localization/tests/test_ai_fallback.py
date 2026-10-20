"""AI fallback is separate, hash-bound, conservative and fully offline."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l
import ai_fallback as ai
import ai_tokens


class AIFallbackTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.c = l.db_connect(self.root/'index.sqlite3'); self.addCleanup(self.c.close)
        for source, role in (('source-a', 'primary'), ('source-b', 'primary'), ('custom-reference-42', 'supplemental')):
            l.evidence_roles.register(self.c, source, role)
        self.base('creature', {'entry': 1, 'name': 'Guard', 'subname': 'Town Watch', 'type': 7, 'unit_class': 1, 'family': 0, 'rank': 0})
        self.base('gameobject', {'entry': 2, 'name': 'Chest', 'type': 3, 'displayid': 10})
        self.base('quest', {'id': 3, 'title': 'Welcome', 'objectives': 'Meet the guard.', 'details': 'Hello, $N.', 'minlevel': 1, 'method': 2, 'type': 0, 'zoneorsort': 1})
        self.base('npc_text', {'id': 4, 'text0_0': 'Hello, $n.', 'text0_1': 'Welcome, $n.', 'prob0': 1, 'lang0': 0})
        self.base('creature_text', {'entry': 1, 'groupid': 0, 'id': 0, 'text': 'Stop, $N!', 'type': 12, 'language': 0, 'probability': 100, 'emote': 0, 'duration': 0, 'sound': 0})
        self.directory = self.root/'ai'/'ruRU'

    def base(self, kind, row, source='target'):
        l.persist_entity(self.c, source, kind, row, 'target.sql', 20)

    def export(self, entity=None):
        return ai.export_requests(l, self.c, self.directory, 'ruRU', entity)

    def request(self, kind='creature', field='name'):
        return next(r for r in ai.jsonl(self.directory/'requests.jsonl') if r['entity']==kind and r['field']==field)

    def stage(self, requests=None, value='Страж', replace=True):
        requests = requests or [self.request()]
        rows = [{k:r[k] for k in ('entity','key','field','english_hash')} | {'translation': value} for r in requests]
        path = self.root/'responses.jsonl'
        path.write_text(''.join(ai.encoded(r)+'\n' for r in rows), encoding='utf8')
        ai.import_results(l, self.directory, 'ruRU', path, 'synthetic-generator/run-1', replace)
        return path

    def validate(self):
        return ai.validate_results(l, self.c, self.directory, 'ruRU')

    def test_export_all_supported_entities_and_authoritative_english(self):
        self.export(); rows=list(ai.jsonl(self.directory/'requests.jsonl'))
        self.assertEqual({r['entity'] for r in rows}, set(ai.KINDS))
        self.assertEqual(self.request()['english'], 'Guard')
        for r in rows:
            self.assertEqual(set(r), {'entity','key','field','english','context','token_contract','english_hash'})
            self.assertEqual(r['english_hash'], ai.digest(r['english']))
            self.assertEqual(r['context']['donor_field_status'], 'MISSING')
        self.assertNotIn('objective:1', {r['field'] for r in rows})
        self.assertEqual(rows, sorted(rows, key=ai.order))

    def test_safe_donor_and_existing_target_excluded(self):
        self.base('creature', {'entry':1,'name':'Guard','type':7,'unit_class':1,'family':0,'rank':0}, 'source-a')
        l.persist_locale(self.c,'source-a','creature','1','ruRU',{'name':'Донор'},'locale.sql',20)
        l.persist_locale(self.c,'target','gameobject','2','ruRU',{'name':'Сохранить'},'locale.sql',20)
        self.export(); rows=list(ai.jsonl(self.directory/'requests.jsonl'))
        self.assertFalse(any(r['entity']=='creature' and r['field']=='name' for r in rows))
        self.assertFalse(any(r['entity']=='gameobject' and r['field']=='name' for r in rows))

    def test_conflict_never_becomes_ai_request(self):
        for source, text in (('source-a','Страж'),('source-b','Охранник')):
            self.base('creature',{'entry':1,'name':'Guard','subname':'Town Watch','type':7,'unit_class':1,'family':0,'rank':0},source)
            l.persist_locale(self.c,source,'creature','1','ruRU',{'name':text},'locale.sql',20)
        self.export();self.assertFalse(any(r['entity']=='creature' for r in ai.jsonl(self.directory/'requests.jsonl')))

    def test_unsupported_not_bypassed(self):
        l.persist_locale(self.c,'source-a','creature','1','ruRU',{'name':'Страж'},'locale.sql',20)
        self.export(); self.assertFalse(any(r['entity']=='creature' for r in ai.jsonl(self.directory/'requests.jsonl')))

    def test_import_validation_and_custom_sql_all_entities(self):
        self.export()
        values = {('creature','name'):'Страж',('gameobject','name'):'Сундук',('quest','details'):'Привет, $N.',
                  ('npc_text','text0_0'):'Привет, $n.',('creature_text','text'):'Стой, $N!'}
        rows=[]
        for (kind,field),value in values.items():
            req=self.request(kind,field);rows.append({k:req[k] for k in ('entity','key','field','english_hash')}|{'translation':value})
        path=self.root/'responses.jsonl';ai.write_rows(path,rows)
        ai.import_results(l,self.directory,'ruRU',path,'synthetic/run')
        report=self.validate();self.assertEqual(report['summary']['valid'],5)
        ai.custom_sql(l,self.directory,'ruRU',report)
        for kind in ai.KINDS:
            sql=(self.directory/'custom'/f'{kind}.sql').read_text(encoding='utf8')
            self.assertIn('IF(',sql);self.assertIn('BINARY b.',sql);self.assertIn('ON DUPLICATE KEY UPDATE',sql)
        manifest=ai.read_json(self.directory/'custom/manifest.json')
        self.assertEqual(manifest['layer'],'ai_custom');self.assertFalse(manifest['approved'])
        self.assertEqual(len(manifest['entries']),5)
        for row in manifest['entries']:
            self.assertEqual(row['provenance']['origin'],'external_ai')
            self.assertEqual(row['provenance']['external_provenance'],'synthetic/run')
            self.assertEqual(len(row['english_hash']),64)

    def test_stale_english_and_stale_context(self):
        self.export();self.stage()
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.name','New name') WHERE source='target' AND kind='creature'")
        self.assertEqual(self.validate()['results'][0]['reason'],'STALE_ENGLISH')
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.name','Guard','$.rank',1) WHERE source='target' AND kind='creature'")
        self.assertEqual(self.validate()['results'][0]['reason'],'STALE_TARGET_CONTEXT')

    def test_new_donor_priority_and_new_target_protection_on_validate(self):
        self.export();self.stage()
        self.base('creature',{'entry':1,'name':'Guard','type':7,'unit_class':1,'rank':0,'family':0},'source-a')
        l.persist_locale(self.c,'source-a','creature','1','ruRU',{'name':'Донор'},'locale.sql',20)
        self.assertEqual(self.validate()['results'][0]['reason'],'DONOR_SOURCE_ONLY')
        l.persist_locale(self.c,'target','creature','1','ruRU',{'name':'Существующий'},'target.sql',20)
        self.assertEqual(self.validate()['results'][0]['reason'],'TARGET_NONEMPTY')

    def test_missing_target_and_forged_key(self):
        self.export();self.stage()
        self.c.execute("DELETE FROM entities WHERE source='target' AND kind='creature'")
        self.assertEqual(self.validate()['results'][0]['reason'],'TARGET_MISSING')

    def test_unknown_request_rejected(self):
        self.export(); req=dict(self.request());req['key']=2
        self.base('creature',{'entry':2,'name':'Guard','type':7,'unit_class':1,'rank':0,'family':0})
        self.stage([req]);self.assertEqual(self.validate()['results'][0]['reason'],'REQUEST_NOT_EXPORTED')

    def test_blank_english_fallback_and_mojibake_rejected(self):
        self.export()
        for text,reason in [('  ','EMPTY_TRANSLATION'),('Guard','CONFIRMED_ENGLISH_FALLBACK'),('ÐŸÐ»Ð¾Ñ‚Ð¾ÑÐ´','SUSPECTED_MOJIBAKE'),('Страж\x00','INVALID_ENCODING_OR_CONTROL')]:
            with self.subTest(reason=reason):
                self.stage(value=text);self.assertEqual(self.validate()['results'][0]['reason'],reason)

    def test_semantic_creature_text_validator_and_npc_variants(self):
        self.export()
        self.stage([self.request('creature_text','text')],value='Стой!')
        result=self.validate()['results'][0];self.assertEqual(result['reason'],'TOKEN_CONTRACT_FAILED')
        self.assertEqual(result['token_validation']['status'],'BLOCK')
        self.stage([self.request('npc_text','text0_1')],value='Добро пожаловать, $N.')
        self.assertEqual(self.validate()['results'][0]['reason'],'TOKEN_CONTRACT_FAILED')
        self.stage([self.request('quest','details')],value='Привет, $n.')
        self.assertEqual(self.validate()['results'][0]['reason'],'TOKEN_CONTRACT_FAILED')

    def test_unknown_contract_not_exported(self):
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.text','Unknown $z') WHERE source='target' AND kind='creature_text'")
        self.export();self.assertFalse(any(r['entity']=='creature_text' for r in ai.jsonl(self.directory/'requests.jsonl')))

    def test_invalid_utf8_duplicate_keys_and_surrogates_import_atomic(self):
        self.export();path=self.stage();before=(self.directory/'translations.jsonl').read_bytes()
        for data in (b'\xff\n',b'{"entity":"creature","entity":"quest"}\n',b'{"translation":"\\ud800"}\n'):
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaises(ValueError):ai.import_results(l,self.directory,'ruRU',path,'test',True)
                self.assertEqual(before,(self.directory/'translations.jsonl').read_bytes())

    def test_conflicting_import_does_not_overwrite(self):
        self.export();self.stage();before=(self.directory/'translations.jsonl').read_bytes()
        with self.assertRaisesRegex(ValueError,'Conflicting AI'):self.stage(value='Охранник',replace=False)
        self.assertEqual(before,(self.directory/'translations.jsonl').read_bytes())

    def test_deterministic_export_import_validation_and_sql(self):
        self.export();first=(self.directory/'requests.jsonl').read_bytes();self.export();self.assertEqual(first,(self.directory/'requests.jsonl').read_bytes())
        self.stage();report=self.validate();ai.custom_sql(l,self.directory,'ruRU',report)
        files={f.name:f.read_bytes() for f in (self.directory/'custom').iterdir()}
        self.stage();self.assertEqual(report,self.validate());ai.custom_sql(l,self.directory,'ruRU',self.validate())
        self.assertEqual(files,{f.name:f.read_bytes() for f in (self.directory/'custom').iterdir()})

    def test_ai_never_changes_donor_index_or_decisions(self):
        self.c.commit();before=(self.root/'index.sqlite3').read_bytes();decision=l.bulk_decision(self.c,'creature','1','ruRU')
        self.export();self.stage();self.validate()
        self.assertEqual(before,(self.root/'index.sqlite3').read_bytes())
        self.assertEqual(decision,l.bulk_decision(self.c,'creature','1','ruRU'))
        self.assertEqual(self.c.execute('SELECT count(*) FROM records').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM source_evidence').fetchone()[0],3)

    def test_sql_escaping_and_newline_normalization(self):
        self.export();self.stage(value="Страж 'Север'\\test\r\n")
        report=self.validate();self.assertEqual(report['results'][0]['translation'],"Страж 'Север'\\test\n")
        self.assertEqual(report['results'][0]['reason'],'TOKEN_CONTRACT_FAILED')
        self.stage(value="Страж 'Север'\\test")
        report=self.validate();sql=ai.sql_statement(l,report['results'][0],'ruRU')
        self.assertIn(l.sql_quote("Страж 'Север'\\test"),sql)

    def test_artifact_tampering_detected(self):
        self.export();self.stage();path=self.directory/'requests.jsonl';path.write_text('',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'requests changed'):self.validate()

    def test_cli_and_coverage(self):
        self.c.commit()
        with patch.object(l,'INDEX',self.root/'index.sqlite3'),patch.object(l,'WORKSPACE',self.root/'workspace'):
            for command in ('ai-export','ai-coverage'):
                argv=['localize.py',command,'--locale','ruRU']+(['--json'] if command=='ai-coverage' else [])
                with patch.object(sys,'argv',argv),contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(l.main(),0)
                self.assertEqual(json.loads(stdout.getvalue())['locale'] if command=='ai-coverage' else json.loads(stdout.getvalue())['requests'], 'ruRU' if command=='ai-coverage' else 9)

    def test_missing_artifact_friendly_error(self):
        with self.assertRaisesRegex(ValueError,'ai-export'):self.validate()

    def test_quest_and_npc_field_level_conflicts_do_not_fill_conflicting_field(self):
        for kind, key, row, field in (
            ('quest', '3', {'id':3,'title':'Welcome','objectives':'Meet the guard.','details':'Hello, $N.','minlevel':1,'method':2,'type':0,'zoneorsort':1}, 'title'),
            ('npc_text', '4', {'id':4,'text0_0':'Hello, $n.','text0_1':'Welcome, $n.','prob0':1,'lang0':0}, 'text0_0')):
            for source,text in (('source-a','Первый'),('source-b','Второй')):
                self.base(kind,row,source)
                l.persist_locale(self.c,source,kind,key,'ruRU',{field:text},'locale.sql',20)
        self.export(); rows=list(ai.jsonl(self.directory/'requests.jsonl'))
        self.assertFalse(any(r['entity']=='quest' and r['field']=='title' for r in rows))
        self.assertTrue(any(r['entity']=='quest' and r['field']=='details' for r in rows))
        self.assertFalse(any(r['entity']=='npc_text' and r['field']=='text0_0' for r in rows))
        self.assertTrue(any(r['entity']=='npc_text' and r['field']=='text0_1' for r in rows))

    def test_conflict_appearing_after_export_blocks_imported_translation(self):
        self.export();self.stage()
        for source,text in (('source-a','Первый'),('source-b','Второй')):
            self.base('creature',{'entry':1,'name':'Guard','type':7,'unit_class':1,'rank':0,'family':0},source)
            l.persist_locale(self.c,source,'creature','1','ruRU',{'name':text},'locale.sql',20)
        self.assertEqual(self.validate()['results'][0]['reason'],'DONOR_CONFLICT')

    def test_missing_target_english_and_structural_proof_not_requested(self):
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.name','') WHERE source='target' AND kind='creature'")
        self.c.execute("UPDATE entities SET fields=json_remove(fields,'$.prob0') WHERE source='target' AND kind='npc_text'")
        self.export();rows=list(ai.jsonl(self.directory/'requests.jsonl'))
        self.assertFalse(any(r['entity'] in ('npc_text','creature') for r in rows))

    def test_removed_english_is_stale(self):
        self.export();self.stage()
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.name','') WHERE source='target' AND kind='creature'")
        self.assertEqual(self.validate()['results'][0]['reason'],'STALE_ENGLISH')

    def test_revalidation_clears_old_custom_sql_when_target_protected(self):
        self.export();self.stage();ai.custom_sql(l,self.directory,'ruRU',self.validate())
        l.persist_locale(self.c,'target','creature','1','ruRU',{'name':'Существующий'},'target.sql',20)
        report=self.validate();ai.custom_sql(l,self.directory,'ruRU',report)
        self.assertNotIn('INSERT INTO',(self.directory/'custom/creature.sql').read_text(encoding='utf8'))
        manifest=ai.read_json(self.directory/'custom/manifest.json')
        self.assertEqual(manifest['entries'],[]);self.assertEqual(len(manifest['rejected']),1)

    def test_duplicate_identical_results_are_one_field(self):
        self.export();path=self.stage();text=path.read_text(encoding='utf8');path.write_text(text+text,encoding='utf8')
        ai.import_results(l,self.directory,'ruRU',path,'synthetic/run',True)
        self.assertEqual(self.validate()['summary']['submitted'],1)

    def test_bad_keys_fields_and_hashes_are_rejected(self):
        self.export();req=self.request()
        for change in ({'key':True},{'key':'1'},{'field':[]},{'field':'objective:1'},{'english_hash':'no'},{'entity':'item'}):
            with self.subTest(change=change):
                row={k:req[k] for k in ('entity','key','field','english_hash')}|{'translation':'Страж'}|change
                with self.assertRaises(ValueError):ai.check_row(l,row,True)

    def test_exact_npc_quest_token_forms_and_escaping(self):
        for kind in ('npc_text','quest'):
            with self.subTest(kind=kind):
                self.assertFalse(ai_tokens.validate(l,kind,'Hello %s','Привет %100s')['valid'])
                self.assertFalse(ai_tokens.validate(l,kind,'Hello \\$n','Привет $n')['valid'])
                self.assertTrue(ai_tokens.validate(l,kind,'Hello \\$n','Привет \\$n')['valid'])
                self.assertTrue(ai_tokens.validate(l,kind,'Hello $gfriend:friend;','Привет $gдруг:подруга;')['valid'])
                self.assertFalse(ai_tokens.validate(l,kind,'Hello $gfriend:friend;','Привет $gдруг')['valid'])

    def test_cli_import_validate_sql_and_human_coverage(self):
        self.c.commit()
        with patch.object(l,'INDEX',self.root/'index.sqlite3'),patch.object(l,'WORKSPACE',self.root/'workspace'):
            def cli(*args):
                with patch.object(sys,'argv',['localize.py',*args]),contextlib.redirect_stdout(io.StringIO()) as out:
                    code=l.main()
                return code,out.getvalue()
            self.assertEqual(cli('ai-export','--locale','ruRU')[0],0)
            directory=l.WORKSPACE/'ai/ruRU'
            req=next(r for r in ai.jsonl(directory/'requests.jsonl') if r['entity']=='creature' and r['field']=='name')
            path=self.root/'external.jsonl';ai.write_rows(path,[{k:req[k] for k in ('entity','key','field','english_hash')}|{'translation':'Страж'}])
            self.assertEqual(cli('ai-import','--locale','ruRU','--input',str(path),'--provenance','synthetic/run')[0],0)
            code,out=cli('ai-validate','--locale','ruRU','--write-sql');self.assertEqual(code,0);self.assertEqual(json.loads(out)['summary']['valid'],1)
            before={f.relative_to(directory).as_posix():f.read_bytes() for f in directory.rglob('*') if f.is_file()}
            code,out=cli('ai-coverage','--locale','ruRU');self.assertEqual(code,0);self.assertIn('Eligible fields',out)
            self.assertEqual(before,{f.relative_to(directory).as_posix():f.read_bytes() for f in directory.rglob('*') if f.is_file()})

    def test_validate_before_import_and_atomic_write_failure(self):
        self.export()
        with self.assertRaisesRegex(ValueError,'ai-import'):self.validate()
        path=self.root/'atomic.txt';path.write_text('original',encoding='utf8')
        with patch.object(ai.os,'replace',side_effect=OSError('synthetic interrupted write')):
            with self.assertRaises(OSError):ai.atomic(path,'new')
        self.assertEqual(path.read_text(encoding='utf8'),'original')

    def test_runtime_printf_contract_reused(self):
        for kind in ('npc_text','quest','skyfire_string','db_script_string'):
            with self.subTest(kind=kind):
                self.assertTrue(ai_tokens.validate(l,kind,'Hello %s, $n! 100%%','Привет %s, $n! 100%%')['valid'])
                self.assertFalse(ai_tokens.validate(l,kind,'Hello %s','Привет %d')['valid'])
                self.assertFalse(ai_tokens.validate(l,kind,'Hello $n','Привет $N')['valid'])

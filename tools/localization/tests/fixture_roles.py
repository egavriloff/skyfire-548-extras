"""Explicit PRIMARY setup for legacy synthetic policy fixtures only."""
import localize
import evidence_roles


def fixture_connect(path):
    conn = localize.db_connect(path)
    digest = evidence_roles.fingerprint({'evidence_role': 'primary'})
    for table in ('sources', 'entities', 'records', 'files'):
        conn.executescript(f"""
        CREATE TEMP TRIGGER fixture_{table}_primary AFTER INSERT ON {table}
        WHEN NEW.source <> 'target'
        BEGIN
          INSERT INTO sources SELECT NEW.source,'reference',NULL WHERE NOT EXISTS (SELECT 1 FROM sources WHERE source=NEW.source);
          INSERT OR IGNORE INTO source_evidence VALUES(NEW.source,'primary','{digest}');
        END;
        """)
    conn.executescript("""
      CREATE TEMP TRIGGER fixture_source_rename AFTER UPDATE OF source ON sources
      BEGIN UPDATE source_evidence SET source=NEW.source WHERE source=OLD.source; END;
    """)
    return conn

"""Pruebas offline del bootstrap RDS AWS: sin conectarse a ningún servicio."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"infrastructure/aws/scripts/03-bootstrap-rds.py"


def load():
    spec=importlib.util.spec_from_file_location("cinegraph_e4_rds_bootstrap",SCRIPT)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BootstrapRdsContractTests(unittest.TestCase):
    def test_movie_source_md5_and_count(self):
        module=load()
        movies=module.load_movies()
        self.assertEqual(len(movies),87585)
        self.assertEqual(len({m[0] for m in movies}),87585)
        self.assertEqual(module.MOVIES_MD5,"0df90835c19151f9d819d0822e190797")

    def test_all_controlled_sql_migrations(self):
        module=load()
        self.assertEqual(len(module.SCHEMA_FILES),5)
        for path in module.SCHEMA_FILES:
            stmts=module.sql_statements(path)
            self.assertGreater(len(stmts),0)
            self.assertNotIn("BEGIN",stmts)
            self.assertNotIn("COMMIT",stmts)

    def test_no_local_bootstrap_or_leakage(self):
        txt=SCRIPT.read_text("utf-8")
        self.assertIn('sslmode="verify-full"',txt)
        self.assertIn('SET TRANSACTION READ ONLY',txt)
        self.assertIn('CONFIRM_RDS_IMPORT',txt)
        self.assertIn('autocommit=True',txt)
        self.assertNotIn('print(password)',txt)
        self.assertNotIn('SecretString)',txt)
        self.assertNotIn('DATABASE_URL=',txt)
        self.assertNotIn('TEST_USERS',txt)
        self.assertNotIn('baseline-v0',txt)


if __name__=="__main__":
    unittest.main()

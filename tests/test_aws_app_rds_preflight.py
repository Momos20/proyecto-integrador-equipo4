"""Contrato de seguridad del preflight de credenciales AWS CineGraph."""
from pathlib import Path
import ast
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"infrastructure/aws/scripts/04-app-rds-preflight.py"


class AppRdsPreflightTests(unittest.TestCase):
    def test_source_parses_and_read_only(self):
        text=SCRIPT.read_text(encoding="utf-8")
        ast.parse(text)
        self.assertIn('SET TRANSACTION READ ONLY',text)
        self.assertIn('sslmode="verify-full"',text)
        self.assertIn('DescribeSecret',text)
        self.assertIn('cinegraph-e4-app-db',text)
        self.assertIn('cinegraph-e4-demo-users',text)
        self.assertNotIn('create_secret(',text)
        self.assertNotIn('UPDATE app_users',text)
        self.assertNotIn('CREATE ROLE',text)
        self.assertNotIn('print(password)',text)

if __name__=="__main__":
    unittest.main()

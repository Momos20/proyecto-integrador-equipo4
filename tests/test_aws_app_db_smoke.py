"""Contrato estático del test seguro de la app RDS desde contenedor Docker."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"infrastructure/aws/scripts/06-app-db-smoke.py"


class AwsDbSmokeContractTests(unittest.TestCase):
    def test_syntax_and_guardrails(self):
        contents=FILE.read_text(encoding="utf-8")
        ast.parse(contents)
        required=(
            "APP_SECRET_ID = \"cinegraph-e4-app-db\"",
            "sslmode=\"verify-full\"",
            "SET TRANSACTION READ ONLY",
            "APP_DATABASE_ROLE_OK",
            "APP_CATALOG_OK: 87585",
            "APP_DEMO_ACCOUNTS_OK: 3",
            "APP_PERMISSIONS_OK",
            "APP_DB_SMOKE_SUCCESS",
            "APP_DB_SMOKE_FAILED",
        )
        for statement in required:
            self.assertIn(statement, contents)
        for forbidden in ("print(secret)", "print(password)", "SecretString)", "master_credentials",
                          "CREATE ROLE", "INSERT INTO", "UPDATE public."):
            self.assertNotIn(forbidden, contents)


if __name__ == "__main__":
    unittest.main()

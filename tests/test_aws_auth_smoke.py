"""Prueba estática de la verificación de autenticación AWS sin exponer credenciales."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infrastructure/aws/scripts/09-auth-smoke.py"


class AwsAuthSmokeContractTests(unittest.TestCase):
    def test_flask_auth_smoke_safe(self):
        data = SCRIPT.read_text("utf-8")
        ast.parse(data)
        for expected in (
            "cinegraph-e4-app-db", "cinegraph-e4-demo-users",
            'BASE_URL = "https://cinegraph.local"',
            'PGSSLMODE="verify-full"', 'SECRET_KEY=session_key',
            "/api/auth/login", "/api/auth/logout",
            "/api/watchlist", "/api/interactions?limit=2",
            "AUTH_TEST_UNAUTHENTICATED_401_OK", "AUTH_TEST_LOGIN_OK",
            "AUTH_TEST_LOGOUT_OK", "CINEGRAPH_AUTH_SMOKE_SUCCESS",
        ):
            self.assertIn(expected, data)
        for forbidden in ("print(demo_password)", "print(db_password)",
                          "print(session_key)", "print(exc)", "INSERT INTO",
                          "UPDATE app_users", "create_secret(",
                          "DELETE FROM"):
            self.assertNotIn(forbidden, data)


if __name__ == "__main__":
    unittest.main()

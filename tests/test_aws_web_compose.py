"""AWS Compose: unicamente web interna y carga segura de credenciales en runtime."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure/aws/compose.web.yaml"
START = ROOT / "infrastructure/aws/scripts/07-start-web.py"


class AwsWebComposeTests(unittest.TestCase):
    def test_compose_is_aws_only_and_loopback(self):
        txt = COMPOSE.read_text("utf-8")
        for required in (
            "127.0.0.1:8000:8000",
            "image: cinegraph-e4-app:main",
            "CINEGRAPH_ENV: production",
            'CINEGRAPH_COOKIE_SECURE: "1"',
            "APP_DB_SECRET_ID: cinegraph-e4-app-db",
            "/opt/cinegraph/runtime/session_key",
            "clickstream.log",
            "read_only: true",
            "no-new-privileges:true",
            "cap_drop:",
        ):
            self.assertIn(required, txt)
        for forbidden in ("postgres:16", "floci:", "DB_PASSWORD:", "SECRET_KEY:",
                          "0.0.0.0:8000:8000", "ports:\n      - \"8000:8000\""):
            self.assertNotIn(forbidden, txt)

    def test_startup_fetches_secrets_and_requires_tls(self):
        txt = START.read_text("utf-8")
        ast.parse(txt)
        for expected in (
            "get_secret_value(", "cinegraph-e4-app-db", 'PGSSLMODE="verify-full"',
            "PGSSLROOTCERT=str(CA_FILE)", "SECRET_KEY=session_key", "os.execvp(",
            "CINEGRAPH_WEB_RUNTIME_READY", "CINEGRAPH_WEB_START_FAILED",
        ):
            self.assertIn(expected, txt)
        for forbidden in (
            "print(password)", "print(credentials)", "print(session_key)",
            "print(exc)", "DATABASE_URL=", "create_secret(",
        ):
            self.assertNotIn(forbidden, txt)


    def test_ssm_launch_script_keeps_local_only(self):
        path = ROOT / "infrastructure/aws/scripts/08-launch-web.sh"
        script = path.read_text("utf-8")
        for required in (
            "SESSION_KEY_PRESENT", "docker compose", "--no-build",
            "--wait-timeout 120", "http://127.0.0.1:8000",
            "HTTP_MOVIELENS_CATALOG_OK: 2", "CINEGRAPH_WEB_LOCAL_READY",
        ):
            self.assertIn(required, script)
        for forbidden in ("docker compose -f docker-compose.yml", "SECRET_KEY=", "DB_PASSWORD="):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()

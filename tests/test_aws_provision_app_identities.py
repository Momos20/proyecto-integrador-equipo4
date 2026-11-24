"""Contrato: el provisioning AWS no imprime contraseñas ni cambia el bootstrap local."""
from pathlib import Path
import ast
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"infrastructure/aws/scripts/05-provision-app-identities.py"

class AwsIdentitiesContractTests(unittest.TestCase):
    def test_strict_confirm_and_tls(self):
        s=SCRIPT.read_text("utf-8")
        ast.parse(s)
        for required in (
            "CONFIRM_APP_CREDENTIALS", 'sslmode="verify-full"',
            "get_secret_value", "create_secret(", "cinegraph-e4-app-db",
            "cinegraph-e4-demo-users", "cinegraph_app",
            "CREATE ROLE", "GRANT SELECT ON TABLE", "GRANT INSERT ON TABLE",
            "user_interactions_interaction_id_seq", "generate_password_hash",
            "check_password_hash", "with conn.transaction()",
        ):
            self.assertIn(required,s)

    def test_credentials_never_echoed(self):
        s=SCRIPT.read_text("utf-8")
        for forbidden in (
            "print(app[", "print(demos[", "print(master_pwd)",
            "print(db_password)", "print(plain)", "print(exc)",
            "traceback.print_exc", "update_secret(",
        ):
            self.assertNotIn(forbidden,s)

    def test_three_demo_accounts_map(self):
        s=SCRIPT.read_text("utf-8")
        self.assertIn('"cine414": 414',s)
        self.assertIn('"cine123": 123',s)
        self.assertIn('"cine456": 456',s)

if __name__=="__main__":
    unittest.main()

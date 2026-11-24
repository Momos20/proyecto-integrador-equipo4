"""Guardas minimas del proxy HTTPS para AWS Academy."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure/aws/compose.https.yaml"
CADDYFILE = ROOT / "infrastructure/aws/Caddyfile"


class AwsHttpsProxyTests(unittest.TestCase):
    def test_caddyfile_uses_domain_and_loopback_backend(self):
        text = CADDYFILE.read_text(encoding="utf-8")
        self.assertIn("{$CINEGRAPH_HOST}", text)
        self.assertIn("reverse_proxy 127.0.0.1:8000", text)
        self.assertIn("admin off", text)
        self.assertNotIn("tls internal", text)
        self.assertNotIn("auto_https off", text)

    def test_compose_is_separate_and_persists_certificates(self):
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("network_mode: host", text)
        self.assertIn("CINEGRAPH_HOST:", text)
        self.assertIn("caddy_data:/data", text)
        self.assertIn("caddy_config:/config", text)
        self.assertIn("Caddyfile:/etc/caddy/Caddyfile:ro", text)
        self.assertIn("read_only: true", text)
        self.assertIn("no-new-privileges:true", text)
        self.assertNotIn("ports:", text)
        self.assertNotIn("5432:5432", text)
        self.assertNotIn("8000:8000", text)
        self.assertNotIn("image: postgres", text)


if __name__ == "__main__":
    unittest.main()

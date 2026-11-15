"""Pruebas seguras (sin AWS, Docker ni PyTorch) de la barrera Floci local."""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parents[1]
MODULE = HERE / "scripts" / "ml" / "run_a9_floci.py"
spec = importlib.util.spec_from_file_location("run_a9_floci", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestLocalOnly(unittest.TestCase):
    def test_local_endpoints(self):
        for endpoint in ("http://127.0.0.1:4566", "http://localhost:4566", "http://floci:4566"):
            self.assertEqual(mod.validate_endpoint(endpoint), endpoint)

    def test_reject_remote_and_https(self):
        for endpoint in (
            "https://s3.amazonaws.com", "http://10.1.2.3:4566", "http://example.com:4566",
            "https://localhost:4566", "http://localhost:4567", "http://localhost:4566/other",
            "http://name:secret@localhost:4566", "http://localhost:4566?x=1",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                mod.validate_endpoint(endpoint)

    def test_parser(self):
        args = mod.parse_args(["--ratings-local", "x.parquet", "--solo-subir"])
        self.assertTrue(args.solo_subir)
        self.assertEqual(args.endpoint_url, mod.LOCAL_ENDPOINT)

    def test_parser_bad_date(self):
        with self.assertRaises(SystemExit):
            mod.parse_args(["--ratings-local", "x.parquet", "--fecha", "2023-02-30"])

    def test_manifest_preserves_miguel_sha(self):
        self.assertEqual(mod.MODEL_SHA256, "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358")


if __name__ == "__main__":
    unittest.main()
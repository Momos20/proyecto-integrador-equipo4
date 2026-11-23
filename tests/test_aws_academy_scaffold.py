"""Comprobaciones offline de la fase 0/1 AWS Academy; no usan credenciales."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / "infrastructure" / "aws"


class CloudFoundationTests(unittest.TestCase):
    def test_template_limits_resources_to_bucket_and_security_groups(self):
        tpl = (AWS / "cloudformation/01-foundation.yaml").read_text(encoding="utf-8")
        assert tpl.count("Type: AWS::S3::Bucket") == 1
        assert tpl.count("Type: AWS::EC2::SecurityGroup") == 2
        assert "AWS::RDS::DBInstance" not in tpl
        assert "AWS::EC2::Instance" not in tpl
        assert "DeletionPolicy: Retain" in tpl
        assert "BlockPublicAcls: true" in tpl
        assert "RestrictPublicBuckets: true" in tpl
        assert "SSEAlgorithm: AES256" in tpl
        assert "SourceSecurityGroupId: !Ref AppSecurityGroup" in tpl
        assert "CidrIp: !Ref AllowedClientCidr" in tpl
        assert "0.0.0.0/0" not in tpl.split("Resources:")[1]

    def test_preflight_never_creates_resources(self):
        script = (AWS / "scripts/00-preflight.sh").read_text(encoding="utf-8")
        for forbidden in ("cloudformation deploy", "run-instances", "create-bucket", "create-db-instance"):
            self.assertNotIn(forbidden, script)
        self.assertIn("sts get-caller-identity", script)
        self.assertIn("cloudformation validate-template", script)

    def test_deploy_requires_explicit_approval_and_private_cidr(self):
        script = (AWS / "scripts/01-foundation.sh").read_text(encoding="utf-8")
        self.assertIn("CONFIRM_LAB_DEPLOY", script)
        self.assertIn("--plan", script)
        self.assertIn("--apply", script)
        self.assertIn("'0.0.0.0/0'", script)
        self.assertIn("--no-fail-on-empty-changeset", script)
        self.assertNotIn("--capabilities CAPABILITY_IAM", script)


if __name__ == "__main__":
    unittest.main()
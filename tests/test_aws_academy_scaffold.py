"""Verifica que AWS es independiente del local y prepara HTTPS compartido sin abrir credenciales."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / "infrastructure/aws"


class CloudFoundationTests(unittest.TestCase):
    def test_foundation_is_only_s3_and_two_security_groups(self):
        tpl = (AWS / "cloudformation/01-foundation.yaml").read_text("utf-8")
        assert tpl.count("Type: AWS::S3::Bucket") == 1
        assert tpl.count("Type: AWS::EC2::SecurityGroup\n") == 2
        assert "Type: AWS::EC2::SecurityGroupIngress" in tpl
        assert "AWS::RDS::DBInstance" not in tpl
        assert "AWS::EC2::Instance" not in tpl
        assert "DeletionPolicy: Retain" in tpl
        assert "BlockPublicAcls: true" in tpl
        assert "RestrictPublicBuckets: true" in tpl
        assert "SSEAlgorithm: AES256" in tpl
        assert "SourceSecurityGroupId: !Ref AppSecurityGroup" in tpl

    def test_no_public_inbound_port_without_explicit_cloudfront_mode(self):
        tpl = (AWS / "cloudformation/01-foundation.yaml").read_text("utf-8")
        assert "Default: None" in tpl
        assert "AllowedValues: [None, RestrictedIP, CloudFront]" in tpl
        assert "SourcePrefixListId: !Ref CloudFrontPrefixListId" in tpl
        assert "Condition: UseCloudFront" in tpl
        assert "Condition: UseRestrictedIP" in tpl
        assert "0.0.0.0/0" not in tpl.split("Resources:")[1]

    def test_preflight_and_sharing_check_are_read_only(self):
        for name in ("00-preflight.sh", "00-check-sharing.sh"):
            s = (AWS / "scripts" / name).read_text("utf-8")
            for unsafe in ("cloudformation deploy", "run-instances", "create-db-instance", "create-distribution"):
                assert unsafe not in s
        sharing = (AWS / "scripts/00-check-sharing.sh").read_text("utf-8")
        assert "cloudfront list-distributions" in sharing
        assert "com.amazonaws.global.cloudfront.origin-facing" in sharing

    def test_foundation_create_requires_separate_apply_and_confirmation(self):
        s = (AWS / "scripts/01-foundation.sh").read_text("utf-8")
        assert "CONFIRM_LAB_DEPLOY" in s
        assert "--plan" in s
        assert "--apply" in s
        assert "CloudFront" in s
        assert "0.0.0.0/0" in s or "RestrictedIP" in s
        assert "--no-fail-on-empty-changeset" in s
        assert "PROFILE=\"\${AWS_PROFILE:-}\"" not in s  # no literal templates left
        assert 'PROFILE="${AWS_PROFILE:-}"' in s

    def test_local_stack_unmodified_by_aws_setup(self):
        assert (ROOT / "docker-compose.yml").is_file()
        assert (ROOT / "docker-compose.floci.yml").is_file()


if __name__ == "__main__":
    unittest.main()

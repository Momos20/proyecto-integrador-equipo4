"""Contrato actual de infraestructura CineGraph en AWS Academy."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
AWS=ROOT/"infrastructure/aws"

class AwsFoundationTests(unittest.TestCase):
    def test_foundation_has_private_bucket_and_two_named_groups(self):
        src=(AWS/"cloudformation/01-foundation.yaml").read_text("utf-8")
        for item in ("BucketName: !Sub 'cinegraph-e4-datalake-${AWS::AccountId}-${AWS::Region}'",
                     "GroupName: cinegraph-e4-app-sg", "GroupName: cinegraph-e4-rds-sg",
                     "DeletionPolicy: Retain", "BlockPublicAcls: true",
                     "RestrictPublicBuckets: true", "SSEAlgorithm: AES256",
                     "SourceSecurityGroupId: !Ref AppSecurityGroup"):
            self.assertIn(item,src)
        self.assertEqual(src.count("Type: AWS::S3::Bucket"),1)
        self.assertEqual(src.count("Type: AWS::EC2::SecurityGroup\n"),2)
        self.assertNotIn("0.0.0.0/0",src.split("Resources:")[1])
        for forbidden in ("AWS::EC2::Instance","AWS::RDS::DBInstance"):
            self.assertNotIn(forbidden,src)

    def test_documentation_has_cli_and_history(self):
        s=(AWS/"README.md").read_text("utf-8")
        for word in ("ACCOUNT_ID", "AWS_REGION", "VPC_ID", "Bitácora",
                     "cloudformation validate-template","cloudformation deploy",
                     "cloudformation describe-stacks","CREATE_COMPLETE","02-db-network.sh --plan"):
            self.assertIn(word,s)

    def test_archived_scripts_not_present(self):
        for f in ("00-retire-legacy-foundation.sh", "00-preflight.sh",
                  "00-check-sharing.sh", "00-check-ec2-rds.sh","01-foundation.sh"):
            self.assertFalse((AWS/"scripts"/f).exists(),f)

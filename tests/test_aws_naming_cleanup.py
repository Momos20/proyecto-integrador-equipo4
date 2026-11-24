"""Naming contract and safe retirement checks (no actual AWS calls)."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
AWS=ROOT/"infrastructure/aws"

class AwsNamingTests(unittest.TestCase):
    def test_bucket_and_groups_have_explicit_professional_names(self):
        s=(AWS/"cloudformation/01-foundation.yaml").read_text("utf-8")
        self.assertIn("BucketName: !Sub 'cinegraph-e4-dev-datalake-${AWS::AccountId}-${AWS::Region}'",s)
        self.assertIn("GroupName: cinegraph-e4-dev-app-sg",s)
        self.assertIn("GroupName: cinegraph-e4-dev-rds-sg",s)
        self.assertIn("DeletionPolicy: Retain",s)
        self.assertIn("Default: None",s)
    def test_stack_names_consistent(self):
        s=(AWS/"scripts/01-foundation.sh").read_text("utf-8")
        db=(AWS/"scripts/02-db-network.sh").read_text("utf-8")
        self.assertIn("STACK_NAME:-cinegraph-e4-dev-foundation",s)
        self.assertIn("FOUNDATION_STACK_NAME:-cinegraph-e4-dev-foundation",db)
        self.assertIn("DB_NETWORK_STACK_NAME:-cinegraph-e4-dev-db-network",db)
    def test_old_stack_cleanup_is_bounded(self):
        s=(AWS/"scripts/00-retire-legacy-foundation.sh").read_text("utf-8")
        for part in ('MODE="${1:---inspect}"',"EXPECTED_ACCOUNT_ID",
                     "cinegraph-lab-foundation-datalakebucket-lrnkpdjo5xiv",
                     "sg-00d7ff2cb71f16854","sg-004792f0dba4268be",
                     "CONFIRM_DELETE_LEGACY_CINEGRAPH",
                     "list-object-versions","describe-network-interfaces",
                     "cloudformation wait stack-delete-complete","s3api delete-bucket"):
            self.assertIn(part,s)
        for unsafe in ("s3 rb --force","s3 rm --recursive","delete-objects","down -v"):
            self.assertNotIn(unsafe,s)

if __name__=="__main__":
    unittest.main()

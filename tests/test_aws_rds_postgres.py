"""Infraestructura PostgreSQL RDS: propiedades estáticas seguras."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
AWS=ROOT/"infrastructure/aws"


class RdsPostgresTests(unittest.TestCase):
    def test_postgres_is_private_named_and_managed(self):
        s=(AWS/"cloudformation/03-rds-postgres.yaml").read_text("utf-8")
        for required in (
            "DBInstanceIdentifier: cinegraph-e4-postgres",
            "EngineVersion: '16.15'", "DBInstanceClass: db.t3.micro",
            "ManageMasterUserPassword: true", "PubliclyAccessible: false",
            "StorageEncrypted: true", "StorageType: gp3",
            "AllocatedStorage: '20'", "MultiAZ: false",
            "DeletionPolicy: Snapshot", "BackupRetentionPeriod: 0",
            "DBSubnetGroupName: !Ref DatabaseSubnetGroupName",
            "- !Ref DatabaseSecurityGroupId",
        ):
            self.assertIn(required,s)
        self.assertNotIn("\n      MasterUserPassword:",s)
        self.assertNotIn("0.0.0.0/0",s)
        self.assertNotIn("AWS::EC2::Instance",s)

    def test_reproducible_commands_documented(self):
        s=(AWS/"README.md").read_text("utf-8")
        self.assertIn("cloudformation/03-rds-postgres.yaml",s)
        self.assertIn("DatabaseSecurityGroupId=$DB_SG",s)
        self.assertIn("ManageMasterUserPassword",s)


if __name__=="__main__":
    unittest.main()

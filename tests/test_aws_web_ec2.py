"""Contrato EC2 web AWS Academy: sin exponer Flask ni SSH al crear la instancia."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
AWS=ROOT/"infrastructure/aws"

class WebEc2Tests(unittest.TestCase):
    def test_ec2_bootstrap_without_public_inbound_or_secrets(self):
        s=(AWS/"cloudformation/04-web-ec2.yaml").read_text("utf-8")
        for expected in (
            "Type: AWS::EC2::Instance",
            "Value: cinegraph-e4-web",
            "IamInstanceProfile: !Ref InstanceProfileName",
            "AssociatePublicIpAddress: true",
            "GroupSet:",
            "- !Ref AppSecurityGroupId",
            "HttpTokens: required",
            "Encrypted: true",
            "VolumeType: gp3",
            "VolumeSize: 24",
            "dnf install -y docker",
        ):
            self.assertIn(expected,s)
        for forbidden in ("AWS::EC2::SecurityGroupIngress", "SecurityGroupIngress:",
                          "0.0.0.0/0", "MasterUserPassword:", "DB_PASSWORD=",
                          "SECRET_KEY=", "KeyName:", "UserData: password"):
            self.assertNotIn(forbidden,s)

    def test_docs_have_iam_and_ssm_preflight(self):
        s=(AWS/"README.md").read_text("utf-8")
        for expected in ("list-attached-role-policies", "describe-instance-information",
                         "describe-images", "cloudformation/04-web-ec2.yaml",
                         "AmazonSSMManagedInstanceCore", "crea solo",
                         "docker-compose.yml"):
            self.assertIn(expected,s)

if __name__=="__main__":
    unittest.main()

"""HTTPS ingress: solo reglas web 80/443, nunca exponer DB, SSH o Flask."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/"infrastructure/aws/cloudformation/05-web-https-ingress.yaml"

class AwsHttpsIngressTests(unittest.TestCase):
    def test_ingress_limited_to_http_and_https(self):
        content=TEMPLATE.read_text("utf-8")
        self.assertEqual(content.count("Type: AWS::EC2::SecurityGroupIngress"), 2)
        self.assertEqual(content.count("CidrIp: 0.0.0.0/0"), 2)
        for expected in ("FromPort: 80", "ToPort: 80", "FromPort: 443", "ToPort: 443", "GroupId: !Ref AppSecurityGroupId"):
            self.assertIn(expected,content)
        for forbidden in ("FromPort: 22\n", "FromPort: 5432\n", "FromPort: 8000\n",
                          "Type: AWS::EC2::SecurityGroup\n",
                          "AWS::RDS::DBInstance","GroupId: !Ref DatabaseSecurityGroupId"):
            self.assertNotIn(forbidden,content)

if __name__=="__main__":
    unittest.main()

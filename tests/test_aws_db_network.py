"""No-network safety checks for Phase 2 AWS Academy database network."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / "infrastructure/aws"


class PrivateDatabaseNetworkTests(unittest.TestCase):
    def test_private_network_stack_creates_no_compute_or_internet_gateway(self):
        template = (AWS / "cloudformation/02-db-network.yaml").read_text("utf-8")
        self.assertEqual(template.count("Type: AWS::EC2::Subnet\n"), 2)
        self.assertEqual(template.count("Type: AWS::EC2::SubnetRouteTableAssociation"), 2)
        self.assertEqual(template.count("Type: AWS::EC2::RouteTable\n"), 1)
        self.assertEqual(template.count("Type: AWS::RDS::DBSubnetGroup"), 1)
        self.assertIn("DBSubnetGroupName: cinegraph-e4-rds-subnets", template)
        self.assertEqual(template.count("MapPublicIpOnLaunch: false"), 2)
        self.assertNotIn("AWS::EC2::Route\n", template)
        for forbidden in ("AWS::EC2::Instance", "AWS::RDS::DBInstance",
                          "AWS::EC2::NatGateway", "AWS::EC2::InternetGateway"):
            self.assertNotIn(forbidden, template)

    def test_script_requires_confirmed_foundation_and_explicit_apply(self):
        script = (AWS / "scripts/02-db-network.sh").read_text("utf-8")
        self.assertIn('FOUNDATION_STACK_NAME:-cinegraph-e4-foundation', script)
        self.assertIn("CREATE_COMPLETE|UPDATE_COMPLETE", script)
        self.assertIn("CONFIRM_LAB_DEPLOY", script)
        self.assertIn("cloudformation validate-template", script)
        self.assertIn("subnet_a.overlaps(subnet_b)", script)
        self.assertIn("candidate.overlaps(existing)", script)
        self.assertIn("AZ_A", script)
        self.assertIn("AZ_B", script)
        self.assertIn("--plan", script)
        self.assertIn("--apply", script)
        self.assertIn("No se modificara.", script.replace("no se modificara.", "No se modificara."))

    def test_script_is_independent_of_local_floci(self):
        script = (AWS / "scripts/02-db-network.sh").read_text("utf-8")
        self.assertNotIn("docker compose", script)
        self.assertNotIn("floci", script)
        self.assertNotIn("docker-compose.yml", script)


if __name__ == "__main__":
    unittest.main()

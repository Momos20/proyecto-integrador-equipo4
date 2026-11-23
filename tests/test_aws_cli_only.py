"""Verificación estática: planificación AWS Academy por comandos y sin acciones mutables."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class CliOnlyDeploymentTests(unittest.TestCase):
    def test_ec2_rds_preflight_is_read_only(self):
        path=ROOT/"infrastructure/aws/scripts/00-check-ec2-rds.sh"
        text=path.read_text(encoding="utf-8")
        for forbidden in ("cloudformation deploy", "cloudformation create-stack",
                          "ec2 run-instances", "ec2 create-subnet", "rds create-db-instance",
                          "ec2 authorize-security-group-ingress", "aws configure set"):
            self.assertNotIn(forbidden,text)
        for expected in ("describe-subnets", "describe-internet-gateways",
                         "describe-route-tables", "describe-instance-type-offerings",
                         "describe-orderable-db-instance-options"):
            self.assertIn(expected,text)

    def test_readme_preserves_local_and_steps(self):
        text=(ROOT/"infrastructure/aws/README.md").read_text(encoding="utf-8")
        self.assertIn("00-check-ec2-rds.sh",text)
        self.assertIn("EC2 público, RDS privado",text)
        self.assertIn("CloudShell",text)
        self.assertIn("HTTPS",text)
        self.assertIn("Docker + Floci local no se modifica",text)

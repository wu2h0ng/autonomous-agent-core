from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import BusinessAgentTemplate, DomainPack  # noqa: E402


class DomainPackContractsTest(unittest.TestCase):
    def test_domain_pack_construction(self) -> None:
        pack = DomainPack(
            pack_id="pack-1",
            name="Content Commerce",
            version="v1",
            domain="content_commerce",
            owner="domain_team",
            metric_contracts=("gmv",),
            business_agent_templates=("bat-1",),
            operation_contracts=("oc-1",),
            eval_pack_ids=("eval-1",),
            state="active",
        )
        self.assertEqual(pack.state, "active")
        self.assertEqual(pack.metric_contracts, ("gmv",))

    def test_business_agent_template_construction(self) -> None:
        template = BusinessAgentTemplate(
            template_id="bat-1",
            name="Analyst",
            domain="content_commerce",
            responsibilities=("monitor",),
            required_evidence=("evidence",),
            allowed_action_types=("propose",),
            default_approval_policy={"R4": "required"},
        )
        self.assertEqual(template.allowed_action_types, ("propose",))
        self.assertEqual(template.default_approval_policy, {"R4": "required"})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from src.tool_registry import get_tool_spec, validate_tool_access


class ToolRegistryTest(unittest.TestCase):
    def test_tool_registry_loads_policy(self) -> None:
        spec = get_tool_spec("portfolio_snapshot")

        self.assertEqual(spec.name, "portfolio_snapshot")
        self.assertEqual(spec.risk_level, "low")
        self.assertEqual(spec.data_type, "portfolio_snapshot")
        self.assertIn("Cash_Anchor", spec.allowed_frameworks)

    def test_tool_access_rejects_wrong_framework(self) -> None:
        with self.assertRaises(PermissionError):
            validate_tool_access(
                "portfolio_snapshot",
                framework_id="Growth_Engine",
                agent_role="worker",
            )

    def test_tool_access_rejects_wrong_agent_role(self) -> None:
        with self.assertRaises(PermissionError):
            validate_tool_access(
                "accept_patch_proposal",
                framework_id="Cash_Anchor",
                agent_role="worker",
            )


if __name__ == "__main__":
    unittest.main()

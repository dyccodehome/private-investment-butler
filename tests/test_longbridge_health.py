from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.longbridge_health import format_longbridge_health, run_longbridge_health


class LongbridgeHealthTest(unittest.TestCase):
    def test_health_passes_with_cli_log_network_and_read_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "logs"
            completed = SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")
            sock = Mock()
            with patch("src.longbridge_health.shutil.which", return_value="/usr/local/bin/longbridge"), patch(
                "src.longbridge_health.longbridge_log_path", return_value=log_path
            ), patch("src.longbridge_health.longbridge_env", return_value={"LONGBRIDGE_LOG_PATH": str(log_path)}), patch(
                "src.longbridge_health.socket.create_connection", return_value=sock
            ), patch(
                "src.longbridge_health.subprocess.run", return_value=completed
            ) as run:
                result = run_longbridge_health(timeout_seconds=3)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["longbridge", "positions", "--format", "json"])
        self.assertEqual(run.call_args_list[1].args[0], ["longbridge", "watchlist", "--format", "json"])
        sock.close.assert_called_once()
        text = format_longbridge_health(result)
        self.assertIn("长桥健康检查", text)
        self.assertIn("永久禁止交易写能力", text)

    def test_health_classifies_log_permission_and_network_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "readonly"
            log_path.write_text("not-a-dir", encoding="utf-8")
            with patch("src.longbridge_health.shutil.which", return_value="/usr/local/bin/longbridge"), patch(
                "src.longbridge_health.longbridge_log_path", return_value=log_path
            ), patch("src.longbridge_health.socket.create_connection", side_effect=OSError("nodename nor servname")):
                result = run_longbridge_health(timeout_seconds=3, run_cli=False)

        self.assertEqual(result["status"], "error")
        categories = {item["category"] for item in result["checks"]}
        self.assertIn("log_permission", categories)
        self.assertIn("network_or_dns", categories)
        self.assertTrue(any("日志目录不可写" in item for item in result["findings"]))
        self.assertTrue(any("OpenAPI" in item for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src import feishu_runtime
from src.knowledge_absorber import PatchProposal
from src.session_lock import pop_pending_action, release_processing, save_pending_action


class FeishuRuntimeTest(unittest.TestCase):
    def test_text_message_handles_command(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send:
            result = feishu_runtime.handle_feishu_text_message("cli", "/help", async_run=False)

        self.assertEqual(result, "command handled")
        self.assertTrue(send.called)
        self.assertIn("/contribute", send.call_args.args[1])

    def test_text_message_handles_command_after_bot_mention(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send:
            result = feishu_runtime.handle_feishu_text_message("cli", "@_user_1 /help", async_run=False)

        self.assertEqual(result, "command handled")
        self.assertTrue(send.called)
        self.assertIn("/contribute", send.call_args.args[1])

    def test_card_callback_handles_missing_pending_action(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send:
            result = feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "reject_constitution_patch", "state_id": "missing"}
            )

        self.assertEqual(result, "no pending action")
        send.assert_called_once()

    def test_card_callback_handles_reject_patch_action(self) -> None:
        save_pending_action(
            chat_id="cli",
            action_id="action-1",
            framework_id="Cash_Anchor",
            reason="PATCH-1",
        )
        with patch("src.feishu_runtime._submit_or_run") as submit:
            result = feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "reject_constitution_patch", "state_id": "action-1"}
            )

        self.assertEqual(result, "callback received")
        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[1], True)
        self.assertEqual(submit.call_args.args[2], "reject_constitution_patch")

    def test_card_callback_background_handles_reject_patch_action(self) -> None:
        save_pending_action(
            chat_id="cli",
            action_id="action-2",
            framework_id="Cash_Anchor",
            reason="PATCH-2",
        )
        with patch("src.feishu_runtime._handle_patch_callback") as callback:
            feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "reject_constitution_patch", "state_id": "action-2"},
                async_run=False,
            )

        callback.assert_called_once_with("reject_constitution_patch", "cli", "Cash_Anchor", "PATCH-2")

    def test_card_callback_background_handles_discuss_patch_action(self) -> None:
        save_pending_action(
            chat_id="cli",
            action_id="action-3",
            framework_id="Cash_Anchor",
            reason="PATCH-3",
        )
        with patch("src.feishu_runtime._handle_patch_callback") as callback:
            feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "discuss_constitution_patch", "state_id": "action-3"},
                async_run=False,
            )

        callback.assert_called_once_with("discuss_constitution_patch", "cli", "Cash_Anchor", "PATCH-3")

    def test_card_callback_accept_normalizes_old_sub_framework_pending_action(self) -> None:
        save_pending_action(
            chat_id="cli",
            action_id="action-legacy-sub",
            framework_id="Cash_Anchor/CN_Dividend_Income",
            reason="PATCH-LEGACY",
        )
        with patch("src.feishu_runtime.accept_patch_proposal", return_value=Path("/tmp/archive.json")) as accept, patch(
            "src.feishu_runtime.communication_gate.send"
        ):
            result = feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "accept_constitution_patch", "state_id": "action-legacy-sub"},
                async_run=False,
            )

        self.assertEqual(result, "callback received")
        accept.assert_called_once_with("Cash_Anchor", "PATCH-LEGACY")

    def test_card_callback_can_fallback_to_patch_payload_when_pending_is_missing(self) -> None:
        with patch("src.feishu_runtime.accept_patch_proposal", return_value=Path("/tmp/archive.json")) as accept, patch(
            "src.feishu_runtime.communication_gate.send"
        ):
            result = feishu_runtime.handle_feishu_card_callback(
                {
                    "chat_id": "cli",
                    "action": "accept_constitution_patch",
                    "state_id": "state-without-memory",
                    "framework_id": "Cash_Anchor/CN_Dividend_Income",
                    "patch_id": "PATCH-FALLBACK",
                },
                async_run=False,
            )

        self.assertEqual(result, "callback received")
        accept.assert_called_once_with("Cash_Anchor", "PATCH-FALLBACK")

    def test_card_callback_can_fallback_to_audit_payload_when_pending_is_missing(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send, patch(
            "src.feishu_runtime.save_user_action"
        ) as save_action:
            result = feishu_runtime.handle_feishu_card_callback(
                {
                    "chat_id": "cli",
                    "action": "force_execute",
                    "state_id": "audit-state-without-memory",
                    "framework_id": "Cash_Anchor",
                    "reason": "audit smoke reason",
                },
                async_run=False,
            )

        self.assertEqual(result, "callback received")
        self.assertIn("继续执行", send.call_args.args[1])
        save_action.assert_called_once()
        self.assertEqual(save_action.call_args.kwargs["framework_id"], "Cash_Anchor")
        self.assertEqual(save_action.call_args.kwargs["reason"], "audit smoke reason")

    def test_failed_patch_callback_restores_pending_action_for_retry(self) -> None:
        save_pending_action(
            chat_id="cli",
            action_id="action-retry",
            framework_id="Cash_Anchor/CN_Dividend_Income",
            reason="PATCH-RETRY",
        )
        with patch("src.feishu_runtime.accept_patch_proposal", side_effect=FileNotFoundError("missing")), patch(
            "src.feishu_runtime.communication_gate.send"
        ):
            result = feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "accept_constitution_patch", "state_id": "action-retry"},
                async_run=False,
            )

        pending = pop_pending_action("action-retry")
        self.assertEqual(result, "callback received")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.framework_id, "Cash_Anchor")

    def test_absorb_background_stores_base_framework_for_sub_framework_target(self) -> None:
        proposal = PatchProposal(
            patch_id="PATCH-6",
            framework_id="Cash_Anchor",
            target_id="Cash_Anchor/CN_Dividend_Income",
            target_file="sub_frameworks/CN_Dividend_Income.md",
            target_name="A 股红利子框架",
            status="proposed",
        )
        with patch("src.feishu_runtime.run_knowledge_absorption", return_value=proposal), patch(
            "src.feishu_runtime.save_pending_action"
        ) as save_pending, patch("src.feishu_runtime.communication_gate.send_card"):
            feishu_runtime._run_absorb_background(
                "cli",
                "Cash_Anchor/CN_Dividend_Income",
                "高股息必须检查分红覆盖率",
            )

        self.assertEqual(save_pending.call_args.kwargs["framework_id"], "Cash_Anchor")

    def test_absorb_text_message_rejects_when_chat_is_busy(self) -> None:
        chat_id = "cli-absorb-busy"
        try:
            with patch("src.feishu_runtime._submit_or_run") as submit, patch(
                "src.feishu_runtime.communication_gate.send"
            ) as send:
                first = feishu_runtime.handle_feishu_text_message(
                    chat_id,
                    "/absorb Cash_Anchor/CN_Dividend_Income 高股息必须检查自由现金流",
                )
                second = feishu_runtime.handle_feishu_text_message(
                    chat_id,
                    "/absorb Cash_Anchor/CN_Dividend_Income 连续新知识",
                )

            self.assertEqual(first, "absorb received")
            self.assertEqual(second, "busy")
            submit.assert_called_once()
            self.assertIn("已有任务", send.call_args.args[1])
        finally:
            release_processing(chat_id)

    def test_patch_callback_normalizes_sub_framework_target_before_accept(self) -> None:
        with patch("src.feishu_runtime.accept_patch_proposal", return_value=Path("/tmp/archive.json")) as accept, patch(
            "src.feishu_runtime.communication_gate.send"
        ):
            feishu_runtime._handle_patch_callback(
                "accept_constitution_patch",
                "cli",
                "Cash_Anchor/CN_Dividend_Income",
                "PATCH-7",
            )

        accept.assert_called_once_with("Cash_Anchor", "PATCH-7")

    def test_patch_discussion_text_records_message(self) -> None:
        with patch("src.feishu_runtime.safe_run_absorb_discussion_turn") as discuss:
            discuss.return_value.status = "need_more_discussion"
            discuss.return_value.reply_to_user = "需要确认：这是买入前规则还是复盘规则？"
            reply = feishu_runtime._handle_patch_discussion_text(
                "cli",
                "Cash_Anchor",
                "PATCH-4",
                "我认为适用边界需要收窄",
            )

        self.assertIn("买入前规则", reply)
        discuss.assert_called_once_with(
            framework_id="Cash_Anchor",
            patch_id="PATCH-4",
            user_message="我认为适用边界需要收窄",
            chat_id="cli",
        )

    def test_patch_discussion_can_be_cancelled_without_llm(self) -> None:
        with patch("src.feishu_runtime.safe_run_absorb_discussion_turn") as discuss, patch(
            "src.feishu_runtime.clear_patch_discussion"
        ) as clear:
            reply = feishu_runtime._handle_patch_discussion_text(
                "cli",
                "Cash_Anchor",
                "PATCH-5",
                "取消讨论",
            )

        self.assertIn("已取消补丁讨论", reply)
        clear.assert_called_once_with("cli")
        discuss.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""手搓多智能体管道的全局状态容器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class PipelineStatus(str, Enum):
    """管道循环用于判断下一步分支的生命周期状态。"""

    RUNNING = "running"
    NEEDS_DISCLOSURE = "needs_disclosure"
    BOUNCED = "bounced"
    AUDIT_REJECTED = "audit_rejected"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SkillRequest:
    """子 Agent 对渐进式数据披露提出的显式申请。"""

    skill_name: str
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class DisclosureRecord:
    """主管道调用 Skill 后披露给子 Agent 的数据记录。"""

    skill_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DebateEntry:
    """AOP 审计官追加的审计与辩论日志。"""

    role: Literal["worker", "auditor", "master", "human"]
    content: str
    verdict: Literal["PASS", "WARN", "REJECT"] = "WARN"


@dataclass
class AgentState:
    """贯穿所有管道节点的唯一事实来源。

    所有管道节点都修改并返回这个对象，而不是传递大量分散参数。
    这样路由、Skill 申请、披露数据、审计辩论日志和最终输出都能保存在同一份可审计记录里。
    """

    user_input: str
    chat_id: str | None = None
    framework_id: str | None = None
    context_bundle_id: str | None = None
    loaded_context_files: list[str] = field(default_factory=list)
    route_reason: str | None = None
    route_attempts: int = 0
    bounce_back: bool = False
    bounce_reason: str | None = None
    requested_skills: list[SkillRequest] = field(default_factory=list)
    disclosed_data: list[DisclosureRecord] = field(default_factory=list)
    worker_notes: list[str] = field(default_factory=list)
    draft_decision: str | None = None
    audit_persona: str | None = None
    audit_log: list[DebateEntry] = field(default_factory=list)
    audit_signal: Literal["PASS", "WARN", "REJECT"] | None = None
    final_answer: str | None = None
    user_action: str | None = None
    status: PipelineStatus = PipelineStatus.RUNNING
    errors: list[str] = field(default_factory=list)

    def reset_for_reroute(self) -> None:
        """子 Agent 弹回后，为下一次路由尝试准备状态。

        这里会刻意保留 ``bounce_reason``，让路由器在下一次尝试时能带上惩罚性上下文。
        """

        # 只清理分配相关字段；保留尝试次数和 bounce_reason 作为链路痕迹。
        self.framework_id = None
        self.context_bundle_id = None
        self.loaded_context_files = []
        self.route_reason = None
        self.bounce_back = False
        self.status = PipelineStatus.RUNNING

    def append_error(self, message: str) -> None:
        """记录终止性管道错误，并把生命周期标记为失败。"""

        self.errors.append(message)
        self.status = PipelineStatus.FAILED

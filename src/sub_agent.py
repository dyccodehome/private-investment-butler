"""带接单预检和两阶段推理的策略孤岛子 Agent 执行器。"""

from __future__ import annotations

from pathlib import Path

from src.init import FRAMEWORKS_DIR
from src.llm_client import LLMClient
from src.state import AgentState, PipelineStatus, SkillRequest


FRAMEWORK_KEYWORDS = {
    "Cash_Anchor": ["现金流", "红利", "股息", "分红", "低估值", "银行", "煤炭", "公用事业", "期权", "option", "covered call", "put", "call", "iv", "权利金"],
    "CN_Alpha_Growth": ["a股", "中国", "成长", "科技自立", "出海", "半导体", "新能源", "ma120", "产业升级", "本土"],
    "US_Disruptive_Growth": ["美股", "us", "ai", "saas", "生物科技", "英伟达", "微软", "全球", "颠覆", "tam"],
}


def load_constitution(framework_id: str) -> str:
    """只加载当前被选中策略框架的宪法。

    这用于强制策略隔离：一个策略 Worker 在处理任务时不会读取其他策略的规则。
    """

    path = FRAMEWORKS_DIR / framework_id / "constitution.md"
    return Path(path).read_text(encoding="utf-8")


def intake_precheck(state: AgentState) -> AgentState:
    """让被选中的子 Agent 判断自己是否应该接单。

    这是弹回机制的守门逻辑。Master 路由器可能分配错误，
    所以子 Agent 会在消耗 LLM 或数据抓取预算之前先做一次低成本本地检查。
    """

    if not state.framework_id:
        state.append_error("Cannot precheck without framework_id.")
        return state

    text = state.user_input.lower()
    keywords = FRAMEWORK_KEYWORDS.get(state.framework_id, [])
    if keywords and not any(keyword in text for keyword in keywords):
        # 拒绝接单，并把任务交还主管道重新路由。
        state.bounce_back = True
        state.bounce_reason = (
            f"{state.framework_id} 预检拒单：用户问题与本策略宪法边界不匹配。"
        )
        state.status = PipelineStatus.BOUNCED
        return state

    # 能加载宪法说明子 Agent 已接单，后续只在自己的策略空间内推理。
    constitution = load_constitution(state.framework_id)
    state.worker_notes.append(
        f"{state.framework_id} 接单。已加载宪法 {len(constitution)} 字。"
    )
    return state


def stage_one_request_skills(state: AgentState) -> AgentState:
    """子 Agent 只读取宪法和用户输入，然后申请所需数据。

    这实现渐进披露：子 Agent 不会预先拿到行情、持仓或新闻数据；
    它必须显式申请下一步推理所需的最小数据集。
    """

    if state.disclosed_data:
        # 当前管道轮次已经披露过数据，不再重复申请。
        return state

    symbol = _extract_symbol_placeholder(state.user_input)
    state.requested_skills = [
        SkillRequest(
            skill_name="hithink-market-query",
            arguments={"symbol": symbol},
            reason="需要通过同花顺问财行情 Skill 获取实时市场事实。",
        ),
        SkillRequest(
            skill_name="trade_history",
            arguments={"symbol": symbol},
            reason="需要读取历史决策逻辑，避免重复犯错。",
        ),
    ]
    # 通知主管道暂停子 Agent 推理，先满足数据申请。
    state.status = PipelineStatus.NEEDS_DISCLOSURE
    return state


def stage_two_decide(state: AgentState) -> AgentState:
    """子 Agent 结合已披露数据和宪法做 If-Then 推理。

    Worker LLM 只能看到当前策略宪法、用户问题和主管道披露的数据。
    其他策略岛仍然保持隐藏。
    """

    data_names = ", ".join(item.skill_name for item in state.disclosed_data) or "no data"
    constitution = load_constitution(state.framework_id or "")
    client = LLMClient.for_framework(state.framework_id)
    state.draft_decision = client.complete(
        system_prompt=(
            "你是私人投资管家的子 Agent。你只能依据当前策略宪法、用户原话、"
            "主管道披露的数据进行 If-Then 推演。不要编造未披露的实时数据。"
        ),
        user_prompt=(
            f"策略框架：{state.framework_id}\n"
            f"策略宪法：\n{constitution}\n\n"
            f"用户原话：{state.user_input}\n\n"
            f"已披露数据来源：{data_names}\n"
            f"已披露数据：{_compact_disclosed_data_for_prompt(state)}\n\n"
            "请输出：1. 核心判断；2. If-Then 执行纪律；3. 需要人工确认的风险点。"
        ),
        agent_role="worker",
        call_site="sub_agent.stage_two_decide",
        framework_id=state.framework_id,
        chat_id=state.chat_id,
        user_query=state.user_input,
    )
    state.worker_notes.append("子 Agent 完成第二阶段推演，等待审计切面拦截。")
    state.status = PipelineStatus.RUNNING
    return state


def _extract_symbol_placeholder(user_input: str) -> str:
    """临时标的提取器，后续可替换为真正的实体解析器。"""

    return user_input.strip().split()[0] if user_input.strip() else "UNKNOWN"


def _compact_disclosed_data_for_prompt(state: AgentState) -> str:
    """只把压缩后的披露元数据传给模型提示词。"""

    compact = []
    for item in state.disclosed_data:
        compact.append(
            {
                "skill_name": item.skill_name,
                "arguments": item.arguments,
                "payload": item.payload,
            }
        )
    return str(compact)

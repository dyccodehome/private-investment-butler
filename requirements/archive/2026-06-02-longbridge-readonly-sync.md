# 长桥只读持仓同步

状态：done

创建日期：2026-06-02

## 背景

美股账户中现金流资产和成长股资产混在同一个长桥账户里。Agent 需要读取长桥持仓，但不能让 LLM 自由调用券商命令，也不能把成长股误写入 Cash Anchor。

## 目标

- 通过固定 Python Provider 调用长桥 CLI。
- 只开放只读命令。
- `/sync longbridge` 生成同步提案，不直接写账本。
- `/apply longbridge cash_anchor` 经用户确认后写入 Cash Anchor。
- Cash Anchor 只接收 QQQI、XQQI、TQQQ。
- 使用长桥 quote 刷新当前价，避免用成本价代替现价。

## 非目标

- 不开放下单、改单、撤单。
- 不让 LLM 拼接 shell 命令。
- 不把其他美股成长持仓写入 Cash Anchor。
- 暂不强制切换到 Longbridge Python SDK。

## 用户流程

1. 用户本地安装并登录长桥 CLI。
2. 用户发送 `/sync longbridge` 查看同步提案。
3. 用户确认后发送 `/apply longbridge cash_anchor`。
4. Agent 重新读取持仓和报价，只写入 Cash Anchor 白名单标的。

## 命令或入口

```text
/sync longbridge
/apply longbridge cash_anchor
```

## 数据文件

- 读取：长桥 CLI 只读输出。
- 写入：`frameworks/Cash_Anchor/data/holdings.csv`
- 写入：`frameworks/Cash_Anchor/data/portfolio_events.csv`

## 验收标准

- [x] 固定调用 `longbridge positions --format json`。
- [x] 固定调用 `longbridge quote <symbols> --format json`。
- [x] 过滤非 Cash Anchor 标的。
- [x] apply 前需要显式命令确认。
- [x] 写入时保留已有分红和税率字段。
- [x] 解析错误、CLI 缺失、超时有明确错误提示。
- [x] 单元测试覆盖解析、过滤、报价和写入。

## 待确认问题

- 是否改用 Longbridge Python SDK 作为长期部署方案。

## 实现记录

- 已实现于 `src/longbridge_provider.py`。

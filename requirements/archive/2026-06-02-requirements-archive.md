# 需求文档留档机制

状态：done

创建日期：2026-06-02

## 背景

用户希望把讨论过的需求留下文档记录，后续可以让 Agent 根据需求文档继续设计和实现，避免只依赖聊天上下文。

## 目标

- 新增一个独立目录保存需求文档。
- 支持正在讨论、已完成、暂停或拒绝的需求归档。
- 提供统一模板，方便后续把需求写清楚。
- README 中说明该目录的用途。

## 非目标

- 暂不实现自动从飞书消息生成需求文档。
- 暂不实现需求状态自动流转。
- 暂不实现需求和代码提交的自动绑定。

## 用户流程

1. 用户提出一个需求。
2. Agent 将需求整理成 Markdown 文档，放入 `requirements/active/`。
3. 用户和 Agent 继续讨论并更新文档。
4. 需求明确后，Agent 根据文档实现。
5. 实现完成后，文档状态改为 `done`，必要时移动到 `requirements/archive/`。

## 命令或入口

当前先通过普通对话触发，不新增飞书命令。

## 数据文件

- 读取：`requirements/active/*.md`
- 写入：`requirements/active/*.md`、`requirements/archive/*.md`

## 验收标准

- [x] 新增 `requirements/` 目录。
- [x] 新增需求文档模板。
- [x] 新增需求目录说明。
- [x] README 记录该目录用途。

## 待确认问题

- 后续是否需要新增飞书命令，例如 `/requirement`，自动把当前讨论整理成需求文档。

## 实现记录

- 2026-06-02：已创建 `requirements/README.md`、`requirements/templates/feature_request.md` 和本需求文档。

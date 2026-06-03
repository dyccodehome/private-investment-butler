# 需求文档留档

这个目录用于保存你和 Agent 讨论过、准备实现或已经实现的产品需求。

## 目录结构

```text
requirements/
├── ROADMAP.md    # 统一待办清单
├── active/      # 正在讨论或准备实现的需求
├── archive/     # 已完成、废弃或暂停的需求
└── templates/   # 需求文档模板
```

## 使用规则

- 新需求先放到 `requirements/active/`。
- 一个需求一个 Markdown 文件。
- 文件名建议使用 `YYYY-MM-DD-short-title.md`。
- 需求实现完成后，可以把文件移动到 `requirements/archive/`，并在文档里记录完成日期。
- 项目级待办统一维护在 `requirements/ROADMAP.md`。
- Agent 后续实现功能时，优先读取对应需求文档，再改代码。

## 状态

- `draft`：草稿，需求还没讨论清楚。
- `reviewing`：正在讨论和复核。
- `ready`：需求已明确，可以实现。
- `done`：已实现并验证。
- `paused`：暂缓。
- `rejected`：放弃。

## 建议写法

复制 `requirements/templates/feature_request.md`，填入：

- 背景
- 目标
- 非目标
- 用户流程
- 命令或入口
- 数据文件
- 验收标准
- 待确认问题

如果是飞书命令类需求，重点写清楚输入格式、回复格式、写入哪些文件。

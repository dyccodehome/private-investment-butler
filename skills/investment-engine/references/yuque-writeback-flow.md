# 语雀写回流程

当用户确认保存分析结果时，按以下 5 步执行：

## Step 1：获取知识库目录结构

调用 `mcp__yuque-mcp__yuque_get_toc`：
- 参数：`repo_id = "{YUQUE_NAMESPACE}"`
- 检查 TOC 中是否存在「{YUQUE_ARCHIVE_DIR}」group 节点及当前模式对应的子 group 节点
- 记录各节点的 `uuid`（Step 2/4 作为 `target_uuid` 使用）
- 注意：`yuque_create_doc` 直接使用 `{YUQUE_NAMESPACE}` 作为 `repo_id`，无需单独获取数字 book_id

## Step 2：按需创建缺失的目录节点

若「{YUQUE_ARCHIVE_DIR}」不存在，调用 `mcp__yuque-mcp__yuque_update_toc` 创建：
```
新建 group 节点，title: "{YUQUE_ARCHIVE_DIR}"
```

若对应模式子目录不存在，在「{YUQUE_ARCHIVE_DIR}」下创建：
```
持仓复盘模式 → title: "持仓复盘"
买卖决策模式 → title: "买卖决策"
宏观分析模式 → title: "宏观分析"
个股研究模式 → title: "个股研究"
```

## Step 3：新建文档

调用 `mcp__yuque-mcp__yuque_create_doc`：
```
repo_id: "{YUQUE_NAMESPACE}"
title:   "{YYYY-MM-DD} {模式} {关键词}"
body:    {本次分析的完整 Markdown 输出内容}
format:  "markdown"
```

文档标题关键词规则：
- 持仓复盘：列出主要标的名称（最多 3 个，超出用「等X只」）→ 如 `2026-04-17 持仓复盘 茅台+宁德+比亚迪`
- 买卖决策：标的名称 → 如 `2026-04-17 买卖决策 宁德时代`
- 宏观分析：事件核心关键词（5字以内）→ 如 `2026-04-17 宏观分析 美联储降息`
- 个股研究：标的名称 → 如 `2026-04-17 个股研究 比亚迪`

## Step 4：挂载到正确目录

调用 `mcp__yuque-mcp__yuque_update_toc`（`prependNode` 或 `appendNode`），将新文档节点挂载到对应模式子目录下（用 Step 1 记录的 uuid 定位目录）。

## Step 5：确认结果

- **成功**：展示文档 URL（从 create_doc 响应获取），格式：`文档已保存：{URL}`
- **失败**：输出错误原因，并将本次分析完整 Markdown 内容重新输出一次供用户手动复制，不静默失败

## 时间规范

文档标题中的日期使用**北京时间（UTC+8）**。MCP 接口若需传入 UTC 参数，调用前自动换算（北京时间 -8 小时），对用户透明。

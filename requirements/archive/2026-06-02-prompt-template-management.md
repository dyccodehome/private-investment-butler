# Prompt 模板集中管理

状态：done

创建日期：2026-06-02

## 背景

代码中存在多段 system prompt 和 user prompt。随着 Agent 角色增多，继续把大段中文 prompt 放在 Python 文件里不利于审阅和维护。

## 目标

- 新增 `prompts/` 目录管理 prompt 正文。
- 包含 worker、auditor、knowledge absorber、discussion、growth review。
- 共享输出风格单独管理。
- 保留 `src/prompts.py` 作为模板加载和渲染层。
- 删除无用的 `src/prompt_policy.py`。

## 非目标

- 不改变现有业务模块调用函数名。
- 不引入复杂模板引擎。
- 不把策略宪法迁入 `prompts/`。

## 用户流程

1. 修改 prompt 时直接编辑 `prompts/**/*.md`。
2. Python 代码继续调用 `src.prompts` 中的函数。
3. 测试确认模板变量被正确替换。

## 命令或入口

无用户命令。

## 数据文件

- 读取：`prompts/**/*.md`
- Python 加载层：`src/prompts.py`

## 验收标准

- [x] prompt 正文迁出 Python。
- [x] system prompt 和 user prompt 分目录管理。
- [x] 共享风格规则集中在 `prompts/shared/response_style.md`。
- [x] 原调用接口保持不变。
- [x] 删除无用 `src/prompt_policy.py`。
- [x] 新增 prompt 渲染测试。

## 待确认问题

- 后续是否需要为不同环境或模型维护多版本 prompt。

## 实现记录

- 已实现于 `prompts/` 和 `src/prompts.py`。

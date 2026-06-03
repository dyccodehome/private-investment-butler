# 飞书长连接和主动推送

状态：done

创建日期：2026-06-02

## 背景

项目不计划申请公网回调地址，因此飞书接入需要使用长连接。本地 Agent 还需要支持定时任务主动推送消息。

## 目标

- 使用飞书 SDK 长连接接收消息事件。
- 接收交互卡片回调。
- 移除 HTTP webhook 代码。
- 支持重启脚本。
- 支持主动推送到默认 `chat_id`。
- 修复本地 CA bundle 路径问题。

## 非目标

- 不申请公网 callback URL。
- 不实现完整后台服务管理系统。
- 不在代码中硬编码 chat_id。

## 用户流程

1. 用户配置 `.env`。
2. 用户运行 `./scripts/restart_feishu.sh`。
3. 用户在飞书里给机器人发消息。
4. Agent 通过长连接接收事件并回复。
5. 定时脚本通过 `FEISHU_DEFAULT_CHAT_ID` 主动推送结果。

## 命令或入口

```bash
./scripts/restart_feishu.sh
python3 -m src.feishu_long_connection
python3 scripts/run_growth_daily_review.py --market CN
```

## 数据文件

- 读取：`.env`
- 读取：`config.yaml`
- 写入：无固定业务数据文件

## 验收标准

- [x] 长连接入口可启动。
- [x] 普通文本消息可进入命令或主 Agent 流程。
- [x] 卡片回调可进入补丁审批流程。
- [x] `FEISHU_DEFAULT_CHAT_ID` 可被读取。
- [x] 主动推送测试成功。
- [x] `restart_feishu.sh` 不再指向不存在的临时证书文件。

## 待确认问题

- 生产部署时是否使用 Docker 或系统服务常驻。

## 实现记录

- 已实现于 `src/feishu_long_connection.py`、`src/feishu_runtime.py`、`src/communication_gate.py`、`scripts/restart_feishu.sh`。

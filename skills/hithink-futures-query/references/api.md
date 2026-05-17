# 期货期权数据查询 API 接口文档

## 接口概述

本文档描述同花顺期货期权数据查询 API 的接口规范，支持查询期货期权的行情、波动率、产销、会员持仓、会员榜单、行权等多种数据。

---

## 基础信息

| 项目 | 说明 |
|------|------|
| 接口地址 | `https://openapi.iwencai.com/v1/query2data` |
| 请求方式 | POST |
| 数据格式 | JSON |
| 编码格式 | UTF-8 |
| 认证方式 | Bearer Token |

---

## 认证方式

### Bearer Token 认证

在请求头中携带 Authorization 字段：

```
Authorization: Bearer {IWENCAI_API_KEY}
```

### 环境变量配置

```bash
export IWENCAI_API_KEY="your_api_key_here"
```

---

## 请求参数

### 请求头 (Headers)

| 参数名 | 必填 | 说明 |
|--------|------|------|
| Authorization | 是 | Bearer Token，格式：`Bearer {API_KEY}` |
| Content-Type | 是 | 固定值：`application/json` |

### 请求体 (Body)

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| query | STRING | 是 | - | 查询问句，如"沪铜期货最新行情" |
| source | STRING | 否 | test | 来源标识 |
| page | STRING | 否 | 1 | 分页页码 |
| limit | STRING | 否 | 10 | 每页条数 |
| is_cache | STRING | 否 | 1 | 是否使用缓存：1-是，0-否 |

### 请求示例

```json
{
  "query": "沪铜期货最新行情",
  "source": "test",
  "page": "1",
  "limit": "10",
  "is_cache": "1"
}
```

---

## 响应参数

### 成功响应

| 参数名 | 类型 | 说明 |
|--------|------|------|
| datas | ARRAY | 期货期权数据列表，对象数组 |

### 响应示例

#### 期货行情数据示例

```json
{
  "datas": [
    {
      "期货代码": "CU2505.SHF",
      "期货简称": "沪铜2505",
      "最新价": "78520",
      "涨跌幅": "1.25%",
      "成交量": "156230",
      "持仓量": "125680",
      "最高价": "78950",
      "最低价": "78100",
      "开盘价": "78200",
      "昨结算": "77550"
    }
  ]
}
```

#### 期权波动率数据示例

```json
{
  "datas": [
    {
      "期权代码": "510050C2504M02600",
      "期权简称": "50ETF购4月2600",
      "标的代码": "510050",
      "最新价": "0.1523",
      "涨跌幅": "5.32%",
      "隐含波动率": "18.56%",
      "历史波动率": "17.82%",
      "行权价": "2.600",
      "到期日": "2025-04-23"
    }
  ]
}
```

#### 会员持仓数据示例

```json
{
  "datas": [
    {
      "期货代码": "RB2510.SHF",
      "期货简称": "螺纹钢2510",
      "会员名称": "某期货公司",
      "多头持仓": "45623",
      "多头增减": "+1234",
      "空头持仓": "32156",
      "空头增减": "-567",
      "净持仓": "13467"
    }
  ]
}
```

#### 产销数据示例

```json
{
  "datas": [
    {
      "期货品种": "原油",
      "库存量": "3500万桶",
      "库存变化": "+120万桶",
      "产量": "1250万桶/日",
      "销量": "1180万桶/日",
      "统计日期": "2025-03-20"
    }
  ]
}
```

---

## 错误响应

### 错误响应格式

| 参数名 | 类型 | 说明 |
|--------|------|------|
| code | INTEGER | 错误码，非0表示错误 |
| message | STRING | 错误描述信息 |

### 常见错误码

| 错误码 | 说明 | 处理建议 |
|--------|------|----------|
| 401 | 认证失败 | 检查 API Key 是否正确或已过期 |
| 403 | 权限不足 | 确认账号有权限访问该接口 |
| 500 | 服务器内部错误 | 稍后重试或联系技术支持 |
| 1001 | 参数错误 | 检查请求参数是否符合规范 |
| 1002 | 查询语句无效 | 检查 query 参数是否合法 |

---

## 数据类型说明

### 支持查询的期货期权数据类型

| 数据类型 | 说明 | 示例查询语句 |
|----------|------|--------------|
| 期货行情 | 期货合约价格、涨跌等 | 沪铜期货最新行情 |
| 期权行情 | 期权合约价格、涨跌等 | 50ETF期权最新价 |
| 波动率数据 | 隐含波动率、历史波动率 | 沪深300期权隐含波动率 |
| 产销数据 | 库存、产量、销量等 | 原油期货库存数据 |
| 会员持仓 | 期货公司持仓排名 | 螺纹钢期货会员持仓排名 |
| 会员榜单 | 成交量、持仓量排行 | 沪铝期货成交量排行 |
| 行权数据 | 行权价、行权量、行权比率 | 50ETF期权行权数据 |

---

## 调用示例

### Python 示例

```python
import urllib.request
import json
import os

url = "https://openapi.iwencai.com/v1/query2data"
headers = {
    "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
    "Content-Type": "application/json"
}
payload = {
    "query": "沪铜期货最新行情",
    "source": "test",
    "page": "1",
    "limit": "10",
    "is_cache": "1"
}

data = json.dumps(payload).encode("utf-8")
request = urllib.request.Request(url, data=data, headers=headers, method="POST")

with urllib.request.urlopen(request, timeout=30) as response:
    result = json.loads(response.read().decode("utf-8"))
    datas = result.get("datas", [])
    print(datas)
```

### cURL 示例

```bash
curl -X POST "https://openapi.iwencai.com/v1/query2data" \
  -H "Authorization: Bearer $IWENCAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "沪铜期货最新行情",
    "source": "test",
    "page": "1",
    "limit": "10",
    "is_cache": "1"
  }'
```

---

## 注意事项

1. **数据来源**：所有数据来源于同花顺问财，使用时需标注数据来源
2. **频率限制**：请关注接口调用频率限制，避免频繁调用
3. **缓存使用**：建议开启缓存（is_cache=1）以提高响应速度
4. **超时设置**：建议设置合理的超时时间（推荐 30 秒）
5. **错误处理**：调用方应妥善处理各类错误情况

---

## 相关链接

- 同花顺问财 Web 端：https://www.iwencai.com/unifiedwap/chat

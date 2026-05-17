"""OpenAPI / Swagger 文档元数据"""

OPENAPI_TAGS = [
    {
        "name": "系统",
        "description": "健康检查、服务信息等无需认证的接口。",
    },
    {
        "name": "用户",
        "description": "注册、登录（JWT Bearer）、获取当前用户信息。",
    },
    {
        "name": "行情",
        "description": (
            "A 股、ETF 基金、黄金行情查询、搜索与图表走势。"
            "图表接口 `/market/chart/{asset_type}/{symbol}?range=today|1m|2m|3m|1y|3y|5y` 返回折线/K 线序列。"
            "行情缓存由后台定时从 AKShare 拉取至 Redis/MySQL。"
        ),
    },
    {
        "name": "自选",
        "description": "用户自选标的 CRUD，加入自选后会被纳入定时行情拉取列表。",
    },
    {
        "name": "涨跌提醒",
        "description": "价格/涨跌幅阈值提醒；触发后写入事件表并自动停用该提醒。",
    },
]

OPENAPI_DESCRIPTION = """
## BigA 行情分析 API

面向 **A 股、基金 ETF、上金所黄金** 的伪实时行情分析后端。

### 数据说明

| 资产类型 | `asset_type` | 数据来源 |
|----------|--------------|----------|
| A 股 | `stock` | 东方财富（AKShare） |
| ETF 基金 | `fund` | 东方财富（AKShare） |
| 黄金 | `gold` | 上海黄金交易所（日线，如 `Au99.99`） |

- **非毫秒级实时**：后台按 `config/settings.yaml` 中 `poll_interval_seconds` 定时轮询（默认 300 秒）。
- **拉取范围**：仅拉取自选列表 + 未触发的活跃提醒中的标的，不做全市场扫描。
- **缓存**：最新行情写入 Redis + MySQL `market_quotes`，服务重启后可恢复。
- **A 股多源降级**：东财日线 → 新浪 → 腾讯 → 雪球 → 东财盘口（`data_source` 字段标识来源）。

### 认证方式

1. `POST /api/v1/users/login` 提交表单 `username`、`password`
2. 复制返回的 `access_token`
3. 点击 Swagger 右上角 **Authorize**，输入：`Bearer <token>`（或仅 token，部分客户端自动补全）

### 提醒条件 `condition_type`

| 值 | 含义 |
|----|------|
| `price_above` | 最新价 ≥ 阈值 |
| `price_below` | 最新价 ≤ 阈值 |
| `change_pct_above` | 涨跌幅(%) ≥ 阈值 |
| `change_pct_below` | 涨跌幅(%) ≤ 阈值 |

### 配置

统一配置文件：`config/settings.yaml`（MySQL、Redis、轮询间隔等）。
"""

# BigA 行情分析后端

一个基于 FastAPI 的 **A 股 / 基金 ETF / 黄金** 行情分析后端项目，通过 AKShare 定时拉取国内公开行情，适合对实时性要求不高的分析场景（默认每 5 分钟刷新一次）。

## 目录结构

```
bigA_py/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口，Swagger / 生命周期 / 健康检查
│   ├── config.py            # 读取 config/settings.yaml
│   ├── init_data.py         # 初始化 MySQL 表与示例数据
│   ├── deps.py              # 公共依赖（当前用户）
│   ├── core/
│   │   ├── database.py      # SQLAlchemy + MySQL 连接
│   │   ├── redis_client.py  # Redis 连接与检测
│   │   ├── security.py      # 密码 bcrypt 加密
│   │   └── openapi.py       # Swagger 文档描述与分组标签
│   ├── models/
│   │   └── __init__.py      # User、WatchlistItem、PriceAlert、AlertEvent
│   ├── schemas/
│   │   └── __init__.py      # Pydantic 请求/响应模型
│   ├── routers/
│   │   ├── users.py         # 注册、登录、当前用户
│   │   ├── market.py        # 行情、指数、搜索、刷新
│   │   ├── watchlist.py     # 自选 CRUD
│   │   └── alerts.py        # 涨跌提醒与事件
│   └── services/
│       ├── quote_provider.py  # AKShare 数据拉取
│       ├── quote_cache.py     # 内存 + Redis 行情缓存
│       ├── scheduler.py       # 后台定时轮询
│       ├── alert_engine.py    # 提醒条件判断
│       └── types.py           # 资产类型、提醒条件枚举
├── config/
│   ├── settings.yaml          # 统一配置（MySQL、Redis、应用参数）
│   ├── settings.example.yaml
│   └── init_mysql.sql         # MySQL 建库建用户脚本
├── tests/
├── requirements.txt
├── .env                       # 可选：CONFIG_FILE 路径
└── README.md
```

## 功能概览

- **行情**：主要指数、自选标的报价、关键词搜索
- **自选**：股票（`stock`）、ETF（`fund`）、上金所黄金（`gold`）
- **提醒**：价格 / 涨跌幅阈值，触发后写入事件表
- **缓存**：行情写入 Redis，重启可恢复
- **配置**：`config/settings.yaml` 统一管理 MySQL、Redis、轮询间隔

## 数据来源

| 类型 | asset_type | 数据源 |
|------|------------|--------|
| A 股、指数 | stock | 东方财富（AKShare） |
| ETF 基金 | fund | 东方财富（AKShare） |
| 黄金 | gold | 上海黄金交易所（如 Au99.99，日线级） |

> 非交易所官方推送，延迟为分钟级；仅拉取自选与活跃提醒中的标的。

## 环境要求

- Python 3.10+
- MySQL 8（本地 `3306`，库名 `bigA_db`）
- Redis（本地 `6379`）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/settings.yaml`（或复制 `config/settings.example.yaml`）：

```yaml
database:
  host: 127.0.0.1
  port: 3306
  name: bigA_db
  user: admin
  password: "123456"

redis:
  host: 127.0.0.1
  port: 6379
  db: 0
```

### 3. 初始化 MySQL

```bash
mysql -u root -p < config/init_mysql.sql
```

### 4. 初始化表与示例数据

```bash
python -m app.init_data
```

默认会创建：

- **应用登录账号**: `admin` / `admin123`（与 MySQL 连接账号无关）
- **示例自选**: 平安银行、贵州茅台、沪深300ETF、黄金9999

### 5. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. 访问

- **Swagger 文档**: http://localhost:8000/api/doc
- **ReDoc 文档**: http://localhost:8000/api/redoc
- **OpenAPI JSON**: http://localhost:8000/api/openapi.json
- **健康检查**: http://localhost:8000/health

## 各模块说明

### 配置相关

- **config/settings.yaml**: 数据库、Redis、JWT 密钥、轮询间隔等
- **app/config.py**: 加载 YAML，生成 MySQL / Redis 连接 URL
- **.env**: 可选，通过 `CONFIG_FILE` 指定其他配置文件路径

### 数据库相关

- **core/database.py**: SQLAlchemy 引擎、`get_db` 依赖、`init_db` 建表
- **models**: `User`、`WatchlistItem`、`PriceAlert`、`AlertEvent`

### 行情服务

- **quote_provider.py**: 多数据源拉取（东财日线 → 新浪 → 腾讯 → 雪球 → 东财盘口）
- **quote_store.py**: 行情快照持久化到 MySQL 表 `market_quotes`
- **scheduler.py**: 按 `poll_interval_seconds` 后台轮询（默认 300 秒）
- **quote_cache.py**: 内存 + Redis + MySQL 三级缓存

### API 路由

| 模块 | 前缀 | 认证 | 说明 |
|------|------|------|------|
| 用户 | `/api/v1/users` | 部分 | 注册、登录、/me |
| 行情 | `/api/v1/market` | 否 | 指数、报价、搜索、刷新 |
| 自选 | `/api/v1/watchlist` | 是 | 自选 CRUD |
| 提醒 | `/api/v1/alerts` | 是 | 提醒 CRUD、事件列表 |

## Swagger 使用说明

1. 打开 http://localhost:8000/api/doc
2. 调用 `POST /api/v1/users/login`，填写 `admin` / `admin123`
3. 复制返回的 `access_token`
4. 点击右上角 **Authorize**，输入：`Bearer <token>`
5. 即可调试自选、提醒等需登录接口

## 接口一览

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |

### 用户

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/users/register` | 注册 |
| POST | `/api/v1/users/login` | 登录，返回 JWT |
| GET | `/api/v1/users/me` | 当前用户（需 token） |

### 行情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/market/status` | 轮询间隔、缓存状态 |
| GET | `/api/v1/market/indices` | 主要指数 |
| GET | `/api/v1/market/quotes` | 行情列表 |
| GET | `/api/v1/market/chart/{asset_type}/{symbol}?range=` | 图表（today/1m/2m/3m/1y/3y/5y） |
| GET | `/api/v1/market/quotes/{asset_type}/{symbol}` | 单标的行情 |
| GET | `/api/v1/market/search?q=` | 搜索标的 |
| POST | `/api/v1/market/refresh` | **异步**提交刷新（立即返回，推荐） |
| GET | `/api/v1/market/refresh/status` | 查询刷新进度 |
| POST | `/api/v1/market/refresh/sync` | 同步刷新（易超时，慎用） |

### 自选（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/watchlist` | 自选列表 |
| POST | `/api/v1/watchlist` | 添加自选 |
| DELETE | `/api/v1/watchlist/{item_id}` | 删除自选 |

### 涨跌提醒（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/alerts` | 提醒列表 |
| POST | `/api/v1/alerts` | 创建提醒 |
| DELETE | `/api/v1/alerts/{alert_id}` | 删除提醒 |
| GET | `/api/v1/alerts/events` | 触发记录 |

## 提醒条件 condition_type

| 值 | 含义 |
|----|------|
| `price_above` | 最新价 ≥ 阈值 |
| `price_below` | 最新价 ≤ 阈值 |
| `change_pct_above` | 涨跌幅(%) ≥ 阈值 |
| `change_pct_below` | 涨跌幅(%) ≤ 阈值 |

示例：贵州茅台跌幅超过 3% 提醒

```json
{
  "symbol": "600519",
  "asset_type": "stock",
  "name": "贵州茅台",
  "condition_type": "change_pct_below",
  "threshold": -3.0
}
```

## 轮询间隔

在 `config/settings.yaml` 中修改：

```yaml
app:
  poll_interval_seconds: 300   # 5 分钟；600 = 10 分钟
```

## 常见问题

**东财接口连接失败（ProxyError）**  
本机若配置了失效的 HTTP 代理会导致拉取失败。可尝试：

```bash
env -u HTTP_PROXY -u HTTPS_PROXY uvicorn app.main:app --reload --port 8000
```

代码中已对 AKShare 请求尝试绕过代理；仍失败时请检查网络或升级 `akshare`。

**行情为空**  
需先将标的加入自选，或调用 `POST /api/v1/market/refresh` 手动刷新。

**全球股指与债券**（见 Swagger「全球股指」「债券收益率」）

| 类型 | 列表 | 图表 |
|------|------|------|
| 全球指数 | `GET /api/v1/market/global/indices` | `GET /api/v1/market/global/chart/{symbol}?range=1y` |
| 国债收益率 | `GET /api/v1/market/bond/yields` | `GET /api/v1/market/bond/chart/{symbol}?range=1y` |

按地区：`us` / `europe` / `asia`。债券 Y 轴为**收益率(%)**，不是股票指数点位。定时刷新会写入 `market_quotes`（`global_index` / `bond_yield`）。

**图表接口**  
`GET /api/v1/market/chart/stock/000001?range=today` → 当日（或最近交易日）分钟走势  

| range | 含义 |
|-------|------|
| `1m` | 约 1 个月日线 |
| `2m` | 约 2 个月日线 |
| `3m` | 约 3 个月日线 |
| `1y` | 约 1 年日线 |
| `3y` | 约 3 年日线 |
| `5y` | 约 5 年日线 |

返回 `points` 数组，前端用 ECharts 等绑定 `time` 与 `price` 即可（数据按需从外部接口拉取，非本地库）。

**A 股拉取策略**  
东财全市场失败时，自动按标的依次尝试：东财日线 → 新浪 → 腾讯 → 雪球 → 东财单只。成功结果写入 Redis 与 MySQL `market_quotes` 表。

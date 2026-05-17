"""全球股指与债券收益率品种目录（配置，非数据库表）"""

GLOBAL_INDEX_CATALOG: list[dict] = [
    {"symbol": "SPX", "name": "标普500", "em_name": "标普500", "region": "us"},
    {"symbol": "NDX", "name": "纳斯达克", "em_name": "纳斯达克", "region": "us"},
    {"symbol": "DJIA", "name": "道琼斯", "em_name": "道琼斯", "region": "us"},
    {
        "symbol": "N225",
        "name": "日经225",
        "em_name": "日经225",
        "region": "asia",
        "sina_hist": "日经225指数",
    },
    {
        "symbol": "KS11",
        "name": "韩国KOSPI",
        "em_name": "韩国KOSPI",
        "region": "asia",
        "sina_hist": "首尔综合指数",
    },
    {"symbol": "HSI", "name": "恒生指数", "em_name": "恒生指数", "region": "asia"},
    {
        "symbol": "TWII",
        "name": "台湾加权",
        "em_name": "台湾加权",
        "region": "asia",
        "sina_hist": "中国台湾加权指数",
    },
    {
        "symbol": "FTSE",
        "name": "英国富时100",
        "em_name": "英国富时100",
        "region": "europe",
        "sina_hist": "英国富时100指数",
    },
    {
        "symbol": "GDAXI",
        "name": "德国DAX30",
        "em_name": "德国DAX30",
        "region": "europe",
        "sina_hist": "德国DAX 30种股价指数",
    },
    {
        "symbol": "FCHI",
        "name": "法国CAC40",
        "em_name": "法国CAC40",
        "region": "europe",
        "sina_hist": "法CAC40指数",
    },
    {
        "symbol": "SX5E",
        "name": "欧洲斯托克50",
        "em_name": "欧洲斯托克50",
        "region": "europe",
        "sina_hist": "欧洲Stoxx50指数",
    },
]

BOND_YIELD_CATALOG: list[dict] = [
    {"symbol": "CN2YT", "name": "中国2年期国债", "market": "cn", "term": "2Y"},
    {"symbol": "CN5YT", "name": "中国5年期国债", "market": "cn", "term": "5Y"},
    {"symbol": "CN10YT", "name": "中国10年期国债", "market": "cn", "term": "10Y"},
    {"symbol": "CN30YT", "name": "中国30年期国债", "market": "cn", "term": "30Y"},
    {"symbol": "US2YT", "name": "美国2年期国债", "market": "us", "term": "2Y"},
    {"symbol": "US5YT", "name": "美国5年期国债", "market": "us", "term": "5Y"},
    {"symbol": "US10YT", "name": "美国10年期国债", "market": "us", "term": "10Y"},
    {"symbol": "US30YT", "name": "美国30年期国债", "market": "us", "term": "30Y"},
]

# symbol -> sina 中文名
BOND_SINA_NAME: dict[str, str] = {item["symbol"]: item["name"] for item in BOND_YIELD_CATALOG}

GLOBAL_INDEX_BY_SYMBOL: dict[str, dict] = {item["symbol"]: item for item in GLOBAL_INDEX_CATALOG}
GLOBAL_INDEX_BY_EM_NAME: dict[str, dict] = {item["em_name"]: item for item in GLOBAL_INDEX_CATALOG}

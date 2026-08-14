# app/core/config.py
# -*- coding: utf-8 -*-
"""
统一配置文件 v2.0
- 所有路径基于项目根目录计算
- 数据库配置从环境变量读取，本地有默认值
- 敏感信息不写入代码
"""

import os
from pathlib import Path

# -------------------- 路径计算 --------------------
# 项目根目录（config.py 所在目录的上级的上级）
BASE_DIR = Path(__file__).parent.parent.parent.absolute()

# 数据目录
DATA_CENTER = os.path.join(BASE_DIR, "data_center")
PROCESSED_DIR = os.path.join(DATA_CENTER, "processed")
FIN_DIR = os.path.join(DATA_CENTER, "processed_financial")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
CHARTS_DIR = os.path.join(BASE_DIR, "charts")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
STATIC_DIR = os.path.join(BASE_DIR, "app", "static")

# 确保必要目录存在
for d in [DATA_CENTER, PROCESSED_DIR, FIN_DIR, OUTPUTS_DIR, 
          REPORTS_DIR, CHARTS_DIR, KNOWLEDGE_DIR, STATIC_DIR]:
    os.makedirs(d, exist_ok=True)


# -------------------- 数据库配置（环境变量优先） --------------------
def get_db_config():
    """从环境变量读取数据库配置，若未设置则使用本地默认值"""
    return {
        'host': os.getenv('MYSQL_HOST', 'localhost'),
        'port': int(os.getenv('MYSQL_PORT', 3307)),
        'user': os.getenv('MYSQL_USER', 'root'),
        'password': os.getenv('MYSQL_PASSWORD', '060401'),
        'database': os.getenv('MYSQL_DATABASE', 'risk_db')
    }

DB_CONFIG = get_db_config()


def get_database_url():
    """返回 SQLAlchemy 兼容的连接字符串"""
    cfg = get_db_config()
    return f"mysql+pymysql://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}?charset=utf8mb4"


# -------------------- 其他配置 --------------------
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
API_VERSION = "v4.0"

# 风险等级阈值（与 riskSystem.py 保持一致）
VOL_THRESHOLDS = {
    "level2": 0.05,
    "level3": 0.15,
    "level4": 0.40
}
MC_TAIL_THRESHOLD = -0.055
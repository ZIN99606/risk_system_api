"""
导入上游AI预测数据到 MySQL risk_db.ai_predictions 表
数据来源：outputs/risk_rating_mixed.parquet（已包含 MC 分位数）
"""

import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, inspect, text
from config import DB_CONFIG

# ======================== 配置路径 ========================
RATING_PATH = "outputs/risk_rating_mixed.parquet"

# 需要保留的 MC 分位数列
MC_COLS = ['q1_1d', 'q5_1d', 'q10_1d', 'q1_5d', 'q5_5d', 'q10_5d']


def get_mysql_engine():
    """创建 MySQL 连接引擎"""
    db = DB_CONFIG
    url = f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['database']}?charset=utf8mb4"
    return create_engine(url, pool_recycle=3600, echo=False)


def load_and_merge_ai_data():
    print("🚀 开始导入AI预测数据到 MySQL...")

    # 1. 检查文件是否存在
    if not os.path.exists(RATING_PATH):
        print(f"❌ 未找到主表文件: {RATING_PATH}")
        return False

    # 2. 读取主表
    df = pd.read_parquet(RATING_PATH)
    print(f"✅ 加载主表: {len(df)} 条记录")

    # 3. 检查 MC 列是否已存在
    df['date'] = pd.to_datetime(df['date'])
    existing_mc = [col for col in MC_COLS if col in df.columns]
    if existing_mc:
        print(f"✅ 主表已包含蒙特卡洛分位数: {existing_mc}")
    else:
        print("⚠️ 警告: 主表中未找到蒙特卡洛分位数列，将仅导入基础字段")

    # 4. 检查必要字段
    required_cols = ['date', 'stock', 'risk_score', 'pred_vol']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"❌ 缺少必要字段: {missing}")
        return False

    # 5. 处理缺失值
    df = df.replace({np.nan: None})

    # 6. 写入 MySQL
    engine = get_mysql_engine()
    
    # 检查表是否存在，如果存在则删除重建
    inspector = inspect(engine)
    if inspector.has_table('ai_predictions'):
        print("⚠️ 表 ai_predictions 已存在，将删除重建")
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS ai_predictions"))
            conn.commit()

    # 写入数据库
    df.to_sql('ai_predictions', engine, index=False, if_exists='replace')
    print(f"✅ 成功写入 MySQL: {len(df)} 条记录 → risk_db.ai_predictions")

    # 8. 打印数据概览
    print("\n📊 数据概览（最新5条）:")
    print(df[['date', 'stock', 'risk_score', 'pred_vol']].head(5).to_string(index=False))

    min_date = df['date'].min()
    max_date = df['date'].max()
    print(f"\n📅 日期范围: {min_date.date()} ~ {max_date.date()}")
    print(f"📋 股票数量: {df['stock'].nunique()} 只")
    print(f"📋 包含 MC 列: {existing_mc if existing_mc else '无'}")

    return True


if __name__ == "__main__":
    success = load_and_merge_ai_data()
    if success:
        print("\n🎉 AI预测数据导入完成！")
    else:
        print("\n❌ 导入失败，请检查文件路径和格式。")
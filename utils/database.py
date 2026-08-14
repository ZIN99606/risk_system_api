# app/utils/database.py
# -*- coding: utf-8 -*-
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

# 将项目根目录加入 path，以便导入 core.config
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.config import DB_CONFIG, get_database_url

# 创建同步引擎（你现有的 riskSystem.py 和 pandas 读取都适用）
_engine = None

def get_engine():
    """获取 SQLAlchemy 同步引擎（单例模式）"""
    global _engine
    if _engine is None:
        # 使用 config.py 中的 get_database_url
        _engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,      # 连接前检测是否有效
            pool_recycle=3600,       # 1小时回收连接
            echo=False
        )
    return _engine

def get_session():
    """获取数据库会话（用于 ORM 操作，如果以后需要）"""
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

@contextmanager
def get_db_connection():
    """
    上下文管理器，用于执行原生 SQL（适配你现有的 mysql.connector 风格）
    用法: with get_db_connection() as conn: cursor = conn.cursor()
    """
    import mysql.connector
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        yield conn
    finally:
        conn.close()

# 对外暴露连接池状态检查
def check_db_health():
    """检查数据库是否可连接"""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"数据库健康检查失败: {e}")
        return False
# app/api/health.py
# -*- coding: utf-8 -*-
"""
健康检查模块
包含存活探针、就绪探针、数据库连通性检查
"""
import sys
import os
from fastapi import APIRouter, status
from datetime import datetime

# 导入数据库配置
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.core.config import DB_CONFIG, API_VERSION

router = APIRouter(tags=["Health"])


@router.get("/health/liveness")
async def liveness_probe():
    """
    【存活探针】仅检查进程是否存活。
    用于 K8s / Render 判断服务是否需要重启。
    """
    return {
        "status": "alive",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/health/readiness")
async def readiness_probe():
    """
    【就绪探针】检查服务是否准备好了处理请求。
    会尝试连接数据库，如果连接失败则返回 503 服务不可用。
    """
    import mysql.connector
    from fastapi import HTTPException

    db_ok = False
    try:
        conn = mysql.connector.connect(**DB_CONFIG, connection_timeout=5)
        if conn.is_connected():
            db_ok = True
        conn.close()
    except Exception as e:
        print(f"❌ 数据库健康检查失败: {e}")

    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed"
        )

    return {
        "status": "ready",
        "database": "connected",
        "version": API_VERSION,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/health")
async def combined_health():
    """
    【综合健康检查】用于快速查看服务状态（与 endpoints.py 保持一致）
    """
    # 简单检查数据库
    db_status = "unknown"
    try:
        import mysql.connector
        conn = mysql.connector.connect(**DB_CONFIG, connection_timeout=3)
        if conn.is_connected():
            db_status = "connected"
        conn.close()
    except:
        db_status = "disconnected"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "risk-system-api",
        "version": API_VERSION,
        "database": db_status,
        "timestamp": datetime.now().isoformat()
    }
# app/main.py
# -*- coding: utf-8 -*-
"""
FastAPI 统一入口
挂载静态文件、跨域、包含所有路由
"""

import os
import sys
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware

# 将项目根目录加入 sys.path（确保能导入 core 和 api）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from app.api.endpoints import router
from app.core.config import STATIC_DIR, BASE_DIR as CONFIG_BASE_DIR

# 创建 FastAPI 应用
app = FastAPI(
    title="A股制造业风控评级系统 API",
    description="三重验证综合风险评估 + RAG 智能报告生成",
    version="v4.0"
)

# ---------- 1. 标准 CORS 中间件 ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 2. 自定义强制 CORS 中间件（兜底） ----------
class ForceCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        # 允许所有方法和头
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        # 如果是 OPTIONS 预检请求，直接返回 200
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

# 将自定义中间件添加到标准 CORS 之后
app.add_middleware(ForceCORSMiddleware)

# ---------- 静态文件挂载 ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=os.path.join(CONFIG_BASE_DIR, "reports")), name="reports")
app.mount("/charts", StaticFiles(directory=os.path.join(CONFIG_BASE_DIR, "charts")), name="charts")

# ---------- 注册路由 ----------
app.include_router(router)

# ---------- 根路径 ----------
@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {
            "message": "A股制造业风控评级系统 API",
            "docs": "/docs",
            "static": "/static/index.html"
        }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# ---------- 启动入口 ----------
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 启动风控评级 API 服务 (统一入口)")
    print(f"📁 静态文件目录: {STATIC_DIR}")
    print("📖 API 文档: http://127.0.0.1:8002/docs")
    print("🌐 前端页面: http://127.0.0.1:8002")
    print("=" * 60)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8002,
        reload=True
    )
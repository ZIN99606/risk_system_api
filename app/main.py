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

# ---------- 跨域配置 ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 静态文件挂载 ----------
# 挂载前端页面和静态资源
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 挂载报告目录（供下载）
app.mount("/reports", StaticFiles(directory=os.path.join(CONFIG_BASE_DIR, "reports")), name="reports")
app.mount("/charts", StaticFiles(directory=os.path.join(CONFIG_BASE_DIR, "charts")), name="charts")

# ---------- 注册路由 ----------
app.include_router(router)

# ---------- 根路径（返回前端页面） ----------
@app.get("/")
async def root():
    """根路径返回前端页面"""
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


# ---------- 启动入口（仅本地调试用） ----------
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 启动风控评级 API 服务 (统一入口)")
    print(f"📁 静态文件目录: {STATIC_DIR}")
    print("📖 API 文档: http://127.0.0.1:8000/docs")
    print("🌐 前端页面: http://127.0.0.1:8000")
    print("=" * 60)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
# -*- coding: utf-8 -*-
"""
RAG 报告生成服务 API
封装 report_generator.py，提供 HTTP 接口
"""

import os
import sys
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import mysql.connector
import json

# 导入修改后的报告生成器
from report_generator import generate_report_from_topic

# ==================== 配置 ====================
# 项目根目录（risk_system 目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 风险评估后端地址
RISK_API_URL = "http://localhost:8000/evaluate"

# 输出目录
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
CHARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")

# 确保目录存在
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(CHARTS_DIR, exist_ok=True)
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

# ==================== 数据库配置（用于K线数据） ====================
DB_CONFIG = {
    'host': 'localhost',
    'port': 3307,
    'user': 'root',
    'password': '060401',
    'database': 'risk_db'
}

# ==================== 股票名称映射 ====================
STOCKS_INFO = [
    {"code": "000333", "name": "美的集团"},
    {"code": "002049", "name": "紫光国微"},
    {"code": "002156", "name": "通富微电"},
    {"code": "002371", "name": "北方华创"},
    {"code": "002459", "name": "晶澳科技"},
    {"code": "002465", "name": "海格通信"},
    {"code": "002594", "name": "比亚迪"},
    {"code": "300014", "name": "亿纬锂能"},
    {"code": "300124", "name": "汇川技术"},
    {"code": "300223", "name": "北京君正"},
    {"code": "300274", "name": "阳光电源"},
    {"code": "300661", "name": "圣邦股份"},
    {"code": "300750", "name": "宁德时代"},
    {"code": "300782", "name": "卓胜微"},
    {"code": "600031", "name": "三一重工"},
    {"code": "600438", "name": "通威股份"},
    {"code": "600584", "name": "长电科技"},
    {"code": "600660", "name": "福耀玻璃"},
    {"code": "600690", "name": "海尔智家"},
    {"code": "601012", "name": "隆基绿能"},
    {"code": "601138", "name": "工业富联"},
    {"code": "601633", "name": "长城汽车"},
    {"code": "601766", "name": "中国中车"},
    {"code": "603501", "name": "韦尔股份"},
    {"code": "603986", "name": "兆易创新"},
    {"code": "688008", "name": "澜起科技"},
    {"code": "688012", "name": "中微公司"},
    {"code": "688521", "name": "芯原股份"},
    {"code": "688599", "name": "天合光能"},
    {"code": "688981", "name": "中芯国际"},
]

# ==================== 创建 FastAPI 应用 ====================
app = FastAPI(
    title="RAG报告生成服务",
    description="基于风险评估结果 + RAG 检索生成 Word 报告",
    version="1.0"
)

# ==================== 跨域配置 ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 托管静态文件 ====================
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
app.mount("/charts", StaticFiles(directory=CHARTS_DIR), name="charts")
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

# ==================== 请求/响应模型 ====================
class ReportRequest(BaseModel):
    stock: str
    topic: str = ""  # 可选，不传则自动生成

class ReportResponse(BaseModel):
    status: str
    docx_path: str
    txt_path: str
    chart_files: list
    preview_text: str
    risk_data: dict


# ==================== API 接口 ====================

@app.get("/")
async def root():
    """根路径：返回前端页面"""
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return JSONResponse(
            status_code=404,
            content={"detail": "index.html not found. Please ensure it exists in the project root."}
        )

@app.get("/stocks")
async def get_stocks():
    """返回所有支持的制造业股票列表"""
    return {
        "stocks": STOCKS_INFO,
        "total": len(STOCKS_INFO),
        "sector": "制造业（电子、电力设备、汽车、机械设备、家用电器、国防军工）"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    risk_api_status = "unknown"
    try:
        resp = requests.get("http://localhost:8000/health", timeout=2)
        if resp.status_code == 200:
            risk_api_status = "connected"
        else:
            risk_api_status = "unhealthy"
    except:
        risk_api_status = "disconnected"

    return {
        "status": "healthy",
        "risk_api": RISK_API_URL,
        "risk_api_status": risk_api_status,
        "reports_dir": REPORTS_DIR,
        "charts_dir": CHARTS_DIR
    }

@app.get("/kline/{stock_code}")
async def get_kline(stock_code: str):
    """返回股票的历史日K线数据（OHLCV）"""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT trade_date, open, high, low, close, volume
        FROM stock_daily_ohlcv
        WHERE stock_code = %s
        ORDER BY trade_date ASC
    """
    cursor.execute(query, (stock_code,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    if not rows:
        raise HTTPException(404, detail="该股票无历史数据")
    for row in rows:
        row['trade_date'] = row['trade_date'].strftime('%Y-%m-%d')
    return {"data": rows}


@app.post("/generate_report")
async def generate_report(request: ReportRequest):
    """
    生成股票风险分析报告

    流程：
    1. 调用风险评估后端 (app.py:8000) 获取该股票的风险数据
    2. 将风险数据注入 RAG 报告生成器
    3. 生成 Word 报告并返回下载链接
    """
    stock_code = request.stock.upper()
    topic = request.topic or f"{stock_code} 制造业股票风险分析"

    # ----- 步骤1：调用风险评估后端 -----
    try:
        resp = requests.post(
            RISK_API_URL,
            json={"stock": stock_code},
            timeout=10
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"风险评估后端返回错误: {resp.text}"
            )
        risk_data = resp.json().get('data', {})
        if not risk_data:
            raise HTTPException(
                status_code=500,
                detail="风险评估后端返回的数据为空"
            )
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail=(
                "⚠️ 风险评估后端未启动！\n"
                "请先启动风险评估服务：\n"
                "cd D:\\SRIBD_intern\\week3\\risk_system\n"
                "python app.py"
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取风险评估数据失败: {str(e)}"
        )

    # ----- 步骤2：调用报告生成器 -----
    try:
        result = generate_report_from_topic(
            topic=topic,
            risk_data=risk_data,
            knowledge_dir=KNOWLEDGE_DIR
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"报告生成失败: {str(e)}"
        )

    # ----- 步骤3：返回结果（按股票代码隔离图表） -----
    # 构建该股票的图表子目录
    stock_chart_dir = os.path.join(CHARTS_DIR, stock_code)
    chart_files_basename = []
    if os.path.exists(stock_chart_dir):
        # 只返回该股票子目录下的 PNG 文件，相对路径为 stock_code/filename.png
        chart_files_basename = [
            f"{stock_code}/{f}" for f in os.listdir(stock_chart_dir)
            if f.endswith('.png')
        ]

    docx_rel_path = os.path.relpath(result['docx_path'], BASE_DIR).replace("\\", "/")
    txt_rel_path = os.path.relpath(result['txt_path'], BASE_DIR).replace("\\", "/")

    return {
        "status": "success",
        "docx_path": docx_rel_path,
        "txt_path": txt_rel_path,
        "chart_files": chart_files_basename,
        "preview_text": result.get('preview_text', ''),
        "risk_data": risk_data
    }


@app.get("/download/{filepath:path}")
async def download_file(filepath: str):
    """下载报告文件或图表"""
    full_path = os.path.join(BASE_DIR, filepath)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {filepath}")
    return FileResponse(full_path, filename=os.path.basename(filepath))


# ==================== 启动入口 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("  📄 RAG报告生成服务")
    print("=" * 60)
    print(f"  风险评估后端: {RISK_API_URL}")
    print(f"  前端页面: http://localhost:8001")
    print(f"  API文档: http://localhost:8001/docs")
    print("=" * 60)

    try:
        resp = requests.get("http://localhost:8000/health", timeout=2)
        if resp.status_code == 200:
            print("✅ 风险评估后端已连接")
        else:
            print("⚠️ 风险评估后端状态异常")
    except:
        print("⚠️ 风险评估后端未启动，请先运行 python app.py")

    print("\n🔥 启动服务...")
    uvicorn.run(
        "report_api:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )
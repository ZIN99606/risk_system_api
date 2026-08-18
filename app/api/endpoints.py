# app/api/endpoints.py
# -*- coding: utf-8 -*-
"""
API 路由层：整合 /evaluate, /generate_report, /stocks, /kline, /download, /health
从原 app.py 和 report_api.py 合并而来
"""

import os
import sys
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np

# 将项目根目录加入 sys.path，以便导入 core 模块
sys.path.append(str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.core.config import (
    BASE_DIR, REPORTS_DIR, CHARTS_DIR, KNOWLEDGE_DIR, DB_CONFIG
)
from app.core.riskSystem import (
    load_all_data_sources, 
    get_single_stock_report,
    get_mysql_engine
)
from app.core.report_generator import generate_report_from_topic

# 股票信息（保持与原 report_api.py 一致）
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

# 创建路由
router = APIRouter()

# ---------- 全局缓存数据源（启动时加载一次） ----------
_DATA_SOURCES = None

def get_data_sources():
    """懒加载数据源，确保只在第一次调用时连接数据库"""
    global _DATA_SOURCES
    if _DATA_SOURCES is None:
        print("🔄 正在加载数据源（MySQL）...")
        _DATA_SOURCES = load_all_data_sources()
        print("✅ 数据源加载完成")
    return _DATA_SOURCES


# ===================== 健康检查 =====================
@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "service": "risk-system-api", "version": "v4.0"}


# ===================== 获取股票列表 =====================
@router.get("/stocks")
async def get_stocks():
    """返回所有支持的制造业股票列表"""
    data = {
        "stocks": STOCKS_INFO,
        "total": len(STOCKS_INFO),
        "sector": "制造业（电子、电力设备、汽车、机械设备、家用电器、国防军工）"
    }
     # 显式创建 JSONResponse 并设置媒体类型
    response = JSONResponse(content=data, media_type="application/json")
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# ===================== K线数据 =====================
@router.get("/kline/{stock_code}")
async def get_kline(stock_code: str):
    """返回股票的历史日K线数据（OHLCV）"""
    try:
        engine = get_mysql_engine()
        query = """
            SELECT trade_date, open, high, low, close, volume
            FROM stock_daily_ohlcv
            WHERE stock_code = %s
            ORDER BY trade_date ASC
        """
        df = pd.read_sql(query, engine, params=(stock_code,))
        if df.empty:
            raise HTTPException(status_code=404, detail="该股票无历史数据")
        df['trade_date'] = df['trade_date'].astype(str)
        return {"data": df.to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {str(e)}")


# ===================== 风险评估 =====================
@router.post("/evaluate")
async def evaluate_stock(request: Dict[str, str]):
    """
    单只股票风险评估
    请求体: {"stock": "000333"}
    """
    stock_code = request.get('stock', '').upper()
    if not stock_code:
        raise HTTPException(status_code=400, detail="缺少 stock 参数")
    
    try:
        data_sources = get_data_sources()
        result = get_single_stock_report(stock_code, data_sources)
        return {"status": "success", "data": result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")


# ===================== RAG 报告生成 =====================
@router.post("/generate_report")
async def generate_report(request: Dict[str, Any]):
    """
    生成 RAG 智能报告
    请求体: {"stock": "000333", "topic": "可选主题"}
    """
    stock_code = request.get('stock', '').upper()
    if not stock_code:
        raise HTTPException(status_code=400, detail="缺少 stock 参数")
    
    topic = request.get('topic', '') or f"{stock_code} 制造业股票风险分析"
    
    try:
        # 1. 先获取风险评估数据
        data_sources = get_data_sources()
        risk_data = get_single_stock_report(stock_code, data_sources)
        
        # 2. 生成报告（直接传入 risk_data）
        result = generate_report_from_topic(
            topic=topic,
            risk_data=risk_data,
            knowledge_dir=KNOWLEDGE_DIR
        )
        
        # 3. 获取该股票的图表文件（按股票代码隔离）
        stock_chart_dir = os.path.join(CHARTS_DIR, stock_code)
        chart_files = []
        if os.path.exists(stock_chart_dir):
            chart_files = [
                f"{stock_code}/{f}" for f in os.listdir(stock_chart_dir)
                if f.endswith('.png')
            ]
        
        # 4. 计算相对路径（用于前端下载）
        docx_rel_path = os.path.relpath(result['docx_path'], BASE_DIR).replace("\\", "/")
        txt_rel_path = os.path.relpath(result['txt_path'], BASE_DIR).replace("\\", "/")
        
        return {
            "status": "success",
            "docx_path": docx_rel_path,
            "txt_path": txt_rel_path,
            "chart_files": chart_files,
            "preview_text": result.get('preview_text', ''),
            "risk_data": risk_data
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


# ===================== 文件下载 =====================
@router.get("/download/{filepath:path}")
async def download_file(filepath: str):
    """
    下载报告文件或图表（支持子目录）
    示例: /download/reports/report_20260814.docx
         /download/charts/000333/stock_000333_radar.png
    """
    full_path = os.path.join(BASE_DIR, filepath)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {filepath}")
    
    # 安全检查：确保文件在项目目录内
    abs_base = os.path.abspath(BASE_DIR)
    abs_file = os.path.abspath(full_path)
    if not abs_file.startswith(abs_base):
        raise HTTPException(status_code=403, detail="禁止访问系统目录")
    
    return FileResponse(full_path, filename=os.path.basename(filepath))
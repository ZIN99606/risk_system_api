# app/models/schemas.py
# -*- coding: utf-8 -*-
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# ---------- 请求模型 ----------
class EvaluateRequest(BaseModel):
    """风险评估请求"""
    stock: str  # 6位股票代码

class ReportRequest(BaseModel):
    """报告生成请求"""
    stock: str
    topic: Optional[str] = ""  # 可选报告主题

# ---------- 响应模型 ----------
class StockInfoResponse(BaseModel):
    """股票列表响应"""
    stocks: List[Dict[str, Any]]
    total: int
    sector: str

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    service: str
    version: str = "v4.0"

class EvaluateResponse(BaseModel):
    """风险评估响应"""
    status: str
    data: Dict[str, Any]  # 直接返回 riskSystem 生成的完整 JSON

class ReportResponse(BaseModel):
    """报告生成响应"""
    status: str
    docx_path: str
    txt_path: str
    chart_files: List[str]
    preview_text: str
    risk_data: Dict[str, Any]
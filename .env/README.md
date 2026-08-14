# A股制造业风控评级系统 API

基于 FastAPI 的风控引擎，整合了深度学习预测（ConvLSTM + Transformer）、财务硬阈值、历史波动率回溯及 RAG 报告生成。

## ✨ 核心功能
- **风险评估** (`/evaluate`): 返回单只股票的Ⅰ~Ⅳ级风险及决策链路。
- **RAG 报告** (`/generate_report`): 生成含图表、行业对比、置信度的 Word 报告。
- **冲突诊断** (`/check_conflicts` 或 CLI): 扫描 30 只制造业股票的评级冲突。
- **模型置信度**: 量化 AI 预测在当前市场状态下的可靠性。

## 🚀 快速开始

### 1. 环境要求
- Python 3.10+
- MySQL 5.7+ (本地或云端)
- （可选）Docker

### 2. 安装依赖
```bash
pip install -r requirements.txt
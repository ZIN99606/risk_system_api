"""
自动复核引擎：将人工归因逻辑固化为代码规则
输入：股票代码、冲突类型、历史价格数据、财务明细数据
输出：自动裁定建议（维持/下调/豁免）+ 归因证据链
"""
import pandas as pd
import numpy as np
import os

# ======================== 路径配置 ========================
DATA_CENTER = "./data_center"
STOCK_QFQ_DIR = os.path.join(DATA_CENTER, "daily", "stocks", "qfq")
BENCHMARK_FILE = os.path.join(DATA_CENTER, "daily", "indices", "sh000300.parquet")
FINANCIAL_PANEL = os.path.join(DATA_CENTER, "financial", "all_stocks_financial_panel.parquet")

# ======================== 核心归因函数 ========================

def auto_review_historical_drawdown(stock_code: str) -> dict:
    """
    归因1：分析最大回撤区间，判断是"系统性熊市"还是"个股暴雷"
    返回：标签 + 证据
    """
    # 1. 加载个股数据
    file_path = os.path.join(STOCK_QFQ_DIR, f"{stock_code}.parquet")
    if not os.path.exists(file_path):
        return {"label": "数据缺失", "suggestion": "无法归因"}
    
    df_stock = pd.read_parquet(file_path)
    df_stock['trade_date'] = pd.to_datetime(df_stock['trade_date'])
    df_stock = df_stock.set_index('trade_date').sort_index()
    df_stock['ret'] = df_stock['close'].pct_change()
    
    # 2. 计算最大回撤区间（找波峰到波谷的日期）
    cummax = df_stock['close'].cummax()
    drawdown = (cummax - df_stock['close']) / cummax
    mdd_date = drawdown.idxmax()
    
    # 找波峰日期（该波谷之前最近的历史最高点）
    peak_date = cummax.loc[:mdd_date].idxmax()
    
    # 3. 计算该区间个股累计跌幅
    stock_loss = (df_stock.loc[mdd_date, 'close'] / df_stock.loc[peak_date, 'close']) - 1  # 负值
    
    # 4. 加载同期沪深300跌幅
    if not os.path.exists(BENCHMARK_FILE):
        return {"label": "基准缺失", "suggestion": "无法归因"}
    
    df_bench = pd.read_parquet(BENCHMARK_FILE)
    df_bench['trade_date'] = pd.to_datetime(df_bench['trade_date'])
    df_bench = df_bench.set_index('trade_date').sort_index()
    bench_loss = (df_bench.loc[mdd_date, 'close'] / df_bench.loc[peak_date, 'close']) - 1
    
    # 5. 计算比例并归因
    ratio = abs(stock_loss) / abs(bench_loss) if bench_loss != 0 else 999
    
    if ratio < 1.2:
        label = "系统性熊市共振"
        suggestion = "下调一级"  # 大盘也跌了这么多，不是个股独有的问题
    elif ratio < 1.8:
        label = "混合因素（大盘+个股）"
        suggestion = "维持原判"  # 有自身问题，但也有大盘拖累
    else:
        label = "个股自身暴雷/基本面崩溃"
        suggestion = "维持Ⅳ级"  # 个股跌得远比大盘惨，说明公司本身出问题了
    
    return {
        "label": label,
        "suggestion": suggestion,
        "peak_date": peak_date.strftime("%Y-%m-%d"),
        "mdd_date": mdd_date.strftime("%Y-%m-%d"),
        "stock_loss_pct": round(stock_loss * 100, 2),
        "bench_loss_pct": round(bench_loss * 100, 2),
        "ratio": round(ratio, 2)
    }


def auto_review_financial_debt(stock_code: str) -> dict:
    """
    归因2：分析负债结构，判断是"良性占款"还是"恶性举债"
    返回：标签 + 建议
    """
    if not os.path.exists(FINANCIAL_PANEL):
        return {"label": "财务面板缺失", "suggestion": "无法归因"}
    
    df_fin = pd.read_parquet(FINANCIAL_PANEL)
    df_fin = df_fin[df_fin['code'] == stock_code].sort_values('report_date')
    if df_fin.empty:
        return {"label": "无财务数据", "suggestion": "无法归因"}
    
    # 取最新一期财报
    latest = df_fin.iloc[-1]
    
    # 提取负债明细（适配您的列名，若不存在则返回未知）
    # 应付账款：对应应付票据及应付账款，列名可能为 accountspayable 或 应付
    payable_col = None
    loan_col = None
    for c in latest.index:
        if 'payable' in c.lower() or '应付' in c:
            payable_col = c
        if 'long' in c.lower() and 'loan' in c.lower() or '长期借款' in c:
            loan_col = c
    
    total_liab = latest.get('liabilitytoasset', 0) * latest.get('asset', 1) / 100  # 推算总负债，粗略
    
    # 如果找不到应付或借款明细，直接基于负债率给建议
    debt_ratio = latest.get('liabilitytoasset', 0)
    
    if payable_col and loan_col:
        payable = latest.get(payable_col, 0)
        loan = latest.get(loan_col, 0)
        
        if payable > loan:
            label = "供应链占款（良性杠杆）"
            suggestion = "下调一级"  # 说明是压榨上游，不是真缺钱
        else:
            label = "主动银行举债（财务杠杆）"
            suggestion = "维持原判"  # 真借了银行的钱，风险真实
    else:
        # 无明细时，看负债率趋势变化
        if len(df_fin) >= 4:
            recent_3 = df_fin['liabilitytoasset'].iloc[-3:].mean()
            older = df_fin['liabilitytoasset'].iloc[:-3].mean()
            if recent_3 < older:
                label = "负债率持续下降（去杠杆）"
                suggestion = "下调一级"
            else:
                label = "负债率持平或上升"
                suggestion = "维持原判"
        else:
            label = "数据不足，按绝对阈值处理"
            suggestion = "维持原判"
    
    return {
        "label": label,
        "suggestion": suggestion,
        "debt_ratio": round(debt_ratio * 100, 2),
        "report_date": latest['report_date'].strftime("%Y-%m-%d")
    }


def auto_review_conflict(stock_code: str) -> dict:
    """
    主入口：综合调用上述两个归因，生成最终自动复核决议
    """
    print(f"🤖 正在对 {stock_code} 执行自动复核归因...")
    
    # 执行两项归因
    hist_review = auto_review_historical_drawdown(stock_code)
    fin_review = auto_review_financial_debt(stock_code)
    
    # 综合建议逻辑
    suggestions = [hist_review.get('suggestion'), fin_review.get('suggestion')]
    
    # 规则：只要有一个说"维持原判"，就维持Ⅳ级；两个都说"下调"，才下调
    if "维持Ⅳ级" in suggestions or "维持原判" in suggestions:
        final_verdict = "系统维持Ⅳ级（自动复核未通过）"
    elif all(s == "下调一级" for s in suggestions if "下调" in s):
        final_verdict = "自动复核通过：建议下调一级"
    else:
        final_verdict = "建议人工混合判断（一升一降）"
    
    return {
        "stock": stock_code,
        "final_verdict": final_verdict,
        "historical_analysis": hist_review,
        "financial_analysis": fin_review
    }


# ======================== 测试运行 ========================
if __name__ == "__main__":
    # 针对美的集团进行自动复核
    result = auto_review_conflict("000333")
    print("\n" + "=" * 60)
    print("【自动复核归因报告】")
    print("=" * 60)
    print(f"最终裁定: {result['final_verdict']}")
    print("\n--- 历史回撤归因 ---")
    print(f"  标签: {result['historical_analysis']['label']}")
    print(f"  建议: {result['historical_analysis']['suggestion']}")
    print(f"  个股跌幅: {result['historical_analysis'].get('stock_loss_pct')}% vs 大盘跌幅: {result['historical_analysis'].get('bench_loss_pct')}%")
    print("\n--- 财务杠杆归因 ---")
    print(f"  标签: {result['financial_analysis']['label']}")
    print(f"  建议: {result['financial_analysis']['suggestion']}")
    print(f"  最新负债率: {result['financial_analysis'].get('debt_ratio')}%")
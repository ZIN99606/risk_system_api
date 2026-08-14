import pandas as pd
import numpy as np
import json
import os
from app.core.config import DB_CONFIG
from app.core.auto_review import auto_review_conflict
from sqlalchemy import create_engine, inspect

def get_mysql_engine():
    db = DB_CONFIG
    url = f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['database']}?charset=utf8mb4"
    return create_engine(url, pool_recycle=3600, echo=False)


# ======================== 全局固定参数 ========================
TRADING_DAYS = 252
RISK_FREE_RATE = 0.02

# ======================== 硬阈值配置（统一管理，方便调参） ========================
# 历史波动率分级阈值（数值为年化波动率，如 0.25 表示 25%）
VOL_THRESHOLDS = {
    "level2": 0.05,   # ≥5%  → Ⅱ级
    "level3": 0.15,   # ≥15% → Ⅲ级
    "level4": 0.40    # ≥40% → Ⅳ级
}
# 历史最大回撤分级阈值（数值为回撤比例，如 0.20 表示 20%）
# 【修改】这些阈值现在仅用于"研究层"的子等级展示，不再用于执行层硬否决
MDD_THRESHOLDS = {
    "level2": 0.05,
    "level3": 0.10,
    "level4": 0.20
}

# ======================== 蒙特卡洛尾部风险硬否决配置 ========================
# 【新增】使用蒙特卡洛模拟的1%极端亏损分位数（q1_1d）作为硬否决触发条件
# 含义：如果模型预测有1%概率单日亏损超过该阈值，触发极端风险
MC_TAIL_THRESHOLD = -0.055  # -5.5%，即预测1%概率亏超5.5% → 触发Ⅳ级
# 备用阈值：也可使用 q5_1d（5%分位数）作为辅助参考
MC_TAIL_THRESHOLD_Q5 = -0.025  # -2.5%

# ======================== 四级处置建议 ========================
RISK_ACTION = {
    "Ⅰ级": "【安全】策略正常运行，无仓位限制，出具常规日报",
    "Ⅱ级": "【预警】风控发提示，新仓规模降30%，杠杆≤1倍，24小时内提交风险说明",
    "Ⅲ级": "【警戒】暂停新开仓，杠杆减半，仓位≤70%，24小时提交处置方案",
    "Ⅳ级": "【极端】强制减仓至30%以下，暂停策略，启动应急预案，投委会审批后恢复"
}

LEVEL_TO_NUM = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}
NUM_TO_LEVEL = {1: "Ⅰ级", 2: "Ⅱ级", 3: "Ⅲ级", 4: "Ⅳ级"}

# ======================== 历史直觉等级映射（可单独提取子等级） ========================
def calc_vol_level(hist_vol: float) -> tuple:
    """返回 (等级数值, 等级文字)"""
    if pd.isna(hist_vol) or hist_vol <= 0:
        return 1, "Ⅰ级"
    elif hist_vol >= VOL_THRESHOLDS["level4"]:
        return 4, "Ⅳ级"
    elif hist_vol >= VOL_THRESHOLDS["level3"]:
        return 3, "Ⅲ级"
    elif hist_vol >= VOL_THRESHOLDS["level2"]:
        return 2, "Ⅱ级"
    else:
        return 1, "Ⅰ级"

def calc_mdd_level(mdd: float) -> tuple:
    """仅用于研究层展示的历史回撤子等级（不参与执行层决策）"""
    if pd.isna(mdd) or mdd <= 0:
        return 1, "Ⅰ级"
    elif mdd >= MDD_THRESHOLDS["level4"]:
        return 4, "Ⅳ级"
    elif mdd >= MDD_THRESHOLDS["level3"]:
        return 3, "Ⅲ级"
    elif mdd >= MDD_THRESHOLDS["level2"]:
        return 2, "Ⅱ级"
    else:
        return 1, "Ⅰ级"

def map_historical_to_level(hist_vol: float, mdd: float, q1_1d: float = None) -> tuple:
    """
    历史直觉等级映射（V3.0 - 回撤仅展示，不参与定级）
    
    参数：
        hist_vol: 历史年化波动率（用于软参考）
        mdd: 历史最大回撤（仅用于研究层展示，不参与等级判定！）
        q1_1d: 蒙特卡洛1%极端分位数（硬否决触发器）
    
    返回：
        (等级数字, 等级文字, 否决原因, 是否触发否决)
    """
    # ========== 第一层：硬否决（基于蒙特卡洛预测，与历史回撤无关） ==========
    if q1_1d is not None and not pd.isna(q1_1d):
        if q1_1d < MC_TAIL_THRESHOLD:
            return 4, "Ⅳ级", f"蒙特卡洛预测极端尾部风险 (q1={q1_1d*100:.2f}%)", True
    
    # ========== 第二层：历史波动率软参考==========
    # 注意：此处定级仅基于长期波动率，历史最大回撤(MDD)已被移出决策层！
    if pd.isna(hist_vol) or hist_vol <= 0:
        vol_level = 1
    elif hist_vol >= 0.60:   # 极端高波动（>60%年化）
        vol_level = 3        # 给Ⅲ级，不再给Ⅳ级（Ⅳ级只留给蒙特卡洛触发）
    elif hist_vol >= 0.40:
        vol_level = 2
    else:
        vol_level = 1
    
    return vol_level, NUM_TO_LEVEL[vol_level], None, False

def map_ai_score_to_level(risk_score: float) -> str:
    if risk_score < 40:
        return "Ⅰ级"
    elif risk_score < 60:
        return "Ⅱ级"
    elif risk_score < 75:
        return "Ⅲ级"
    else:
        return "Ⅳ级"

# ======================== 数据加载 ========================
def load_all_data_sources():
    """从 MySQL 读取所有数据源"""
    engine = get_mysql_engine()
    inspector = inspect(engine)
    
    data = {}
    
    # 1. AI 预测表
    if inspector.has_table('ai_predictions'):
        ai_df = pd.read_sql("SELECT * FROM ai_predictions", engine)
        ai_df['date'] = pd.to_datetime(ai_df['date'])
        data['ai'] = ai_df
        print(f"✅ 从 MySQL 加载AI预测数据: {len(ai_df)} 条")
    else:
        print("⚠️ ai_predictions 表不存在，请先运行 import_ai_predictions.py")
        data['ai'] = pd.DataFrame()
    
    # 2. 历史指标
    if inspector.has_table('historical_metrics'):
        hist_df = pd.read_sql("SELECT * FROM historical_metrics", engine)
        data['historical'] = hist_df
        print(f"✅ 从 MySQL 加载历史市场直觉: {len(hist_df)} 只股票")
    else:
        print("⚠️ historical_metrics 表不存在，请先运行 historical_risk_calculator.py")
        data['historical'] = pd.DataFrame()
    
    # 3. 财务指标
    if inspector.has_table('financial_metrics'):
        fin_df = pd.read_sql("SELECT * FROM financial_metrics", engine)
        data['financial'] = fin_df
        print(f"✅ 从 MySQL 加载财务硬阈值直觉: {len(fin_df)} 只股票")
    else:
        print("⚠️ financial_metrics 表不存在，请先运行 financial_risk_calculator.py")
        data['financial'] = pd.DataFrame()

    # ========== 4. 【新增】行业平均水平 ==========
    if inspector.has_table('sector_stats'):
        sector_stats_df = pd.read_sql("SELECT * FROM sector_stats", engine)
        data['sector_stats'] = sector_stats_df
        print(f"✅ 从 MySQL 加载行业平均水平: {len(sector_stats_df)} 个行业")
    else:
        print("⚠️ sector_stats 表不存在，请先运行 historical_risk_calculator.py")
        data['sector_stats'] = pd.DataFrame()

    # 5. 加载财务行业均值
    if inspector.has_table('financial_sector_stats'):
        fin_sector_stats = pd.read_sql("SELECT * FROM financial_sector_stats", engine)
        data['financial_sector_stats'] = fin_sector_stats
        print(f"✅ 从 MySQL 加载财务行业均值: {len(fin_sector_stats)} 个行业")
    else:
        data['financial_sector_stats'] = pd.DataFrame()

    # ========== 【新增】预计算历史波动率基准（用于置信度评估） ==========
    if 'historical' in data and not data['historical'].empty:
        hist_vols = data['historical']['hist_vol'].dropna()
        if len(hist_vols) > 10:
            data['hist_benchmark'] = {
                'mean': hist_vols.mean(),
                'std': hist_vols.std()
            }
            print(f"✅ 历史波动率基准已计算: 均值={hist_vols.mean():.2%}, 标准差={hist_vols.std():.2%}")
        else:
            # 如果历史数据太少（比如少于 10 只股票），使用保守默认值
            data['hist_benchmark'] = {'mean': 0.25, 'std': 0.10}
            print("⚠️ 历史数据不足，使用默认波动率基准: 均值=25%, 标准差=10%")
    else:
        # 如果没有历史数据表，使用默认值
        data['hist_benchmark'] = {'mean': 0.25, 'std': 0.10}
        print("⚠️ 未加载到历史数据，使用默认波动率基准: 均值=25%, 标准差=10%")
    return data


# ======================== 动态阈值辅助函数 ========================
def calc_dynamic_mc_threshold(pred_vol: float) -> float:
    """
    根据预测年化波动率计算动态硬否决阈值。
    公式: threshold = -2.33 * (pred_vol / sqrt(252))
    对应1%分位数的理论值（正态分布假设）。
    """
    if pd.isna(pred_vol) or pred_vol <= 0:
        return -0.04  # 兜底固定阈值
    daily_vol = pred_vol / np.sqrt(252)
    return -2.33 * daily_vol

# ======================== 综合评估 ========================
def evaluate_stock_comprehensive(stock_code: str, data_sources: dict) -> dict:
    ai_df = data_sources['ai']
    ai_row = ai_df[ai_df['stock'] == stock_code].sort_values('date').iloc[-1]
    ai_score = ai_row['risk_score']
    ai_level = map_ai_score_to_level(ai_score)
    ai_num = LEVEL_TO_NUM[ai_level]

    # ---- 读取蒙特卡洛尾部风险分位数与预测波动率 ----
    q1_1d = ai_row.get('q1_1d', np.nan)
    q5_1d = ai_row.get('q5_1d', np.nan)
    q10_1d = ai_row.get('q10_1d', np.nan)
    pred_vol = ai_row.get('pred_vol', 0.30)  # 预测年化波动率，若无则用0.3兜底

    # ========== 🆕 评分校准（修正上游评分头与波动率脱节的问题） ==========
    # 原理：上游 risk_score 普遍偏低（如 37分对应Ⅰ级），但 pred_vol 是准的。
    # 因此用 pred_vol 重新映射一个合理的业务分数，覆盖原始 ai_score。
    # 映射规则：年化波动率 15% → 55分（Ⅲ级起点），40% → 87.5分（Ⅳ级）
    # 低于 15% 时，保持原始分数不变（不干预低波动区间的评分）
    
    # 只有年化波动率 >= 15% 时才进行校准（避免干扰低波动股票的正常评分）
    if pred_vol >= 0.15:
        # 线性映射：15% → 55分，40% → 87.5分
        # 公式：score = 55 + (vol - 0.15) / 0.25 * 32.5
        calibrated_score = 55 + (pred_vol - 0.15) / 0.25 * 32.5
        calibrated_score = min(87.5, max(55, calibrated_score))  # 限制在 55~87.5 之间
        
        # 只有当校准后的分数明显高于原始分数时才覆盖（修正低估）
        if calibrated_score > ai_score * 1.1:  # 比原分高 10% 以上才修正
            original_score = ai_score
            ai_score = calibrated_score
            # 重新映射等级
            ai_level = map_ai_score_to_level(ai_score)
            ai_num = LEVEL_TO_NUM[ai_level]
            print(f"   🔧 评分校准: {original_score:.1f} → {ai_score:.1f} (基于 pred_vol={pred_vol:.2%})")
    # ========== 校准结束 ==========

    # ---- 动态硬否决阈值 ----
    dynamic_threshold = calc_dynamic_mc_threshold(pred_vol)

    # ---- 历史数据（仅用于展示及原始波动率等级） ----
    hist_vol = np.nan
    mdd = np.nan
    if data_sources['historical'] is not None:
        hist_row = data_sources['historical'][data_sources['historical']['stock'] == stock_code]
        if not hist_row.empty:
            row = hist_row.iloc[0]
            hist_vol = row.get('hist_vol', 0)
            mdd = row.get('max_drawdown', 0)

    vol_num, vol_level = calc_vol_level(hist_vol) if not pd.isna(hist_vol) else (1, "Ⅰ级")

    # ---- 财务数据 ----
    fin_level = "Ⅰ级"
    fin_num = 1
    fin_data = {}
    if data_sources['financial'] is not None:
        fin_row = data_sources['financial'][data_sources['financial']['stock'] == stock_code]
        if not fin_row.empty:
            row = fin_row.iloc[0]
            fin_level = row['financial_risk_level']
            fin_num = LEVEL_TO_NUM[fin_level]
            fin_data = {
                "debt_ratio_pct": row.get('debt_ratio_pct', np.nan),
                "current_ratio": row.get('current_ratio', np.nan),
                "consecutive_neg_quarters": row.get('consecutive_neg_quarters', 0),
                "financial_level": fin_level,
                "level_debt": row.get('level_debt', 'Ⅰ级'),
                "level_liquidity": row.get('level_liquidity', 'Ⅰ级'),
                "level_growth": row.get('level_growth', 'Ⅰ级')
            }

    # ---- 获取行业（在读取历史数据后） ----
    sector = None
    if data_sources['historical'] is not None:
        hist_row = data_sources['historical'][data_sources['historical']['stock'] == stock_code]
        if not hist_row.empty:
            sector = hist_row.iloc[0].get('sector', None)

    # ======================== 加权融合 ========================
    w_ai, w_fin, w_hist = 0.50, 0.30, 0.20
    level_to_score_val = {1: 12.5, 2: 37.5, 3: 62.5, 4: 87.5}
    score_ai = ai_score
    score_fin = level_to_score_val[fin_num]
    score_hist = level_to_score_val[vol_num]

    composite_score = (score_ai * w_ai) + (score_fin * w_fin) + (score_hist * w_hist)

    if composite_score < 30:
        final_num = 1
    elif composite_score < 55:
        final_num = 2
    elif composite_score < 75:
        final_num = 3
    else:
        final_num = 4

    # ======================== 否决项 ========================
    # 1. 财务硬底线
    if fin_num == 4 and final_num < 3:
        final_num = 3

    # 2. 蒙特卡洛硬否决（动态阈值）
    mc_veto_triggered = False
    veto_reason = None
    if not pd.isna(q1_1d) and q1_1d < dynamic_threshold:
        mc_veto_triggered = True
        veto_reason = f"蒙特卡洛预测极端尾部风险，等级上调一级 (q1={q1_1d*100:.2f}%)"
        final_num = min(4, final_num + 1)  # ✅ 在原等级基础上+1，最高不超过Ⅳ级

    final_level = NUM_TO_LEVEL[final_num]
    final_action = RISK_ACTION[final_level]

    # ---- 构建历史数据 ----
    hist_data = {
        "hist_vol_pct": round(hist_vol * 100, 2) if not pd.isna(hist_vol) else np.nan,
        "max_drawdown_pct": round(mdd * 100, 2) if not pd.isna(mdd) else np.nan,
        "vol_level": vol_level,
        "mdd_level": calc_mdd_level(mdd)[1] if not pd.isna(mdd) else "Ⅰ级",
        "mc_veto_triggered": mc_veto_triggered,
        "veto_reason": veto_reason,
        "historical_level": vol_level
    }
    hist_num = vol_num

    # ======================== 冲突检测 ========================
    conflicts = []
    if mc_veto_triggered and ai_num <= 2:
        conflicts.append(f"🛑 硬否决生效：{veto_reason}（AI原判{ai_level}）")
    if composite_score >= 75 and ai_score < 40:
        conflicts.append(f"⚠️ 加权偏离：综合得分 {composite_score:.1f} 远高于AI原始分 {ai_score}")
    if ai_num == 1 and hist_num >= 3 and fin_num >= 3:
        conflicts.append(f"🔍 异常背离：模型评为Ⅰ级，但历史波动率≥Ⅲ级且财务≥Ⅲ级")

     # ========== 置信度计算 ==========
    # 1. 从 data_sources 中读取预计算的历史基准（在 load_all_data_sources 中已算好）
    benchmark = data_sources.get('hist_benchmark', {})
    mu_hist = benchmark.get('mean', 0.2)      # 如果取不到，默认 20% 作为均值
    sigma_hist = benchmark.get('std', 0.1)    # 如果取不到，默认 10% 作为标准差
    
    # 2. 计算 Z 分数（当前预测波动率偏离历史均值多少个标准差）
    z_score = (pred_vol - mu_hist) / sigma_hist if sigma_hist > 0 else 0
    
    # 3. 根据 Z 分数映射置信度
    if z_score >= 3.0:
        confidence_score = 0.15
    elif z_score >= 2.5:
        confidence_score = 0.30
    elif z_score >= 2.0:
        confidence_score = 0.50
    elif z_score >= 1.5:
        confidence_score = 0.70
    else:
        confidence_score = 0.95
    
    # 4. 冲突修正（如果有冲突，置信度打 7 折）
    if conflicts and len(conflicts) > 0:
        confidence_score *= 0.7
    
    # 5. 蒙特卡洛硬否决修正（触发时置信度封顶 30%）
    if mc_veto_triggered:
        confidence_score = min(confidence_score, 0.30)
    
    # 6. 限制边界并保留两位小数
    confidence_score = max(0.05, min(0.95, round(confidence_score, 2)))
    # ========== 【位置①】到这里结束 ==========

    # ======================== 构建 result ========================
    result = {
        "executive": {
            "stock": stock_code,
            "sector": sector,
            "final_level": final_level,
            "action": final_action,
            "ai_level": ai_level,
            "historical_level": vol_level,
            "financial_level": fin_level,
            "mc_veto_triggered": mc_veto_triggered,
            "veto_reason": veto_reason,
            "dynamic_threshold": round(dynamic_threshold * 100, 2)
        },
        "research": {
            "ai_score": round(ai_score, 1),
            "ai_L1": round(ai_row.get('L1_contrib', 0), 1),
            "ai_L2": round(ai_row.get('L2_contrib', 0), 1),
            "ai_L3": round(ai_row.get('L3_contrib', 0), 1),
            "pred_vol_pct": round(ai_row.get('pred_vol', 0) * 100, 2),
            "pred_beta": round(ai_row.get('pred_beta', 0), 3),
            "mc_q1_1d": round(q1_1d * 100, 2) if not pd.isna(q1_1d) else np.nan,
            "mc_q5_1d": round(q5_1d * 100, 2) if not pd.isna(q5_1d) else np.nan,
            "mc_q10_1d": round(q10_1d * 100, 2) if not pd.isna(q10_1d) else np.nan,
            "dynamic_threshold": round(dynamic_threshold * 100, 2),
            "composite_score": round(composite_score, 1),
            
            # ========== 【新增】置信度字段 ==========
            "confidence_score": confidence_score,
            
            "historical": hist_data,
            "financial": fin_data,
            "conflicts": conflicts,
            "auto_review_verdict": None,
            "review_detail": None
        }
    }

    if conflicts:
        review = auto_review_conflict(stock_code)
        if "建议下调一级" in review.get('final_verdict', ''):
            new_num = max(1, final_num - 1)
            new_level = NUM_TO_LEVEL[new_num]
            result['executive']['final_level'] = new_level
            result['executive']['action'] = RISK_ACTION[new_level]
            result['research']['auto_review_verdict'] = "自动复核通过，已下调一级"
        else:
            result['research']['auto_review_verdict'] = "自动复核未通过，维持原等级"
        result['research']['review_detail'] = review

    return result

# ======================== 单只股票标准报告 ========================
def get_single_stock_report(stock_code: str, data_sources: dict) -> dict:
    result = evaluate_stock_comprehensive(stock_code, data_sources)
    exec_layer = result['executive']
    research = result['research']
    hist_raw = research.get('historical', {})
    fin_raw = research.get('financial', {})

    # ---- 获取股票所在行业及行业均值 ----
    sector = exec_layer.get('sector', None)
    
    # 如果 evaluate 没有透传 sector，从历史数据中获取（备用）
    if not sector and data_sources.get('historical') is not None:
        hist_row = data_sources['historical'][data_sources['historical']['stock'] == stock_code]
        if not hist_row.empty:
            sector = hist_row.iloc[0].get('sector', None)
    
    sector_stats = {}
    if sector:
        # 优先从 data_sources 获取（启动时加载）
        stats_df = data_sources.get('sector_stats')
        if stats_df is not None and not stats_df.empty:
            stats_row = stats_df[stats_df['sector'] == sector]
            if not stats_row.empty:
                row = stats_row.iloc[0]
                sector_stats = {
                    "sector_avg_vol": round(row.get('sector_avg_vol', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_vol')) else np.nan,
                    "sector_avg_mdd": round(row.get('sector_avg_mdd', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_mdd')) else np.nan,
                    "sector_avg_sharpe": round(row.get('sector_avg_sharpe', np.nan), 2) if not pd.isna(row.get('sector_avg_sharpe')) else np.nan,
                    "sector_avg_var": round(row.get('sector_avg_var', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_var')) else np.nan,
                    "sector_avg_return": round(row.get('sector_avg_return', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_return')) else np.nan,
                }
                print(f"DEBUG: 从 data_sources 获取行业均值成功: {sector_stats}")
        else:
            # 如果 data_sources 中没有，直接从数据库查询（备选）
            try:
                import mysql.connector
                from config import DB_CONFIG
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM sector_stats WHERE sector = %s", (sector,))
                stats_row_list = cursor.fetchall()
                cursor.close()
                conn.close()
                if stats_row_list:
                    row = stats_row_list[0]
                    sector_stats = {
                        "sector_avg_vol": round(row.get('sector_avg_vol', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_vol')) else np.nan,
                        "sector_avg_mdd": round(row.get('sector_avg_mdd', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_mdd')) else np.nan,
                        "sector_avg_sharpe": round(row.get('sector_avg_sharpe', np.nan), 2) if not pd.isna(row.get('sector_avg_sharpe')) else np.nan,
                        "sector_avg_var": round(row.get('sector_avg_var', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_var')) else np.nan,
                        "sector_avg_return": round(row.get('sector_avg_return', np.nan) * 100, 2) if not pd.isna(row.get('sector_avg_return')) else np.nan,
                    }
                    print(f"DEBUG: 从数据库获取行业均值成功: {sector_stats}")
            except Exception as e:
                print(f"⚠️ 查询行业均值失败: {e}")

    # ========== 🆕 新增：财务指标行业均值 ==========
    fin_sector_stats = {}
    if sector and data_sources.get('financial_sector_stats') is not None:
        fin_stats_row = data_sources['financial_sector_stats'][data_sources['financial_sector_stats']['sector'] == sector]
        if not fin_stats_row.empty:
            row = fin_stats_row.iloc[0]
            fin_sector_stats = {
                "sector_avg_debt": round(row.get('sector_avg_debt', np.nan), 2) if not pd.isna(row.get('sector_avg_debt')) else np.nan,
                "sector_avg_current": round(row.get('sector_avg_current', np.nan), 2) if not pd.isna(row.get('sector_avg_current')) else np.nan,
            }

    # ---- 合并两个 stats ----
    sector_stats.update(fin_sector_stats)


    # ---- 计算历史子等级 ----
    hist_vol = hist_raw.get('hist_vol_pct', np.nan)
    mdd = hist_raw.get('max_drawdown_pct', np.nan)
    vol_val = hist_vol / 100 if not pd.isna(hist_vol) else np.nan
    mdd_val = mdd / 100 if not pd.isna(mdd) else np.nan

    vol_num, vol_level = calc_vol_level(vol_val)
    mdd_num, mdd_level = calc_mdd_level(mdd_val)

    fin_debt_level = fin_raw.get('level_debt', 'Ⅰ级')
    fin_liq_level = fin_raw.get('level_liquidity', 'Ⅰ级')
    fin_growth_level = fin_raw.get('level_growth', 'Ⅰ级')

    # ---- 计算各维度贡献度 ----
    level_to_score_val = {1: 12.5, 2: 37.5, 3: 62.5, 4: 87.5}
    ai_score = research['ai_score']
    fin_num = LEVEL_TO_NUM[exec_layer['financial_level']]
    hist_num = LEVEL_TO_NUM[exec_layer['historical_level']]

    score_ai = ai_score
    score_fin = level_to_score_val[fin_num]
    score_hist = level_to_score_val[hist_num]

    w_ai, w_fin, w_hist = 0.50, 0.30, 0.20
    contrib_ai = score_ai * w_ai
    contrib_fin = score_fin * w_fin
    contrib_hist = score_hist * w_hist
    contrib_dict = {"模型": contrib_ai, "财务": contrib_fin, "历史波动率": contrib_hist}

    # ---- 判定决策来源 ----
    mc_veto = exec_layer.get('mc_veto_triggered', False)
    fin_level = exec_layer['financial_level']
    final_level = exec_layer['final_level']

    if mc_veto:
        dominant_source = "蒙特卡洛否决"
    elif fin_level == "Ⅳ级" and final_level == "Ⅲ级":
        dominant_source = "财务否决"
    else:
        dominant_source = max(contrib_dict, key=contrib_dict.get)

    # ---- 构建报告 ----
    report_record = {
        "stock": stock_code,
        "sector": sector,
        "eval_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "final_level": exec_layer['final_level'],
        "final_level_num": LEVEL_TO_NUM[exec_layer['final_level']],
        "action": exec_layer['action'],
        "verdict_status": "已终裁（自动复核确认）" if research.get('conflicts') else "已终裁（无冲突）",
        
        "ai_level": exec_layer['ai_level'],
        "hist_level": exec_layer['historical_level'],
        "fin_level": exec_layer['financial_level'],
        
        "veto_reason": exec_layer.get('veto_reason', None),
        "mc_veto_triggered": mc_veto,
        "dominant_source": dominant_source,
        
        "ai_score": research['ai_score'],
        "ai_L1": research['ai_L1'],
        "ai_L2": research['ai_L2'],
        "ai_L3": research['ai_L3'],
        "pred_vol_pct": research['pred_vol_pct'],
        "pred_beta": research['pred_beta'],
        
        "mc_q1_1d_pct": research.get('mc_q1_1d', np.nan),
        "mc_q5_1d_pct": research.get('mc_q5_1d', np.nan),
        "mc_q10_1d_pct": research.get('mc_q10_1d', np.nan),
        "dynamic_threshold_pct": research.get('dynamic_threshold', np.nan),
        
        "hist_vol_pct": hist_vol,
        "max_drawdown_pct": mdd,
        "vol_level": vol_level,
        "mdd_level": mdd_level,
        
        "debt_ratio_pct": fin_raw.get('debt_ratio_pct', np.nan),
        "current_ratio": fin_raw.get('current_ratio', np.nan),
        "consecutive_neg_quarters": fin_raw.get('consecutive_neg_quarters', np.nan),
        "fin_level_debt": fin_debt_level,
        "fin_level_liquidity": fin_liq_level,
        "fin_level_growth": fin_growth_level,
        
        "composite_score": research.get('composite_score', np.nan),
        # ========== 新增置信度 ==========
        "confidence_score": research.get('confidence_score', np.nan),

        "sector_avg_vol_pct": sector_stats.get('sector_avg_vol', np.nan),
        "sector_avg_mdd_pct": sector_stats.get('sector_avg_mdd', np.nan),
        "sector_avg_sharpe": sector_stats.get('sector_avg_sharpe', np.nan),
        "sector_avg_return_pct": sector_stats.get('sector_avg_return', np.nan),
        "sector_avg_debt_pct": sector_stats.get('sector_avg_debt', np.nan),
        "sector_avg_current_ratio": sector_stats.get('sector_avg_current', np.nan),
        
        "conflict_count": len(research.get('conflicts', [])),
        "has_conflict": 1 if research.get('conflicts') else 0,
        "auto_review_verdict": research.get('auto_review_verdict', "未触发复核"),
        "review_detail": research.get('review_detail', {})
    }

    # ---- RAG 摘要 ----
    lines = []
    lines.append(f"{report_record['stock']}({stock_code})在{report_record['eval_date']}的风险评估为{report_record['final_level']}风险。")
    lines.append(f"主要风险来源是{report_record['dominant_source']}。")

    if not pd.isna(report_record.get('hist_vol_pct')):
        vol_compare = ""
        if not pd.isna(report_record.get('sector_avg_vol_pct')):
            diff = report_record['hist_vol_pct'] - report_record['sector_avg_vol_pct']
            if diff > 0:
                vol_compare = f"（高于行业均值{report_record['sector_avg_vol_pct']:.1f}%，{diff:.1f}%）"
            else:
                vol_compare = f"（低于行业均值{report_record['sector_avg_vol_pct']:.1f}%，{-diff:.1f}%）"
        lines.append(f"该股票历史年化波动率为{report_record['hist_vol_pct']}%（等级{report_record['vol_level']}）{vol_compare}，历史最大回撤为{report_record['max_drawdown_pct']}%（等级{report_record['mdd_level']}）。")

    if not pd.isna(report_record.get('mc_q1_1d_pct')):
        lines.append(f"蒙特卡洛预测：1%概率单日亏损 {report_record['mc_q1_1d_pct']:.2f}%，5%概率单日亏损 {report_record['mc_q5_1d_pct']:.2f}%。")

    lines.append(f"模型给出{report_record['ai_score']}分（{report_record['ai_level']}），")
    
    if report_record['has_conflict']:
        lines.append("但系统检测到严重冲突。自动复核发现：")
        review = report_record.get('review_detail', {})
        hist = review.get('historical_analysis', {})
        if hist:
            lines.append(f"在{hist.get('peak_date')}至{hist.get('mdd_date')}期间，个股跌幅{hist.get('stock_loss_pct')}%，同期大盘跌幅{hist.get('bench_loss_pct')}%，")
            lines.append(f"属{hist.get('label')}，因此{hist.get('suggestion')}。")
        fin = review.get('financial_analysis', {})
        if fin:
            lines.append(f"财务层面，{fin.get('label')}，最新负债率{fin.get('debt_ratio')}%，{fin.get('suggestion')}。")
        lines.append(f"综合裁决：{review.get('final_verdict', '维持原判')}。")
    else:
        lines.append("三方评级一致，无冲突。")
    
    lines.append(f"最终处置建议：{report_record['action']}")
    report_record['rag_summary'] = "".join(lines).replace("。", "。\n")

    return report_record

# ======================== 批量生成 ========================
def generate_batch_report(data_sources):
    all_records = []
    available_stocks = data_sources['ai']['stock'].unique().tolist()
    print(f"📊 正在批量生成 {len(available_stocks)} 只股票的风险报告...")
    for stock in available_stocks:
        try:
            record = get_single_stock_report(stock, data_sources)
            all_records.append(record)
        except Exception as e:
            print(f"   ⚠️ 股票 {stock} 评估失败: {e}")
            continue
    df_report = pd.DataFrame(all_records)
    if not df_report.empty:
        df_report['rank_by_risk'] = df_report['final_level_num'].rank(ascending=False, method='min').astype(int)
        df_report = df_report.sort_values('final_level_num', ascending=False).reset_index(drop=True)
    return df_report

# ======================== 主程序 ========================
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("🚀 启动三重验证综合风险评估系统（AI + 历史 + 财务）")
    print("=" * 60)

    data = load_all_data_sources()
    if data is None:
        exit(1)

    # 检查命令行参数：--all 或 -a 表示批量模式
    batch_mode = "--all" in sys.argv or "-a" in sys.argv

    # 过滤掉参数，提取股票代码
    args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    
    if batch_mode:
        # ==================== 批量模式 ====================
        print("📊 批量模式：为所有30只制造业股票生成风险报告...")
        available_stocks = data['ai']['stock'].unique().tolist()
        print(f"📋 共 {len(available_stocks)} 只股票\n")
        
        output_dir = "./reports/single"
        os.makedirs(output_dir, exist_ok=True)
        
        success_count = 0
        failed_stocks = []
        
        for idx, stock in enumerate(available_stocks, 1):
            try:
                # 只打印进度，不输出详细控制台摘要
                print(f"  [{idx}/{len(available_stocks)}] 正在生成 {stock} ...", end=" ", flush=True)
                record = get_single_stock_report(stock, data)
                json_path = os.path.join(output_dir, f"{stock}_risk_report.json")
                output_data = {k: v for k, v in record.items()}
                if 'eval_date' in output_data:
                    output_data['eval_date'] = str(output_data['eval_date'])
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
                print("✅")
                success_count += 1
            except Exception as e:
                print(f"❌ 失败: {e}")
                failed_stocks.append(stock)
                continue
        
        print(f"\n✅ 批量生成完成！")
        print(f"   成功: {success_count}/{len(available_stocks)} 只股票")
        if failed_stocks:
            print(f"   失败: {failed_stocks}")
        print(f"   报告目录: {output_dir}")
        
    else:
        # ==================== 单只模式 ====================
        if len(args) < 1:
            print("❌ 请指定股票代码，例如: python riskSystem.py 002049")
            print("   或使用 --all 批量生成所有股票的报告")
            stock_code = "000333"  # 默认兜底
        else:
            stock_code = args[0]

        print(f"🔍 正在生成单只股票报告: {stock_code}")
        print("-" * 60)

        record = get_single_stock_report(stock_code, data)

        output_dir = "./reports/single"
        os.makedirs(output_dir, exist_ok=True)

        json_path = os.path.join(output_dir, f"{stock_code}_risk_report.json")
        output_data = {k: v for k, v in record.items()}
        if 'eval_date' in output_data:
            output_data['eval_date'] = str(output_data['eval_date'])
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"✅ 单只股票报告已保存至: {json_path}")

        # ---- 控制台详细摘要（仅单只模式） ----
        print("\n" + "=" * 70)
        print("📋 【风险评估报告】")
        print("=" * 70)

        research = record.get('research', {})
        exec_layer = record.get('executive', {})

        # -------- 1. 输入层 --------
        print("\n📥 【输入层】各维度原始数据")
        print("-" * 70)
        print(f"  🤖 AI模型预测:")
        print(f"       综合风险分: {record['ai_score']} 分 → 等级 {record['ai_level']}")
        print(f"       L1时序: {record['ai_L1']} | L2财务: {record['ai_L2']} | L3环境: {record['ai_L3']}")
        print(f"       预测波动率: {record['pred_vol_pct']}% | Beta: {record['pred_beta']}")

        if not pd.isna(record.get('mc_q1_1d_pct')):
            print(f"\n  🎯 蒙特卡洛模拟（1000条路径）:")
            print(f"       1% 极端亏损分位数: {record['mc_q1_1d_pct']}%")
            print(f"       5% 极端亏损分位数: {record['mc_q5_1d_pct']}%")
            print(f"       10% 极端亏损分位数: {record['mc_q10_1d_pct']}%")
            if not pd.isna(record.get('dynamic_threshold_pct')):
                print(f"       🔹 动态硬否决阈值: {record['dynamic_threshold_pct']}%")

        print(f"\n  📊 财务基本面:")
        print(f"       综合等级: {record['fin_level']}")
        print(f"       负债率: {record['debt_ratio_pct']}% (等级 {record['fin_level_debt']})")
        print(f"       流动比率: {record['current_ratio']} (等级 {record['fin_level_liquidity']})")
        print(f"       连续负增长: {record['consecutive_neg_quarters']}季 (等级 {record['fin_level_growth']})")

        print(f"\n  📈 历史回溯 (仅参考，不参与定级):")
        print(f"       历史波动率: {record['hist_vol_pct']}% (等级 {record['vol_level']})")
        print(f"       历史最大回撤: {record['max_drawdown_pct']}% (等级 {record['mdd_level']})")

        # -------- 2. 计算层（加权融合） --------
        composite = research.get('composite_score', np.nan)
        if not pd.isna(composite):
            print("\n⚖️ 【计算层】加权融合过程")
            print("-" * 70)
            print("  权重: AI 50% | 财务 30% | 历史波动率 20%")
            print(f"  综合得分 = {composite} 分")
            print(f"  映射规则: <30→Ⅰ级, 30~55→Ⅱ级, 55~75→Ⅲ级, ≥75→Ⅳ级")
            veto_override = record.get('mc_veto_triggered', False)
            if veto_override:
                print(f"  加权融合等级: （被否决覆盖）")
            else:
                print(f"  加权融合等级: {record['final_level']}")

        # -------- 3. 否决层 --------
        mc_veto = record.get('mc_veto_triggered', False)
        veto_reason = record.get('veto_reason', None)
        fin_veto = (record['fin_level'] == "Ⅳ级" and record['final_level'] == "Ⅲ级")

        if mc_veto or fin_veto:
            print("\n🛑 【否决层】硬否决检查")
            print("-" * 70)
            if mc_veto:
                print(f"  ⛔ 蒙特卡洛硬否决触发: {veto_reason}")
                print("     → 综合等级在原等级基础上上调一级")
            if fin_veto:
                print("  ⛔ 财务硬否决触发: 基本面等级为Ⅳ级")
                print("     → 综合等级至少提升至 Ⅲ级（若低于Ⅲ级）")

        # -------- 4. 决策层 --------
        print("\n📤 【决策层】最终风控指令")
        print("=" * 70)
        print(f"  🏷️  综合风险等级: {record['final_level']} (决策来源: {record['dominant_source']})")
        print(f"  📋 处置建议: {record['action']}")

        if record['has_conflict']:
            print(f"\n  ⚠️ 存在 {record['conflict_count']} 个冲突，复核裁决: {record['auto_review_verdict']}")

        print("\n" + "=" * 70)
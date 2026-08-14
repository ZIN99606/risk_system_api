import pandas as pd
import numpy as np
import os

# ======================== 硬阈值与参数配置（与 riskSystem.py 保持一致） ========================
LEVEL_TO_NUM = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}
NUM_TO_LEVEL = {1: "Ⅰ级", 2: "Ⅱ级", 3: "Ⅲ级", 4: "Ⅳ级"}

# 历史波动率分级（仅用于子等级展示）
VOL_THRESHOLDS = {"level2": 0.05, "level3": 0.15, "level4": 0.40}
MDD_THRESHOLDS = {"level2": 0.05, "level3": 0.10, "level4": 0.20}

# 蒙特卡洛硬否决阈值
MC_TAIL_THRESHOLD = -0.055  # 1%分位数 < -5.5% → 升高一级

def calc_vol_level(hist_vol: float) -> tuple:
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
    历史直觉等级（仅用于研究层参考）：
    - 硬否决由蒙特卡洛 q1_1d 触发（返回Ⅳ级）
    - 否则仅基于历史波动率（回撤不参与定级）
    """
    # 第一层：蒙特卡洛硬否决（独立于历史回撤）
    if q1_1d is not None and not pd.isna(q1_1d):
        if q1_1d < MC_TAIL_THRESHOLD:
            return 4, "Ⅳ级"
    # 第二层：波动率软参考（回撤完全移除）
    if pd.isna(hist_vol) or hist_vol <= 0:
        vol_level = 1
    elif hist_vol >= 0.60:
        vol_level = 3
    elif hist_vol >= 0.40:
        vol_level = 2
    else:
        vol_level = 1
    return vol_level, NUM_TO_LEVEL[vol_level]

def map_ai_score_to_level(risk_score: float) -> str:
    if risk_score < 40:
        return "Ⅰ级"
    elif risk_score < 60:
        return "Ⅱ级"
    elif risk_score < 75:
        return "Ⅲ级"
    else:
        return "Ⅳ级"

def load_data():
    ai_df = pd.read_parquet("outputs/risk_rating_mixed.parquet")
    pred_df = pd.read_parquet("outputs/risk_prediction_convlstm.parquet")
    
    # ---- 修复：统一日期列类型 ----
    ai_df['date'] = pd.to_datetime(ai_df['date'])
    pred_df['date'] = pd.to_datetime(pred_df['date'])
    
    mc_cols = ['date', 'stock', 'q1_1d', 'q5_1d', 'q10_1d']
    existing = [c for c in mc_cols if c in pred_df.columns]
    if existing:
        ai_df = ai_df.merge(pred_df[existing], on=['date', 'stock'], how='left')
    
    hist_df = pd.read_parquet("./data_center/historical_risk_metrics_full.parquet")
    fin_df = pd.read_parquet("./data_center/financial_risk_metrics.parquet")
    return ai_df, hist_df, fin_df

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

def analyze_stock(stock_code, ai_df, hist_df, fin_df, hist_benchmark):
    # ---- AI 与蒙特卡洛 ----
    ai_row = ai_df[ai_df['stock'] == stock_code].sort_values('date').iloc[-1]
    ai_score = ai_row['risk_score']
    ai_level = map_ai_score_to_level(ai_score)
    ai_num = LEVEL_TO_NUM[ai_level]
    q1_1d = ai_row.get('q1_1d', np.nan)
    q5_1d = ai_row.get('q5_1d', np.nan)
    q10_1d = ai_row.get('q10_1d', np.nan)
    pred_vol = ai_row.get('pred_vol', 0.30)  # 预测年化波动率，若无则用0.3兜底

        # ========== 🆕 评分校准（与 riskSystem.py 保持一致） ==========
    if pred_vol >= 0.15:
        calibrated_score = 55 + (pred_vol - 0.15) / 0.25 * 32.5
        calibrated_score = min(87.5, max(55, calibrated_score))
        if calibrated_score > ai_score * 1.1:
            ai_score = calibrated_score
            ai_level = map_ai_score_to_level(ai_score)
            ai_num = LEVEL_TO_NUM[ai_level]
    # ========== 校准结束 ==========

    # ---- 动态硬否决阈值（基于该股票自身的预测波动率） ----
    dynamic_threshold = calc_dynamic_mc_threshold(pred_vol)

    # ---- 历史（仅用于展示和波动率等级） ----
    hist_row = hist_df[hist_df['stock'] == stock_code].iloc[0]
    hist_vol = hist_row['hist_vol']
    mdd = hist_row['max_drawdown']
    vol_num, vol_level = calc_vol_level(hist_vol)
    _, mdd_level = calc_mdd_level(mdd)

    # ---- 财务 ----
    fin_row = fin_df[fin_df['stock'] == stock_code].iloc[0]
    fin_level = fin_row['financial_risk_level']
    fin_num = LEVEL_TO_NUM[fin_level]

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

    # 2. 蒙特卡洛硬否决（升高一级）
    mc_veto = False
    if not pd.isna(q1_1d) and q1_1d < dynamic_threshold:
        mc_veto = True
        final_num = min(4, final_num + 1)  # ✅ 在原等级基础上+1

    final_level = NUM_TO_LEVEL[final_num]
    hist_level = vol_level  # 仅研究层

    # ---- 冲突检测（动态阈值适配） ----
    conflicts = []
    if mc_veto and ai_num <= 2:
        conflicts.append(f"🛑 硬否决(升级一级）：MC q1={q1_1d*100:.2f}% < 动态阈值 {dynamic_threshold*100:.2f}%，AI原判{ai_level}")
    if composite_score >= 75 and ai_score < 40:
        conflicts.append(f"⚠️ 加权偏离：综合得分{composite_score:.1f}远超AI分{ai_score}")
    if ai_num == 1 and vol_num >= 3 and fin_num >= 3:
        conflicts.append(f"🔍 异常背离：AI Ⅰ级，历史波动率{vol_level}且财务{fin_level}")

    # ========== 【新增】置信度计算（与 riskSystem.py 逻辑一致） ==========
    mu_hist = hist_benchmark.get('mean', 0.2)
    sigma_hist = hist_benchmark.get('std', 0.1)
    z_score = (pred_vol - mu_hist) / sigma_hist if sigma_hist > 0 else 0
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

    if conflicts and len(conflicts) > 0:
        confidence_score *= 0.7
    if mc_veto:
        confidence_score = min(confidence_score, 0.30)
    confidence_score = max(0.05, min(0.95, round(confidence_score, 2)))

    return {
        "stock": stock_code,
        "ai_score": ai_score,
        "ai_level": ai_level,
        "hist_vol_pct": round(hist_vol * 100, 2),
        "mdd_pct": round(mdd * 100, 2),
        "vol_level": vol_level,
        "mdd_level": mdd_level,
        "hist_level": hist_level,
        "fin_level": fin_level,
        "composite_score": round(composite_score, 1),
        "final_level": final_level,
        "mc_veto": mc_veto,
        "mc_q1_1d_pct": round(q1_1d * 100, 2) if not pd.isna(q1_1d) else np.nan,
        "mc_q5_1d_pct": round(q5_1d * 100, 2) if not pd.isna(q5_1d) else np.nan,
        "mc_q10_1d_pct": round(q10_1d * 100, 2) if not pd.isna(q10_1d) else np.nan,
        "dynamic_threshold": round(dynamic_threshold * 100, 2),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "confidence_score": confidence_score,          # 新增
    }

def main():
    print("=" * 70)
    print("🔍 扫描30只制造业股票冲突情况（最新逻辑：加权融合 + 蒙特卡洛否决）")
    print("=" * 70)

    try:
        ai_df, hist_df, fin_df = load_data()
        print(f"✅ 加载AI数据: {len(ai_df)} 条")
        print(f"✅ 加载历史数据: {len(hist_df)} 只")
        print(f"✅ 加载财务数据: {len(fin_df)} 只")
    except FileNotFoundError as e:
        print(f"❌ 数据文件缺失: {e}")
        return

    # ========== 【新增】计算全市场历史波动率基准（用于置信度） ==========
    hist_vols = hist_df['hist_vol'].dropna()
    if len(hist_vols) > 10:
        hist_benchmark = {
            'mean': hist_vols.mean(),
            'std': hist_vols.std()
        }
        print(f"✅ 历史波动率基准: 均值={hist_vols.mean():.2%}, 标准差={hist_vols.std():.2%}")
    else:
        hist_benchmark = {'mean': 0.25, 'std': 0.10}
        print("⚠️ 历史数据不足，使用默认基准: 均值=25%, 标准差=10%")

    stocks = ai_df['stock'].unique().tolist()
    print(f"📋 共 {len(stocks)} 只股票\n")

    results = []
    for stock in stocks:
        try:
            results.append(analyze_stock(stock, ai_df, hist_df, fin_df, hist_benchmark))
        except Exception as e:
            print(f"   ⚠️ {stock} 分析失败: {e}")

    df = pd.DataFrame(results)

    print("-" * 70)
    print("📊 【冲突统计】")
    print("-" * 70)
    has_conflict = df[df['conflict_count'] > 0]
    print(f"   总股票数: {len(df)}")
    print(f"   存在冲突: {len(has_conflict)} ({len(has_conflict)/len(df)*100:.1f}%)")
    print(f"   无冲突: {len(df[df['conflict_count'] == 0])}")

    print("\n📊 【等级分布（最终融合）】")
    print("-" * 70)
    level_dist = df['final_level'].value_counts().sort_index()
    for level, cnt in level_dist.items():
        print(f"   {level}: {cnt} 只 ({cnt/len(df)*100:.1f}%)")

    print("\n📊 【蒙特卡洛触发统计】")
    print("-" * 70)
    mc_trig = df[df['mc_veto'] == True]
    print(f"   触发蒙特卡洛硬否决股票数: {len(mc_trig)}")
    if len(mc_trig) > 0:
        print("   触发股票:", ", ".join(mc_trig['stock'].tolist()))

    print("\n" + "-" * 70)
    print("🔴 【详细诊断明细】")
    print("-" * 70)
    for _, row in df.iterrows():
        print(f"\n   {row['stock']} | 综合分: {row['composite_score']} → 最终等级: {row['final_level']}")
        print(f"      AI: {row['ai_score']} ({row['ai_level']})")
        print(f"      历史波动率: {row['hist_vol_pct']}% (等级 {row['vol_level']}) | 回撤 {row['mdd_pct']}% (仅展示)")
        print(f"      财务: {row['fin_level']}")
        print(f"      MC: q1={row['mc_q1_1d_pct']}%, q5={row['mc_q5_1d_pct']}%, q10={row['mc_q10_1d_pct']}%")
        # ========== 【新增】置信度输出 ==========
        conf = row['confidence_score']
        conf_pct = conf * 100
        if conf < 0.35:
            tip = "⚠️ 置信度极低，模型预测不可靠，请重点参考实时数据"
        elif conf < 0.65:
            tip = "⚡ 置信度偏低，建议交叉验证"
        else:
            tip = "✅ 置信度较高，可参考"
        print(f"      模型置信度: {conf_pct:.1f}% ({tip})")
        if row['mc_veto']:
            print(f"      ⛔ 触发蒙特卡洛硬否决")
        if row['conflict_count'] > 0:
            for c in row['conflicts']:
                print(f"      ⚠️ {c}")

    output_dir = "./reports"
    os.makedirs(output_dir, exist_ok=True)
    df.to_parquet(os.path.join(output_dir, "conflict_analysis_latest.parquet"), index=False)
    print("\n" + "=" * 70)
    print(f"📁 详细数据已保存至: ./reports/conflict_analysis_latest.parquet")
    print("=" * 70)

if __name__ == "__main__":
    main()
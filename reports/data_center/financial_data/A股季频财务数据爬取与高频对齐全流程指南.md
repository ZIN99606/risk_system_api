好的，下面是最终版的完整文档内容，可以直接复制保存为 `A股季频财务数据爬取与高频对齐全流程指南.md`：

```markdown
# 📊 A股季频财务数据爬取与高频对齐全流程指南

本文档全面记录了从低频季报财务数据获取、清洗、增量更新到高频日度点对点（Point-in-Time）对齐的完整工程流水线。

---

## 一、 财务数据爬取阶段（原始数据采集）

项目通过自动化脚本结合 **Baostock** 与 **AkShare** 双数据源，对目标股票池进行季频财务数据的增量更新与安全抓取。

### 1. 爬取的数据指标与字段对照
爬取保存的原始财务报表及指标字段对应的中文意义如下：

#### ① 资产负债表 (`balance`) - 数据源：Baostock
*   `statdate` / `report_date`: 报告期（财报所属季度末日期，如 `2023-12-31`）
*   `pubdate` / `announce_date`: 公告期（财报正式对外披露的日期）
*   `total_assets`: 总资产（反映企业资产规模）
*   `liquid_assets`: 流动资产（反映企业短期可变现资产）
*   `total_liab`: 总负债（反映企业整体负债规模）
*   `liquid_liab`: 流动负债（反映企业短期债务压力）
*   `owner_equity`: 所有者权益 / 净资产（反映股东投入资本及留存收益）

#### ② 利润表 (`profit`) - 数据源：Baostock
*   `statdate` / `report_date`: 报告期
*   `pubdate` / `announce_date`: 公告期
*   `total_operate_revenue` / `revenue`: 营业收入（反映主营业务规模与成长性）
*   `operate_profit`: 营业利润（反映核心经营盈利能力）
*   `net_profit`: 净利润（反映归属于母公司或整体的最终盈利）

#### ③ 现金流量表 (`cashflow`) - 数据源：Baostock
*   `statdate` / `report_date`: 报告期
*   `pubdate` / `announce_date`: 公告期
*   `catg_operate_cash_flow` / `operate_cash_flow`: 经营活动现金流量净额（反映主营业务造血能力与现金回笼质量）
*   `invest_cash_flow`: 投资活动现金流量净额（反映资本开支与对外投资情况）
*   `finance_cash_flow`: 筹资活动现金流量净额（反映借款、分红及股权融资情况）

#### ④ 周转天数 (`turnover`) - 数据源：AkShare
*   `report_date`: 报告期
*   `days_receivable`: 应收账款周转天数（反映应收账款回收速度与资金占用情况）
*   `days_inventory`: 存货周转天数（反映产品变现及库存积压风险）

> ⚠️ **注意**：`days_payable`（应付账款周转天数）因 AkShare 数据源无法提供该字段，已从后续清洗与导出流程中完全移除。下游模型/规则不应依赖该指标。

### 2. 爬取阶段产出的文件及内容
爬虫脚本执行后，会将原始数据以**单只股票独立文件**的形式保存至以下物理目录：

*   **存储路径**：`./data_center/financial/`
*   **产出文件结构**：
    ```text
    data_center/financial/
    ├── balance/{symbol}.parquet       # 单股资产负债表历史明细
    ├── profit/{symbol}.parquet        # 单股利润表历史明细
    ├── cashflow/{symbol}.parquet      # 单股现金流量表历史明细
    └── turnover/{symbol}.parquet      # 单股营运周转天数明细（不含 days_payable）
    ```

---

## 二、 财务数据处理与高频对齐全流程

由于财务数据是**季频**的（每个季度发布一次），而量化回测或机器学习模型通常需要**日频**特征，且需要严格防止未来函数并剔除问题公司，因此需要执行专项清洗与对齐流水线。

### 1. 全市场面板组装与清洗步骤
在将单股数据转化为全市场统一的面板数据（Panel Data）前，需经过以下清洗步骤：
1. **单股基础清洗**：
   * 统一时间格式：将 `report_date` 和 `announce_date` 转换为标准 Datetime 类型。
   * 去重与排序：按 `report_date` 排序去重，确保每个股票在同一报告期仅保留一条有效记录。
   * 类型强转：将各项财务指标通过 `pd.to_numeric` 转换为浮点数类型（`np.float64`），异常文本或空值转为 `NaN`。
2. **多维大宽表合并**：
   * 将全市场所有股票的四大表数据按 `code` 和 `report_date` 纵向拼接，并横向整合，生成包含全市场、全历史报告期的长表或面板数据。
   * 产出组装前的核心清洗面板文件：`all_stocks_financial_panel.parquet`（存储在 `./data_center/financial/` 目录下）。
3. **衍生因子计算**：
   * 计算 **营业收入同比增长率**（`income_yoy`）和 **净利润同比增长率**（`netprofit_yoy`）。
4. **行业中性化（仅对部分指标）**：
   * 对以下 4 个指标进行行业中性化处理，生成对应的 `_neutral` 版本：
     - `days_receivable` → `days_receivable_neutral`
     - `days_inventory` → `days_inventory_neutral`
     - `income_yoy` → `income_yoy_neutral`
     - `netprofit_yoy` → `netprofit_yoy_neutral`

### 2. 高频对齐与掩码过滤步骤
1. **日频主时间轴对齐（Point-in-Time）**：
   * 读取日度行情生成的标准交易日历（`master_calendar`）。
   * 通过前向填充（`ffill`），将季频财报平滑扩展到每一个交易日。**确保在下一季财报正式公告日前，每一天获取的都是当时“最新可用”的财报，彻底根除未来函数。**
2. **多源联动掩码过滤（过滤问题公司）**：
   * 读取日度行情的有效交易掩码（`target_mask`）。
   * 对停牌/退市日期，将财务数据填充为 `0.0`（作为中性基准值），而非置为 `NaN`。这样既保留了财务数据的连续性，又不会让模型将停牌日误判为正常交易日。

### 3. 处理阶段产出的文件及内容
经过独立清洗与对齐脚本处理后，最终在 `./data_center/processed_financial/` 目录下产出以下高频特征资产：

*   **存储路径**：`./data_center/processed_financial/`
*   **产出文件结构与详细内容**：
    ```text
    data_center/processed_financial/
    ├── fin_feature_{指标名}.parquet        # 【最终高频对齐因子宽表】如 fin_feature_roe.parquet, fin_feature_total_assets.parquet 等
    └── fin_feature_names.json              # 【辅助元数据清单】记录了所有成功转换并输出的财务因子名称列表
    ```
*   **最终 `fin_feature_{指标名}.parquet` 宽表内容说明**：
    *   **行索引（Index）**：全市场日度交易日历（`master_calendar`）。
    *   **列名（Columns）**：全市场股票代码列表（`target_stocks`）。
    *   **单元格值**：经过 `ffill` 扩展并应用掩码（停牌日填充 0）后的高频对齐数值，可直接与日度技术因子进行矩阵运算。

### 4. 数据质量总结
- **优势**：
  - 核心基本面指标（净利润、ROE、资产负债率）缺失率极低（<4%），可直接用于量化建模。
  - 数据严格避免了未来函数（公告日前保持旧财报，公告日跳变生效）。
  - 所有日期对齐处理均已完成，`days_receivable`、`days_inventory`、`income_yoy`、`netprofit_yoy` 四个指标已提供行业中性化版本（`*_neutral`）。
- **注意事项**：
  - 对于缺失值，**未做任何填充**，完全保留原始 `NaN`（停牌日被填充为 0 除外）。
  - **已剔除 `days_payable`（应付账款周转天数）**，因 AkShare 数据源无法提供该字段，所有相关代码和导出文件均不含此列。
  - 已剔除冗余的高缺失率特征（`ebittointerest`），避免干扰模型。
```
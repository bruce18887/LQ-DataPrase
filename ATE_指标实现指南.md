# ATE 量产测试指标 — 项目实现指南

> 本文基于 [ATE_量产测试关键指标.md](./ATE_量产测试关键指标.md)，对照 DataPhrase 项目现有架构，**逐项**映射实现状态。
> 标注：✅ 已完成（含注释 comment） / ⚠️ 部分完成 / 📝 待实现 / 🚫 不可实现

---

## 项目架构速览

| 层级 | 技术 | 关键路径 |
|------|------|---------|
| **后端 API** | Django 6.0 + DRF ViewSet | `apps/analysis/views.py` → `services/statistics.py` |
| **前端页面** | Vue 3 + TS + ECharts + AgGrid | `pages/analysis/AnalysisPage.vue` → `api/analysis.ts` |
| **状态管理** | Pinia (Composition API) | `stores/analysis.ts` |
| **数据处理** | Celery 异步解析 → Pandas DataFrame | `apps/datafiles/parsers/*` |
| **文件存储** | 本地 media/ + SQLite/PostgreSQL | `apps/datafiles/models.py DataFile` |

---

## 一、良率类指标（Yield Metrics）

> 良率是量产测试中最核心、最受关注的指标，直接决定产品盈利能力和生产效益。

### 1.1 CP Yield（晶圆良率）

| 指标 | 公式 | 说明 | 实现状态 | 实现位置 / 备注 |
|------|------|------|---------|----------------|
| **Die Yield** | `(Good Dies / Total Dies) × 100%` | 单颗晶圆上通过 CP 测试的好芯片占比 | ✅ 完成 | `apps/dashboard/views.py:DashboardSummaryView` L70 — `yield_pct = pass_count / total_rows` |
| **Wafer Yield** | `(Good Wafers / Total Wafers) × 100%` | 生产线良率，反映工艺控制稳定性 | ⚠️ 部分完成 | 当前 `DashboardSummaryView` 按单文件计算良率，等价于单 Wafer。多 Wafer 跨文件聚合尚未独立实现 |
| **Lot Yield** | `(Good Lots / Total Lots) × 100%` | 批次级别的良率统计 | 📝 **Todo** | 现有 `multi_lot` API 只做直方图叠加，未按 Lot 聚合亮率。需新增 `services/yield_analysis.py:aggregate_lot_yield()` |

**分析要点对照：**

| 分析要点 | 实现状态 | 说明 |
|---------|---------|------|
| CP Yield 是晶圆级的第一道筛选，直接影响无效成本浪费 | ✅ comment | 前端 Dashboard 首屏展示 |
| 成熟工艺的 CP Yield 目标通常 ≥ 95% | ✅ comment | 前端可设目标参考线（Target Line） — 当前 `ChartConfigPanel` 未实现此配置 |
| 低良率需要结合 Bin Map 定位是否为系统性问题或随机性问题 | ⚠️ 部分完成 | Bin Map ✅，系统性/随机性**自动判定**逻辑未实现 |

### 1.2 FT Yield（最终测试良率）

| 指标 | 公式 | 说明 | 实现状态 | 实现位置 / 备注 |
|------|------|------|---------|----------------|
| **FT Yield** | `(Pass Chips / Total Tested Chips) × 100%` | 成品测试的通过率 | ✅ 完成（隐含） | 项目未区分 CP/FT，同一套 parser 和 dashboard 逻辑通用。当前 `DashboardSummaryView.yield_pct` 等价于 FT Yield |

**分析要点对照：**

| 分析要点 | 实现状态 | 说明 |
|---------|---------|------|
| FT Yield 是出货前最后一道质量关口 | ✅ comment | 前端展示 |
| 成熟产品 FT Yield 目标 ≥ 98% | ✅ comment | 前端可设目标参考线 — 当前未实现 |
| FT Yield 明显低于 CP Yield 时，说明成品阶段存在问题 | ⚠️ 部分完成 | 需多文件对比功能：同一批 Die 的 CP 与 FT 良率差值分析 — `multi_lot` 接口未支持此场景 |

### 1.3 First Pass Yield (FPY) — 首次通过率

| 指标 | 公式 | 说明 | 实现状态 | 实现位置 / 备注 |
|------|------|------|---------|----------------|
| **FPY** | `(首次测试通过数 / 总测试数) × 100%` | 不经过重测/返修首次即通过的比率 | ✅ 完成（隐含） | `DashboardSummaryView` 的 `yield_pct` 本质上等同于 FPY（解析器按单次测试结果计算）。**严格 FPY 需区分 Retest 记录** — 当前数据文件不含 Retest 标志列，需在后续解析器升级中增加 `RESULT_FLAG` 识别 |

**行业基准对照（仅供参考，非实现项）：**

| 行业 | 典型 FPY | 世界级 FPY | 实现状态 | 说明 |
|------|---------|-----------|---------|------|
| 消费电子 | 95-98% | > 99% | ✅ comment | 前端可配置目标线 |
| 汽车电子 | 97-99% | > 99.5% | ✅ comment | 同上 |
| 医疗设备 | 90-95% | > 98% | ✅ comment | 同上 |
| 航天/军工 | 85-95% | > 97% | ✅ comment | 同上 |

**分析要点对照：**

| 分析要点 | 实现状态 | 说明 |
|---------|---------|------|
| FPY 是所有测试效率指标中最重要的一个 | ✅ comment | Dashboard 首屏突出展示 |
| 低 FPY 意味着大量重测成本与产能浪费 | ✅ comment | 辅助说明文案 |
| 对于多站测试流程，应计算 RTY = 各站 FPY 的乘积 | 📝 **Todo** | 需定义多站流程模型（见 1.4） |

### 1.4 Rolled Throughput Yield (RTY)

| 指标 | 公式 | 说明 | 实现状态 | 实现位置 / 备注 |
|------|------|------|---------|----------------|
| **RTY** | `FPY₁ × FPY₂ × ... × FPYₙ` | 多站累积首次通过率 | 📝 **Todo** | 需 `services/flow_yield.py:compute_rty()`。例如 5 个站点各 98% FPY → RTY ≈ 90.4% |

**依赖前提：**
- 需要数据中能区分测试站点（Station / Step），当前解析器仅按文件粒度处理
- 需要用户在文件上传时能标注"第 N 站"

---

## 二、良率损失与趋势分析指标

### 2.1 Yield Excursion / Crash（良率漂移/崩盘）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 产品良率突然或持续偏离正常基线（Baseline） | 📝 **Todo** | 需建立基线：取前 N 个 Lot 的平均良率作为基准 |
| Fab 里最紧急的警报，一旦发生需要立即成立跨部门作战小组 | ✅ comment | 前端可显示提示级别，但**自动报警通知**属 🚫 不可实现（见不可实现报告） |
| 通过良率趋势图监控逐批/逐日良率波动 | 📝 **Todo** | 见 2.2 |

### 2.2 Yield Trend（良率趋势）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 按时间序列绘制 Lot/Wafer 的 Yield 折线图 | 📝 **Todo** | 需新增 `analysis:yield_trend` 接口，按 `uploaded_at` 聚合各文件良率 |
| 关注**渐进式下降**（工艺退化）vs **突变式下跌**（设备故障/误操作） | 📝 **Todo** | 需在趋势图上标注两种模式：连续 N 点下降 vs 单点大幅偏离 |
| 使用 SPC 方法设定控制上限/下限（UCL/LCL） | 📝 **Todo** | 需在 `services/statistics.py` 新增 `compute_spc_limits()`（均值 ± 3σ），并在趋势图上绘制控制线 |

### 2.3 Yield By Zone（分区良率）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 将 Wafer 划分为中心区、中间环、边缘区 | 📝 **Todo** | 需在 `services/statistics.py` 新增 `compute_zonal_yield()`：按 die 坐标 `(x, y)` 到 Wafer 中心的距离划分三区 |
| 分析不同区域良率差异，识别工艺均匀性问题 | 📝 **Todo** | 返回三区各自良率 + 差异百分比，前端展示分区统计 |
| CMP 不均匀、光刻聚焦偏差 | ✅ comment | 分析结果中的文字提示 |
| 边缘区域良率偏低通常是光刻/刻蚀问题 | ✅ comment | 分析结果中的文字提示 |
| 前端 Wafer Map 分区高亮 | 📝 **Todo** | `WaferMapPanel.vue` 需新增分区着色模式 |

---

## 三、参数分布与过程能力指标（Parametric & Capability Metrics）

### 3.1 CPK / PPK（过程能力指数）

| 指标 | 公式 | 判定标准 | 实现状态 | 实现位置 / 备注 |
|------|------|---------|---------|----------------|
| **Cp** | `(USL - LSL) / 6σ` | Cp ≥ 1.33 良好，Cp ≥ 1.67 优秀 | 📝 **Todo** | 当前 `compute_cpk` 只返回 Cpk，未单独返回 Cp。需扩展该函数 |
| **Cpk** | `min(USL - μ, μ - LSL) / 3σ` | Cpk ≥ 1.33 达标，Cpk ≥ 1.67 优秀 | ✅ 完成 | `services/statistics.py:compute_cpk()` L205-219 |
| **Pp** | 同 Cp 但使用总标准差 | 反映长期过程表现 | 📝 **Todo** | 需扩展函数，增加 `use_overall_std` 参数 |
| **Ppk** | 同 Cpk 但使用总标准差 | 反映长期过程表现 | 📝 **Todo** | 同上 |

**分析要点对照：**

| 分析要点 | 实现状态 | 说明 |
|---------|---------|------|
| Cpk < 1.0：过程变异超出规格，间歇性失效 | ⚠️ 部分完成 | `compute_cpk` 返回 `cpk_level`（'poor' / 'marginal' / 'good' / 'excellent'），但等级边界代码中未对照 ≤1.0 阈值 |
| Cpk 1.0 ~ 1.33：过程能力尚可，需监控 | ⚠️ 部分完成 | 同上，需确认 Cpk 等级映射逻辑 |
| Cpk ≥ 1.33：过程能力健康 | ⚠️ 部分完成 | 同上 |
| 汽车芯片要求 Cpk ≥ 1.67 | ✅ comment | 前端 Cpk 标识可配置行业阈值 |
| Cpk 高不一定代表数据真实，需警惕数据被软件截断 | 📝 **Todo** | 需在 `compute_range_statistics` 中增加**截断检测**：检查参数值是否在规格限边界处出现堆积（如 >5V 全写 5V） |

### 3.2 参数分布统计

| 指标 | 说明 | 实现状态 | 实现位置 / 备注 |
|------|------|---------|----------------|
| **均值 (Mean)** | 参数平均值，判断是否偏离目标值 | ✅ 完成 | `compute_range_statistics()` |
| **标准差 (Std Dev / σ)** | 参数离散程度，越小越好 | ✅ 完成 | 同上 |
| **Vt Spread** | 阈值电压的标准差，衡量 Die 间一致性 | ⚠️ 部分完成 | `compute_range_statistics` 可计算任意参数 σ，但未对 Vt 做专项指标突出展示 |
| **Range (Max - Min)** | 参数范围，识别离群点 | ✅ 完成 | `compute_range_statistics` 返回 min/max |

**分析方法对照：**

| 分析方法 | 实现状态 | 说明 |
|---------|---------|------|
| **直方图**：检查正态分布（-3σ ~ 3σ） | ✅ 完成 | `HistogramChart.vue` + `analysis:histogram` |
| 非正态分布可能原因：测试异常、设备问题、工艺波动、批次混料 | ✅ comment | 前端直方图页面可显示提示文字 |
| **箱线图**：对比多组数据的分散性和离群点 | 📝 **Todo** | 需后端 `analysis:boxplot` + 前端 `BoxPlotChart.vue` |
| **散点图**：两测试项关联性检查 | ✅ 完成 | `CorrelationPanel.vue` + `analysis:correlation` |

### 3.3 Guardband（保护带/裕量分析）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 在规格限内部设置更紧的测试限，补偿测试系统误差 | ✅ 完成 | `analysis:histogram`、`analysis:serial_distribution`、`analysis:site_stats` 均支持 `range_type`（RDL/DR/CL/S3/S4/S6）参数切换 |
| 关键参数通常保留 10-20% 的裕量 | 📝 **Todo** | 需 `services/guardband.py:compute_guardband_margin()`：对每个参数计算 (测试限 - 规格限) / 规格限范围 × 100% |
| 裕量过小 → 误杀良品过多 | 📝 **Todo** | 同上报告，标注 < 5% 裕量的参数为"高风险" |
| 裕量过大 → 不良品漏检风险 | 📝 **Todo** | 同上报告，标注 > 30% 裕量的参数为"过度保护" |

---

## 四、分 Bin 分析指标（Binning Metrics）

> 分 Bin 方案由**测试程序（Test Program）**定义，每个 Bin 的含义、判据、优先级均在程序中设定。量产数据分析直接以程序输出的 Bin 结果为准，无需在分析端重新定义。

### 4.1 Bin Count & Bin Ratio（分 Bin 计数与比例）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| Bin 1 良品（全规格通过） | ✅ 完成 | `analysis:bin_stats` + 前端 Bin Pie Chart |
| Bin 2 降级品（放宽规格通过） | ✅ 完成 | `bin_stats` 返回所有 Bin 计数和百分比 |
| Bin 3 功能失效 | ✅ 完成 | 同上 |
| Bin 4 参数失效 | ✅ 完成 | 同上 |
| Bin 5 接触/开路失效 | ✅ 完成 | 同上 |
| Bin 6 漏电流失效 | ✅ 完成 | 同上 |
| ... 更多分类，根据产品自定义 | ✅ comment | Bin 分类由程序定义，数据分析系统只做统计 |

### 4.2 Bin Pareto（分 Bin 帕累托分析）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 按失效 Bin 数量/比例从高到低排序 | ⚠️ 部分完成 | `calculate_fail_bin_statistics` 有 `sort_index`，但未返回**累积百分比** |
| **80/20 法则**：约 80% 的失效来自前 2-3 个 Failing Bin | 📝 **Todo** | 需前端 `ParetoChart.vue`：柱状图按降序 + 累积折线叠加 + 80% 参考线标注 |
| 聚焦 Top Failing Bin 进行根因分析 | 📝 **Todo** | Pareto 图自动高亮前 3 个 Bin |
| 跟踪前三大失效 Bin 占比的**变化趋势** | 📝 **Todo** | 需将 Bin Pareto 接入趋势分析（见 §7.1 Bin Trend Chart） |

### 4.3 Bin Map（晶圆 Bin 分布图）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 用颜色编码在 Wafer 上标注每个 Die 的 Bin 结果 | ✅ 完成 | `WaferMapPanel.vue` 按 bin 着色 |
| **团簇缺陷**识别（局部工艺问题） | 📝 **Todo** | 当前只做可视化展示，**自动识别团簇模式**需空间聚类算法 — 属 🚫 不可实现（见不可实现报告） |
| **边缘集中失效**识别（光刻/刻蚀问题） | 📝 **Todo** | 需 `services/wafer_spatial.py:detect_edge_concentration()`：统计边缘区 vs 中心区失效比例差异 |
| **系统性重复失效**识别（光罩问题） | 📝 **Todo** | 需跨 Die 位置的周期性模式检测 |
| **随机散落失效**识别（颗粒污染） | ⚠️ 部分完成 | 可视化可观察到，但无自动标注 |

### 4.4 Parametric Map（参数分布图）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 用颜色渐变显示连续参数值在 Wafer 上的分布 | ✅ 完成 | `analysis:wafer_map` 支持 `param` 参数，`WaferMapPanel.vue` 颜色渐变 |
| 识别空间模式：一角电流偏高、中心区域电压偏低 | ⚠️ 部分完成 | 可视化可观察，但无自动空间异常检测 |
| 定位设备腔体均匀性问题和工艺偏移 | ✅ comment | 人工观察分析辅助 |

---

## 五、测试效率指标（Test Efficiency Metrics）

### 5.1 Test Time（测试时间）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| `测试成本 = (ATE 机时费率 × Test Time) / 单次测试芯片数` | ⚠️ 部分完成 | Test Time 已在解析器提取（metadata），但**ATE 机时费率**属 🚫 不可实现（见不可实现报告） |
| 测试时间每增加 1 秒，量产成本可能增加数百万美元 | ✅ comment | 前端可展示成本估算说明 |
| ATE 测试成本约占芯片总成本的 5-8% | ✅ comment | 同上 |
| **多站点并行测试**：同时测试多颗 Die | ⚠️ 部分完成 | Site 信息已解析，但未计算"并行效率"指标（见 5.3） |
| **测试项裁剪**：基于 CPK 分析剔除冗余测试项 | 🚫 **不可实现** | 测试项裁剪需修改 ATE 测试程序本身，非数据分析系统范畴。可由系统输出"CPK 长期稳定项"报告辅助决策 |
| **向量压缩优化** | 🚫 **不可实现** | 测试向量压缩属于 ATE 编程/DFT 工程，完全不在本系统能力范围内 |

### 5.2 UPH（Unit Per Hour，每小时产出）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| `UPH = 3600 / (Test Time per Unit + Handler/Prober Index Time)` | 📝 **Todo** | 需 `services/efficiency.py:compute_uph()`。Test Time 已有，但 **Handler/Prober Index Time** 不在 ATE 数据文件中 — 需用户手动输入或从设备日志获取 |
| 反映产线综合产出效率 | 📝 **Todo** | UPH 计算后前端展示 |
| 受测试时间、机台取放速度、多站点并行数共同影响 | 📝 **Todo** | 多因素关联分析需 `multi_site` × `test_time` 联合统计 |

### 5.3 Multi-site Efficiency（多站点效率）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| `Multi-site Efficiency = (实际并行效率 / 理论最大值) × 100%` | 📝 **Todo** | 需 `services/efficiency.py:compute_site_efficiency()`：各 Site 良率均衡性 / 总测试时间理论最优值 |
| 并行测试存在信号串扰、热管理等问题 | ✅ comment | 分析结果说明 |
| 目标：32 站点并行下效率 ≥ 85% | ✅ comment | 前端基准线 |

### 5.4 Equipment Utilization（设备利用率）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| **Availability**：设备可用时间占比 | 🚫 **不可实现** | 需要设备运行日志/状态机数据，ATE 数据文件不含此类信息（见不可实现报告） |
| **OEE** = Availability × Performance × Quality | 🚫 **不可实现** | 同 Availability 原因 |
| **MTTR（平均修复时间）**：故障响应 ≤ 1h，修复 ≤ 30min | 🚫 **不可实现** | 需要设备维修工单系统数据 |
| **SMED（快速换型时间）**：换型时间 ≤ 2h | 🚫 **不可实现** | 需要生产线 MES 系统数据 |

---

## 六、测试系统一致性指标（Test System Consistency Metrics）

### 6.1 GR&R（量具重复性与再现性）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| **重复性（Repeatability）**：同一测试机多次测试同一芯片的结果一致性 | 📝 **Todo** | 需 `services/grr.py`：计算每个参数在多次测量中的 σ_repeatability。前提：需要"同一芯片多次测试"的数据，即 Retest 数据或多 Loop 数据 |
| **再现性（Reproducibility）**：不同测试机/不同操作员测试同一芯片的结果一致性 | 📝 **Todo** | 需 `services/grr.py`：跨机台/跨文件同参数的 σ_reproducibility |
| 行业标准：GR&R ≤ 10% 优秀，10-30% 可接受，> 30% 不可接受 | ✅ comment | 结果分级标注 |
| **依赖前提** | 📝 注意 | 严格 GR&R 要求"同一颗芯片在不同条件下重复测试"，这在量产数据中很少见。量产数据场景下，应改用**单机台统计稳定性**替代重复性，用**机台间同 Lot 参数偏差**替代再现性 |

### 6.2 Correlation（机台间相关性）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 比较不同 ATE 测试机对同一批芯片的测试结果 | 📝 **Todo** | 需扩展 `multi_lot` 接口：按 tester 分组后做同参数交叉散点图 |
| 关键参数的相关性斜率应接近 1，R² ≥ 0.99 | 📝 **Todo** | 需在 `CorrelationPanel.vue` 中叠加回归线 + 方程标注 |
| 定期（每周/每月）执行 Golden Sample 比对 | 📝 **Todo** | Golden Sample（金样）是物理芯片，需 `apps/golden_sample/` 模型记录其基准值和漂移历史 |

### 6.3 Tester-to-Tester Variation（机台间偏差）

| 指标原文要点 | 实现状态 | 说明 |
|-------------|---------|------|
| 同一产品在多台 ATE 上测试时，参数的均值偏移量 | 📝 **Todo** | 需扩展 `multi_lot` 接口：按 tester/equipment_id 分组，返回各参数 mean 差异表 |
| 偏差过大需排查：Load Board、Socket、校准参数、测试程序差异 | ✅ comment | 分析结果说明文字 |

---

## 七、数据分析方法与可视化工具

### 7.1 趋势分析

| 图表类型 | 用途 | 实现状态 | 说明 |
|---------|------|---------|------|
| **Yield Trend Chart** | 逐 Lot/日/周良率趋势，发现漂移或突变 | 📝 **Todo** | 需后端 `analysis:yield_trend` + 前端 `YieldTrendChart.vue` |
| **Bin Trend Chart** | 各 Bin 比例随时间变化，发现失效模式转移 | 📝 **Todo** | 需后端 `analysis:bin_trend`（按时间聚合各 Bin%） + 前端堆叠面积图或折线图 |
| **Parameter Trend Chart** | 关键参数均值/标准差的日趋势 — "数据体温表" | 📝 **Todo** | 需后端 `analysis:param_trend` + 前端 `ParamTrendChart.vue` |

### 7.2 分布分析

| 图表类型 | 用途 | 实现状态 | 说明 |
|---------|------|---------|------|
| **直方图** | 判断参数是否正态分布，识别双峰/截断/拖尾 | ✅ 完成 | `HistogramChart.vue` + `analysis:histogram` |
| **箱线图** | 对比多组数据（不同机台/不同批次）的分散性 | 📝 **Todo** | 需后端 `analysis:boxplot` + 前端 `BoxPlotChart.vue` |
| **概率图（QQ Plot）** | 验证正态性假设 | 📝 **Todo** | 需后端新增 `scipy.stats.probplot` 调用 + 前端 `QQPlotChart.vue` |

### 7.3 关联分析

| 图表类型 | 用途 | 实现状态 | 说明 |
|---------|------|---------|------|
| **散点图矩阵** | 检查多个参数之间的关联性是否异常 | ⚠️ 部分完成 | `CorrelationPanel.vue` 仅支持两参数；`CorrelationMatrixPanel.vue` 前端存在但后端无批量相关系数矩阵 API |
| **相关性热力图** | 量化参数间相关系数，发现异常耦合 | 📝 **Todo** | 需后端 `analysis:correlation_matrix` action，返回 N×N 相关系数矩阵，前端渲染为热力图 |

### 7.4 空间分析

| 图表类型 | 用途 | 实现状态 | 说明 |
|---------|------|---------|------|
| **Bin Map** | 晶圆上 Bin 分布可视化 | ✅ 完成 | `WaferMapPanel.vue` 按 Bin 着色 |
| **Parametric Map** | 参数值的晶圆空间分布 | ✅ 完成 | `analysis:wafer_map` 支持 `param` 着色 |

### 7.5 失效分析

| 图表类型 | 用途 | 实现状态 | 说明 |
|---------|------|---------|------|
| **Pareto 图** | 按失效 Bin/失效项排序，聚焦 Top 问题 | ⚠️ 部分完成 | `dashboard` 返回 `fail_test_items`（排序后列表），前端仅渲染为表格，未做 Pareto 柱+折线图 |
| **鱼骨图** | 根因分析，定位失效的根本原因 | 🚫 **不可实现** | 鱼骨图是人工团队讨论工具，自动生成需要 LLM 因果推理（见不可实现报告） |
| **Why-Why 分析** | 逐层深入，找到根本对策 | 🚫 **不可实现** | 同上，需 AI 根因分析能力 |

---

## 八、各环节核心指标汇总

### CP 测试 — 当前覆盖度

| 优先级 | 指标 | 目标监控频率 | 实现状态 | 当前实现 / 缺口 |
|-------|------|------------|---------|---------------|
| 1 | CP Yield | 每片 Wafer | ✅ 完成 | `DashboardSummaryView` — 可切换文件即实时计算 |
| 2 | Bin Map + Bin Pareto | 每片 Wafer | ⚠️ 部分完成 | Bin Map ✅ / Pareto 前端图 📝 — `fail_test_items` 表已排序但无累积折线 |
| 3 | Vt / Idsat 等参数 Cpk | 每 Lot | ✅ 完成 | `analysis:cpk` + `analysis:histogram` |
| 4 | Yield By Zone | 每 Lot | 📝 **Todo** | 需 `compute_zonal_yield()` |

### FT 测试 — 当前覆盖度

| 优先级 | 指标 | 目标监控频率 | 实现状态 | 当前实现 / 缺口 |
|-------|------|------------|---------|---------------|
| 1 | FT Yield | 每批 | ✅ 完成 | 同 CP Yield 逻辑 |
| 2 | FPY / RTY | 每批 | ⚠️ 部分完成 | FPY ✅ / RTY 📝 — 需多站流程模型 |
| 3 | 参数分布 + Cpk | 每 Lot | ✅ 完成 | `analysis:histogram` + `analysis:cpk` |
| 4 | GR&R / Correlation | 每月 | ⚠️ 部分完成 | 参数相关性 ✅ / GR&R 📝 |

---

## 九、常见陷阱与注意事项（指标文档第 9 节）

> 以下为指标文档列出的"常见陷阱"，逐条评估系统可提供的辅助检查能力。

| 陷阱 | 说明 | 实现状态 | 系统实现方式 |
|------|------|---------|------------|
| **Cpk 虚高** | 测试软件截断了超限数据（如 >5V 记录为 5V），Cpk 虚高但不代表良率高 | 📝 **Todo** | `compute_range_statistics` 需增加**边界堆积检测**：检查 ≤USL_min 和 ≥USL_max 的值是否异常集中 |
| **环境因素忽略** | 湿度/温度变化导致测试结果漂移，雨天测试失败需排查车间湿度 | 🚫 **不可实现** | 温湿度传感器数据不在 ATE 文件范畴。如需实现，需接入 IoT 系统 |
| **样本量不足** | 数据量过小得出的统计结论不可靠 | 📝 **Todo** | 后端各统计接口增加 `min_samples` 校验：< 30 条时在响应中标记 `confidence: 'low'` |
| **Gr&R 未定期验证** | 探针磨损、Socket 老化会导致测试结果漂移 | 📝 **Todo** | 系统可提供"上次 GR&R 分析距今天数"提示（在实现了 GR&R 分析后） |
| **只看总良率** | 总良率高但某个关键 Bin 比例上升，可能掩盖重大质量问题 | 📝 **Todo** | `dashboard` 增加 Bin Trend 对比: 总良率 vs 各 Bin 比例变化 |
| **忽略 Retest 影响** | Retest 通过率虚高 FPY，掩盖真实质量问题 | 📝 **Todo** | 解析器需增加 Retest 列识别。当前解析器直接以最终测试结果为准，无法区分重测 |
| **Golden Sample 未更新** | 金样本身已漂移，比对失去意义 | 📝 **Todo** | 需 `GoldenSample` 模型记录基准值 + 最近校验日 + 漂移趋势告警 |

---

## 十、公式实现状态对照

| 公式 | 实现状态 | 说明 |
|------|---------|------|
| `CP Yield = (Good Dies / Total Dies) × 100%` | ✅ 完成 | `DashboardSummaryView` |
| `FT Yield = (Pass Units / Total Units) × 100%` | ✅ 完成 | 同上 |
| `FPY = (Pass on First Try / Total) × 100%` | ✅ 完成 | 同上（有待 Retest 识别增强） |
| `RTY = FPY₁ × FPY₂ × ... × FPYₙ` | 📝 **Todo** | `services/flow_yield.py` |
| `Cpk = min((USL - μ) / 3σ, (μ - LSL) / 3σ)` | ✅ 完成 | `compute_cpk()` |
| `Cp = (USL - LSL) / 6σ` | 📝 **Todo** | 需扩展 `compute_cpk()` 返回 Cp |
| `Pp / Ppk` | 📝 **Todo** | 需扩展函数，增加 `use_overall_std` 参数 |
| `UPH = 3600 / (Test Time + Index Time)` | 📝 **Todo** | `services/efficiency.py` |
| `GR&R % = (Measurement Error / Total Variation) × 100%` | 📝 **Todo** | `services/grr.py` |

---

## 十一、TODO 优先级计划（完整版）

### P0 — 当前轮次应完成（与现有架构紧密耦合，低风险）

| 编号 | 任务 | 涉及文件 | 对应指标文档 |
|------|------|---------|------------|
| TODO-01 | **相关性矩阵批量 API** `analysis:correlation_matrix` | `apps/analysis/views.py` | §3.2 / §7.3 |
| TODO-02 | 前端 **ParetoChart.vue**（柱状图 + 累积折线 + 80% 参考线） | `frontend/src/pages/analysis/components/ParetoChart.vue` | §4.2 / §7.5 |
| TODO-03 | 前端 **箱线图 BoxPlotChart.vue** + 后端 `analysis:boxplot` | `frontend/src/components/charts/BoxPlotChart.vue`, `apps/analysis/views.py` | §3.2 / §7.2 |
| TODO-04 | **参数趋势图** `analysis:param_trend` + `ParamTrendChart.vue` | `apps/analysis/views.py`, `services/statistics.py`, 前端 | §7.1 |
| TODO-05 | Cpk 计算扩展：返回 **Cp + Pp + Ppk** | `services/statistics.py:compute_cpk()` | §3.1 |
| TODO-06 | **Bin 趋势 API** `analysis:bin_trend` | `apps/analysis/views.py` | §7.1 |

### P1 — 紧接轮次完成

| 编号 | 任务 | 涉及文件 | 对应指标文档 |
|------|------|---------|------------|
| TODO-07 | **Yield Trend 良率趋势** `analysis:yield_trend` + SPC 控制限 | `apps/analysis/views.py`, `services/statistics.py` | §2.1 / §2.2 |
| TODO-08 | 前端 **YieldTrendChart.vue**（折线图 + UCL/LCL 控制线） | `frontend/src/pages/dashboard/` | §2.2 |
| TODO-09 | **Yield By Zone** 分区良率 `compute_zonal_yield()` | `services/statistics.py` | §2.3 |
| TODO-10 | 前端 **Wafer Map 分区高亮/分区统计** | `WaferMapPanel.vue` | §2.3 |
| TODO-11 | 前端 **QQ Plot 组件** `QQPlotChart.vue` + 后端 `analysis:qqplot` | 前端 + `apps/analysis/views.py` | §3.2 / §7.2 |
| TODO-12 | **多 Lot 良率对比**（扩展 `multi_lot`） | `apps/analysis/views.py` | §1.2 |
| TODO-13 | **UPH 计算** `services/efficiency.py:compute_uph()` | `apps/analysis/services/efficiency.py` | §5.2 |

### P2 — 后续迭代

| 编号 | 任务 | 涉及文件 | 对应指标文档 |
|------|------|---------|------------|
| TODO-14 | **GR&R 分析模块** `services/grr.py` | `apps/analysis/services/grr.py` | §6.1 |
| TODO-15 | **Golden Sample 管理** 模型 + 基准值 + 漂移记录 | `apps/golden_sample/` | §6.2 / 陷阱 |
| TODO-16 | **裕量分析报告** `services/guardband.py` — 计算各参数测试限与规格限之间的裕量 | `apps/analysis/services/guardband.py` | §3.3 |
| TODO-17 | **RTY 累积良率** 多站流程模型 + 计算 | `apps/analysis/services/flow_yield.py` | §1.4 |
| TODO-18 | **Box-Cox 正态性变换** 扩展 `compute_range_statistics` | `services/statistics.py` | §3.2 |
| TODO-19 | **Multi-site 效率指数** `services/efficiency.py` | `apps/analysis/services/efficiency.py` | §5.3 |
| TODO-20 | **Cpk 数据截断/边界堆积检测** | `services/statistics.py` | §3.1 / 陷阱 |
| TODO-21 | **机台间相关性/偏差分析** 跨文件 `cross_tester` action | `apps/analysis/views.py` | §6.2 / §6.3 |
| TODO-22 | **样本量不足提醒** 所有统计接口 < 30 条标记 `confidence: low` | `apps/analysis/views.py` 多个 | 陷阱 |
| TODO-23 | **Bin Trend 趋势** + 总良率 vs Bin 占比变化对比 | `apps/analysis/views.py` | §4.2 / 陷阱 |
| TODO-24 | **Retest 列识别** 解析器增强 | `apps/datafiles/parsers/` | 陷阱 |
| TODO-25 | **边缘集中失效检测** `detect_edge_concentration()` | `services/statistics.py` | §4.3 |
| TODO-26 | **目标线/Target Line 配置** 前端 ChartConfigPanel 增加可配置阈值 | `ChartConfigPanel.vue` | §1 多处 |

---
---

# 🚫 不可实现报告

> 以下为指标文档中提到的功能/指标，在当前 DataPhrase 项目架构下**客观上无法实现**或**实现代价远超系统边界**。每项均说明了不可实现的原因和可能的替代方案。

---

## 🚫-1 鱼骨图（Ishikawa Diagram）自动生成

**来源：** §7.5 失效分析 > 鱼骨图

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 对失效根因进行鱼骨图分析，定位人机料法环五大因素 |
| **为什么不可实现** | 鱼骨图是人工团队讨论和领域经验驱动的分析工具。自动生成需要：（1）理解该批次的生产上下文（谁操作、哪台设备、哪个工艺配方）；（2）具备半导体失效机理因果推理能力（即 LLM 级别的领域 AI）。当前系统只做统计计算和可视化，不具备因果推理能力 |
| **替代方案** | 系统输出 **Pareto 分析** + **各维度统计对比**（按 Site/按 Batch/按时间/按参数），为工程师的人工鱼骨图分析提供数据输入，但不代替分析过程 |

---

## 🚫-2 Why-Why 分析自动生成

**来源：** §7.5 失效分析 > Why-Why 分析

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 逐层深入追问"为什么"，找到根本对策 |
| **为什么不可实现** | 与鱼骨图同理。Why-Why 是对话式的追问过程（例如："为什么 Vt 偏高？→ 栅氧厚度偏薄 → 为什么偏薄？→ 氧化炉温度偏低 → …"），每个"为什么"的答案都需要工艺知识和现场排查，系统没有这些信息源 |
| **替代方案** | 可考虑在未来接入 **LLM 模块**（如 OpenAI API + RAG 半导体知识库），提供"Why-Why 辅助建议"。但这是 P3+ 的远期规划，当前不应列入开发计划 |

---

## 🚫-3 环境因素（温/湿度）关联分析

**来源：** §9 常见陷阱 > 环境因素忽略

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 湿度/温度变化导致测试结果漂移，雨天测试失败需排查车间湿度 |
| **为什么不可实现** | 温度、湿度传感器数据完全不在 ATE 测试数据文件中。ATE 文件只包含电性测试结果（电压/电流/频率等）。温度环境数据来自 Fab/车间 IoT 系统或 SCADA 系统，属于不同数据源 |
| **替代方案** | 如果未来接入车间 IoT 系统（如 MES/SCADA），可将温湿度数据作为独立维度导入，与测试数据进行**时间戳对齐 Join**。当前阶段在 UI 中仅做文字提醒："环境因素（温/湿度）可能影响测试结果，请核对生产记录" |

---

## 🚫-4 设备利用率（Availability / OEE / MTTR / SMED）

**来源：** §5.4 Equipment Utilization

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 设备可用时间占比（Availability）、OEE = A × P × Q、MTTR ≤ 1h、SMED ≤ 2h |
| **为什么不可实现** | 这些指标要求的数据源是：（1）设备运行/停机/维护日志 → 需要 MES 或 CIM 系统；（2）生产节拍和计划 → 需要 ERP/APS 系统；（3）维修工单和维修时间 → 需要 EAM/CMMS 系统。ATE 数据文件完全不包含这些信息 |
| **替代方案** | 系统可以在有了 Multi-site Efficiency 和 Test Time 数据后，输出"测试站利用率估算"（Test Time 占比）。但 Availability / OEE / MTTR / SMED 必须由生产管理系统（MES）提供，不属于 ATE 数据分析系统的范畴 |

---

## 🚫-5 ATE 机时费率与成本分析

**来源：** §5.1 Test Time > 测试成本公式

| 维度 | 说明 |
|------|------|
| **指标文档要求** | `测试成本 = (ATE 机时费率 × Test Time) / 单次测试芯片数` |
| **为什么不可实现** | ATE 机时费率是商业/采购/运营数据（每小时几百到上千美元不等，因设备型号和工厂而异），不属于 ATE 测试数据文件。与测试数据分析系统属于不同的数据域 |
| **替代方案** | 系统可以计算并展示 **Test Time**（已完成），并提供"成本估算器"让用户**手动输入**机时费率。系统只做 `Test Time × Rate / Site Count` 乘法，费率由用户自行管理 |

---

## 🚫-6 测试项裁剪决策（基于 CPK 自动去冗余测试项）

**来源：** §5.1 Test Time > 优化方向 > 基于 CPK 分析剔除冗余测试项

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 通过 CPK 分析找出长期稳定项，建议从测试程序中移除 |
| **为什么不可实现** | （1）测试程序的修改是 ATE 测试工程师的编程工作，涉及测试向量的增删和控制流程变更；（2）"冗余测试项"的判定不是纯统计问题 — CPK 高不代表该测试项可移除（可能是关键安全项）；（3）移除测试项有质量风险和客户稽核风险 |
| **替代方案** | 系统输出 **"长期 CPK 稳定项报告"**（CPK > 2.0 且连续 30+ Lot 无超限的参数列表），作为测试工程师的**辅助决策参考**。最终是否裁剪由工程师和 QA 共同决定 |

---

## 🚫-7 测试向量压缩优化

**来源：** §5.1 Test Time > 优化方向 > 向量压缩优化

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 优化测试向量以缩短测试时间 |
| **为什么不可实现** | 向量压缩是 DFT（可测性设计）+ ATE 测试编程的专业工程领域，涉及 ATPG 工具（如 TetraMAX）、扫描链重组、压缩比选择等。完全不在数据统计分析系统的能力范围内 |
| **替代方案** | 无。此项应标记为"超出系统边界" |

---

## 🚫-8 Golden Sample（金样）物理管理

**来源：** §6.2 Correlation > Golden Sample 比对 / §9 陷阱 > Golden Sample 未更新

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 金样本身的物理管理和漂移检测 |
| **为什么不可实现** | Golden Sample 是一颗或多颗**物理芯片**，存放在特定环境中。系统无法知道：（1）物理金样是否被调换或损坏；（2）金样存储环境是否合规；（3）金样是否被正确使用 |
| **替代方案** | 系统可以建立 **GoldenSample 数据模型**（TODO-15），记录该金样的基准参数值、最近校验日期、和最近若干次的测试数据。当测试数据与基准值的偏差超过阈值时，系统标记"金样可能已漂移，建议校验"。但金样的**物理存在性验证**始终需要人工确认 |

---

## 🚫-9 团簇缺陷自动识别（空间聚类算法）

**来源：** §4.3 Bin Map > 团簇缺陷识别

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 自动识别 Wafer Map 上的失效团簇 |
| **为什么不可实现** | （1）自动空间聚类（如 DBSCAN）需要合理设定参数（min_samples、eps），而这些参数高度依赖具体产品和工艺；（2）不同产品的 Wafer 布局差异很大（Die 间距、排数不一），通用聚类效果不可靠；（3）误报/漏报率无法保证，可能误导工程师。这不是一个简单的功能点，而是一个需要大量训练和验证的算法工程 |
| **替代方案** | (a) 保持当前可视化方式（工程师肉眼观察）；（b）在 TODO-25 中实现边缘集中失效检测（边缘 vs 中心的简单统计），这是确定性算法不涉及复杂聚类；（c）未来如果数据量足够大且有标注数据，可引入轻量空间统计（Moran's I 空间自相关）做异常提示 |

---

## 🚫-10 系统性重复失效模式自动检测

**来源：** §4.3 Bin Map > 系统性重复失效（光罩问题）

| 维度 | 说明 |
|------|------|
| **指标文档要求** | 识别跨 Die 位置的周期性重复失效模式 |
| **为什么不可实现** | 需要检测 Wafer 上以光罩（Reticle）为周期的重复失效模式。这要求：（1）知道该产品的 Reticle 尺寸（Field Size）；（2）实现周期性模式检测算法（如 FFT/自相关分析）。这些信息不在 ATE 数据文件中，且算法复杂度超出了本系统的"统计可视化"定位 |
| **替代方案** | 保持当前 Bin Map 可视化方式。工程师可以通过肉眼观察重复性模式（如每隔 4×4 Die 出现相同缺陷），系统提供颜色区分支持 |

---

## 不可实现项汇总

| 编号 | 指标原文项 | 受阻原因 | 替代方案 |
|------|----------|---------|---------|
| 🚫-1 | 鱼骨图自动生成 | 需 LLM 因果推理 | 输出 Pareto + 多维统计为人工分析提供输入 |
| 🚫-2 | Why-Why 分析 | 需 LLM + 工艺知识 | 远期 P3+ 可考虑 LLM 辅助 |
| 🚫-3 | 环境因素（温湿度） | 数据源不在 ATE 文件中 | 接入 IoT/SCADA 系统后时间戳对齐 |
| 🚫-4 | 设备利用率/OEE/MTTR/SMED | 需 MES/CIM/CMMS 数据 | MES 系统范畴，不属本系统 |
| 🚫-5 | ATE 机时费率/成本分析 | 商业运营数据 | 提供手动输入费率 + 简单乘法 |
| 🚫-6 | 测试项自动裁剪 | 需修改 ATE 程序 + 风险决策 | 输出长期CPK稳定项报告辅助决策 |
| 🚫-7 | 测试向量压缩 | ATPG/DFT 专业工程 | 超出系统边界 |
| 🚫-8 | Golden Sample 物理管理 | 物理实体 | GoldenSample 数据模型做偏差检测 |
| 🚫-9 | 团簇缺陷自动聚类 | 算法复杂度 + 参数依赖 | 可视化 + 边缘简单统计 |
| 🚫-10 | 系统性重复模式检测 | 需光罩尺寸信息 + 周期检测算法 | 保持可视化观察 |

---

## 附录：关键数据流

```
原始文件 (.csv/.std)
    │
    ▼
parsers/*.py ───→ pd.DataFrame + metadata (dict)
    │                 │
    │                 ├── df  : 所有测试数据行
    │                 └── meta: mins/maxs/units/site_col/bin_col/test_time...
    │
    ▼
services/statistics.py ───→ 统计计算结果
    │
    ▼
views.py (AnalysisViewSet / StatisticsViewSet)
    │
    ▼
JSON Response ───→ api/analysis.ts ───→ Pinia stores/analysis.ts
                                              │
                                              ▼
                                     pages/analysis/*.vue (ECharts 渲染)
```

**文件解析后 metadata 结构参考：**

```python
metadata = {
    'format': 'CTA8290D',
    'mins': {'ParamA': '-5.0', 'ParamB': '0.0', ...},
    'maxs': {'ParamA': '5.0', 'ParamB': '3.3', ...},
    'units': {'ParamA': 'V', 'ParamB': 'A', ...},
    'test_time': 12.5,
    'site_count': 8,
    'program_name': 'XXX_V1.0',
}
```
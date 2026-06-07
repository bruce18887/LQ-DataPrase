# 修复：直方图「范围类型」不影响分箱，Limit/3σ 线挤在一处

## 背景 / 根因
截图 `test/bar1.png`：选了「3 Sigma」范围类型，但 Limit 线和 3σ 线全挤在 X≈10.5，没落到对应位置。

三处叠加问题：
1. 后端 `compute_histogram_stats` 永远按 RowDataLimit 分箱（gap≈(14.3-8.0)/20），数据跨度仅 0.0073 → 全落进一个 bin，X 轴被撑到 6.9~15.3。
2. 前端 `useHistogram` 没把 `range_type` 发给后端 → 切换范围类型后端分箱不变。
3. `HistogramChart.vue` 的 `switch(rangeType)` 把 Limit 线（USL/LSL）画到了 3σ 值上，篡改了规格限位置。

## 决策
- 范围类型 → 决定分箱范围 + X 轴范围（与「范围对比」表 Gap 列语义一致）。
- Limit 线永远画真实规格限；缩放到 3σ 时超出范围的规格限线随视图裁剪掉（用户已确认）。
- CPK / Site 良率仍基于 RowDataLimit（不变）。

## 任务清单
- [x] 后端 `compute_histogram_stats` 增加 `range_type` / `custom_low` / `custom_high` 参数，按所选范围分箱（含退化回退）。
- [x] 后端 `histogram` view 读取并透传 `range_type` / `custom_low` / `custom_high`（新增 `_to_float`）。
- [x] 前端 `useHistogram` 接收 rangeType/custom，发送 `range_type`，并 watch 重新拉取。
- [x] 前端 `SingleParamTab` + `HistogramTab` 把 rangeType/custom 传入 `useHistogram`。
- [x] 前端 `HistogramChart.vue` 移除 switch 篡改，Limit 线永远用真实规格限。
- [x] 后端测试：`test/test_histogram_range_type.py` 新增分箱单测（4 用例全过）。
- [x] E2E：analysis.spec.ts 新增「切换范围类型触发 histogram 重新请求并重渲染」用例。
- [x] 验证：vue-tsc 通过 + 后端单测通过 + Playwright 实测截图核对。

## Review
**根因**：`range_type` 是三处脱节——后端永远按 RowDataLimit 分箱、前端从不发送、`HistogramChart` 里反而拿它去篡改 Limit 线坐标。
所以「选 3σ」既不重新分箱（数据全挤一个 bin），又把 USL/LSL 线挪到了 3σ 值上和 3σ 线重叠。

**修法**：
- 分箱范围改由 `range_type` 经 `resolve_limits` 决定（CL 支持自定义上下限），X 轴随之缩放；CPK / Site 良率仍锚定规格限。
- Limit 线恒画真实规格限，缩放出界时由 ECharts 裁剪（用户确认）。
- 前端切换 `range_type`/自定义限即重新请求后端。

**验证**：实测 `CON_PWMO` 选 3σ 后数据铺满 24 bin、正态曲线居中、3σ 虚线落在图两端、规格限按预期裁剪；改前同参数全部挤在单个 bin。

**注意**：`HistogramChart` 仍保留 `rangeType` prop（仅供 watch 触发重绘），分箱已在服务端完成；`safe_gap` 除以 20（非 25），分箱跨度约为所选范围的 1.25 倍。

---

# 改动：X 轴固定 24 等宽桶（limit 线落在桶边缘）

## 需求
按所选范围类型（如 RowDataLimit）：range/20 为桶宽，limit 线内 20 桶（LSL/USL 落在桶边缘），线外左右各 2 桶 = 24 桶；另加首尾 ±∞ 捕获桶收纳极端离群点（不计入 24）。X 轴桶数固定不随数据变动。

## 改动
- [x] `apps/analysis/services/data_services.py` `compute_histogram_stats`：
  - `bin_start = bin_min - 2.5*gap` + `range(26)`（25 内桶、limit 在桶中心）
    → `inner_edges = [bin_min + (k-2)*gap for k in range(25)]`（24 内桶、limit 在桶边缘 k=2/k=22）。
  - 中心循环 `range(25)` → `range(24)`。总桶数 26（24 + 2∞）不变。
- [x] `frontend/.../composables/useHistogram.ts`：范围对比表「Gap」列 `/25` → `/20`，与服务端真实桶宽一致。
- [x] `apps/analysis/tests.py`：新增 5 个分箱契约测试。

## 验证
- 后端单测：`python manage.py test apps.analysis` → 5 passed（26 桶、gap=range/20、limit 落边缘、内侧恰 20 桶、RDL/DR/S3/S4/S6 一致）。
- 实测真实文件：RDL/S3/S6/DR 均产出 26 桶，site 直方图长度一致，百分比合计 ~100%。

## 注意
- `safe_gap` 本就 `/20`，故桶宽语义与「除以 20」一致；此前内桶 25、limit 在桶中心（偏移半桶），现改为内桶 24、limit 在桶边缘。
- CPK / Site 良率仍锚定 RowDataLimit，不受影响。
- 前端 `HistogramChart` 的 `splitNumber: 24` 为坐标轴刻度提示，与桶数无强耦合，无需改动。

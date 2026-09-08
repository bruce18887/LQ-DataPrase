# 晶圆图页面对齐保守重设计原型 · 设计文档（2026-09-08）

> 参考：`docs/plans/analysis-conservative-preview.html` Tab 2（晶圆图）。
> 改造程度（用户拍板）：**方案 B —— 功能+布局对齐，保持单文件单图**；多片并排不在本轮。
> 预览稿标注的 F1（zonal_yield 404 被吞）/F2（global_judgment 死字段）两处「接真」已在
> 2026-09-02（S4 端点上线）与 2026-09-05（global_judgment 透传删除、口径统一）完成，本轮不涉及。

## 用户决策记录（逐项拍板，勿自行推翻）

1. **改造程度 = B**：做着色 4 档、左栏两表、自动结论条、die 尺寸真实化、Edge/Notch 标签语义、
   分区改独立 checkbox；保持单文件单图，多片并排不做。
2. **参数值着色归一 = 双口径自适应**：有真规格限按 LSL→USL 归一（超限饱和两端）；无规格限按
   该参数数据自身 min→max 归一；图例标注当前口径。
3. **Edge/Notch = 只改标签语义**：「Wafer Edge」checkbox 改名「边界圆+Notch」，功能不变
   （画外接圆 + Notch 缺口标记），**不引入**「剔除边缘 die」能力。
4. **自动结论条 = 做**，按预览稿口径（三环带极差 <0.5pp → 无径向梯度文案；否则提示可下钻）。
5. **分区交互 = 独立 checkbox + 覆盖着色**（预览稿形态）：勾选→环带着色覆盖原着色；
   取消→恢复 colorBy 着色。
6. **参数值着色复用判定参数下拉**（不加第二个参数选择控件）。
7. **统计呈现 = 左栏两张表**（分区良率表 + 该片统计表），取消顶部四统计卡与分区三卡。
8. **高度调节 = 窄 range + 数字提示**（替换 el-slider show-input 的占半行宽形态）。
9. **逐点值下发 = 直接在 points 补 value 字段**（payload 增约 20–30%，接受）。

## 布局

```
┌─ dp-analysis-toolbar 盒（现状不动：文件选择 360px + 说明文字）─┐
└────────────────────────────────────────────────────────────┘
┌─ 控制工具条（预览稿 .toolbar 形态）──────────────────────────┐
│ 着色: [判定结果|Site|Bin|参数值]  ☑边界圆+Notch  ☑分区模式     │
│                    高度 [──●──] 550              [加载晶圆图] │
└────────────────────────────────────────────────────────────┘
┌─ 左栏 25% ─────────┐┌─ 右栏 75% ──────────────────────────┐
│ ┌ 分区良率 表 ─────┐││ ┌ 晶圆图卡（ECharts）─────────────┐ │
│ │环带|Die|Pass|Yield│││ └───────────────────────────────┘ │
│ └─────────────────┘││ └ 自动结论条（.diag 形态）─────────┘ │
│ ┌ 该片统计 表 ─────┐││                                     │
│ │总die/Pass/Fail/  │││                                     │
│ │良率/坐标列/die尺寸│││                                     │
│ └─────────────────┘││                                     │
└────────────────────┘└─────────────────────────────────────┘
```

- 左右分栏对齐预览稿 `.row .col-l/.col-r`（25% / 75%），与单文件 tab 同比例。
- 「全局判定」按钮删除：与「判定参数不选」同口径（2026-09-05 已统一），UI 冗余。
- 「加载晶圆图」按钮移到工具条右端（现状在左端第一格）。
- 错误横幅（waferError / zonalError 分区失败）位置不变。

## 状态机

- `colorBy ∈ {result, site, bin, param}`（radio 4 档；原 zone 档移出）
- `zoneMode: boolean`（独立 checkbox）
- 显示规则：`zoneMode=true` → 环带着色（1/3·2/3 虚线环，预览稿形态）；`false` → 按 colorBy
- 判定口径：判定参数空 = 全部 die 按结果判定；非空 = 按该参数越限判定（现状不变）

## 后端改动（apps/analysis/services/data_services/wafer_map.py）

- `compute_wafer_map_data` 新增逐点 `value`：选中判定参数时（无论 color_by）对每个有效点补
  `value: float`，来源 `pd.to_numeric(get_1d_from(df, param), errors='coerce')` 整列向量化
  （与 xs/ys 同模式）；NaN 点省略 value 字段。
- 视图层同时下发 `spec_low/spec_high`（`resolve_spec_limits` 结果，可能为 null）供前端归一。
- 归一计算在**前端**做（保持「后端给原始数据、前端管显示」分层）：
  - spec_low/high 均非 null → 按 LSL→USL 归一，超限饱和到 0/1；
  - 否则按响应逐点 value 的 min/max 归一；
  - LSL==USL 退化 → 按数据范围口径兜底并在图例标注。
- **Bin 着色零后端改动**：points 已有 `bin` 字段，前端分组 + `getSiteColors8` 8 色循环
  （>8 组循环取色，图例注明）。

## 前端着色数据流（buildOption 分支）

- `result`：现状不变（Pass/Fail 两系列）。
- `site`：现状不变（color_group 分组 8 色循环）。
- `bin`：按 `p.bin` 分组 → 系列色 → 图例列 bin 名。
- `param`：单 scatter 系列 + `visualMap`（continuous，绿→红，min/max 按双口径）；
  NaN 值点单独灰色「无值」系列。
- `zoneMode=true`：环带着色（现状 zone 分支迁移）+ 1/3·2/3 虚线环。
- die 尺寸：`symbolSize` 从写死 [8,8] 改按 `wafer.die_size` 与坐标 span 的比例计算
  （预览稿：`die * scale * 0.86`，下限 1.6px）。

## 左栏两表与结论条

- **分区良率表**（列：环带|Die|Pass|Yield）：数据源 `zonal_yield` 端点（零后端改动）。
  现状「勾选分区才发请求」改为**选中文件后默认拉一次**（供左栏常驻表），判定参数变化时重拉。
  Yield 阈值色 ≥99.6% 绿 / 否则 warn；空区 yield=None 显示 `-`。
- **该片统计表**（行：总 die / Pass / Fail / 良率 / 坐标列 / die_size）：
  数据源 `waferData.stats` + `waferData.wafer`（均后端已下发，零改动）。
- **自动结论条**：三区 yield 均 non-null 时，按极差生成：
  - 极差 < 0.5pp → 「三环带良率 X% ~ Y%，极差仅 Z 个百分点 → 无径向梯度，失效集中在
    特定 Site/Bin 分裂（可切单文件 tab 看 Site 分层）」；
  - 否则 → 「存在径向梯度，可按环带下钻」。
  纯前端计算，文案由数据生成不套模板。
- 顶部四统计卡与分区三卡删除（数字并入两表）。

## 错误处理

- `waferLoadSeq`/`zonalLoadSeq` 双通道 seq+fileId 守卫现状不动。
- 「参数值」着色在 value 全空（参数列全 NaN）→ 该档降级：图例区提示「所选参数在坐标有效点
  上无有效值」，图面回落 Pass/Fail 着色，不弹错误横幅。
- LSL==USL 退化 → 数据范围口径兜底 + 图例标注。

## e2e 计划

- 迁移定位器：`wafermap-model-not-found`、`wafermap-hidden-tab-init`、
  `tab-independent-files`（晶圆图 pane 无 `[data-filter]` 契约保持）中统计卡 → 左栏两表。
- 新增用例：
  1. 着色 4 档切换重渲染（series 数/图例断言）；
  2. 分区 checkbox 勾选 → 环带着色+虚线环，取消 → 回原着色；
  3. 参数值着色：有规格限按 spec 归一 / 无规格限按数据归一；
  4. 左栏两表数字 == 图 title 子文本 stats（防口径漂移）；
  5. 自动结论条极差 <0.5pp 文案分支。
- 契约属性：`data-wafer-color`、`data-wafer-zone-table`、`data-wafer-stat-table`、
  `data-wafer-conclusion`；写进 `e2e/README.md` 选择器契约章节。

## 验证门禁

1. `npm run build`（vue-tsc -b + vite）。
2. `manage.py test apps.analysis`（串行；`tests_wafer_map_points.py` 等价性保持 + 新 value 断言）。
3. 晶圆图定向 e2e + 分析页全量 e2e（Playwright 自起后端；跑前查 8000 占用者命令行与数据目录，
   跑完释放端口）。
4. 双主题走查（用户 dev 开着时）：着色 4 档、分区叠加、左栏两表、结论条、窄 range。
   新样式全部语义 token（--bg-3 / --border / mono tabular-nums / --info mix），无新颜色。
5. 每批完成即 commit（R1）。

## 行数预算

现有 317 行 + 左栏两表 ~60 + 结论条 ~20 + 着色分支 ~60 ≈ 460 行 < 600；
逼近上限时把两表拆 `WaferStatTables.vue` 子组件。

## 不做的事（YAGNI 出仓）

- 多片并排、文件多选（拍板保持单文件）。
- Edge die 真剔除（只改标签）。
- 后端 zonal_yield / 分区口径改动（已接真）。
- 着色状态持久化到 store（保持 local ref 与现状一致）。

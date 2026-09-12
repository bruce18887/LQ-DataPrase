# 序列分布多 Site 重叠可读性优化设计

- 日期：2026-09-12
- 状态：已批准（brainstorming §1–§4 逐节确认）
- 范围：`frontend/src/pages/analysis/components/SerialChart.vue`（单文件分析序列分布图）；后端零改动

## 背景与问题

序列分布图为每 Site 一个 scatter 系列（`symbolSize` 固定 6、全不透明）。大文件场景
（真实案例：54k dies、4 site，降采样后 ≈8000 点）在 ≈1400px 画布上暴露四类问题：

1. **Site 间互相遮挡**：绘制序 Site1→Site4，后画盖先画，稀疏 Site 被最密 Site 的实色带完全盖住；
2. **带内高密度糊成实色带**：每像素 >1 点 + 不透明 → 密度/分布形态不可见；
3. **Fail/超界点被主带淹没**，无法一眼挑出；
4. 跨 Site 对比手段缺失（仅图例隐藏、X 轴缩放）。

用户确认的四个目标：各 Site 都可见（消遮挡）、带内密度/形态可见、异常/尾点突出、Site 间对比。
用户确认的实现形态（A+C）：智能默认渲染 + 「按 Site 拆分」开关 + 点径/透明度 slider。

## 方案总览（路线 3）

默认视图 = 渲染层消噪包（§1）；勾选开关切换按 Site 拆分小多图（§2）；
slider 细调点径/透明度（§3）。测试与回归见 §4。

## §1 渲染层默认优化（两模式公共底座）

### 1.1 自适应点径/透明度

纯函数 `autoPointStyle(pointCount)`，`pointCount` = 全部系列 data 长度之和
（降采样后、拆 Fail 层前）：

| pointCount | symbolSize | opacity |
|---|---|---|
| < 5,000 | 6（现状） | 0.85 |
| 5,000 – 20,000 | 4 | 0.5 |
| > 20,000 | 3 | 0.35 |

### 1.2 绘制顺序：最密垫底

按各 Site 点数**降序**赋 ECharts `z`（最密 z 最小先画垫底，稀疏在上）。
series 数组顺序与 `legend.data` 仍保持 site 升序——图例顺序与直方图等其它图表
一致的既有约定不变（z 只改绘制序，不改数组序）。

### 1.3 Fail/超界强调层

`is_fail=1` 或 `anchor∈{2,3}` 的点从各 site 系列抽出，合并为**单个置顶系列**：

- name `Fail/超界`；`itemStyle.color` = 主题语义色 `colors.errorColor`
  （night `#f5576c` / light `#b91c1c`，取自 `utils/echarts-theme.ts`）；
- opacity 1、symbolSize = 生效点径 + 2、`z` 大于所有 site 系列；
- 点数据携带 `realSite`，tooltip 显示所属 Site；legend 增 `Fail/超界` 一项；
- 全部系列级样式，**兼容 large 模式**（large 不支持逐点样式，故用独立系列实现）。

拆分模式下该层按 lane 复制（同名系列，legend 单项联动所有 lane）。

### 1.4 后端零改动

降采样（每 site ≤2000 点）、`is_fail`、`anchor` 均已在响应契约中；
后端下发的 `symbolSize: 6` 被前端生效值覆盖。

## §2 按 Site 拆分小多图模式

- **开关**：头部工具栏「按 Site 拆分」checkbox，仅 site 系列数 ≥2 时显示。
- **布局**（同一 ECharts 实例内）：N 条等高 grid lane，百分比表达——top≈12% 留标题、
  bottom≈22% 留 X 轴标签+图例，其余 N 等分、lane 间距 2%；
  全 lane 共享 `yAxisMin/Max`（复用现有离群裁剪逻辑）与同一 category X 轴；
  仅**最末 lane** 显示 X 轴标签（rotate 45），其余 lane 隐藏标签/刻度；
  lane 标签 = 该 lane `yAxis.name`（`Site n`，`nameLocation: 'end'`），
  文字色 = 该 Site 系列色。
- **交互联动**：`dataZoom inside` 的 `xAxisIndex` 覆盖全 lane 轴（tooltip 为
  `trigger: 'item'`，无 axisPointer，不引入 link 配置），任一 lane 缩放/平移全 lane 同步。
- **系列组织**：每 lane 仅本 Site pass 点（套 §1 点径/透明度）；Fail/超界层按 lane 复制；
  LSL/USL/σ 参考线按 lane 复制（同名系列，legend 单项控制全 lane）；
  拆分模式 legend **只保留参考线条目**（lane 即 site 图例，去重复表达）。
- **权衡备注**：dock 面板默认 440px、4 lane 时每 lane 绘图区 ≈65px，看带域形态够用；
  site 多时配合面板既有最大化按钮；不做自动加高（YAGNI）。

## §3 控件、状态语义与主题

- **工具栏**（SerialChart 头部行、右对齐、现序列列选择器左侧；仅图表可见时渲染）：
  「按 Site 拆分」checkbox；点径 slider 2–8 step 1（宽 ~110px）；
  透明度 slider 10–100 step 5（显示 %）。
- **自动/手动语义**：两个 override ref（null = 自动）；slider 显示**生效值**，
  自动时值提示带「(自动)」后缀；拖动即写 override；
  **每次 `props.data` 重载（换参/换文件/切过滤）override 清零回自动**；
  「按 Site 拆分」勾选态不随重载重置（会话级偏好）；
  **不做任何持久化**（不进 localStorage / 服务端图表记忆——重载回自动即期望行为，
  并规避 R5 跨上下文状态泄漏类问题）。
- **主题（R7）**：工具栏文字走 `var(--el-text-color-secondary)` 等 CSS token；
  slider/checkbox 为 EP 组件自动双主题；图表色只取 `getSiteColors8(isDark)` 与
  `colors.errorColor`；组件内零硬编码 hex。
- **体量**：SerialChart.vue 232 行 → 预计 ≈390 行（< 600 行红线，不拆文件）；
  SingleParamTab、后端零改动。

## §4 测试与回归

**新增 e2e** `frontend/e2e/analysis/serial-overlap.spec.ts`：

1. 自动档②（CTA8280F_FT，10k 行）：site 系列 `symbolSize=4`、`opacity=0.5`；
   Fail/超界系列 `opacity=1`、`z` 大于所有 site 系列、色 = 当前主题 `errorColor`；
   `legend.data` 前段 = site 升序。
2. slider 覆盖与重置：拖点径→7 后 option 同步；换参数触发重载 → 回自动值。
3. 拆分模式：勾选后 `grid.length === siteCount`、全 lane yAxis min/max 一致、
   仅末 lane 显示 X 标签、dataZoom 覆盖全轴、legend 无 Site 项且有规格限项；
   取消勾选恢复单 grid。
4. 自动档①（Site12358-Chip12345_c，500 点）：`symbolSize=6`、`opacity=0.85`。
5. 双主题：断言 1 在 night/light 各跑一遍（errorColor 随主题变）。

**回归面**（既有 spec 必须全绿）：legend-color、axis-label-precision、serial-no-column、
chart-filter-switches、chart-memory、outlier 系列。不受影响的依据：series 数组顺序不变、
后端契约不变、OutlierHintBar 不变。

**手动视觉验证**：dev 环境对 10k fixture 合并/拆分 × night/light 截图存
`.qoder/verify_serial_*.png` 比对；e2e 跑完释放端口（CLAUDE.md 硬规则）；
todo.md 记 review。

## 假设与边界

- ECharts large 模式（≥5000 点）不支持逐点样式 → 全部新增样式为系列级
  （opacity/z/color），Fail 强调以独立系列实现。
- 降采样行为不变；本方案只改视觉层与前端交互，不动统计口径
  （pass/fail 计数、均值/σ、限值解析均不变）。
- tooltip 契约不变（realSerial/realY/anchor），仅新增 realSite 展示。

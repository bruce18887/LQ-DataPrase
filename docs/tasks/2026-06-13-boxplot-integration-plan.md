# BoxPlot Integration Plan

## 任务状态

### 已完成 ✅
- [x] T1: Modify `SingleParamTab.vue` — add boxplot toggle, integrate useBoxPlot, add BoxPlotChart to template
- [x] T2: Modify `AnalysisPage.vue` — remove BoxPlot tab and BoxPlotSection import
- [x] T3: Delete `BoxPlotSection.vue`
- [x] T4: Verify TypeScript compilation
- [x] T5: Verify in browser — toggle boxplot, param switching, ignoreNoLimit sync
- [x] T6: 删除死代码 `BoxPlotPanel.vue`
- [x] T7: 恢复 groupBy 选择器（功能回归修复）
- [x] T8: 添加 boxplot loading 状态指示器
- [x] T9: 更新 e2e 测试用例

---

## 发现的问题

### 🔴 问题 1：死代码未清理
**文件**: `frontend/src/pages/analysis/components/BoxPlotPanel.vue`
**状态**: 文件仍存在，但没有任何模块导入它
**方案**: 删除该文件

### 🔴 问题 2：groupBy 硬编码为 'site' — 功能回归
**位置**: `SingleParamTab.vue` 第 193 行
**问题**: 旧版 BoxPlotPanel 提供了 groupBy 下拉选择（无分组/按Site/按Bin），新版硬编码为 'site'
**影响**: 没有 Site 列的文件只能显示 overall 箱线图，无法切换到 bin 分组
**方案**: 在 toolbar 添加 el-select 下拉框

### 🟡 问题 3：无 loading 状态指示器
**位置**: `SingleParamTab.vue` 第 194-201 行
**问题**: useBoxPlot 返回 `loading` 但未被解构使用
**方案**: 解构 `boxPlotLoading`，添加 el-skeleton

### 🟡 问题 4：BoxPlotStatsTable 无 loading 状态
**位置**: `SingleParamTab.vue` 第 46 行
**问题**: stats 为 null 时表格直接消失，无 spinner
**方案**: 添加 loading 条件控制

### 🟢 问题 5：ignoreNoLimit 同步是间接的
**问题**: ignoreNoLimit 未传递给 useBoxPlot，依赖 histogram fast-path 间接过滤
**方案**: 添加注释说明机制

---

## 详细实施步骤

### Step 1: 删除 BoxPlotPanel.vue 死代码

**文件**: `frontend/src/pages/analysis/components/BoxPlotPanel.vue`
**操作**: 删除文件

```bash
# 验证无引用
grep -r "BoxPlotPanel" frontend/src/
# 预期: 无输出

# 删除文件
rm frontend/src/pages/analysis/components/BoxPlotPanel.vue
```

---

### Step 2: 恢复 groupBy 选择器

**文件**: `frontend/src/pages/analysis/components/SingleParamTab.vue`

#### 2.1 添加 groupBy 选项常量
```typescript
// 在 showJitter ref 之后添加
const groupBy = ref('site')
const groupByOptions = [
  { label: '按 Site 分组', value: 'site' },
  { label: '按 Bin 分组', value: 'bin' },
  { label: '不分组', value: '' },
]
```

#### 2.2 在 toolbar 添加下拉框
```vue
<!-- 在 showJitter checkbox 之后添加 -->
<el-select
  v-if="showBoxPlot"
  v-model="groupBy"
  size="small"
  style="width: 120px; margin-left: 8px"
  placeholder="分组方式"
>
  <el-option
    v-for="opt in groupByOptions"
    :key="opt.value"
    :label="opt.label"
    :value="opt.value"
  />
</el-select>
```

#### 2.3 传递 groupBy 给 useBoxPlot
```typescript
// 修改 useBoxPlot 调用，传递响应式 groupBy
const { boxPlotData, loading: boxPlotLoading } = useBoxPlot(
  () => props.fileId,
  localSelectedParam,
  groupBy,  // 已经是 ref，无需修改
  showBoxPlot,
)
```

---

### Step 3: 添加 boxplot loading 状态

**文件**: `frontend/src/pages/analysis/components/SingleParamTab.vue`

#### 3.1 解构 boxPlotLoading
```typescript
// 修改解构
const { boxPlotData, loading: boxPlotLoading } = useBoxPlot(
  () => props.fileId,
  localSelectedParam,
  groupBy,
  showBoxPlot,
)
```

#### 3.2 在 BoxPlotChart wrapper 添加 loading 指示器
```vue
<div
  v-if="showBoxPlot && chartMode === 'distribution'"
  :key="`bp-${localSelectedParam}`"
  class="chart-wrapper chart-wrapper--bottom"
  style="min-height: 400px; margin-top: 12px; position: relative;"
>
  <el-skeleton
    v-if="boxPlotLoading"
    :rows="6"
    animated
    style="position: absolute; inset: 0; z-index: 10; background: var(--el-bg-color);"
  />
  <BoxPlotChart
    :data="currentBoxPlotData"
    :show-jitter="showJitter"
    :visible="showBoxPlot"
  />
</div>
```

#### 3.3 为 BoxPlotStatsTable 添加 loading 状态
```vue
<BoxPlotStatsTable
  v-if="showBoxPlot && boxPlotOverallStats && !boxPlotLoading"
  :stats="boxPlotOverallStats"
/>
<el-skeleton
  v-else-if="showBoxPlot && boxPlotLoading"
  :rows="4"
  animated
  style="margin-top: 8px;"
/>
```

---

### Step 4: 更新 e2e 测试用例

**文件**: `frontend/e2e/analysis/analysis.spec.ts`

#### 4.1 更新现有 boxplot 测试
```typescript
test('箱线图 toggle 显示', async ({ page }) => {
  await selectAnalysisFile(page)
  await selectParam(page)
  await page.click('.el-radio-button:has-text("数值分布")')
  await page.click('label:has-text("显示箱线图")')

  const resp = await page.waitForResponse(
    (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
    { timeout: 20_000 },
  )
  expect(resp.status()).toBe(200)

  await expectChartRendered(page.locator('.chart-wrapper--bottom'))
  await expect(page.locator('.boxplot-stats-table')).toBeVisible()
})
```

#### 4.2 添加 groupBy 切换测试
```typescript
test('箱线图 groupBy 切换', async ({ page }) => {
  await selectAnalysisFile(page)
  await selectParam(page)
  await page.click('.el-radio-button:has-text("数值分布")')
  await page.click('label:has-text("显示箱线图")')

  await page.waitForResponse(
    (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
  )

  await page.click('.el-select:has-text("按 Site 分组")')
  await page.click('.el-select-dropdown__item:has-text("按 Bin 分组")')

  const resp = await page.waitForResponse(
    (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
  )
  expect(resp.status()).toBe(200)

  await expectChartRendered(page.locator('.chart-wrapper--bottom'))
})
```

#### 4.3 添加 Jitter toggle 测试
```typescript
test('箱线图 Jitter 散点切换', async ({ page }) => {
  await selectAnalysisFile(page)
  await selectParam(page)
  await page.click('.el-radio-button:has-text("数值分布")')
  await page.click('label:has-text("显示箱线图")')

  await page.waitForResponse(
    (r) => r.url().includes('/statistics/boxplot/') && r.status() < 500,
  )

  await page.click('label:has-text("Jitter散点")')

  await expectChartRendered(page.locator('.chart-wrapper--bottom'))
})
```

---

### Step 5: 浏览器验证清单 (T5)

```bash
# 运行所有分析相关测试
cd frontend
npm run test:e2e -- --grep "箱线图|boxplot"

# 运行回归测试
npm run test:e2e -- --grep "@regression"

# 运行完整分析测试
npm run test:e2e -- project=analysis
```

**手动验证清单**：
- [ ] 分布模式下 toggle 箱线图 — 图表出现/消失
- [ ] toggle Jitter — 散点叠加显示
- [ ] 切换参数 — 数据刷新，无旧数据显示
- [ ] 同时开启 QQ 和 Box — 切换参数无竞态条件
- [ ] 切换文件 — 状态正确重置
- [ ] BoxPlotStatsTable 显示当前参数的正确统计
- [ ] 无有效数值数据的参数 — 显示占位文本
- [ ] ECharts 无 emitsOptions 错误
- [ ] groupBy 切换 — 图表正确重新加载
- [ ] loading 状态 — skeleton 正确显示和消失

---

## 文件修改清单

| 文件 | 操作 | 行数变化 |
|------|------|----------|
| `frontend/src/pages/analysis/components/BoxPlotPanel.vue` | 删除 | -248 |
| `frontend/src/pages/analysis/components/SingleParamTab.vue` | 修改 | +25 |
| `frontend/e2e/analysis/analysis.spec.ts` | 修改 | +80 |

**总计**: 删除 1 文件，修改 2 文件，净增约 -143 行

---

## 风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| groupBy 切换导致 API 错误 | 低 | 中 | 后端已支持 group_by 参数，前端只需传递 |
| loading skeleton 闪烁 | 中 | 低 | 使用 position: absolute 避免布局跳动 |
| e2e 测试超时 | 低 | 低 | 增加 timeout 到 20s |
| 同时开启 QQ+Box 的竞态 | 低 | 中 | useBoxPlot 内部已有 enabled guard |

---

## 验证命令

```bash
# TypeScript 编译检查
cd frontend && npx vue-tsc --noEmit

# 运行 e2e 测试
npm run test:e2e -- --grep "箱线图"

# 运行所有分析测试
npm run test:e2e -- project=analysis

# 查看测试报告
npm run test:e2e:report
```

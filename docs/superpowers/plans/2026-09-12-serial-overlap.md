# 序列分布多 Site 重叠可读性优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让单文件分析的序列分布散点图在多 Site 大文件下不再糊成实色带/互相遮挡：自适应点径透明度 + 最密垫底 + Fail 置顶强调层 + 点径/透明度 slider + 「按 Site 拆分」小多图模式。

**Architecture:** 纯前端渲染层改造，集中于 `SerialChart.vue` 的 `buildOption`：pass/fail 点拆分、系列级 `z`/`opacity`/`symbolSize`、拆分模式用 N 组 grid/xAxis/yAxis 小多图共享刻度并由 dataZoom 联动；后端契约零改动。

**Tech Stack:** Vue 3 SFC + ECharts 6（canvas/SVG）、Element Plus 控件、Playwright e2e（读 `__echartsInstance__.getOption()` 断言）。

**规格来源:** `docs/superpowers/specs/2026-09-12-serial-overlap-design.md`（§1–§4 编号下文引用）。

---

## 文件结构

| 操作 | 路径 | 职责 |
|---|---|---|
| Modify | `frontend/src/pages/analysis/components/SerialChart.vue` | 工具栏控件 + buildOption 重构（唯一被改的实现文件，终态 ≈430 行 < 600 红线） |
| Create | `frontend/e2e/analysis/serial-overlap.spec.ts` | 本功能全部 e2e（自动档/z 序/Fail 层/slider/拆分/双主题/快照） |

## 前置与约定

- Shell 为 PowerShell：环境变量用 `$env:PW_DEV_SERVER='1'`；命令分隔用 `;`。
- e2e 默认由 playwright webServer 自起前后端（`frontend/playwright.config.ts`）。**跑 e2e 前确认没有手动残留的 dev server**（lessons：复用旧后端进程 → 结果无效）：`netstat -ano | findstr ":3000 :8000"` 应无 LISTENING；有则先停掉手动会话。
- 红/绿迭代用 `$env:PW_DEV_SERVER='1'`（vite dev 免每次 build）；最终验证用默认 preview 构建再跑一遍。
- R2④：`waitForResponse` 必须在触发动作**之前**注册（helper `enterSerial` 已遵守）。
- 提交风格跟随仓库：`feat(serial): …` / `test(serial): …`（中文描述）。
- 每个 Task 结束跑构建门禁：`npm run build`（frontend 目录；R8：vue-tsc -b 才是真门禁）。

---

### Task 1: e2e 骨架 + 渲染层默认优化（spec §1）

**Files:**
- Create: `frontend/e2e/analysis/serial-overlap.spec.ts`
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue`

- [ ] **Step 1: 写失败测试（spec 骨架 + 自动档两用例）**

创建 `frontend/e2e/analysis/serial-overlap.spec.ts`：

```ts
import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParamWithSpecLimits } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 序列分布多 Site 重叠可读性（spec: docs/superpowers/specs/2026-09-12-serial-overlap-design.md）
 *  - §1 自适应点径/透明度分级 + 最密垫底 z 序 + Fail/超界 置顶强调层
 *  - §3 slider 覆盖与重载重置
 *  - §2 按 Site 拆分小多图
 *  - §4 双主题 errorColor + 视觉快照
 */

const SINGLE = '.single-param-tab'
const SERIAL_CANVAS = `${SINGLE} .serial-chart-wrapper div[_echarts_instance_]`

/** 读图表实例 option（useChart 把实例挂在容器 div 本身） */
async function readOption(loc: Locator): Promise<any> {
  return loc.evaluate((el: any) => el.__echartsInstance__?.getOption?.() ?? null)
}

/** 进分析页 → 选带规格限参数 → 开序列分布；返回 canvas 与 serial 响应 */
async function enterSerial(page: Page, fileLabel: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, fileLabel)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  const limited = await selectParamWithSpecLimits(page)
  test.skip(!limited, '当前文件没有带真实规格限的参数')
  // R2④：waitForResponse 必须在触发动作之前注册
  const respPromise = page.waitForResponse(
    (r) =>
      r.url().includes('/analysis/serial_distribution/') &&
      r.request().method() === 'POST' &&
      r.status() < 500,
    { timeout: 30_000 },
  )
  await page.getByText('显示序列分布').click()
  const resp = await respPromise
  const canvas = page.locator(SERIAL_CANVAS).first()
  await expect(canvas).toBeVisible({ timeout: 20_000 })
  return { canvas, resp }
}

/** 分级表一致性（spec §1.1）：点径/透明度由总点数决定 */
function expectedTier(total: number) {
  if (total < 5000) return { size: 6, opacity: 0.85 }
  if (total <= 20000) return { size: 4, opacity: 0.5 }
  return { size: 3, opacity: 0.35 }
}

/** site 系列 + Fail/超界 系列的点数总和（= 拆 Fail 层前的 pointCount） */
function siteAndFailTotals(opt: any): number {
  return (opt?.series ?? []).reduce(
    (a: number, s: any) =>
      /^Site /.test(s.name) || s.name === 'Fail/超界' ? a + (s.data?.length ?? 0) : a,
    0,
  )
}

test.describe('@p1 序列分布多 Site 重叠可读性', { tag: ['@p1', '@analysis'] }, () => {
  test('自动档：分级表一致 + 最密垫底 + Fail/超界置顶强调层 + 图例 Site 升序', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const opt = await readOption(canvas)
    const series: any[] = opt.series ?? []
    const siteSeries = series.filter((s) => /^Site /.test(s.name))
    expect(siteSeries.length, '应至少 2 个 site 系列').toBeGreaterThanOrEqual(2)

    const total = siteAndFailTotals(opt)
    expect(total, 'fixture 应走高密度路径（>=5000 点）').toBeGreaterThanOrEqual(5000)
    const tier = expectedTier(total)
    for (const s of siteSeries) {
      expect(s.symbolSize, '自动点径').toBe(tier.size)
      expect(s.itemStyle.opacity, '自动透明度').toBe(tier.opacity)
    }

    // z 序：按点数降序严格单调（最密垫底，spec §1.2）
    const counts = siteSeries.map((s) => s.data.length)
    const zs = siteSeries.map((s) => s.z)
    for (let i = 1; i < siteSeries.length; i++) {
      if (counts[i] === counts[i - 1]) continue
      expect(counts[i] < counts[i - 1] ? zs[i] > zs[i - 1] : zs[i] < zs[i - 1]).toBe(true)
    }

    // 图例前段 = site 升序（数组序不变约定）
    const legend: string[] = opt.legend[0].data
    expect(legend.slice(0, siteSeries.length)).toEqual(siteSeries.map((s) => s.name))

    // Fail/超界 强调层（spec §1.3）；全 pass fixture 退化为「不应存在」
    if (body.fail_count > 0) {
      const fail = series.find((s) => s.name === 'Fail/超界')
      expect(fail, 'Fail/超界 强调层应存在').toBeTruthy()
      expect(fail.itemStyle.opacity).toBe(1)
      expect(fail.z).toBeGreaterThan(Math.max(...zs))
      expect(legend).toContain('Fail/超界')
    } else {
      expect(series.find((s) => s.name === 'Fail/超界')).toBeUndefined()
    }
  })

  test('自动档①：500 点文件保持 6px/0.85', async ({ page }) => {
    const { canvas } = await enterSerial(page, 'Site12358-Chip12345_c')
    const opt = await readOption(canvas)
    const siteSeries = (opt.series ?? []).filter((s: any) => /^Site /.test(s.name))
    expect(siteSeries.length).toBeGreaterThanOrEqual(2)
    const total = siteAndFailTotals(opt)
    expect(total).toBeLessThan(5000)
    expect(expectedTier(total)).toEqual({ size: 6, opacity: 0.85 })
    for (const s of siteSeries) {
      expect(s.symbolSize).toBe(6)
      expect(s.itemStyle.opacity).toBe(0.85)
    }
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run（frontend 目录）: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1`
Expected: FAIL —— `itemStyle.opacity` 为 undefined、无 `Fail/超界` 系列、无 `z` 字段。

- [ ] **Step 3: 实现 §1（SerialChart.vue 四处编辑）**

编辑 `frontend/src/pages/analysis/components/SerialChart.vue`：

3a. 在 `const isLarge = computed(...)` 之后插入分级函数与生效值：

```ts
// —— 重叠可读性（spec 2026-09-12 §1.1）：按总点数自适应点径/透明度，
// 大文件散点不再糊成实色带；slider 覆盖在后续任务接入 ——
function autoPointStyle(count: number): { size: number; opacity: number } {
  if (count < 5000) return { size: 6, opacity: 0.85 }
  if (count <= 20000) return { size: 4, opacity: 0.5 }
  return { size: 3, opacity: 0.35 }
}
const siteCount = computed(() => (props.data?.series_data || []).length)
const autoStyle = computed(() => autoPointStyle(pointCount.value))
const effSize = computed(() => autoStyle.value.size)
const effOpacity = computed(() => autoStyle.value.opacity)
```

3b. `toPoint` 签名与返回加 site（供 Fail 层 tooltip）：把

```ts
  function toPoint(p: number[], _idx: number) {
```

改为 `function toPoint(p: number[], siteName: string) {`，并在返回对象中追加 `site: siteName,`（与 `realY/realSerial/isFail/anchor` 同级）。

3c. 替换 series 构建块（原「颜色按系列统一」整段 map）为 pass/fail 拆分 + z 序 + Fail 层：

```ts
  // —— pass/fail 拆分：fail/超界点抽到置顶强调层（spec §1.3；large 模式
  // 不支持逐点样式，强调只能靠独立系列）——
  const siteSeriesRaw: { name: string; data: number[][] }[] = d.series_data || []
  const siteColors = getSiteColors8(isDark.value)
  const passData: any[][] = siteSeriesRaw.map(() => [])
  const failDataBySite: any[][] = siteSeriesRaw.map(() => [])
  siteSeriesRaw.forEach((sd, idx) => {
    ;(sd.data || []).forEach((p: number[]) => {
      const pt = toPoint(p, sd.name)
      if (!pt) return
      if (pt.isFail || pt.anchor !== 0) failDataBySite[idx].push(pt)
      else passData[idx].push(pt)
    })
  })
  const failAll = failDataBySite.flat()
  // 绘制序：最密垫底（spec §1.2）——按点数降序赋 z；数组序保持 site 升序
  // （图例顺序与直方图等其它图表一致的既有约定）
  const counts = siteSeriesRaw.map((sd) => (sd.data || []).length)
  const zOfSite = new Map<number, number>()
  counts
    .map((c, i) => i)
    .sort((a, b) => counts[b] - counts[a])
    .forEach((idx, rank) => zOfSite.set(idx, 2 + rank))

  const series: any[] = siteSeriesRaw.map((sd, idx) => ({
    name: sd.name, type: 'scatter',
    data: passData[idx],
    symbolSize: effSize.value,
    itemStyle: { color: siteColors[idx % 8], opacity: effOpacity.value },
    z: zOfSite.get(idx),
    ...(isLarge.value ? { large: true } : {}),
  }))
  if (failAll.length) {
    series.push({
      name: 'Fail/超界', type: 'scatter', data: failAll,
      symbolSize: effSize.value + 2,
      itemStyle: { color: colors.value.errorColor, opacity: 1 },
      z: 10, // 高于所有 site 系列（site z = 2..N+1）
      ...(isLarge.value ? { large: true } : {}),
    })
  }
```

3d. marks 循环加 `z: 20`（参考线恒在数据带之上）：在 `markLine: mark.markLine, silent: true,` 后加 `z: 20,`。

3e. tooltip formatter 首行加 site 归属：把

```ts
        let html = `${p.seriesName}<br/>${serialCol}: ${pt.realSerial ?? p.value[0]}<br/>结果: ${pt.isFail ? 'FAIL' : 'PASS'}`
```

改为：

```ts
        let html = `${p.seriesName}`
        if (p.seriesName === 'Fail/超界' && pt.site) html += ` · ${pt.site}`
        html += `<br/>${serialCol}: ${pt.realSerial ?? p.value[0]}<br/>结果: ${pt.isFail ? 'FAIL' : 'PASS'}`
```

（legend 无需改：`series.map(name)` 天然 = site 升序 + Fail/超界 + marks。）

- [ ] **Step 4: 运行确认通过**

Run: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1`
Expected: 2 passed。

- [ ] **Step 5: 构建门禁**

Run: `npm run build`
Expected: 成功（vue-tsc -b + vite build 无错）。

- [ ] **Step 6: 提交**

```powershell
git add frontend/e2e/analysis/serial-overlap.spec.ts frontend/src/pages/analysis/components/SerialChart.vue
git commit -m "feat(serial): 序列分布自适应点径/透明度 + 最密垫底 + Fail/超界置顶强调层"
```

---

### Task 2: 点径/透明度 slider + 重载重置（spec §3）

**Files:**
- Modify: `frontend/e2e/analysis/serial-overlap.spec.ts`（追加用例）
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue`

- [ ] **Step 1: 追加失败测试**

在 describe 内追加：

```ts
  test('slider 覆盖与重载重置：拖改生效、数据重载回自动', async ({ page }) => {
    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    const siteSymbol = () =>
      readOption(canvas).then((o: any) => o?.series?.find((s: any) => /^Site /.test(s.name))?.symbolSize)
    const siteOpacity = () =>
      readOption(canvas).then((o: any) => o?.series?.find((s: any) => /^Site /.test(s.name))?.itemStyle?.opacity)
    await expect.poll(siteSymbol).toBeGreaterThanOrEqual(3)

    // 点径 自动值 → 键盘 +3 步；断言覆盖生效（max 8 封顶）
    const before = await siteSymbol()
    const sizeBtn = page.locator(`${SINGLE} .serial-header__slider`).nth(0).locator('.el-slider__button')
    await sizeBtn.focus()
    for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowRight')
    await expect.poll(siteSymbol).toBe(Math.min(before + 3, 8))

    // 透明度 -1 步（step 5 → 百分比 -5 → 小数 -0.05），仍为 5 的整数倍
    const opBtn = page.locator(`${SINGLE} .serial-header__slider`).nth(1).locator('.el-slider__button')
    await opBtn.focus()
    await page.keyboard.press('ArrowLeft')
    const opNow = await siteOpacity()
    expect(Math.round(opNow * 100) % 5).toBe(0)

    // 切过滤触发数据重载 → override 清零回自动（spec §3）
    const respPromise = page.waitForResponse(
      (r) =>
        r.url().includes('/analysis/serial_distribution/') &&
        r.request().method() === 'POST' &&
        r.status() < 500,
      { timeout: 30_000 },
    )
    await page.locator(`${SINGLE} .chart-toggles .el-checkbox`).filter({ hasText: '仅用Pass数据(Bin1)' }).click()
    await respPromise
    const opt = await readOption(canvas)
    const tier = expectedTier(siteAndFailTotals(opt))
    await expect.poll(siteSymbol).toBe(tier.size)
    await expect.poll(siteOpacity).toBe(tier.opacity)
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1 --grep "slider"`
Expected: FAIL —— `.serial-header__slider` 定位器超时。

- [ ] **Step 3: 实现工具栏与 override 语义**

3a. import 行：`import { computed } from 'vue'` → `import { computed, ref, watch } from 'vue'`。

3b. 替换 Task 1 的两行生效值 computed 为带 override 版本：

```ts
/** 手动覆盖（null = 自动）：每次数据重载清零，避免手动值毁掉小文件（spec §3） */
const pointSizeOverride = ref<number | null>(null)
const opacityOverridePct = ref<number | null>(null) // 百分比 10-100
watch(() => props.data, () => {
  pointSizeOverride.value = null
  opacityOverridePct.value = null
})
const effSize = computed(() => pointSizeOverride.value ?? autoStyle.value.size)
const effOpacityPct = computed(() => opacityOverridePct.value ?? Math.round(autoStyle.value.opacity * 100))
const effOpacity = computed(() => effOpacityPct.value / 100)
const sizeAutoHint = computed(() => (pointSizeOverride.value == null ? '(自动)' : ''))
const opacityAutoHint = computed(() => (opacityOverridePct.value == null ? '(自动)' : ''))
```

3c. 模板：把原 `<div v-if="showSelector" class="serial-col-selector">…</div>` 整块包进新工具栏行（选择器原样内嵌）：

```html
    <!-- 工具栏：点径/透明度 slider + 序列列选择器（spec §3；拆分开关见后续任务） -->
    <div class="serial-header">
      <div class="serial-header__slider">
        <span class="serial-header__label">点径 {{ effSize }}{{ sizeAutoHint }}</span>
        <el-slider
          :model-value="effSize" :min="2" :max="8" :step="1" size="small"
          class="serial-header__range"
          @update:model-value="(v: number | [number, number]) => (pointSizeOverride = Array.isArray(v) ? v[0] : v)"
        />
      </div>
      <div class="serial-header__slider">
        <span class="serial-header__label">透明度 {{ effOpacityPct }}%{{ opacityAutoHint }}</span>
        <el-slider
          :model-value="effOpacityPct" :min="10" :max="100" :step="5" size="small"
          class="serial-header__range"
          @update:model-value="(v: number | [number, number]) => (opacityOverridePct = Array.isArray(v) ? v[0] : v)"
        />
      </div>
      <div v-if="showSelector" class="serial-col-selector">
        <span class="serial-col-selector__label">序列列</span>
        <el-select
          :model-value="activeSerialCol"
          size="small"
          style="width: 200px"
          @update:model-value="(v: string) => emit('update:serialCol', v)"
        >
          <el-option
            v-for="c in serialCandidates"
            :key="c"
            :label="c"
            :value="c"
          />
        </el-select>
      </div>
    </div>
```

3d. 样式：`.serial-col-selector` 规则删除 `margin-bottom: 8px;`（间距归工具栏），并追加：

```css
.serial-header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.serial-header__slider {
  display: flex;
  align-items: center;
  gap: 6px;
}
.serial-header__label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.serial-header__range {
  width: 110px;
}
```

3e. `useChart` 依赖数组追加 `() => effSize.value, () => effOpacityPct.value`。

- [ ] **Step 4: 运行确认通过**

Run: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1`
Expected: 3 passed（含 Task 1 两例不回归）。

- [ ] **Step 5: 构建门禁 + 提交**

Run: `npm run build` → 成功后：

```powershell
git add frontend/e2e/analysis/serial-overlap.spec.ts frontend/src/pages/analysis/components/SerialChart.vue
git commit -m "feat(serial): 点径/透明度 slider 与重载回自动语义"
```

---

### Task 3: 按 Site 拆分小多图（spec §2）

**Files:**
- Modify: `frontend/e2e/analysis/serial-overlap.spec.ts`（追加用例）
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue`

- [ ] **Step 1: 追加失败测试**

```ts
  test('按 Site 拆分：N lane 共享刻度 + 联动缩放 + 图例去 Site', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    const n = (body.series_data || []).length
    test.skip(n < 2, 'fixture 无多 site，拆分模式不适用')
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(n)
    const opt = await readOption(canvas)
    expect(opt.xAxis.length).toBe(n)
    expect(opt.yAxis.length).toBe(n)
    // 共享刻度（跨 Site 可比）
    expect(new Set(opt.yAxis.map((y: any) => y.min)).size).toBe(1)
    expect(new Set(opt.yAxis.map((y: any) => y.max)).size).toBe(1)
    // 仅末 lane 显示 X 标签
    opt.xAxis.forEach((x: any, i: number) => {
      expect(x.axisLabel.show, `lane ${i} X 标签`).toBe(i === n - 1)
    })
    // 缩放联动覆盖全 lane
    expect(opt.dataZoom[0].xAxisIndex).toEqual(Array.from({ length: n }, (_, i) => i))
    // 图例去 Site、保留参考线
    const legend: string[] = opt.legend[0].data
    expect(legend.some((l) => /^Site /.test(l))).toBe(false)
    expect(legend.length).toBeGreaterThan(0)
    // 取消勾选恢复单面板
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(1)
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1 --grep "按 Site 拆分"`
Expected: FAIL —— `getByText('按 Site 拆分')` 超时。

- [ ] **Step 3: 实现拆分模式**

3a. 脚本加开关 ref（会话级偏好，不随重载重置）：

```ts
/** 按 Site 拆分小多图开关（spec §2；会话级偏好，不随数据重载重置） */
const splitBySite = ref(false)
```

3b. 模板工具栏首位插入 checkbox：

```html
      <el-checkbox v-if="siteCount >= 2" v-model="splitBySite" size="small">按 Site 拆分</el-checkbox>
```

3c. buildOption 中把 Task 1 的「series 构建 + fail 层 + marks 循环」区域整体替换为模式感知版本（从 `const series: any[] = siteSeriesRaw.map(` 到 marks 循环结束）：

```ts
  const split = splitBySite.value && siteSeriesRaw.length >= 2
  const laneCount = split ? siteSeriesRaw.length : 1

  const series: any[] = siteSeriesRaw.map((sd, idx) => ({
    name: sd.name, type: 'scatter',
    data: passData[idx],
    ...(split ? { xAxisIndex: idx, yAxisIndex: idx } : {}),
    symbolSize: effSize.value,
    itemStyle: { color: siteColors[idx % 8], opacity: effOpacity.value },
    ...(split ? {} : { z: zOfSite.get(idx) }),
    ...(isLarge.value ? { large: true } : {}),
  }))
  if (split) {
    // Fail 层按 lane 复制（同名系列 → 图例单项联动所有 lane）
    failDataBySite.forEach((fdata, idx) => {
      if (!fdata.length) return
      series.push({
        name: 'Fail/超界', type: 'scatter', data: fdata,
        xAxisIndex: idx, yAxisIndex: idx,
        symbolSize: effSize.value + 2,
        itemStyle: { color: colors.value.errorColor, opacity: 1 },
        ...(isLarge.value ? { large: true } : {}),
      })
    })
  } else if (failAll.length) {
    series.push({
      name: 'Fail/超界', type: 'scatter', data: failAll,
      symbolSize: effSize.value + 2,
      itemStyle: { color: colors.value.errorColor, opacity: 1 },
      z: 10,
      ...(isLarge.value ? { large: true } : {}),
    })
  }

  // —— 轴/网格：合并单面板；拆分 N 条同步 lane（spec §2：top 12% 留标题、
  // bottom 22% 留 X 标签+图例，其余 N 等分、lane 间距 2%）——
  function xAxisDef(i: number, showLabel: boolean) {
    return {
      type: 'category', data: continuousSerials, gridIndex: i,
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      ...(showLabel
        ? {
            name: serialCol, nameTextStyle: { color: tc },
            nameLocation: 'middle', nameGap: 30,
            axisLabel: { rotate: 45, interval: 'auto', fontSize: 9, color: tc },
          }
        : { axisLabel: { show: false }, axisTick: { show: false } }),
    }
  }
  function yAxisDef(i: number, laneName: string | null, laneColor?: string) {
    return {
      type: 'value', gridIndex: i, min: yAxisMin, max: yAxisMax,
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: { formatter: formatAxisValue, fontSize: 9, color: tc },
      ...(laneName
        ? {
            name: laneName, nameLocation: 'end', nameGap: 6,
            nameTextStyle: { color: laneColor, fontSize: 10, fontWeight: 'bold' },
          }
        : {
            name: unit ? `${param} (${unit})` : param,
            nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 40,
          }),
    }
  }

  let grids: any[]
  let xAxes: any[]
  let yAxes: any[]
  let dataZoom: any[]
  if (split) {
    const lanePct = 66 / laneCount
    grids = siteSeriesRaw.map((_, i) => ({
      left: 70, right: 30,
      top: `${12 + i * lanePct}%`,
      height: `${Math.max(lanePct - 2, 4)}%`,
    }))
    xAxes = siteSeriesRaw.map((_, i) => xAxisDef(i, i === laneCount - 1))
    yAxes = siteSeriesRaw.map((sd, i) => yAxisDef(i, sd.name, siteColors[i % 8]))
    dataZoom = [{ type: 'inside', xAxisIndex: siteSeriesRaw.map((_, i) => i) }]
  } else {
    grids = [{ top: 60, bottom: 85 }]
    xAxes = [xAxisDef(0, true)]
    yAxes = [yAxisDef(0, null)]
    dataZoom = [{ type: 'inside', xAxisIndex: [0] }]
  }

  // 参考线按 lane 复制（同名系列，图例单项控制全 lane）
  for (const mark of d.marks || []) {
    const lineColor = mark.markLine?.data?.[0]?.lineStyle?.color
    for (let lane = 0; lane < laneCount; lane++) {
      series.push({
        name: mark.name, type: mark.type || 'scatter', data: mark.data || [],
        markLine: mark.markLine, silent: true,
        xAxisIndex: lane, yAxisIndex: lane, z: 20,
        ...(lineColor ? { itemStyle: { color: lineColor } } : {}),
      })
    }
  }

  // 拆分模式图例只留参考线条目（lane 即 site 图例，去重复表达）
  const markNames = (d.marks || []).map((m: any) => m.name)
  const legendData = split ? markNames : series.map((s: any) => s.name)
```

3d. 返回 option 中替换五处：

```ts
    legend: { data: legendData, bottom: 5, type: 'scroll', textStyle: { color: tc } },
```
```ts
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom,
    grid: grids,
    series,
```
（原单对象 `xAxis: {...} / yAxis: {...} / dataZoom: [...] / grid: {...}` 与 `legend: { data: series.map(...) ... }` 全部以上述替换。）

3e. `useChart` 依赖数组追加 `() => splitBySite.value`。

- [ ] **Step 4: 运行确认通过**

Run: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1`
Expected: 4 passed。

- [ ] **Step 5: 构建门禁 + 提交**

Run: `npm run build` → 成功后：

```powershell
git add frontend/e2e/analysis/serial-overlap.spec.ts frontend/src/pages/analysis/components/SerialChart.vue
git commit -m "feat(serial): 按 Site 拆分小多图模式（共享刻度+联动缩放）"
```

---

### Task 4: 双主题断言 + 视觉快照（spec §4-5/6）

**Files:**
- Modify: `frontend/e2e/analysis/serial-overlap.spec.ts`（追加两用例；无实现改动——守线 + 产出视觉证据）

- [ ] **Step 1: 追加用例**

```ts
  test('双主题：Fail 层色随主题 errorColor', async ({ page }) => {
    const { canvas, resp } = await enterSerial(page, RECOMMENDED.analysis)
    const body = await resp.json()
    test.skip(!(body.fail_count > 0), 'fixture 全 pass，无 Fail 层')
    const failColor = () =>
      readOption(canvas).then(
        (o: any) => o?.series?.find((s: any) => s.name === 'Fail/超界')?.itemStyle?.color,
      )
    const themeNow = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const expectFor = (t: string | null) => (t === 'light' ? '#b91c1c' : '#f5576c')
    const t0 = await themeNow()
    await expect.poll(failColor).toBe(expectFor(t0))
    await page.locator('button.theme-toggle').click()
    const t1 = t0 === 'light' ? 'night' : 'light'
    await expect(page.locator('html')).toHaveAttribute('data-theme', t1)
    await expect.poll(failColor).toBe(expectFor(t1))
  })

  test('视觉快照：合并/拆分 × 双主题存 .qoder/verify_serial_*.png', async ({ page }) => {
    const { canvas } = await enterSerial(page, RECOMMENDED.analysis)
    const themeNow = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const shot = (name: string) => canvas.screenshot({ path: `../.qoder/verify_serial_${name}.png` })
    const t0 = await themeNow()
    await shot(`merged_${t0}`)
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBeGreaterThanOrEqual(2)
    await shot(`split_${t0}`)
    await page.locator('button.theme-toggle').click()
    const t1 = t0 === 'light' ? 'night' : 'light'
    await expect(page.locator('html')).toHaveAttribute('data-theme', t1)
    await shot(`split_${t1}`)
    await page.getByText('按 Site 拆分').click()
    await expect.poll(async () => (await readOption(canvas))?.grid?.length).toBe(1)
    await shot(`merged_${t1}`)
  })
```

- [ ] **Step 2: 运行全 spec**

Run: `$env:PW_DEV_SERVER='1'; npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1`
Expected: 6 passed；`../.qoder/` 下新增 `verify_serial_merged_*.png` / `verify_serial_split_*.png` 共 4 张。

- [ ] **Step 3: 目视快照**

用 Read 工具查看 4 张 png：合并视图应见半透明带 + 稀疏 Site 透出 + Fail 点置顶；拆分视图应见 N 条 lane、末 lane 有 X 标签、lane 标签带 Site 色。不符则回 Task 1/3 调参后重跑。

- [ ] **Step 4: 提交（仅 spec，png 为验证产物不入库）**

```powershell
git add frontend/e2e/analysis/serial-overlap.spec.ts
git commit -m "test(serial): 双主题 errorColor 断言 + 合并/拆分视觉快照"
```

---

### Task 5: 回归 + 收尾

- [ ] **Step 1: 既有 spec 回归（默认 preview 构建，不用 dev server）**

Run（frontend 目录，不带 PW_DEV_SERVER）:

```powershell
npx playwright test legend-color axis-label-precision serial-no-column chart-filter-switches chart-memory outlier --project=P1 --project=P2
```

Expected: 全绿。依据（spec §4）：series 数组序不变、后端契约不变、OutlierHintBar 不变；若红先 `git stash` 对照判定是否本功能引入（R8②）。

- [ ] **Step 2: 新 spec 默认构建复跑**

Run: `npx playwright test e2e/analysis/serial-overlap.spec.ts --project=P1`
Expected: 6 passed。

- [ ] **Step 3: 端口释放确认（CLAUDE.md 硬规则）**

Run: `netstat -ano | findstr ":3000 :8000"`
Expected: 无 LISTENING 行（playwright webServer 自收）；若有残留手动进程则停掉。

- [ ] **Step 4: todo.md 记 review**

在 `docs/tasks/todo.md` 末尾追加「2026-09-12 序列分布多 Site 重叠可读性优化」review 段：改动文件、e2e 结果（新 spec 6 passed + 回归全绿）、快照路径、遗留说明（>20k 档无 fixture，靠分级表一致性断言覆盖逻辑）。

- [ ] **Step 5: 提交收尾**

```powershell
git add docs/tasks/todo.md
git commit -m "docs(todo): 序列分布重叠优化 review 记录"
```

---

## 规格覆盖自查

| spec 条目 | 落地任务 |
|---|---|
| §1.1 自适应分级 | Task 1（实现 + 两档断言 + 分级表一致性） |
| §1.2 最密垫底 z 序 | Task 1（z 单调断言） |
| §1.3 Fail/超界 强调层 | Task 1（opacity/z/legend/tooltip site） |
| §1.4 后端零改动 | 全计划无后端文件 |
| §2 拆分小多图 | Task 3（grid/轴/联动/图例断言） |
| §3 控件与 override 语义 | Task 2（slider + 重载重置断言）；checkbox 在 Task 3 |
| §3 主题 R7 | Task 4（双主题 errorColor 断言）+ 控件仅 CSS token |
| §4 e2e 1–5 | Task 1–4 |
| §4 回归面 | Task 5 Step 1 |
| §4 视觉快照/端口/todo | Task 4 Step 2-3、Task 5 Step 3-4 |

# 审查刀一：serial 开子集直方图 + pptx 进度回调 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 serial 图的高亮可以右键打开子集直方图（A 案），并让 PPTX 批量图表导出像 xlsx 一样逐参数上报进度。

**Architecture:** 前端只动两个组件：`ChartContextMenu` 增加菜单项，`SerialChart` 直接调用模块单例 `useSubsetPanels`（不经过 `SingleParamTab`，避免它 589/600 行触阈）。后端只动两个文件：`export_ppt.py` 增加 `progress_cb` 参数并在每张 slide 落地后回调，`runner.py` 把已有的 `_cb` 同时传给 pptx 分支。判据分层：T1 钉后端回调契约与 runner 接线，T3 钉浏览器里的真实菜单、请求体与面板；不新增 T2，因为 `selectionGeometry` / `useSubsetPanels` 的纯函数判据已存在，本次新增的只是接线。

**Tech Stack:** Vue 3 + TypeScript + ECharts + Playwright；Django + DRF + python-pptx + matplotlib + unittest。

**Spec:** `docs/reference/feature-gap-review-2026-11-16.md` §5、§3.2-①、§8-1；测试分层与门禁节奏见 `docs/reference/testing-gates.md`。

## Global Constraints

- **600 行硬约束**：`git ls-files '*.py' '*.ts' '*.vue'` 全仓生效。**不得往 `frontend/src/pages/analysis/components/SingleParamTab.vue`（589 行）和 `frontend/e2e/analysis/subset-drilldown.spec.ts`（565 行）加行**；新 e2e 用例必须落在新文件。
- **双主题**：只认 CSS token，不新增裸色。本次复用 `ChartContextMenu` 现有 `role="menuitem"` 样式，dark/light 自动跟随，不写新样式块。
- **版本控制**：从 master 另开 `feature/gap-review-quick-wins`；master 上不提交产品代码；不 push（origin 是公开仓库）。
- **门禁节奏**：每笔 commit 前 `cd frontend && npm run test:e2e:affected`；收口/并入 master 前 `node scripts/e2e_pool.mjs --slots=4` + 后端全套。判绿取日志末尾 `RESULT:` / `OK` 行，不取退出码。
- **一条 bash 命令只跑一个 Playwright 档位**；跑前确认端口空闲，跑后释放。
- **本计划只做报告 §8 的刀一 + 报告入库**；不做 prune timer、`jobs/` 占用统计、管理员跨用户、过载提示、SFTP 保留期、桌面日志轮转。
- **语义假设（已按用户方向预设）**：§5 取 **A 案**（菜单对「当前高亮集合」开子图，不是「刚刚框的那一下」）；§3.2-① 取 **补 `progress_cb`**。若拍板不同，先改计划再动代码。

## File Structure

- `frontend/src/pages/analysis/components/ChartContextMenu.vue`：highlight 菜单分支新增「打开子集直方图」项与 `open-subset` emit。
- `frontend/src/pages/analysis/components/SerialChart.vue`：引入 `useSubsetPanels` 单例，处理 `open-subset`，用当前 `highlight.serials` + `highlight.serialCol` 建面板并关菜单。
- `frontend/e2e/analysis/serial-subset-panel.spec.ts`（新建）：真实浏览器接线证明。
- `apps/export/export_ppt.py`：`build_batch_charts_pptx` 新增 `progress_cb=None`，每渲染出一张 slide 回调一次。
- `apps/jobs/runner.py`：把 `total` / `_cb` 提到分支之前，pptx 分支传入 `progress_cb=_cb`。
- `test/backend/test_jobs_chart_params.py`：新增 runner 侧「pptx 分支收到进度回调」的 T1。
- `test/backend/test_export_ppt_progress.py`（新建）：builder 侧「每个渲染参数回调一次、跳过参数不虚报」的 T1。
- `docs/tasks/todo.md`：新增本批任务台账。
- `docs/reference/feature-gap-review-2026-11-16.md`：作为 spec 一并入库（当前 untracked）。
- `docs/superpowers/plans/2026-11-16-gap-review-quick-wins.md`：本计划。

---

### Task 1: 台账、分支与 spec 入库

**Files:**
- Modify: `docs/tasks/todo.md`
- Commit: `docs/reference/feature-gap-review-2026-11-16.md`, `docs/superpowers/plans/2026-11-16-gap-review-quick-wins.md`

**Interfaces:**
- Produces: 分支 `feature/gap-review-quick-wins`；todo.md 里本批的勾选清单与门禁表。

- [ ] **Step 1: 从 master 开分支**

```bash
git switch -c feature/gap-review-quick-wins master
```

Expected: `Switched to a new branch 'feature/gap-review-quick-wins'`

- [ ] **Step 2: 在 `docs/tasks/todo.md` 末尾追加本批条目**

```markdown
# 任务：审查刀一（serial 开子集 + pptx 进度，2026-11-16）

计划：`docs/superpowers/plans/2026-11-16-gap-review-quick-wins.md`
依据：`docs/reference/feature-gap-review-2026-11-16.md` §5（A 案）、§3.2-①、§8-1。

## 勾选清单

- [ ] T1：pptx `progress_cb` builder 侧 + runner 接线
- [ ] T3：serial 高亮右键「打开子集直方图」
- [ ] 收口：`npx vitest run` / `npm run lint:e2e` / `npm run build` / `npm run test:e2e:affected` / 行数闸
- [ ] 并入 master（需用户点头；并入前全量池 + 后端全套）

## 门禁记录（执行时填判据行）

| 档 | 命令 | 实测判据行 |
|---|---|---|
| T1 | `manage.py test test.backend.test_jobs_chart_params test.backend.test_export_ppt_progress` | |
| T3 | `npx playwright test e2e/analysis/serial-subset-panel.spec.ts --project=P1 --workers=1` | |
| 全量 vitest | `npx vitest run` | |
| e2e 类型 | `npm run lint:e2e` | |
| 前端构建 | `npm run build` | |
| affected | `npm run test:e2e:affected` | |
| 行数闸 | `npx vitest run test/unit/lineLimit.spec.ts` | |
```

- [ ] **Step 3: 提交 docs（报告当前 untracked，先钉住）**

```bash
git add docs/reference/feature-gap-review-2026-11-16.md docs/superpowers/plans/2026-11-16-gap-review-quick-wins.md docs/tasks/todo.md
git commit -m "docs(plan): 审查刀一计划与五项核查报告入库"
git status --short
```

Expected: `git status --short` 无输出。

---

### Task 2: pptx 逐参数进度回调（后端）

**Files:**
- Modify: `apps/export/export_ppt.py:26-31`（签名）、`:65`（循环）、`:151`（加图之后）
- Modify: `apps/jobs/runner.py:152-169`
- Test: `test/backend/test_jobs_chart_params.py`（新增 1 条）
- Test: `test/backend/test_export_ppt_progress.py`（新建）

**Interfaces:**
- Produces: `build_batch_charts_pptx(..., progress_cb=None)`；回调签名 `progress_cb(done: int) -> None`，**每真实产出一张 slide 调一次**，跳过的参数不虚报。
- Consumes: `runner.write_progress(path, done, total)` 的既有语义（`done/total` 折成 1–100 写入侧车）。

- [ ] **Step 1: 写失败测试（runner 侧接线）**

在 `test/backend/test_jobs_chart_params.py` 的 `JobChartParamsTests` 末尾追加：

```python
    def test_pptx_branch_receives_progress_cb(self):
        captured = self._capture(chart_format='pptx', params=['F32', 'I32'])
        cb = captured['kwargs'].get('progress_cb')
        self.assertTrue(callable(cb), 'pptx 分支必须与 xlsx 一样收到进度回调')
        cb(1)
        sidecar = os.path.join(self.tmpdir, runner.PROGRESS_FILENAME)
        with open(sidecar, encoding='utf-8') as fh:
            self.assertEqual(fh.read(), '50', '1/2 个参数应写成 50%')
```

- [ ] **Step 2: 写失败测试（builder 侧回调次数）**

新建 `test/backend/test_export_ppt_progress.py`：

```python
"""pptx 导出的逐参数进度回调（builder 侧判据）。

runner 侧只钉「回调被传进来」；这里钉回调的**次数与时机**：
每真实产出一张 slide 调一次，参数不在 df 里（被 continue 跳过）时不虚报。
"""
from types import SimpleNamespace

import pandas as pd
from django.test import SimpleTestCase

from apps.export.export_ppt import build_batch_charts_pptx


class PptxProgressCallbackTests(SimpleTestCase):
    def test_callback_fires_once_per_rendered_param(self):
        calls = []
        df = pd.DataFrame({
            'A': [1.0, 2.0, 3.0, 4.0],
            'B': [1.0, 2.0, 3.0, 4.0],
        })
        metadata = {'units': {'A': 'V', 'B': 'V'},
                    'mins': {'A': '1', 'B': '1'},
                    'maxs': {'A': '4', 'B': '4'},
                    'format': 'CTA8290D'}
        datafile = SimpleNamespace(filename='p.csv', format_type='CTA8290D',
                                   program_name='P')

        blob = build_batch_charts_pptx(
            datafile, df, metadata, ['A', 'MISSING', 'B'],
            progress_cb=calls.append)

        self.assertGreater(len(blob), 0, 'PPTX 不得为空')
        self.assertEqual(calls, [1, 2],
                         '只对真实渲染出的参数回调，跳过的参数不虚报')
```

- [ ] **Step 3: 跑测试确认失败**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_jobs_chart_params test.backend.test_export_ppt_progress
```

Expected: FAIL。`test_pptx_branch_receives_progress_cb` 报 `AssertionError: pptx 分支必须与 xlsx 一样收到进度回调`；`test_callback_fires_once_per_rendered_param` 报 `TypeError: build_batch_charts_pptx() got an unexpected keyword argument 'progress_cb'`。

- [ ] **Step 4: 实现 `export_ppt.py`**

签名（`apps/export/export_ppt.py:26-31`）改为：

```python
def build_batch_charts_pptx(datafile, df, metadata, params,
                            show_limit=True, show_3sigma=False,
                            show_4sigma=False, show_6sigma=True,
                            show_normal=False, show_kde=False,
                            dpi=EXPORT_DPI_DEFAULT,
                            cpk_thresholds=None,
                            progress_cb=None):
```

docstring 的 `Parameters` 段补一句：

```python
    progress_cb : callable, optional
        ``progress_cb(done:int)``，每真实产出一张 slide 调一次；总数由调用方持有。
```

循环前初始化计数器（`prs = Presentation()` 之后）：

```python
    rendered = 0
```

循环末尾、`add_picture` 之后追加：

```python
        slide.shapes.add_picture(buf, left, top, width=Inches(9), height=Inches(5.5))

        rendered += 1
        if progress_cb:
            progress_cb(rendered)
```

- [ ] **Step 5: 实现 `runner.py`**

把 `apps/jobs/runner.py:152-169` 改成：

```python
    write_progress(progress, 1, 3)

    total = max(1, len(params))

    def _cb(done: int, _total=total, _p=progress):
        write_progress(_p, done, _total)

    if task.get('chart_format') == 'pptx':
        payload = build_batch_charts_pptx(
            _datafile_proxy(task), df, metadata, params, **show,
            dpi=task['dpi'], cpk_thresholds=thresholds,
            progress_cb=_cb)
    else:
        payload = build_batch_charts_xlsx_with_charts(
            df, metadata, params, site_col=get_site_column(df), **show,
            dpi=task['dpi'], cpk_thresholds=thresholds,
            workers=1, progress_cb=_cb,
            groups=task.get('groups'),
            max_items_per_sheet=task.get('max_items_per_sheet', DEFAULT_MAX_ITEMS_PER_SHEET))
```

- [ ] **Step 6: 跑测试确认通过**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_jobs_chart_params test.backend.test_export_ppt_progress
```

Expected: `OK`，且 `Ran 4 tests`（`test_jobs_chart_params` 原有 2 条 + 新增 1 条；`test_export_ppt_progress` 1 条）。

- [ ] **Step 7: 提交**

```bash
git add apps/export/export_ppt.py apps/jobs/runner.py test/backend/test_jobs_chart_params.py test/backend/test_export_ppt_progress.py
git commit -m "feat(export): pptx 批量图表逐参数上报进度"
```

---

### Task 3: serial 高亮右键开子集直方图（前端）

**Files:**
- Modify: `frontend/src/pages/analysis/components/ChartContextMenu.vue:11-13,26-27`
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue:13-18,22-34,369-383`
- Test: `frontend/e2e/analysis/serial-subset-panel.spec.ts`（新建）

**Interfaces:**
- Produces: `ChartContextMenu` 新增 emit `'open-subset'`；`SerialChart` 新增 `openSubsetFromHighlight()`。
- Consumes: `useSubsetPanels().create(selection: ChartSelection)`（模块单例，`useSubsetPanels.ts:78-87,120`）；`useSerialHighlight()` 的 `serials` / `serialCol` / `clear`。

- [ ] **Step 1: 写失败 e2e 测试（新文件，不碰 565 行的 subset-drilldown）**

新建 `frontend/e2e/analysis/serial-subset-panel.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { loginAs } from '../helpers/auth'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile, selectParam, ensureChartToggles } from '../helpers/params'

/**
 * serial 高亮 → 右键「打开子集直方图」的接线证明（A 案）。
 * 语义：菜单对「当前高亮集合」开子图，不是「刚刚框的那一下」。
 * 组合判据在 T1/T2；这里只钉真实渲染 + 菜单接线 + 请求体身份。
 */
const SINGLE = '.single-param-tab'
const PREFIX = 'e2e_serial_subset_'

const CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,VCC,',
  'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,V,',
  'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,3,',
  'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,3.6,',
  '1,1,1,1,TRUE,1,0,0,None,4.1,10,1.0,3.3,',
  '2,1,2,1,TRUE,1,0,0,None,4.1,10,1.5,3.2,',
  '3,1,3,2,TRUE,1,0,0,None,4.1,10,0.5,3.4,',
  '4,1,4,2,TRUE,1,0,0,None,4.2,10,10.0,3.3,',
  '5,1,5,2,TRUE,1,0,0,None,4.2,10,11.0,3.2,',
  '6,1,6,2,TRUE,1,0,0,None,4.2,10,12.0,3.3,',
  '',
].join('\n')

let filename = ''
let csvPath = ''

test.describe('serial 高亮开子集直方图', { tag: ['@p1', '@analysis'] }, () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async ({ browser }) => {
    filename = `${PREFIX}${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, CSV, 'utf-8')
    const page = await browser.newPage()
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })
    await page.close()
  })

  test.afterAll(async ({ browser }) => {
    cleanupQuiet(csvPath)
    // storageState 必须显式清空：browser.newPage()/newContext() 会继承 P1 的
    // admin.json 登录态，token 有效期内 /login 被守卫弹回 /dashboard（同
    // subset-drilldown.spec.ts:68-75 的约定）。
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, PREFIX)
    await ctx.close()
  })

  async function openSerial(page: import('@playwright/test').Page) {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
    await ensureChartToggles(page, { serial: true })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="serial"]`))
  }

  /** 在容器盒内按分数坐标拖拽；先滚到视口顶部，避免 y 落到折叠线以下。 */
  async function drag(page: import('@playwright/test').Page, sel: string,
                      fx0: number, fy0: number, fx1: number, fy1: number) {
    await page.locator(sel).evaluate((el) => el.scrollIntoView({ block: 'start' }))
    const box = await page.locator(sel).boundingBox()
    expect(box).not.toBeNull()
    const b = box!
    const x0 = b.x + b.width * fx0
    const y0 = b.y + b.height * fy0
    const x1 = b.x + b.width * fx1
    const y1 = b.y + b.height * fy1
    await page.mouse.move(x0, y0)
    await page.mouse.down()
    await page.mouse.move(x1, y1, { steps: 8 })
    await page.mouse.up()
    return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 }
  }

  /** 读 serial 图高亮叠加系列的真实序列号。 */
  function highlightSerials(host: import('@playwright/test').Locator) {
    return host.evaluate((el: any) => {
      const series = el.__echartsInstance__?.getOption?.()?.series ?? []
      return series.filter((s: any) => s.name === '高亮芯片')
        .flatMap((s: any) => s.data ?? [])
        .map((p: any) => p.realSerial) as (number | string)[]
    })
  }

  test('框选高亮 → 右键打开子集直方图（n=3，高亮保持）', async ({ page }) => {
    await openSerial(page)
    const chartB = `${SINGLE} [data-chart-key="serial"] .chart-b`
    // 与 subset-drilldown.spec.ts:219 同一块已知矩形：右上覆盖 serial 4/5/6，
    // mouseup 立即消费为高亮。
    await drag(page, chartB, 0.55, 0.06, 0.98, 0.45)
    const host = page.locator(`${SINGLE} .serial-chart-wrapper div[_echarts_instance_]`)
    await expect.poll(async () => (await highlightSerials(host)).length,
      { timeout: 15_000 }).toBe(3)
    expect([...(await highlightSerials(host))].sort((a, b) => Number(a) - Number(b)))
      .toEqual([4, 5, 6])

    // 右键只开 highlight 菜单；R2①：waitForResponse 必须在触发点击之前注册。
    await page.locator(chartB).evaluate((el) => el.scrollIntoView({ block: 'start' }))
    const box = await page.locator(chartB).boundingBox()
    expect(box).not.toBeNull()
    const requery = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/')
        && r.request().method() === 'POST'
        && r.request().postData()?.includes('"kind":"serials"') === true
        && r.request().postData()?.includes('"serials":[4,5,6]') === true,
      { timeout: 20_000 },
    )
    await page.mouse.click(box!.x + box!.width * 0.75, box!.y + box!.height * 0.25,
      { button: 'right' })
    const menu = page.locator('[data-chart-context-menu]')
    await expect(menu).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-menu-create-subset]')).toHaveCount(0)
    const openItem = page.locator('[data-menu-open-subset]')
    await expect(openItem).toBeVisible()
    await openItem.click()
    await expect(menu).toHaveCount(0)

    const resp = await requery
    expect(resp.status()).toBe(200)
    const panel = page.locator('[data-subset-panel]')
    await expect(panel).toHaveCount(1)
    await expect(panel).toHaveAttribute('data-subset-n', '3', { timeout: 15_000 })
    const title = panel.locator('.subset-panel__title')
    await expect(title).toContainText('KELVIN_VIN 子集')
    await expect(title).toContainText('3 颗序列')
    // 面板展示即贡献高亮（并集语义）；开子图后高亮不得丢。
    await expect.poll(async () => (await highlightSerials(host)).length,
      { timeout: 15_000 }).toBeGreaterThanOrEqual(3)
  })
})
```

- [ ] **Step 2: 跑新用例确认失败**

先确认 8000/3000 空闲；若被占，改用本机动态区间（1024–15000）之外的端口，例如：

```bash
cd frontend && npx playwright test e2e/analysis/serial-subset-panel.spec.ts --project=P1 --workers=1
```

（端口被占时：`E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test ...`）

Expected: FAIL，`[data-menu-open-subset]` 找不到（菜单里只有 `[data-menu-clear-highlight]`）。

- [ ] **Step 3: 实现 `ChartContextMenu.vue`**

模板 highlight 分支（`:11-13`）改为：

```html
      <template v-if="mode === 'highlight'">
        <button type="button" role="menuitem" data-menu-open-subset @click="emit('open-subset')">打开子集直方图</button>
        <button type="button" role="menuitem" data-menu-clear-highlight @click="emit('clear')">清除高亮</button>
      </template>
```

emit 类型（`:27`）改为：

```ts
const emit = defineEmits<{ create: []; clear: []; 'open-subset': []; close: [] }>()
```

- [ ] **Step 4: 实现 `SerialChart.vue`**

模板（`:13-18`）加监听：

```html
    <ChartContextMenu
      :menu="brush.menu"
      mode="highlight"
      @open-subset="openSubsetFromHighlight"
      @clear="highlight.clear()"
      @close="brush.closeMenu"
    />
```

脚本 import 区（`useSerialHighlight` 那一行之后）加：

```ts
import { useSubsetPanels } from '../composables/useSubsetPanels'
```

单例声明（`const highlight = useSerialHighlight()` 之后）加：

```ts
const subsetPanels = useSubsetPanels()
```

处理函数放在 `brush` 定义之后：

```ts
/**
 * A 案：菜单对「当前高亮集合」开子图，不是「刚刚框的那一下」。
 * immediate 模式下 mouseup 已消费选区，此时手上只有高亮集合本身。
 */
function openSubsetFromHighlight() {
  const serials = highlight.serials.value
  if (!serials.length) return
  subsetPanels.create({
    kind: 'serials',
    serials: [...serials],
    serial_col: highlight.serialCol.value,
  })
  brush.closeMenu()
}
```

- [ ] **Step 5: 跑新用例确认通过**

```bash
cd frontend && npx playwright test e2e/analysis/serial-subset-panel.spec.ts --project=P1 --workers=1
```

Expected: `1 passed`，末尾 `RESULT:` 行为绿（若用 affected 档，取 `RESULT: PASS`）。

- [ ] **Step 6: 前端静态与构建验证**

```bash
cd frontend && npm run build
cd frontend && npm run lint:e2e
cd frontend && npx vitest run test/unit/lineLimit.spec.ts
```

Expected: build 无 TS 诊断；lint:e2e `error TS` 0 处；行数闸 `Tests 20 passed`（以实际文件数为准，但不得新增 `EXEMPT`）。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/analysis/components/ChartContextMenu.vue frontend/src/pages/analysis/components/SerialChart.vue frontend/e2e/analysis/serial-subset-panel.spec.ts
git commit -m "feat(analysis): serial 高亮右键开子集直方图"
```

---

### Task 4: 收口门禁与台账

**Files:**
- Modify: `docs/tasks/todo.md`（把 Task 1 留下的门禁表填上实测判据行）
- Modify: `docs/reference/feature-gap-review-2026-11-16.md`（在文首「方法」段后加一行进展，可选）

**Interfaces:**
- Consumes: Task 2/3 的代码与测试。
- Produces: 可并入本地 master 的验证树；并入动作仍需用户点头。

- [ ] **Step 1: 全量 vitest**

```bash
cd frontend && npx vitest run
```

Expected: `Test Files ... passed`、`Tests ... passed`，exit 0。

- [ ] **Step 2: 每批 commit 前的 affected 门禁**

```bash
cd frontend && npm run test:e2e:affected
```

Expected: 末行 `RESULT: PASS`；`NO AFFECTED TESTS` 不是绿灯。

- [ ] **Step 3: 行数闸**

```bash
cd frontend && npx vitest run test/unit/lineLimit.spec.ts
```

Expected: 通过，且没有新增豁免条目。

- [ ] **Step 4: 把实测判据行填进 `docs/tasks/todo.md` 的门禁表**

逐档填入上一步的原文行（不要只写「通过」）。

- [ ] **Step 5: 提交台账**

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 审查刀一收口门禁记录"
```

- [ ] **Step 6: 并入 master 前的全量档（需用户点头后执行）**

```bash
node scripts/e2e_pool.mjs --slots=4
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test
```

Expected: 池末行 `unexpected 0`（或红项逐条归因且与本批无关）；后端 `OK`、`grep -cE "^(FAIL|ERROR):"` = 0。跑完释放端口。

- [ ] **Step 7: FF 并入本地 master（需用户点头；不 push）**

```bash
git merge-base --is-ancestor master HEAD
git switch master
git merge --ff-only feature/gap-review-quick-wins
git branch -d feature/gap-review-quick-wins
git status --short
```

Expected: `--ff-only` 成功；`git status --short` 无输出。

---

## 自审

**1. Spec 覆盖**

- 报告 §5 A 案：Task 3 的菜单项、`openSubsetFromHighlight`、新 e2e 全覆盖。
- 报告 §3.2-①：Task 2 的 builder 回调、runner 接线、两条 T1 全覆盖。
- 报告 §8-1 验证：Task 4 的 vitest、affected、行数闸覆盖；全量池/后端全套放在并入前。
- 报告入库：Task 1 Step 3。
- 600 行约束：File Structure 明确不碰 `SingleParamTab.vue` 与 `subset-drilldown.spec.ts`；新 e2e 独立文件。
- 双主题：复用现有 token 样式，无新增 CSS。

**2. 占位符扫描**

- 没有 TBD/TODO/「稍后补」；所有代码与命令均为可执行原文。
- 端口命令给了默认值与回退值；门禁表在 Task 4 要求填实测原文，不是占位。

**3. 类型一致性**

- `progress_cb(done: int)`：builder 与 runner 的 `_cb(done, _total, _p)` 一致，xlsx 分支签名未变。
- `'open-subset'`：`defineEmits`、模板 `emit('open-subset')`、父组件 `@open-subset`、e2e `[data-menu-open-subset]` 四点一致。
- `ChartSelection`：`{ kind: 'serials', serials, serial_col }` 与 `selectionGeometry.ts:10-12` 一致。
- `useSubsetPanels().create(selection)` 与 `useSubsetPanels.ts:78-87` 一致。

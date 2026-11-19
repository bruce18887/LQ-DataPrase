# 批4 刀三：文件列表刷新保留勾选 + 激活刷新 + out_of_memory 码表 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉「列表刷新吞勾选」（FIX-1）与「四个 sibling loader 不随激活刷新」（FIX-4），并给 `out_of_memory` 补前端码表（审查报告 §2.1-A 的防御项）。

**Architecture:** FIX-1 用 Element Plus 的 `reserve-selection`（表格已有 `row-key`）；FIX-4 把 `FileListTab.vue` 的四个 loader 从 `onMounted` 迁到 `onActivated`（与占用 chip 同一口径），首进 mounted+activated 只发一次；两条 T3 判据分开写，分别钉「刷新后 selectedCount 仍为 N」与「激活回 /data 时五类请求各一次」。`out_of_memory` 只是 `ERROR_CODE_MAP` 的一行 + T2 高频守卫码列表。

**Tech Stack:** Vue 3 + Element Plus + Playwright；Vitest（node 环境）。

**Spec:** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §10（FIX-1 / FIX-4）；`docs/reference/feature-gap-review-2026-11-16.md` §2.1-A；门禁节奏见 `docs/reference/testing-gates.md`。

## Global Constraints

- **600 行硬约束**：`FileListTab.vue` 466、`FileListTable.vue` 460、`combine.spec.ts` 172；本批只增量小改，不碰 `SingleParamTab.vue`（589）与 `subset-drilldown.spec.ts`（565）。
- **双主题**：本批不动颜色/样式；FIX-1/FIX-4 无新增 CSS。
- **版本控制**：从 master（当前 `9308a8b`）另开 `feature/batch4c-data-refresh`；master 上不提交产品代码；不 push。
- **门禁**：`frontend/src/utils/error.ts` 命中 GLOBAL；`pages/data/**` 命中 data 模块。收口**只跑一次**全量池 + 后端全套 + vitest + lint（设计 §10 的排批要求）。
- **FIX-1 与 FIX-4 的判据必须分两条用例**（设计 §10 原话）：一条钉「刷新后勾选保留」，另一条钉「激活请求各一次」，不许写在同一条断言里。
- **不改** `DataManagement.vue` 的 `onActivated(loadFiles)`（父页全量列表已有 `data.spec.ts` 的「只拉一次」判据）；FIX-4 只改 `FileListTab.vue` 的四个 sibling loader。

## File Structure

- `frontend/src/utils/error.ts`：`ERROR_CODE_MAP` 加 `out_of_memory`。
- `frontend/test/unit/error.spec.ts`：高频守卫码列表加 `out_of_memory`。
- `frontend/src/pages/data/components/FileListTable.vue`：selection 列加 `reserve-selection`。
- `frontend/src/pages/data/components/FileListTab.vue`：四个 loader 从 `onMounted` 迁到 `onActivated`，更新注释。
- `frontend/e2e/data/file-list-selection.spec.ts`（新建）：FIX-1 的刷新保留判据。
- `frontend/e2e/data/file-list-activation.spec.ts`（新建）：FIX-4 的五类请求计数。
- `docs/tasks/todo.md`：本刀台账与门禁记录。

---

### Task 1: `out_of_memory` 码表 + T2

**Files:**
- Modify: `frontend/src/utils/error.ts`
- Modify: `frontend/test/unit/error.spec.ts`

- [ ] **Step 0: 从 master 开分支**

```bash
git switch -c feature/batch4c-data-refresh master
```

Expected: `Switched to a new branch 'feature/batch4c-data-refresh'`

- [ ] **Step 1: 写失败测试**

在 `frontend/test/unit/error.spec.ts` 的高频守卫码列表里加入 `'out_of_memory'`：

```ts
    for (const code of ['no_valid_params', 'no_site_column', 'no_data', 'no_serial_column', 'out_of_memory']) {
      expect(ERROR_CODE_MAP[code]).toBeTruthy()
    }
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run test/unit/error.spec.ts
```

Expected: FAIL（`out_of_memory` 未映射）。

- [ ] **Step 3: 加映射**

`frontend/src/utils/error.ts` 的 `ERROR_CODE_MAP` 加一行（置于合适位置，保持 snake_case）：

```ts
  out_of_memory: '服务器内存不足，请关闭其他任务后重试',
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run test/unit/error.spec.ts
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/utils/error.ts frontend/test/unit/error.spec.ts
git commit -m "fix(utils): 补 out_of_memory 错误码中文映射"
```

---

### Task 2: FIX-1 刷新保留勾选

**Files:**
- Modify: `frontend/src/pages/data/components/FileListTable.vue:25`
- Test: `frontend/e2e/data/file-list-selection.spec.ts`（新建）

**Interfaces:**
- Consumes: 表格已有的 `:row-key="(row) => row.id"`；工具栏 `selectedCount` 由 `selection-change` 驱动。

- [ ] **Step 1: 写失败 e2e**

新建 `frontend/e2e/data/file-list-selection.spec.ts`：

```ts
import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadMultipleFiles, expectUploadSuccess } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { loginAs } from '../helpers/auth'

/**
 * FIX-1：列表刷新不得吞掉刚勾选的行。
 * 旧实现整份替换 files[] 会清空 EP 内建 selection，工具栏 selectedCount 随之归零。
 * 判据不靠时序：等两行都可见后再勾，刷新完成后直接读按钮上的计数。
 */
const PREFIX = 'e2e_fix1_sel_'
let seq = 0
let paths: string[] = []

async function uploadSingles(page: Page, count: number): Promise<string[]> {
  const stamp = `${Date.now()}_${seq++}`
  const out: string[] = []
  for (let i = 0; i < count; i++) {
    const p = path.join(os.tmpdir(), `${PREFIX}${stamp}_${i}.csv`)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, p)
    out.push(p)
  }
  const uploadVisible = await page.locator('.content-section:visible .upload-section').isVisible().catch(() => false)
  if (!uploadVisible) {
    await page.locator('button').filter({ hasText: '上传文件' }).click()
  }
  await uploadMultipleFiles(page, out)
  await expectUploadSuccess(page)
  paths.push(...out)
  return out
}

function rowByName(page: Page, name: string) {
  return page
    .locator('.content-section:visible .el-table .el-table__row')
    .filter({ hasText: name })
}

function bulkDeleteButton(page: Page) {
  return page.locator('button').filter({ hasText: /批量删除/ })
}

test.describe('文件列表刷新保留勾选', { tag: ['@p2', '@data'] }, () => {
  test.afterAll(async ({ browser }) => {
    for (const p of paths) cleanupQuiet(p)
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, PREFIX)
    await ctx.close()
  })

  test('勾选 2 行后触发列表刷新，selectedCount 仍为 2', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')
    await gotoApp(page, '/data')
    const first = await uploadSingles(page, 2)
    for (const p of first) {
      await expect(rowByName(page, path.basename(p))).toBeVisible({ timeout: 15_000 })
    }
    for (const p of first) {
      await rowByName(page, path.basename(p)).locator('.el-checkbox').first().click()
    }
    await expect(bulkDeleteButton(page)).toContainText('批量删除 (2)')

    // 触发一次列表刷新：再上传 1 个文件 → filesVersion → loadFiles 整份替换。
    const extra = await uploadSingles(page, 1)
    await expect(rowByName(page, path.basename(extra[0]))).toBeVisible({ timeout: 15_000 })

    // FIX-1 正判据：刷新后 selectedCount 仍是 2（旧实现会回到「批量删除」无计数）。
    await expect(bulkDeleteButton(page)).toContainText('批量删除 (2)')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/file-list-selection.spec.ts --project=P2 --workers=1
```

Expected: FAIL，最后一条 `批量删除 (2)` 找不到（刷新后变成 `批量删除`）。

- [ ] **Step 3: 加 `reserve-selection`**

`frontend/src/pages/data/components/FileListTable.vue:25` 改为：

```html
      <el-table-column type="selection" width="44" align="center" reserve-selection />
```

（表格已有 `:row-key="(row: any) => row.id"`，无需再加。）

- [ ] **Step 4: 跑测试确认通过**

同 Step 2 命令。Expected: `1 passed`（加 2 条 auth.setup 共 3 passed）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/components/FileListTable.vue frontend/e2e/data/file-list-selection.spec.ts
git commit -m "fix(data): 文件列表刷新保留勾选"
```

---

### Task 3: FIX-4 sibling loader 激活刷新

**Files:**
- Modify: `frontend/src/pages/data/components/FileListTab.vue:77,408-434`
- Test: `frontend/e2e/data/file-list-activation.spec.ts`（新建）

**Interfaces:**
- Consumes: 父页 `DataManagement.vue` 的 `onActivated(loadFiles)` 继续负责 `/files/?page_size=9999`；本任务只让子组件 `FileListTab` 的 `loadFiles`（分页列表）+ 三个下拉 loader 随激活刷新。

- [ ] **Step 1: 写失败 e2e**

新建 `frontend/e2e/data/file-list-activation.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import { gotoApp, navByMenu } from '../helpers/nav'

/**
 * FIX-4：四个 sibling loader 与占用 chip 一样随激活刷新。
 * 从仪表板客户端路由回 /data，六类请求各恰好一次：
 * 父页全量列表（page_size=9999）、子页分页列表（file_type=single）、
 * product_codes、format_types、list_tags、usage。
 */
test.describe('数据管理激活刷新 sibling loaders', { tag: ['@p2', '@data'] }, () => {
  test('从仪表板回数据管理：六类请求各一次', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 20_000 })

    await navByMenu(page, '仪表板')
    await expect(page.getByTestId('page-identity')).toContainText('仪表板')

    const hits = {
      fullList: 0,
      pageList: 0,
      productCodes: 0,
      formatTypes: 0,
      tags: 0,
      usage: 0,
    }
    page.on('request', (r) => {
      const url = r.url()
      if (!url.includes('/api/v1/files/')) return
      if (url.includes('/files/usage/')) hits.usage++
      else if (url.includes('/files/product_codes/')) hits.productCodes++
      else if (url.includes('/files/format_types/')) hits.formatTypes++
      else if (url.includes('/files/list_tags/')) hits.tags++
      else if (/\/files\/\?page_size=9999(&|$)/.test(url)) hits.fullList++
      else if (/\/files\/\?(.*&)?file_type=single/.test(url)) hits.pageList++
    })

    await navByMenu(page, '数据管理')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 15_000 })

    await expect.poll(() => ({ ...hits }), { timeout: 15_000 }).toEqual({
      fullList: 1,
      pageList: 1,
      productCodes: 1,
      formatTypes: 1,
      tags: 1,
      usage: 1,
    })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/file-list-activation.spec.ts --project=P2 --workers=1
```

Expected: FAIL；`pageList/productCodes/formatTypes/tags` 计数为 0（仍只挂在 onMounted）。

- [ ] **Step 3: 迁到 `onActivated`**

`frontend/src/pages/data/components/FileListTab.vue`：

1. 第 77 行 import 去掉 `onMounted`（若文件其它地方无使用）：
```ts
import { ref, computed, reactive, watch, onActivated } from 'vue'
```
2. 删除 `onMounted(() => { loadFiles(); loadProductCodes(); loadFormatTypes(); loadAllTags() })` 整块。
3. 把 `onActivated` 改为：
```ts
// FIX-4（2026-11-17）：四个 sibling loader 与占用 chip 同一口径，全部挂 onActivated。
// keep-alive 下 mounted 一个会话只跑一次；Explorer 直接拷文件进来 / 切页回来都要看到新列表。
// 首进 mounted+activated 都触发，所以只挂 activated 恰好一次；判据
// `e2e/data/file-list-activation.spec.ts`（六类请求各一次）与 `data.spec.ts`
// 的「全量文件列表只拉一次」对照。
onActivated(() => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
  loadUsage()
})
```
4. 更新上方长注释的末段：删掉「另外四个 loader 仍挂在 onMounted（没跟着走 activated）是既有行为，本批不改」整句，改为指向 FIX-4 的新口径（激活级、首进只一次、判据文件名）。

- [ ] **Step 4: 跑测试确认通过**

同 Step 2 命令。Expected: `1 passed`（加 2 条 auth.setup 共 3 passed）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/components/FileListTab.vue frontend/e2e/data/file-list-activation.spec.ts
git commit -m "fix(data): 文件列表四个 loader 随激活刷新"
```

---

### Task 4: 台账与全量门禁

**Files:**
- Modify: `docs/tasks/todo.md`

- [ ] **Step 1: 追加本刀条目**

```markdown
# 任务：批4 刀三（列表刷新保留勾选 + 激活刷新 + out_of_memory，2026-11-17）

设计：`docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §10（FIX-1 / FIX-4）
计划：`docs/superpowers/plans/2026-11-17-batch4c-data-refresh.md`

## 勾选清单

- [ ] `out_of_memory` 码表 + T2
- [ ] FIX-1 `reserve-selection` + 刷新保留 e2e
- [ ] FIX-4 四个 loader 迁 `onActivated` + 六类请求 e2e
- [ ] 全量门禁（GLOBAL）
- [ ] 并入 master（需用户点头；不 push）

## 门禁记录

| 档 | 命令 | 实测判据行 |
|---|---|---|
| T2 | `npx vitest run test/unit/error.spec.ts` | |
| FIX-1 | `npx playwright test e2e/data/file-list-selection.spec.ts --project=P2 --workers=1` | |
| FIX-4 | `npx playwright test e2e/data/file-list-activation.spec.ts --project=P2 --workers=1` | |
| 全量 vitest | `npx vitest run` | |
| e2e 类型 | `npm run lint:e2e` | |
| 前端构建 | `npm run build` | |
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | |
| 后端全套 | `manage.py test` | |
```

- [ ] **Step 2: 全量门禁**

```bash
cd frontend && npx vitest run
cd frontend && npm run lint:e2e
cd frontend && npm run build
node scripts/e2e_pool.mjs --slots=4
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test
```

一条命令一档；池与后端可并行。填表取原文。

- [ ] **Step 3: 提交与并入（需用户点头；不 push）**

```bash
git add docs/tasks/todo.md docs/superpowers/plans/2026-11-17-batch4c-data-refresh.md
git commit -m "docs(todo): 批4 刀三收口门禁"
git merge-base --is-ancestor master HEAD
git switch master
git merge --ff-only feature/batch4c-data-refresh
git branch -d feature/batch4c-data-refresh
git status --short
```

---

## 自审

**Spec 覆盖：** FIX-1（Task 2）、FIX-4（Task 3）、`out_of_memory`（Task 1）、全量门禁（Task 4）。两条 e2e 判据分开写，符合设计 §10 的硬要求。

**占位符：** 无；代码、命令、断言均为可执行原文。

**类型一致：** `reserve-selection` 依赖的 `row-key` 已存在；FIX-4 只改子组件，父页 `onActivated(loadFiles)` 不动；`out_of_memory` 键为 snake_case。

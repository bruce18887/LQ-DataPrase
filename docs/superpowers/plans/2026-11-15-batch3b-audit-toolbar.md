# 批3b（一）· 操作审计页统一 toolbar 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把操作审计页的筛选卡片改成一条「左条件 / 右查询」的工具栏，并产出两页共用的工具栏壳 `AdminPageToolbar.vue`；用户管理页在第二份计划里消费同一个壳。

**Architecture:** 新增 `pages/admin/components/AdminPageToolbar.vue`（左/右命名 slot、空槽不渲染包裹层、宽度 token 抄 `SearchCriteria.vue` 的 `flex: 1 1 260px; min-width: 180px` 一族）。审计页用一层 `<el-form>` 包住壳：左槽四颗筛选 + 重置，右槽查询按钮（`native-type="submit"` 仍能提交，因为按钮在 form 的后代里）。判据分两层：T2 源码接线（testid 仍挂在 `el-form-item`、宽度类绑在控件上），T3 实测盒宽（阈值就是修复后声明的 160 / 180 / 190，不凑常数）。

**Tech Stack:** Vue 3 + Element Plus 2.14.0、vitest（T2，node 环境、不装 jsdom、不用 `@vue/test-utils`）、Playwright（T3，单 spec 走 `scripts/e2e_pool.mjs`）。

**Spec:** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §6.1–§6.4 与 §7.7。测试分层与门禁节奏看 `docs/reference/testing-gates.md`，本文件不重复正文。

**执行顺序：** 本计划必须先于 `docs/superpowers/plans/2026-11-15-batch3b-user-management-toolbar.md` 执行——它产出的 `AdminPageToolbar.vue` 是两份计划共用的壳。第二份计划负责批次级主题收敛（`element-plus-theme.css` 的 `.el-select__wrapper`）、介绍书构建与最终收口全量档；本计划只跑 affected 档和目标 T3，**不**重复跑批次收口全量。

---

## Global Constraints

- 前端 Vue 单文件不超过 **600 行**（`.claude/CLAUDE.md`；判据 `scripts/line-limit.mjs`，`.vue` 数整个 SFC）。
- 任何前端改动同时维护 **light 与 night** 两套主题；本计划新增的工具栏与控件只允许用语义 token（`--bg-*` / `--text-*` / `--border-*` / `--p-space-*` / `--p-fs-*`）。
- 判绿取日志末尾的 `Tests N passed` / `RESULT:` 行，**不取 `$?`**；输出整段落盘再 grep，禁 `| tail`。
- 单文件 e2e 走池：`node scripts/e2e_pool.mjs --slots=1 -- <spec>`，不裸跑 playwright（裸跑会自己抢 8000/3000 端口）。
- 本计划**不碰**另一会话未提交的 `apps/export/*` 四个文件，不 stage、不 commit。
- 不 push；`origin` 是公开仓库。

## 0. 开工前必读的六条事实（2026-11-15 现量）

1. **行数闸**：`frontend/src/pages/admin/AuditLogPage.vue` = **250 行**；`frontend/test/unit/audit.spec.ts` = **594/600 行** ⇒ 本批一行都不许往 `audit.spec.ts` 里加，新增 T2 另起文件。新文件受通用 600 行闸，全部远低于阈值。
2. **e2e 契约**（spec §6.4，必须继续成立）：
   - 8 个 `data-testid` 挂在**包裹层**：审计页四个 `audit-event|audit-username|audit-date-from|audit-date-to`；用户管理页四个 `edit-username|edit-display-name|edit-email|edit-role`（后者在第二份计划里随对话框迁移）。
   - `ElInput` 是 `inheritAttrs: false` 且把 attrs 并到原生 input 上 ⇒ testid 写 `<el-input>` 上时 `[data-testid] input` 会命中 0 个；必须继续挂 `el-form-item`。
   - `.audit-table`（`audit.spec.ts:115/215`）、列序 `td:nth-child(3)` = 事件（`:278`）、`.el-pagination__sizes .el-select`、`.el-table__expand-icon` 全部保留。
3. **T2 源码绊线**：`frontend/test/unit/auditFormat.spec.ts:101-111,146-168` 剥注释扫描 `AuditLogPage.vue`，要求 `AUDIT_PAGE_SIZE_DEFAULT` / `AUDIT_PAGE_SIZE_MAX` / `USERNAME_QUERY_MAX` 三个常量名留在代码行里，且禁止 `maxlength="150"` 与 `[20, 50, 100]` 字面量 ⇒ 改造时 import 与 `pageSizes` 保持原样。
4. **EP 定位器两条实测**（`audit.spec.ts:29-34`）：testid 挂 `el-form-item`；非 filterable 的 `el-select` 点外层 `.el-select`，不点里面被排出文档流的 input。
5. **affected 判据**（`scripts/affected-rules.mjs`）：`frontend/src/pages/admin/` → `admin` 模块；`frontend/test/` → `unit`；本计划不碰 `frontend/src/styles/`（全局清单）。实际档位以 `npm run test:e2e:affected` 现判为准，命中模块数 >6 才升全量。
6. **宽度语言**：抄 `frontend/src/pages/sftp/components/SearchCriteria.vue:504` 的 `min-width: 0` 与 `:542` 的 `flex: 1 1 260px; min-width: 180px`，不新造一套宽度语言。下拉 160、日期 190 是同一族的定宽档（`SearchCriteria.vue:506/551` 的先例）。

## 1. 文件地图

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/src/pages/admin/components/AdminPageToolbar.vue` | 两页共用的工具栏壳：左右命名 slot、空槽不渲染、宽度 token | 新建（Task 1） |
| `frontend/test/unit/adminToolbarWiring.spec.ts` | 壳与审计页的源码接线 T2（自有判据，不塞 `audit.spec.ts`） | 新建（Task 1/2） |
| `frontend/src/pages/admin/AuditLogPage.vue` | 筛选卡片 → 工具栏接线 | 改模板/import/style（Task 2） |
| `frontend/e2e/admin/audit.spec.ts` | 既有契约用例 + 新增实测盒宽用例 | 追加一条 T3（Task 2） |
| `docs/intro/.vitepress/theme/components/AuditMock.vue` | 介绍书里的审计复刻：重置在左、查询在右 | 改工具栏顺序（Task 3） |

不动的：`frontend/test/unit/audit.spec.ts`（594/600，逐字不动）、`frontend/src/utils/audit.ts`（纯层零改动）、`design-tokens.css`（只用既有 token）。

---

## Task 1: 共享壳 `AdminPageToolbar.vue` + 壳的 T2 判据

**Files:**
- Create: `frontend/src/pages/admin/components/AdminPageToolbar.vue`
- Create: `frontend/test/unit/adminToolbarWiring.spec.ts`

**Interfaces:**
- Produces:
  - 命名 slot：`left`（左条件组）、`right`（右动作组）。
  - 壳提供的宽度类：`.admin-filter-input`（`flex: 1 1 260px; min-width: 180px`）、`.admin-filter-select`（`width: 160px`）、`.admin-filter-date`（`width: 190px`）。
  - 空槽语义：`$slots.left` / `$slots.right` 不存在时不渲染对应包裹层（用户管理页左槽留空，不出现空占位）。

- [ ] **Step 1: 写失败的壳判据**

创建 `frontend/test/unit/adminToolbarWiring.spec.ts`：

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const SHELL = '../../src/pages/admin/components/AdminPageToolbar.vue'

describe('AdminPageToolbar：两页共用的壳', () => {
  it('左右两个命名 slot 都在，且空槽不渲染包裹层', () => {
    const code = read(SHELL)
    expect(code).toContain('<slot name="left" />')
    expect(code).toContain('<slot name="right" />')
    expect(code).toMatch(/v-if="\$slots\.left"/)
    expect(code).toMatch(/v-if="\$slots\.right"/)
  })

  it('宽度语言与 SearchCriteria 同源：输入可压到 180、下拉 160、日期 190', () => {
    const code = read(SHELL)
    expect(code).toMatch(/\.admin-filter-input[^}]*min-width:\s*180px/s)
    expect(code).toMatch(/\.admin-filter-select[^}]*width:\s*160px/s)
    expect(code).toMatch(/\.admin-filter-date[^}]*width:\s*190px/s)
  })

  it('只吃语义 token，不写死颜色/字号（双主题的前提）', () => {
    const code = read(SHELL)
    expect(code).toContain('var(--bg-3)')
    expect(code).toContain('var(--border-2)')
    expect(code).not.toMatch(/(?:^|[^\w-])font-size:\s*\d+(?:\.\d+)?px/m)
    expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
```

- [ ] **Step 2: 跑 T2，确认它先红**

Run:
```bash
cd frontend && npx vitest run test/unit/adminToolbarWiring.spec.ts 2>&1
```
Expected: FAIL，`ENOENT` 指向 `src/pages/admin/components/AdminPageToolbar.vue`。

- [ ] **Step 3: 创建壳（逐字如下）**

创建 `frontend/src/pages/admin/components/AdminPageToolbar.vue`：

```vue
<template>
  <div class="admin-page-toolbar">
    <div v-if="$slots.left" class="admin-page-toolbar__left">
      <slot name="left" />
    </div>
    <div v-if="$slots.right" class="admin-page-toolbar__right">
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
.admin-page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-3);
  margin-bottom: var(--p-space-3);
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

.admin-page-toolbar__left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  flex: 1 1 auto;
  min-width: 0;
}

.admin-page-toolbar__right {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  flex: 0 0 auto;
  margin-left: auto;
}

/* 宽度语言与 pages/sftp/components/SearchCriteria.vue:504/542 同源：
   flex-basis 给「还能呼吸」的宽度，min-width 允许被压短但不许压成一条缝。 */
.admin-page-toolbar :deep(.admin-filter-input) {
  flex: 1 1 260px;
  min-width: 180px;
}

.admin-page-toolbar :deep(.admin-filter-select) {
  width: 160px;
}

.admin-page-toolbar :deep(.admin-filter-date) {
  width: 190px;
}
</style>
```

- [ ] **Step 4: 跑 T2，确认转绿**

Run:
```bash
cd frontend && npx vitest run test/unit/adminToolbarWiring.spec.ts 2>&1
```
Expected: `Tests 3 passed (3)`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/admin/components/AdminPageToolbar.vue frontend/test/unit/adminToolbarWiring.spec.ts
git commit -m "feat(frontend): 新增管理页共用的工具栏壳（批3b）"
```

---

## Task 2: 审计页接线 + 实测盒宽 T3

**Files:**
- Modify: `frontend/src/pages/admin/AuditLogPage.vue:3-48`（筛选卡片整块）、`:106-122`（import）、`:196-198`（旧表单边距规则）
- Modify: `frontend/test/unit/adminToolbarWiring.spec.ts`（追加审计页接线判据）
- Modify: `frontend/e2e/admin/audit.spec.ts`（追加一条 `@p2` 实测盒宽用例）

**Interfaces:**
- Consumes: `AdminPageToolbar.vue` 的 `left` / `right` slot 与三个宽度类（Task 1）。
- Produces: 审计页 DOM 形状 `el-form.audit-filter-form > .admin-page-toolbar > .admin-page-toolbar__left/__right`；四个 testid 仍挂在 `el-form-item` 上；`[data-testid=audit-username] .el-input` / `[data-testid=audit-event] .el-select` / 两个 `[data-testid=audit-date-*] .el-date-editor` 可被 T3 量到 160 / 180 / 190 的下限。

- [ ] **Step 1: 追加失败的 T2 接线判据**

在 `frontend/test/unit/adminToolbarWiring.spec.ts` 末尾追加：

```ts
const AUDIT = '../../src/pages/admin/AuditLogPage.vue'

const codeOf = (text: string): string =>
  text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')

describe('审计页接线：testid 不挪窝、宽度类真绑上', () => {
  it('四个 data-testid 仍挂在 el-form-item 上，不挪到控件上', () => {
    const code = codeOf(read(AUDIT))
    for (const id of ['audit-event', 'audit-username', 'audit-date-from', 'audit-date-to']) {
      expect(code, `${id} 不在 el-form-item 上`).toMatch(
        new RegExp(`<el-form-item[^>]*data-testid="${id}"`),
      )
      expect(code, `${id} 被挪到了控件上`).not.toMatch(
        new RegExp(`<(?:el-input|el-select|el-date-picker)[^>]*data-testid="${id}"`),
      )
    }
  })

  it('五颗筛选控件真的带上了宽度类', () => {
    const code = read(AUDIT)
    expect(code).toMatch(/<el-select[^>]*class="admin-filter-select"/)
    expect(code).toMatch(/<el-input[^>]*class="admin-filter-input"/)
    expect(code.match(/<el-date-picker[^>]*class="admin-filter-date"/g) ?? []).toHaveLength(2)
  })

  it('工具栏走壳的左右两个命名槽：重置在左、查询在右', () => {
    const code = read(AUDIT)
    expect(code).toContain('<AdminPageToolbar>')
    const left = code.slice(code.indexOf('<template #left>'), code.indexOf('</template>', code.indexOf('<template #left>')))
    const right = code.slice(code.indexOf('<template #right>'))
    expect(left, '重置没有留在左槽').toContain('重置')
    expect(right, '查询没有落在右槽').toContain('查询')
  })
})
```

- [ ] **Step 2: 追加失败的 T3 实测盒宽用例**

在 `frontend/e2e/admin/audit.spec.ts` 的 `test.describe('操作审计', ...)` 内追加：

```ts
  test('@p2 工具栏：四颗筛选控件的实测盒宽不低于声明下限', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '操作审计').click()
    await expect(page).toHaveURL(/\/admin\/audit/)
    const box = page.locator('.admin-page-toolbar')
    await expect(box).toBeVisible()
    await expect(page.locator('[data-testid="audit-username"] .el-input')).toBeVisible()

    const widths = await page.evaluate(() => {
      const rect = (sel: string): number => {
        const el = document.querySelector(sel)
        return el ? el.getBoundingClientRect().width : 0
      }
      return {
        event: rect('[data-testid="audit-event"] .el-select'),
        username: rect('[data-testid="audit-username"] .el-input'),
        from: rect('[data-testid="audit-date-from"] .el-date-editor'),
        to: rect('[data-testid="audit-date-to"] .el-date-editor'),
      }
    })

    // 阈值就是修复后 CSS 的声明值：select 160、input min-width 180、date 190。
    // 不断「等于」：flex-basis 260 允许在宽视口里长，判据只防「被压成一条缝」。
    expect(widths.event, '事件下拉被压窄了').toBeGreaterThanOrEqual(160)
    expect(widths.username, '账号输入框被压到 180 以下').toBeGreaterThanOrEqual(180)
    expect(widths.from, '起日期被压窄了').toBeGreaterThanOrEqual(190)
    expect(widths.to, '止日期被压窄了').toBeGreaterThanOrEqual(190)
  })
```

- [ ] **Step 3: 跑红（T2 与 T3 各一次）**

Run:
```bash
cd frontend && npx vitest run test/unit/adminToolbarWiring.spec.ts 2>&1
```
Expected: FAIL，审计页接线三条红（还没有 `AdminPageToolbar` / 宽度类）。

Run:
```bash
node scripts/e2e_pool.mjs --slots=1 -- e2e/admin/audit.spec.ts 2>&1
```
Expected: 新加那条红在 `.admin-page-toolbar` 不可见；既有契约用例应仍绿（旧页面的 testid 未动）。

- [ ] **Step 4: 改审计页（整块替换）**

把 `frontend/src/pages/admin/AuditLogPage.vue` 顶部 `:3-48` 的 `<el-card class="filter-card">…</el-card>` 整块替换为：

```vue
    <el-form
      :model="filters"
      inline
      class="audit-filter-form"
      @submit.prevent="applyFilters"
    >
      <AdminPageToolbar>
        <template #left>
          <!-- data-testid 仍挂 el-form-item：ElInput 是 inheritAttrs:false 且把 attrs 并到原生
               input 上，挂 el-input 上时「[data-testid] input」会命中 0 个；非 filterable 的
               el-select 点外层 .el-select，不点那个被排出文档流的 input。 -->
          <el-form-item label="事件" data-testid="audit-event">
            <el-select
              v-model="filters.event"
              clearable
              placeholder="全部事件"
              class="admin-filter-select"
            >
              <el-option
                v-for="(label, code) in AUDIT_EVENT_LABELS"
                :key="code"
                :label="label"
                :value="code"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="账号" data-testid="audit-username">
            <el-input
              v-model="filters.username"
              placeholder="操作者或目标账号"
              clearable
              :maxlength="USERNAME_QUERY_MAX"
              class="admin-filter-input"
            />
          </el-form-item>
          <el-form-item label="起" data-testid="audit-date-from">
            <el-date-picker
              v-model="filters.dateFrom"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="开始日期"
              class="admin-filter-date"
            />
          </el-form-item>
          <el-form-item label="止" data-testid="audit-date-to">
            <el-date-picker
              v-model="filters.dateTo"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="结束日期"
              class="admin-filter-date"
            />
          </el-form-item>
          <el-button @click="resetFilters">重置</el-button>
        </template>
        <template #right>
          <el-button type="primary" native-type="submit">查询</el-button>
        </template>
      </AdminPageToolbar>
    </el-form>
```

在 `<script setup>` 的 import 区（`AuditLogPage.vue:106-122`）末尾追加：

```ts
import AdminPageToolbar from './components/AdminPageToolbar.vue'
```

把 `AuditLogPage.vue:196-198` 这两条旧规则：

```css
.filter-card :deep(.el-form--inline .el-form-item) {
  margin-bottom: 0;
}
```

替换为：

```css
.audit-filter-form :deep(.el-form-item) {
  margin: 0;
}
```

> 为什么 `el-form` 包在壳外面：查询按钮用 `native-type="submit"` 留在 `<form>` 后代里，Enter 提交与点按钮走同一条 `@submit.prevent="applyFilters"`；把 form 只包左槽会让右槽按钮变成不会提交的普通按钮。

- [ ] **Step 5: 跑绿（T2 + T3）**

Run:
```bash
cd frontend && npx vitest run test/unit/adminToolbarWiring.spec.ts 2>&1
```
Expected: `Tests 6 passed (6)`。

Run:
```bash
node scripts/e2e_pool.mjs --slots=1 -- e2e/admin/audit.spec.ts 2>&1
```
Expected: 汇总行 `unexpected 0`，且包含新加的那条 `@p2 工具栏`。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/admin/AuditLogPage.vue frontend/test/unit/adminToolbarWiring.spec.ts frontend/e2e/admin/audit.spec.ts
git commit -m "feat(frontend): 操作审计页改用统一 toolbar 壳（批3b）"
```

---

## Task 3: 介绍书复刻的审计工具栏对齐

**Files:**
- Modify: `docs/intro/.vitepress/theme/components/AuditMock.vue:22-30`

- [ ] **Step 1: 改复刻工具栏（左条件 + 重置，右查询）**

把 `AuditMock.vue` 的 `<div class="m-toolbar">…</div>` 整块替换为：

```vue
    <div class="m-toolbar">
      <select v-model="ev" class="m-select"><option value="">全部事件</option><option v-for="e in AU_EVENTS" :key="e" :value="e">{{ e }}</option></select>
      <input v-model="acct" class="m-input" placeholder="账号" style="width:120px">
      <input v-model="from" type="date" class="m-input">
      <span class="m-label">至</span>
      <input v-model="to" type="date" class="m-input">
      <button class="m-btn" @click="reset">重置</button>
      <span class="grow"></span>
      <button class="m-btn pri" @click="toast('审计查询完成（演示）· 筛选口径即时生效')">查询</button>
    </div>
```

- [ ] **Step 2: 自证不是假文档**

Run:
```bash
node scripts/intro/check.mjs 2>&1
```
Expected: PASS（末行 PASS；本步不跑 `intro:build`，构建与两页一起在第二份计划的收口档执行）。

- [ ] **Step 3: 提交**

```bash
git add docs/intro/.vitepress/theme/components/AuditMock.vue
git commit -m "docs(intro): 审计复刻工具栏对齐左右槽（批3b）"
```

---

## Task 4: 本计划的 affected 门禁

本计划是批3b 的中间切片：完整的收口全量档（全量池 + 后端全套 + 介绍书构建）在第二份计划最后一步跑。本步只证明「审计页这一刀 + 共享壳」自身是干净的。

- [ ] **Step 1: T2 全量**

Run:
```bash
cd frontend && npx vitest run 2>&1 | tee ../tasks/b3b_audit_vitest.log
```
Expected: 末尾 `Test Files N passed (N)` / `Tests M passed (M)`；用 `grep -c "failed"` 核对为 0。

- [ ] **Step 2: e2e 类型与构建**

Run:
```bash
cd frontend && npm run lint:e2e 2>&1 | tee ../tasks/b3b_audit_lint.log
cd frontend && npm run build 2>&1 | tee ../tasks/b3b_audit_build.log
```
Expected: `error TS` 0 处；`✓ built in …`。

- [ ] **Step 3: 行数闸**

Run:
```bash
cd frontend && npx vitest run test/unit/lineLimit.spec.ts 2>&1 | tee ../tasks/b3b_audit_linelimit.log
```
Expected: `Tests 15 passed (15)`；本计划不给任何文件加豁免。

- [ ] **Step 4: affected**

Run:
```bash
cd frontend && npm run test:e2e:affected 2>&1 | tee ../tasks/b3b_audit_affected.log
```
Expected: 末行 `RESULT: PASS`；计划档位应至少含 `unit` 与 `e2e:admin`。若现判命中 >6 模块升全量，也算 PASS，但**不要**把它当批次收口档（收口在第二份计划）。

- [ ] **Step 5: 提交台账（可并入 Task 3 的 docs 提交）**

把上面四份日志的判据行写进 `docs/tasks/todo.md` 的批3b 条目（第二份计划会补全整批）。本步不改产品代码。

---

## 收口口径（交给第二份计划）

- 本计划结束时，`AdminPageToolbar.vue` 已存在且审计页在用它；用户管理页仍是旧 KPI 卡片 + 页底添加表单，**这是预期的中间态**。
- 第二份计划必须在本计划的 `admin` affected 绿之后开工；它负责 `UserManagement.vue`、`UserFormDialog.vue`、`UserKpiChips.vue`、`roleLabelHygiene.spec.ts` 的迁移、两处死规则收敛、night `.el-select__wrapper` 的 T3、介绍书构建与批次收口全量。

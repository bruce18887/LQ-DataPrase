# 批3b（二）· 用户管理页统一 toolbar 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户管理页改成「KPI chip 行 + 一条工具栏（左槽留空、右槽新增账号）+ 表格 + 共用表单对话框」，同时收敛 `UserManagement.vue` 与全局主题层两处 `.el-select .el-input__wrapper` 死规则，并完成批3b 的收口门禁。

**Architecture:** 页面拆成三个组件：`UserKpiChips.vue`（四颗 chip + EP 矢量图标）、`UserFormDialog.vue`（新增/编辑共用，按 `mode` 分叉载荷）、`AdminPageToolbar.vue`（第一份计划已产出，本计划只消费）。页面本体只保留表格、行操作与数据装载；表单态与提交载荷类型放进 `userFormTypes.ts`。判据分三层：T2 源码接线（emoji 清零、testid 位置、角色下拉归位、死规则消失）、T3 行为（新增/编辑/删除流程与 KPI chip 的 SVG 图标）、T3 主题（night 下 `.el-select__wrapper` 覆写真的生效）。

**Tech Stack:** Vue 3 + Element Plus 2.14.0、`@element-plus/icons-vue`、vitest（T2，node 环境）、Playwright（T3，单 spec 走 `scripts/e2e_pool.mjs`）。

**Spec:** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §6.2–§6.6 与 §7.7/§7.9。测试分层与门禁节奏看 `docs/reference/testing-gates.md`。

**执行顺序：** 本计划必须在 `docs/superpowers/plans/2026-11-15-batch3b-audit-toolbar.md` **之后**执行——它消费那份计划产出的 `AdminPageToolbar.vue`。本计划负责批3b 的**唯一一次**收口全量档（全量池 + 后端全套）与介绍书构建。

---

## Global Constraints

- 前端 Vue 单文件不超过 **600 行**（`.claude/CLAUDE.md`；判据 `scripts/line-limit.mjs`，`.vue` 数整个 SFC）。
- 任何前端改动同时维护 **light 与 night** 两套主题；新增颜色/间距/字号一律走语义 token。
- 判绿取日志末尾的 `Tests N passed` / `RESULT:` / `Ran N tests ... OK` 行，**不取 `$?`**；输出整段落盘再 grep，禁 `| tail`。
- 单文件 e2e 走池：`node scripts/e2e_pool.mjs --slots=1 -- <spec>`。
- 本计划**不碰**另一会话未提交的 `apps/export/*` 四个文件；收口后端全量会包含它们，台账里要注明。
- 不 push；`origin` 是公开仓库。

## 0. 开工前必读的七条事实（2026-11-15 现量）

1. **行数闸**：`frontend/src/pages/admin/UserManagement.vue` = **578/600 行**（本计划必须先拆再改）；`frontend/test/unit/audit.spec.ts` = **594/600 行** ⇒ 一行都不许往它里加；`frontend/e2e/admin/admin.spec.ts` = **427 行**（本计划新增约 70 行，仍在 600 内）。
2. **e2e 契约**（spec §6.4）：四个 `edit-*` testid 继续挂在 `el-form-item` 上；`admin.spec.ts:294` 的 `[data-testid="edit-username"] input`、`:322` 的 `[data-testid="edit-role"] .el-select` 形状必须可用。页底添加表单的定位 `.user-management .el-form .el-form-item`（`:31-34`）在对话框 `append-to-body` 后会脱离 `.user-management` 祖先 ⇒ 必须改成对话框作用域 + `create-*` testid。
3. **`roleLabelHygiene.spec.ts:136-146`** 把「所有角色下拉」钉在 `UserManagement.vue`。两个下拉迁进 `UserFormDialog.vue` 后，这条判据的目标文件必须跟着搬（否则 `blocks.length === 0` 先红）；`delegation` 那条仍钉 `UserManagement.vue`（表格里的 `roleLabel`）。
4. **死规则两处**：`UserManagement.vue:555` 的 `:deep(.el-select .el-input__wrapper)` 与 `src/styles/element-plus-theme.css:598` 的 night 规则在 EP 2.14 **恒不命中**（theme-chalk 里真类名是 `.el-select__wrapper`）。本批两处一起清，并把 night 触发区底色/边框改由 `.el-select__wrapper` 承载。
5. **EP 状态类**（`frontend/node_modules/element-plus/theme-chalk/el-select.css` 现查）：`.el-select__wrapper.is-focused`、`.el-select__wrapper.is-hovering:not(.is-focused)`。night 覆写必须同时给这两态留焦点/悬停反馈，不能用一个静态 `!important box-shadow` 把焦点环抹掉。
6. **源码级字号守门**：`frontend/e2e/global/fonts.spec.ts:155` 扫 `frontend/src` 的所有 `.vue/.css/.ts`，禁硬编码 `font-size` / `fontSize` / `--*font-size: Npx`（装饰大字须写 `@type-scale-one-off`）。本计划新组件全部走 `--p-fs-*`。
7. **affected 判据**：`frontend/src/pages/admin/` → `admin`；`frontend/src/styles/` → **GLOBAL**（`scripts/affected-rules.mjs:177`）。本计划改 `element-plus-theme.css` ⇒ 收口前那次 affected 会升全量池 + 后端全套，和显式收口档同构；台账要记两边的判据行，但不要把同一棵树重复跑两轮之外的额外轮次。

## 1. 文件地图

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/src/pages/admin/components/UserKpiChips.vue` | 四颗 KPI chip + EP 矢量图标 | 新建（Task 1） |
| `frontend/src/pages/admin/components/userFormTypes.ts` | 新增/编辑载荷的判别联合类型 | 新建（Task 2） |
| `frontend/src/pages/admin/components/UserFormDialog.vue` | 新增/编辑共用对话框（含 `mode` 分叉、创建字段、编辑校验） | 新建（Task 2） |
| `frontend/test/unit/adminUserFormWiring.spec.ts` | 本计划全部 T2 源码接线判据 | 新建（Task 1/2/3/5） |
| `frontend/src/pages/admin/UserManagement.vue` | 薄页：chip 行 + 工具栏 + 表格 + 对话框 | 重写（Task 3） |
| `frontend/test/unit/roleLabelHygiene.spec.ts` | 角色下拉判据目标迁到 `UserFormDialog.vue` | 改 `FILES` 与第 ④ 组（Task 2） |
| `frontend/e2e/admin/admin.spec.ts` | 新增流程改对话框定位 + KPI chip 新用例 | 改 helper/四条用例 + 追加一条（Task 4） |
| `frontend/src/styles/element-plus-theme.css` | night select 触发区改 `.el-select__wrapper` | 改 `:597-600`（Task 5） |
| `frontend/src/pages/admin/AuditLogPage.vue` | 订正「两处死规则不在本批」的过期注释 | 只改注释（Task 5） |
| `frontend/e2e/theme/admin-select-theme.spec.ts` | night/light `.el-select__wrapper` 覆写 T3 | 新建（Task 5） |
| `docs/intro/.vitepress/theme/components/UsersMock.vue` | 复刻：去掉搜索框、按钮改「新增账号」 | 改模板/脚本（Task 6） |
| `docs/intro/guide/09-admin.md` | 两页文案同步 | 改一句（Task 6） |
| `docs/tasks/todo.md` | 批3b 收口台账 | 追加一节（Task 7） |

不动的：`frontend/test/unit/audit.spec.ts`（594/600）、`apps/accounts/*`（后端零改动）、`AdminPageToolbar.vue`（第一份计划产出，逐字消费）。

---

## Task 1: `UserKpiChips.vue` + chip 的 T2 判据

**Files:**
- Create: `frontend/src/pages/admin/components/UserKpiChips.vue`
- Create: `frontend/test/unit/adminUserFormWiring.spec.ts`

**Interfaces:**
- Produces: 组件 props `{ total: number; active: number; locked: number; admins: number }`；DOM 类 `.user-kpi-chips` > `.kpi-chip`（四个），每个 chip 内 `.el-icon > svg`。
- 图标固定：总用户 `UserFilled`、活跃 `CircleCheck`、锁定 `Lock`、管理员 `Stamp`。`Stamp` 是 spec §6.2 留下的二选一（`Medal` / `Stamp`）；本计划默认 `Stamp`，Task 6 的肉眼确认步若判定近形则换 `Medal`（只改 import 与 `chips` 一行）。

- [ ] **Step 1: 写失败的 T2（chip 部分）**

创建 `frontend/test/unit/adminUserFormWiring.spec.ts`：

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

/** 整行注释不参与判定：兜底理由与历史说明要能写在注释里。 */
const codeOf = (text: string): string =>
  text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')

const CHIPS = '../../src/pages/admin/components/UserKpiChips.vue'

describe('UserKpiChips：四个 chip、四个 EP 图标、零 emoji', () => {
  it('四个标签与四个 EP 图标都在', () => {
    const code = read(CHIPS)
    for (const label of ['总用户', '活跃', '锁定', '管理员']) {
      expect(code, `chip 少了「${label}」`).toContain(`label: '${label}'`)
    }
    for (const icon of ['UserFilled', 'CircleCheck', 'Lock', 'Stamp']) {
      expect(code, `chip 少了图标 ${icon}`).toContain(icon)
    }
  })

  it('代码行里没有 emoji（旧 KPI 的 👥✅🛡️ 不许复活）', () => {
    const code = codeOf(read(CHIPS))
    expect(code, 'KPI chip 里又出现了 emoji').not.toMatch(
      /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u,
    )
  })
})
```

- [ ] **Step 2: 跑 T2，确认先红**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts 2>&1
```
Expected: FAIL，`ENOENT` 指向 `UserKpiChips.vue`。

- [ ] **Step 3: 创建 chip 组件（逐字如下）**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Lock, Stamp, UserFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  total: number
  active: number
  locked: number
  admins: number
}>()

const chips = computed(() => [
  { key: 'total', label: '总用户', value: props.total, icon: UserFilled, tone: 'brand' },
  { key: 'active', label: '活跃', value: props.active, icon: CircleCheck, tone: 'success' },
  { key: 'locked', label: '锁定', value: props.locked, icon: Lock, tone: 'warn' },
  { key: 'admins', label: '管理员', value: props.admins, icon: Stamp, tone: 'info' },
])
</script>

<template>
  <div class="user-kpi-chips">
    <div
      v-for="chip in chips"
      :key="chip.key"
      class="kpi-chip"
      :class="`kpi-chip--${chip.tone}`"
    >
      <el-icon class="kpi-chip__icon"><component :is="chip.icon" /></el-icon>
      <span class="kpi-chip__label">{{ chip.label }}</span>
      <span class="kpi-chip__value">{{ chip.value }}</span>
    </div>
  </div>
</template>

<style scoped>
.user-kpi-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-2);
  margin-bottom: var(--p-space-3);
}

.kpi-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-1);
  padding: var(--p-space-1) var(--p-space-3);
  border: 1px solid var(--border-2);
  border-radius: 999px;
  background: var(--bg-2);
  color: var(--text);
  font-size: var(--p-fs-small);
}

.kpi-chip__icon {
  color: var(--text-2);
}

.kpi-chip--brand .kpi-chip__icon { color: var(--brand); }
.kpi-chip--success .kpi-chip__icon { color: var(--success); }
.kpi-chip--warn .kpi-chip__icon { color: var(--warn); }
.kpi-chip--info .kpi-chip__icon { color: var(--info); }

.kpi-chip__value {
  font-weight: var(--p-fw-semibold);
  font-variant-numeric: tabular-nums;
}
</style>
```

- [ ] **Step 4: 跑 T2，确认转绿**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts 2>&1
```
Expected: `Tests 2 passed (2)`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/admin/components/UserKpiChips.vue frontend/test/unit/adminUserFormWiring.spec.ts
git commit -m "feat(frontend): 用户管理 KPI 收成 chip 行（批3b）"
```

---

## Task 2: `UserFormDialog.vue` + 载荷类型 + `roleLabelHygiene` 目标迁移

**Files:**
- Create: `frontend/src/pages/admin/components/userFormTypes.ts`
- Create: `frontend/src/pages/admin/components/UserFormDialog.vue`
- Modify: `frontend/test/unit/roleLabelHygiene.spec.ts:22-25`（`FILES`）与 `:135-146`（第 ④ 组）
- Modify: `frontend/test/unit/adminUserFormWiring.spec.ts`（追加对话框判据）

**Interfaces:**
- Consumes: `userFormTypes.ts` 的 `UserFormUser` / `UserFormPayload`。
- Produces:
  - `UserFormPayload` 判别联合：
    - `{ mode: 'create'; username: string; password: string; role: string }`
    - `{ mode: 'edit'; display_name: string; email: string; role: string }`
  - 组件 props `{ modelValue: boolean; mode: 'create' | 'edit'; user: UserFormUser | null; saving: boolean }`；emits `update:modelValue` / `submit`。
  - 运行时 testid：`edit-username|edit-display-name|edit-email|edit-role`（编辑模式）与 `create-username|create-password|create-role`（创建模式），全部挂在 `el-form-item` 上。

- [ ] **Step 1: 追加失败的 T2（对话框部分）**

在 `adminUserFormWiring.spec.ts` 末尾追加：

```ts
const DIALOG = '../../src/pages/admin/components/UserFormDialog.vue'
const TYPES = '../../src/pages/admin/components/userFormTypes.ts'

describe('UserFormDialog：edit-* 不挪窝，create-* 独立，载荷按 mode 分叉', () => {
  it('三个静态 edit-* testid 挂在 el-form-item 上', () => {
    const code = read(DIALOG)
    for (const id of ['edit-username', 'edit-display-name', 'edit-email']) {
      expect(code, `${id} 不在 el-form-item 上`).toMatch(
        new RegExp(`<el-form-item[^>]*data-testid="${id}"`),
      )
    }
  })

  it('角色那一格的 testid 按 mode 分叉，edit-role 与 create-role 都在源码里', () => {
    const code = read(DIALOG)
    expect(code).toMatch(
      /<el-form-item[\s\S]{0,200}:data-testid="mode === 'edit' \? 'edit-role' : 'create-role'"/,
    )
    expect(code).toMatch(/data-testid="create-username"/)
    expect(code).toMatch(/data-testid="create-password"/)
  })

  it('角色下拉只此一处，两个选项与后端 choices 同集合', () => {
    const code = read(DIALOG)
    expect(code).toMatch(/<el-select v-model="form\.role">/)
    expect(code).toContain('<el-option label="用户" value="user" />')
    expect(code).toContain('<el-option label="管理员" value="administrator" />')
  })

  it('载荷类型是判别联合：create 不带 email，edit 不带 username/password', () => {
    const code = read(TYPES)
    expect(code).toMatch(/mode: 'create';\s*username: string;\s*password: string;\s*role: string/)
    expect(code).toMatch(/mode: 'edit';\s*display_name: string;\s*email: string;\s*role: string/)
  })
})
```

- [ ] **Step 2: 改 `roleLabelHygiene.spec.ts`（目标先红）**

把 `:22-25` 的 `FILES` 改为：

```ts
const FILES = {
  util: 'utils/roleLabel.ts', topbar: 'components/layout/Topbar.vue',
  dialog: 'components/layout/AccountDialog.vue', mgmt: 'pages/admin/UserManagement.vue',
  userForm: 'pages/admin/components/UserFormDialog.vue',
} as const
```

把第 ④ 组（`:135-146`）整块替换为：

```ts
describe('判据 ④：角色下拉与后端 ROLE_CHOICES 同步（清单从模型读）', () => {
  it('UserFormDialog.vue 里**每个** `v-model="….role"` 下拉都与模型同集合，并报出动的是哪一侧', () => {
    const backend = roleChoices(readFileSync(MODELS_PY, 'utf8'))
    const blocks = roleSelectBlocks(readSrc(FILES.userForm))
    expect(blocks.length, '一个角色下拉都没抓到：对话框搬家或结构变了，这条判据要重新对形状').toBeGreaterThan(0)
    blocks.forEach((opts, i) => {
      const extra = opts.filter((v) => !backend.includes(v))
      const missing = backend.filter((v) => !opts.includes(v))
      expect(extra, `第 ${i + 1} 个下拉多出 ${extra.join('/')} —— 前端加了后端没有的选项：改页面，本测试不用动`).toEqual([])
      expect(missing, `第 ${i + 1} 个下拉缺 ${missing.join('/')} —— 后端 choices 已加而前端没跟上：下拉选项与 types 的 User.role 一起补`).toEqual([])
    })
  })

  it('角色下拉只剩 UserFormDialog 一处（UserManagement 不再自带第二个）', () => {
    expect(roleSelectBlocks(readSrc(FILES.mgmt))).toEqual([])
  })
})
```

- [ ] **Step 3: 跑 T2，确认两头都红**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts test/unit/roleLabelHygiene.spec.ts 2>&1
```
Expected: 对话框判据 `ENOENT`；`roleLabelHygiene` 第 ④ 组红在「一个角色下拉都没抓到」或 `ENOENT`。

- [ ] **Step 4: 创建载荷类型**

创建 `frontend/src/pages/admin/components/userFormTypes.ts`：

```ts
/** 用户管理新增/编辑对话框的载荷：按 mode 分叉，提交侧不用再猜哪些字段非空。 */
export interface UserFormUser {
  username: string
  display_name: string
  email: string
  role: string
}

export type UserFormPayload =
  | { mode: 'create'; username: string; password: string; role: string }
  | { mode: 'edit'; display_name: string; email: string; role: string }
```

- [ ] **Step 5: 创建对话框（逐字如下）**

创建 `frontend/src/pages/admin/components/UserFormDialog.vue`：

```vue
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import type { UserFormPayload, UserFormUser } from './userFormTypes'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  user: UserFormUser | null
  saving: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: UserFormPayload]
}>()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '', display_name: '', email: '', role: 'user' })

/**
 * 与 AccountDialog 的 profileRules 同一条规则、同一段文案：两个弹窗都能改 email，措辞不许分叉。
 * 只管格式，不加 required —— 邮箱列 blank=True，留空合法；display_name 后端零约束，前端不造第二套判据。
 */
const editRules: FormRules = {
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}
const createRules: FormRules = {}

const title = computed(() => (props.mode === 'edit' ? '编辑账号' : '新增账号'))

function reset() {
  form.username = props.mode === 'edit' ? (props.user?.username ?? '') : ''
  form.password = ''
  form.display_name = props.mode === 'edit' ? (props.user?.display_name ?? '') : ''
  form.email = props.mode === 'edit' ? (props.user?.email ?? '') : ''
  form.role = props.mode === 'edit' ? (props.user?.role ?? 'user') : 'user'
  formRef.value?.clearValidate()
}

watch(
  () => [props.modelValue, props.user] as const,
  ([visible]) => {
    if (visible) reset()
  },
  { flush: 'post' },
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (props.mode === 'edit') {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    emit('submit', {
      mode: 'edit',
      display_name: form.display_name.trim(),
      email: form.email.trim(),
      role: form.role,
    })
    return
  }
  if (form.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  emit('submit', {
    mode: 'create',
    username: form.username,
    password: form.password,
    role: form.role,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="460px"
    :close-on-click-modal="false"
    append-to-body
    class="user-form-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="mode === 'edit' ? editRules : createRules"
      label-width="72px"
      @submit.prevent="submit"
    >
      <el-form-item v-if="mode === 'edit'" label="用户名" data-testid="edit-username">
        <el-input :model-value="user?.username" disabled />
      </el-form-item>
      <el-form-item v-else label="用户名" data-testid="create-username">
        <el-input v-model="form.username" />
      </el-form-item>
      <el-form-item v-if="mode === 'create'" label="密码" data-testid="create-password">
        <el-input v-model="form.password" type="password" />
      </el-form-item>
      <el-form-item v-if="mode === 'edit'" label="显示名" data-testid="edit-display-name">
        <el-input v-model="form.display_name" maxlength="150" />
      </el-form-item>
      <el-form-item v-if="mode === 'edit'" label="邮箱" prop="email" data-testid="edit-email">
        <el-input v-model="form.email" placeholder="可留空" />
      </el-form-item>
      <el-form-item
        label="角色"
        :data-testid="mode === 'edit' ? 'edit-role' : 'create-role'"
      >
        <el-select v-model="form.role">
          <el-option label="用户" value="user" />
          <el-option label="管理员" value="administrator" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">
        {{ mode === 'edit' ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>
```

- [ ] **Step 6: 跑 T2，确认转绿**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts test/unit/roleLabelHygiene.spec.ts 2>&1
```
Expected: 两个文件全绿；`roleLabelHygiene` 第 ④ 组数到 1 个角色下拉且与后端 choices 同集合。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/admin/components/UserFormDialog.vue frontend/src/pages/admin/components/userFormTypes.ts frontend/test/unit/adminUserFormWiring.spec.ts frontend/test/unit/roleLabelHygiene.spec.ts
git commit -m "feat(frontend): 新增/编辑共用账号对话框并迁移角色下拉判据（批3b）"
```

---

## Task 3: `UserManagement.vue` 薄页重写

**Files:**
- Modify: `frontend/src/pages/admin/UserManagement.vue`（整文件重写，578 → 约 430 行）
- Modify: `frontend/test/unit/adminUserFormWiring.spec.ts`（追加页面接线判据）

**Interfaces:**
- Consumes: `UserKpiChips.vue`（Task 1）、`UserFormDialog.vue` 与 `UserFormPayload`（Task 2）、`AdminPageToolbar.vue`（第一份计划）。
- Produces: 页面 DOM `UserKpiChips` + `.admin-page-toolbar`（左槽缺失、右槽「新增账号」）+ `.el-table` + `.user-form-dialog`（append-to-body）。

- [ ] **Step 1: 追加失败的 T2（页面部分）**

在 `adminUserFormWiring.spec.ts` 末尾追加：

```ts
const PAGE = '../../src/pages/admin/UserManagement.vue'

describe('UserManagement：薄页——只有 chip 行、工具栏、表格与对话框', () => {
  it('三个管理页组件都接上了', () => {
    const code = read(PAGE)
    expect(code).toContain('<UserKpiChips')
    expect(code).toContain('<AdminPageToolbar>')
    expect(code).toContain('<UserFormDialog')
  })

  it('页内不再自带对话框/内联添加表单', () => {
    const code = codeOf(read(PAGE))
    expect(code).not.toContain('<el-dialog')
    expect(code).not.toContain('添加用户')
    expect(code).not.toContain('el-divider')
  })

  it('左槽留空（决策 D 归批4），右槽有「新增账号」', () => {
    const code = read(PAGE)
    expect(code).not.toContain('<template #left>')
    expect(code).toContain('<template #right>')
    expect(code).toContain('新增账号')
  })

  it('KPI 四个数逐项传给 chip 组件', () => {
    const code = read(PAGE)
    for (const prop of ['total', 'active', 'locked', 'admins']) {
      expect(code, `KPI prop ${prop} 没传给 UserKpiChips`).toContain(`:${prop}="kpi.${prop}"`)
    }
  })

  it('页面代码行零 emoji（旧 KPI 与 roleIcon 已换 EP 图标）', () => {
    const code = codeOf(read(PAGE))
    expect(code).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })
})
```

- [ ] **Step 2: 跑 T2，确认先红**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts 2>&1
```
Expected: 页面五条红在旧页面上（没有 `UserKpiChips` / `AdminPageToolbar` / `UserFormDialog`，仍有 `<el-dialog` 与 emoji）。

- [ ] **Step 3: 重写页面模板（顶部整块 + 角色格）**

把 `UserManagement.vue` 的模板改成下面这个形状；**表格列与操作列那段 340 推导注释（原 `:64-72`）逐字保留**，只替换 KPI 区、工具栏、角色格与页底两块：

```vue
<template>
  <div class="user-management">
    <UserKpiChips
      :total="kpi.total"
      :active="kpi.active"
      :locked="kpi.locked"
      :admins="kpi.admins"
    />

    <AdminPageToolbar>
      <template #right>
        <el-button type="primary" @click="openCreate">新增账号</el-button>
      </template>
    </AdminPageToolbar>

    <el-card class="table-card">
      <el-table :data="users" stripe>
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="display_name" label="显示名" min-width="120" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <span class="role-cell">
              <el-icon class="role-icon"><component :is="roleIcon(row.role)" /></el-icon>
              {{ roleLabel(row.role) }}
            </span>
          </template>
        </el-table-column>
        <!-- 其余列（状态 / 创建时间 / 最后登录 / 操作）逐字保留原文件 :46-107 -->
      </el-table>
    </el-card>

    <UserFormDialog
      v-model="formVisible"
      :mode="formMode"
      :user="editing"
      :saving="saving"
      @submit="onFormSubmit"
    />
  </div>
</template>
```

删除原 `:148-168` 的 `el-divider` + `<h3>➕ 添加用户</h3>` + 页底 `el-card` 添加表单；删除原 `:111-146` 的编辑对话框（迁进 `UserFormDialog.vue`）。

- [ ] **Step 4: 重写脚本（整块替换原 `<script setup>`）**

```ts
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Stamp, UserFilled } from '@element-plus/icons-vue'

import api from '../../api'
import { collectAllPages } from '../../utils/paging'
import { useAuthStore } from '../../stores/auth'
import { roleLabel } from '../../utils/roleLabel'
import AdminPageToolbar from './components/AdminPageToolbar.vue'
import UserKpiChips from './components/UserKpiChips.vue'
import UserFormDialog from './components/UserFormDialog.vue'
import type { UserFormPayload } from './components/userFormTypes'

interface User {
  id: number
  username: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  date_joined: string
  last_login: string | null
  lockout_until: string | null
}

const users = ref<User[]>([])
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editing = ref<User | null>(null)
const saving = ref(false)
const auth = useAuthStore()

/**
 * 本行是不是当前登录账号。禁用/删除自己会把自己锁在门外：
 * 登录端点对停用账号直接 403、SimpleJWT 也立刻吊销 token，只能直连数据库恢复。
 * 后端 UserManagementViewSet._guard_lockout 是权威守卫（这里只是不让点）。
 * 硬刷新后 auth.user 可能为 null（本页不自拉 profile），此时按钮回落成可点，
 * 由后端 400 + toast 兜住。
 */
function isSelf(user: User): boolean {
  return user.id === auth.user?.id
}

const kpi = computed(() => ({
  total: users.value.length,
  active: users.value.filter((u) => u.is_active && !isLocked(u)).length,
  locked: users.value.filter((u) => isLocked(u)).length,
  admins: users.value.filter((u) => u.role === 'administrator').length,
}))

function isLocked(user: User): boolean {
  if (!user.lockout_until) return false
  return new Date(user.lockout_until) > new Date()
}

function roleIcon(role: string) {
  return role === 'administrator' ? Stamp : UserFilled
}

function statusClass(user: User): string {
  if (isLocked(user)) return 'locked'
  if (!user.is_active) return 'disabled'
  return 'active'
}

function statusLabel(user: User): string {
  if (isLocked(user)) return 'locked'
  if (!user.is_active) return 'disabled'
  return 'active'
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 分页取全。DRF 默认 PAGE_SIZE=20（config/settings/base.py:214-215，本 ViewSet 未覆写
 * pagination_class），而本页**没有翻页控件**：只读第一页的话，第 21 个用户起在页面上
 * 不可达，而 kpi 的四个数全按 `users` 统计 ⇒ 数字静默失真。跟着 `next` 取完；
 * 50 页护栏只为防坏响应自指成死循环，正常账号规模远不到。
 */
async function loadUsers() {
  try {
    const { rows, truncated } = await collectAllPages<User>(
      async (url) => (await api.get(url)).data,
      '/auth/users/',
    )
    users.value = rows
    if (truncated) {
      ElMessage.warning(`用户多于 ${rows.length} 条，本次只取到前若干页，统计可能偏小`)
    }
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出（utils/error.ts formatError）
  }
}

function openCreate() {
  editing.value = null
  formMode.value = 'create'
  formVisible.value = true
}

function openEdit(user: User) {
  editing.value = user
  formMode.value = 'edit'
  formVisible.value = true
}

async function onFormSubmit(payload: UserFormPayload) {
  saving.value = true
  try {
    if (payload.mode === 'edit' && editing.value) {
      await api.put(`/auth/users/${editing.value.id}/`, {
        display_name: payload.display_name,
        email: payload.email,
        role: payload.role,
      })
      ElMessage.success('账号已更新')
      const self = isSelf(editing.value)
      formVisible.value = false
      loadUsers()
      // 改的是登录账号自己时补拉一次 profile：降级成功后 Pinia 的 user.role 还停在旧值
      // （stores/auth.ts:35 读内存态），不补拉侧栏会按管理员继续渲染。fetchProfile 失败会先
      // logout 再抛，而账号已存好，所以就地吞掉。刻意不写 e2e 判据：降级种子唯一 admin 会塌池。
      if (self) await auth.fetchProfile().catch(() => undefined)
    } else if (payload.mode === 'create') {
      await api.post('/auth/users/', {
        username: payload.username,
        password: payload.password,
        role: payload.role,
      })
      ElMessage.success('用户已添加')
      formVisible.value = false
      loadUsers()
    }
  } catch {
    // 守卫失败与网络错误由拦截器弹文案，列表保持原样
  } finally {
    saving.value = false
  }
}

async function toggleUser(user: User) {
  try {
    await api.put(`/auth/users/${user.id}/`, { is_active: !user.is_active })
    ElMessage.success('状态已更新')
    loadUsers()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function resetPassword(user: User) {
  // 旧实现发的是硬编码 '123456'（6 位），而后端 AdminResetPasswordSerializer.new_password
  // 是 min_length=8 ⇒「重置密码」按钮从来没成功过一次。改成管理员当场输入新密码，
  // 长度门槛与后端同值：本页 inputPattern /^.{8,}$/ 的 8 == serializers.py:205 的 8
  // （强度校验另见 :208-212，前端不复制它，弱密码由后端 400 兜住）。
  let value: string
  try {
    ({ value } = await ElMessageBox.prompt(
      `为 ${user.username} 设置新密码（至少 8 位）`,
      '重置密码',
      {
        confirmButtonText: '重置',
        cancelButtonText: '取消',
        inputPattern: /^.{8,}$/,
        inputErrorMessage: '密码至少 8 位',
      },
    ))
  } catch {
    return // 取消：prompt 关闭时 reject 'cancel'
  }
  try {
    await api.post(`/auth/users/${user.id}/reset_password/`, { new_password: value })
    ElMessage.success(`已重置 ${user.username} 的密码，请告知其登录后修改`)
    loadUsers()
  } catch {
    // 真实错误 toast 由拦截器弹出
  }
}

async function unlockUser(user: User) {
  try {
    await api.post(`/auth/users/${user.id}/unlock/`)
    ElMessage.success('账户已解锁')
    loadUsers()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function deleteUser(user: User) {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${user.username}？`, '确认')
    await api.delete(`/auth/users/${user.id}/`)
    ElMessage.success('已删除')
    loadUsers()
  } catch {
    // ElMessageBox.confirm 取消会 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

onMounted(loadUsers)
```

- [ ] **Step 5: 精简样式**

从 `<style scoped>` 删除：`.kpi-grid` 到 `.kpi-card__value`（原 `:419-480`）、两条 KPI 媒体查询（原 `:567-577`）、死规则 `:deep(.el-select .el-input__wrapper)`（原 `:555-557`），以及随页底添加表单一起消失的 `:deep(.el-divider)` 块（原 `:563-565`）。保留 `.table-card`、角色/状态、表格 token、输入框、按钮等其余样式。`.role-icon` 继续用 `font-size: var(--p-fs-title)`。

- [ ] **Step 6: 跑 T2 + 构建**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts test/unit/roleLabelHygiene.spec.ts 2>&1
cd frontend && npm run build 2>&1
```
Expected: T2 全绿；`npm run build` 的 `vue-tsc -b` 零诊断、`✓ built in …`。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/admin/UserManagement.vue frontend/test/unit/adminUserFormWiring.spec.ts
git commit -m "refactor(frontend): 用户管理页拆薄并接上工具栏与共用对话框（批3b）"
```

---

## Task 4: `admin.spec.ts` 适配新对话框 + KPI chip T3

**Files:**
- Modify: `frontend/e2e/admin/admin.spec.ts:24-35`（旧 helper）、`:194-204`、`:238-244`、`:279-290`（三条创建流程）、追加一条 `@p2` KPI/chip 用例

- [ ] **Step 1: 先跑红（新页面 + 旧定位器）**

Run:
```bash
node scripts/e2e_pool.mjs --slots=1 -- e2e/admin/admin.spec.ts 2>&1
```
Expected: 三条创建流程红在 `addUserField` 找不到 `.user-management .el-form`（页底表单已删除）；其余表格/权限用例绿。这是 Task 3 的预期连带，不是回归。

- [ ] **Step 2: 替换 helper**

把 `admin.spec.ts:24-35` 的 `addUserField` 整块替换为：

```ts
/**
 * 新增账号对话框：批3b 起「添加用户」从页底内联表单移进 UserFormDialog（append-to-body），
 * 页内 el-form 定位不再可达；字段用 create-* testid，与编辑弹窗的 edit-* 分开。
 */
async function openCreateDialog(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: '新增账号', exact: true }).click()
  const dialog = page.locator('.user-form-dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

async function createUser(page: Page, username: string): Promise<Locator> {
  const dialog = await openCreateDialog(page)
  await dialog.locator('[data-testid="create-username"] input').fill(username)
  await dialog.locator('[data-testid="create-password"] input').fill('e2ePass123')
  await dialog.getByRole('button', { name: '创建', exact: true }).click()
  await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })
  await expect(dialog).toBeHidden()
  return page.locator('.el-table tbody tr').filter({ hasText: username })
}
```

- [ ] **Step 3: 三条创建流程改用 `createUser`**

1. `@p2 新增并删除用户`（原 `:194-204`）：把 `addUserField(...).fill(...)` 与 `getByRole('button', { name: '添加' }).click()` 整段替换为：

```ts
    await createUser(page, uniqueName)
    const newRow = page.locator('.el-table tbody tr').filter({ hasText: uniqueName })
    await expect(newRow.getByText(uniqueName, { exact: true })).toBeVisible({ timeout: 15_000 })
```

2. `@p2 禁用 / 启用用户`（原 `:238-244`）：同样替换为：

```ts
    const row = await createUser(page, uniqueName)
    await expect(row).toHaveCount(1)
```

3. `@p1 编辑弹窗`（原 `:279-290`）：把创建段替换为：

```ts
    const row = await createUser(page, username)
    await expect(row).toHaveCount(1)

    await row.getByRole('button', { name: '编辑', exact: true }).click()
    const dialog = page.locator('.user-form-dialog')
    await expect(dialog).toBeVisible()
```

> 原 `:290` 的 `.user-edit-dialog` 改成 `.user-form-dialog`；其余 `edit-*` testid、邮箱校验、角色下拉与保存流程逐字保留。

- [ ] **Step 4: 追加 KPI chip / 工具栏 T3**

在 describe 内追加：

```ts
  test('@p2 工具栏与 KPI：四个 chip 带 SVG 图标、左槽为空、右槽新增账号可达', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    const chips = page.locator('.user-kpi-chips .kpi-chip')
    await expect(chips).toHaveCount(4)
    for (const label of ['总用户', '活跃', '锁定', '管理员']) {
      const chip = chips.filter({ hasText: label })
      await expect(chip).toHaveCount(1)
      await expect(chip.locator('svg'), `${label} chip 没有 EP 矢量图标`).toHaveCount(1)
      await expect(chip).toContainText(/\d+/)
    }

    // 决策 D 的左槽本批留空 ⇒ 壳不渲染空占位；右槽按钮可达
    await expect(page.locator('.admin-page-toolbar__left')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '新增账号', exact: true })).toBeVisible()

    // 角色列也从 emoji 换成 SVG 图标
    await expect(page.locator('.el-table .role-cell', { hasText: '管理员' }).first().locator('svg'))
      .toHaveCount(1)
  })
```

- [ ] **Step 5: 跑绿**

Run:
```bash
node scripts/e2e_pool.mjs --slots=1 -- e2e/admin/admin.spec.ts 2>&1
```
Expected: 汇总行 `unexpected 0`，包含新增的 KPI/工具栏用例；`@p1 编辑弹窗` 的邮箱校验与角色切换仍绿。

- [ ] **Step 6: 提交**

```bash
git add frontend/e2e/admin/admin.spec.ts
git commit -m "test(e2e): 用户管理新增流程改走共用对话框并补 KPI chip 判据（批3b）"
```

---

## Task 5: 两处死规则收敛 + night `.el-select__wrapper` T3

**Files:**
- Modify: `frontend/src/styles/element-plus-theme.css:597-600`
- Modify: `frontend/src/pages/admin/AuditLogPage.vue:240-245`（过期注释）
- Create: `frontend/e2e/theme/admin-select-theme.spec.ts`
- Modify: `frontend/test/unit/adminUserFormWiring.spec.ts`（追加主题源码判据）

**Interfaces:**
- Consumes: 第一份计划的审计页 `[data-testid=audit-event] .el-select`（night/light 测试靶子）；Task 3 已删除 `UserManagement.vue:555` 死规则。
- Produces: 全局 night 规则 `.el-select__wrapper`（底色 + 边框）；焦点/悬停态仍走 `#f9a825`。

- [ ] **Step 1: 追加失败的主题源码 T2**

在 `adminUserFormWiring.spec.ts` 末尾追加：

```ts
const THEME = '../../src/styles/element-plus-theme.css'

describe('批次级主题收敛：select 触发区由 .el-select__wrapper 承载', () => {
  it('night 规则指向 .el-select__wrapper，死规则 .el-select .el-input__wrapper 已不存在', () => {
    const theme = codeOf(read(THEME))
    expect(theme).toMatch(/:root\[data-theme="night"\] \.el-select__wrapper/)
    expect(theme).toMatch(/\.el-select__wrapper\.is-focused/)
    expect(theme).not.toMatch(/\.el-select \.el-input__wrapper/)
    expect(codeOf(read(PAGE)), '页面里还留着死规则').not.toMatch(/\.el-select \.el-input__wrapper/)
  })
})
```

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts 2>&1
```
Expected: 这条红（全局 CSS 还是旧选择器）。

- [ ] **Step 2: 写失败的主题 T3**

创建 `frontend/e2e/theme/admin-select-theme.spec.ts`：

```ts
import { test, expect } from '@playwright/test'

import { loginAs } from '../helpers/auth'

/**
 * 批3b §6.5：EP 2.14 的 select 触发区是 `.el-select__wrapper`，
 * 旧规则 `.el-select .el-input__wrapper` 在 theme-chalk 里恒不命中。
 * 这条用例盯两件事：night 覆写真的落到 wrapper 上（不是只写在 CSS 里），
 * 且焦点态没有被一个静态 !important 阴影抹掉。
 */
test.describe('@theme 管理页 select 触发区主题覆写', { tag: ['@p2', '@theme'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('@p2 night 下 audit-event 的 .el-select__wrapper 底色与 light 不同', async ({ page }) => {
    await loginAs(page, 'admin')
    await page.goto('/admin/audit')
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    const wrapper = page.locator('[data-testid="audit-event"] .el-select__wrapper')
    await expect(wrapper).toBeVisible()

    const read = () =>
      wrapper.evaluate((el) => {
        const s = getComputedStyle(el)
        return { bg: s.backgroundColor, shadow: s.boxShadow }
      })

    const light = await read()
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    await expect(wrapper).toBeVisible()
    const night = await read()

    expect(night.bg, 'night 下事件下拉仍是 light 的底色 ⇒ 覆写没落到 wrapper 上').not.toBe(light.bg)
    expect(night.bg, 'night 覆写值不是全局主题层那一条').toBe('rgba(255, 255, 255, 0.05)')
    expect(night.shadow, 'night 下边框没有由 .el-select__wrapper 承载').toContain(
      'rgba(255, 255, 255, 0.1)',
    )

    // 焦点态：点开 select，wrapper 必须仍有可辨识的焦点环（不能被静态阴影吃掉）
    await page.locator('[data-testid="audit-event"] .el-select').click()
    await expect(wrapper).toHaveClass(/is-focused/)
    const focused = await read()
    expect(focused.shadow, '焦点环被静态 !important 阴影抹掉了').toContain('rgb(249, 168, 37)')
    await page.keyboard.press('Escape')
  })
})
```

Run:
```bash
node scripts/e2e_pool.mjs --slots=1 -- e2e/theme/admin-select-theme.spec.ts 2>&1
```
Expected: 红在 `night.bg` 不等于 `rgba(255, 255, 255, 0.05)`（旧规则没生效）。

- [ ] **Step 3: 改全局主题规则**

把 `element-plus-theme.css:597-600` 整块替换为：

```css
/* 选择器强制覆盖：EP 2.14 的 select 触发区是 .el-select__wrapper，
 * `.el-select .el-input__wrapper` 在 theme-chalk/el-select.css 里一条规则都没有（恒不命中）。 */
:root[data-theme="night"] .el-select__wrapper {
  background-color: rgba(255, 255, 255, 0.05) !important;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1) inset !important;
}

:root[data-theme="night"] .el-select__wrapper.is-focused,
:root[data-theme="night"] .el-select__wrapper.is-hovering:not(.is-focused) {
  box-shadow: 0 0 0 1px #f9a825 inset !important;
}
```

- [ ] **Step 4: 订正审计页的过期注释**

把 `AuditLogPage.vue:240-245` 的注释整块替换为：

```css
/* 本仓装的 element-plus 2.14.0 里，select 的触发区用的是它自己的 .el-select__wrapper：
 * theme-chalk/el-select.css 里有这个类，而 `.el-select .el-input__wrapper` 一条规则都没有 ⇒
 * 旧写法恒不命中。全局 night 覆写在 src/styles/element-plus-theme.css 的选择器段，同样只认
 * .el-select__wrapper；这里保留 light 主题的底色基线。 */
```

- [ ] **Step 5: 跑绿（T2 + T3）**

Run:
```bash
cd frontend && npx vitest run test/unit/adminUserFormWiring.spec.ts 2>&1
node scripts/e2e_pool.mjs --slots=1 -- e2e/theme/admin-select-theme.spec.ts 2>&1
```
Expected: T2 全绿；主题 T3 `unexpected 0`，焦点态断言绿。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles/element-plus-theme.css frontend/src/pages/admin/AuditLogPage.vue frontend/e2e/theme/admin-select-theme.spec.ts frontend/test/unit/adminUserFormWiring.spec.ts
git commit -m "fix(theme): select 触发区改由 .el-select__wrapper 承载并补双主题判据（批3b）"
```

---

## Task 6: 介绍书复刻与文案同步

**Files:**
- Modify: `docs/intro/.vitepress/theme/components/UsersMock.vue`
- Modify: `docs/intro/guide/09-admin.md:3`

- [ ] **Step 1: `UsersMock.vue` 去掉搜索框、按钮改口**

脚本：删除 `const q = ref('')` 与 `const vis = computed(...)`（`kpi` 仍用 `computed`，保留 `ref, computed` 导入）。

模板 `m-toolbar` 整块替换为：

```vue
    <div class="m-toolbar">
      <span class="grow"></span>
      <button class="m-btn pri" @click="create">新增账号</button>
    </div>
```

`v-for="u in vis"` 改成 `v-for="u in users"`。

`create()` 里的对话框标题与说明改成：

```ts
  dialog('新增账号', '<p>用户名 / 密码 / 角色三项；此处演示创建一个合成账号。</p>', [
```

- [ ] **Step 2: 介绍书文案同步**

把 `09-admin.md:3` 改成：

```markdown
管理员专属：账号角色、启用状态、锁定与全量操作留痕。两个面板均为可操作复刻——试试新增账号 / 禁用 / 解锁 / 删除（带撤销），操作会实时写入下方审计表。
```

- [ ] **Step 3: 构建与走读**

Run:
```bash
npm run intro:build 2>&1
node scripts/intro/check.mjs 2>&1
```
Expected: 构建成功；`check.mjs` 末行 PASS（红线扫描 0 命中）。

然后按 `.claude/CLAUDE.md`「产品介绍书定期维护」：`npm run intro:dev` 打开 09 章，桌面 + 420px 各看一遍，控制台零报错。

- [ ] **Step 4: 图标肉眼确认（spec §7.9）**

在浏览器里打开 `/admin/users`（light + night 两主题），确认：
- 总用户 `UserFilled`、活跃 `CircleCheck`、锁定 `Lock` 不与常见功能近形；
- 管理员 `Stamp` 的「印章」语义成立。若判定像常见按钮/功能，把 `UserKpiChips.vue` 与 `UserManagement.vue` 的 `Stamp` 换成 `Medal`（两处 import + 两处引用），重跑 Task 1/3 的 T2 与 Task 4 的 T3 即可。

- [ ] **Step 5: 提交**

```bash
git add docs/intro/.vitepress/theme/components/UsersMock.vue docs/intro/guide/09-admin.md
git commit -m "docs(intro): 用户管理复刻对齐 chip 行与新增账号对话框（批3b）"
```

---

## Task 7: 批次收口门禁 + 台账

**Files:**
- Modify: `docs/tasks/todo.md`（追加批3b 收口节）

- [ ] **Step 1: 全量 T2**

Run:
```bash
cd frontend && npx vitest run 2>&1 | tee ../tasks/b3b_vitest.log
```
Expected: 末尾 `Test Files N passed (N)` / `Tests M passed (M)`；`grep -cE "failed|FAIL"` 为 0（日志里允许出现 `failed` 字样只在测试名/注释时人工复核）。

- [ ] **Step 2: e2e 类型与构建**

Run:
```bash
cd frontend && npm run lint:e2e 2>&1 | tee ../tasks/b3b_lint_e2e.log
cd frontend && npm run build 2>&1 | tee ../tasks/b3b_build.log
```
Expected: `error TS` 0 处；`✓ built in …`。

- [ ] **Step 3: 行数闸**

Run:
```bash
cd frontend && npx vitest run test/unit/lineLimit.spec.ts 2>&1 | tee ../tasks/b3b_linelimit.log
```
Expected: `Tests 15 passed (15)`；本批不给任何文件加豁免。

- [ ] **Step 4: affected（预计 GLOBAL）**

Run:
```bash
cd frontend && npm run test:e2e:affected 2>&1 | tee ../tasks/b3b_affected.log
```
Expected: `decide: 全量 e2e（兜底命中）`（`frontend/src/styles/` 在全局清单）；末行 `RESULT: PASS`。若它已真跑全量池 + 后端全套，判据行照记；**不要**把它的输出当成 Step 5/6 的替代，收口档仍按下两条显式跑。

- [ ] **Step 5: 收口全量池**

Run:
```bash
node scripts/e2e_pool.mjs --slots=4 2>&1 | tee tasks/b3b_pool.log
```
Expected: 汇总行含 `unexpected 0` 与 `结论 MEASURED`；文件/用例数现记。跑完释放端口。

- [ ] **Step 6: 后端全套**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test 2>&1 | tee tasks/b3b_backend.log
```
Expected: `Ran N tests …` / `OK (skipped=16)`；`grep -cE "^(FAIL|ERROR):"` 为 0。⚠ 工作树可能仍挂着另一会话的 `apps/export/*` 未提交改动（本批没碰）；套件会包含它们，台账里注明。

- [ ] **Step 7: 介绍书最终门**

Run:
```bash
npm run intro:build 2>&1
node scripts/intro/check.mjs 2>&1
```
Expected: 构建成功、`check.mjs` PASS。

- [ ] **Step 8: 写台账**

在 `docs/tasks/todo.md` 末尾追加（按批1/批2/批3a 的格式）：

```markdown
# 任务：批3b 两页统一 toolbar（2026-11-15，计划 Task 7 收口）

## 状态：**已收口，未 push**

- 计划一：`docs/superpowers/plans/2026-11-15-batch3b-audit-toolbar.md`
- 计划二：`docs/superpowers/plans/2026-11-15-batch3b-user-management-toolbar.md`

## 收口七档（每档取判据行，不取退出码）

| 档 | 命令 | 实测判据行 |
|---|---|---|
| 后端全量 | `CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test` | `Ran … tests` / `OK (skipped=16)` / `FAIL|ERROR` 0 |
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | `unexpected 0 · 结论 MEASURED`（文件/用例现记） |
| 全量 vitest | `npx vitest run` | `Test Files … passed` / `Tests … passed` |
| e2e 类型 | `npm run lint:e2e` | `error TS` 0 处 |
| 前端构建 | `npm run build`（含 `vue-tsc -b`） | `✓ built in …`，零 TS 诊断 |
| 行数闸 | `npx vitest run test/unit/lineLimit.spec.ts` | `Tests 15 passed (15)`；无新豁免 |
| affected | `npm run test:e2e:affected` | `decide: 全量 e2e（兜底命中）` + `RESULT: PASS` |

三档测试数现读：T1 0（后端零改动）/ T2 `adminToolbarWiring.spec.ts` + `adminUserFormWiring.spec.ts` + `roleLabelHygiene.spec.ts` 增量 / T3 `admin.spec.ts` + `audit.spec.ts` + `theme/admin-select-theme.spec.ts` 增量。
```

- [ ] **Step 9: 提交台账**

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 批3b 收口台账（计划一/二、七档判据行）"
```

---

## 收口后的遗留（归批4，不在本批做）

- **决策 D**：用户管理页左槽的前端搜索/角色筛选（`UserManagement.vue` 列表已是 `collectAllPages` 全量，零后端改动）——批4 往 `AdminPageToolbar` 左槽里塞，不再动壳结构。
- **UX-1**：重复项卡片的「锁定本组」工效项（批3a 台账 §10.1），批4 先确认用户是否真要。
- **`repair-center.spec.ts` 591/600**：批4/批3b 后续任何扩展之前先拆 `e2e/data/duplicate-keep.spec.ts`（本批没动它）。

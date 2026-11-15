# 批4 刀一 · e2e 拆文件与助手抽取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `frontend/e2e/data/repair-center.spec.ts`（591/600 行）里重复项一族拆成 `frontend/e2e/data/duplicate-keep.spec.ts`，并先把它与同族 spec 共用的四个助手抽进 `frontend/e2e/helpers/`，全程不削弱任何一条既有判据。

**Architecture:** 两步分离 —— ① 先把「谁调用」改成 helper（取数通路逐字不变），② 再搬文件。顺序反了就无法归因：一次改动同时改「谁调用」和「怎么调用」时，任何红点都可能是两件事之一。等价性由机械闸证明（用例标题集合相等），不靠人眼看 diff。

**Tech Stack:** Playwright（`@playwright/test`，TypeScript e2e 规格）、Node（`scripts/*.mjs` 门禁）、vitest（`frontend/test/unit/`）。

**Spec:** `docs/superpowers/specs/2026-11-15-batch4a-e2e-split-and-username-guard-design.md` —— §2 是本计划正文，§1 的 E1-E10 是立据。

## Global Constraints

- 600 行闸：`scripts/line-limit.mjs:18` `LINE_LIMIT = 600`，口径是 `git ls-files '*.py' '*.ts' '*.vue'` 的**整文件行数**（`:26` 刻意含 `*.ts`）。本刀两个 spec 都必须显著低于它。
- **不许往 `apps/datafiles/tests.py` 加任何行**：它冻在豁免精确值 1959（`scripts/line-limit.mjs:36-37`），多一行即 `kind:'grew'` 报红。
- 逐字搬运纪律：助手表体、docblock、用例断言一律照原样走，只改 `import` 与被搬内容的缩进。**不得以「顺手改好」为名调整任何断言、超时或定位器。**
- 不做取数通路统一：`frontend/e2e/helpers/cleanup.ts:34-47` 的 `page.request` 写法更干净，但本刀不采用（设计稿 §2.1）。
- 不动其余 fetch 变体：`view-data.spec.ts:22/:170/:184`、`settings/settings.spec.ts:45`、`settings/chart-memory.spec.ts:43`、`sftp/reconnect.spec.ts:250`、`batch/batch-phase.spec.ts:69`、`data/renderer-memory.spec.ts:90`、`data/data.spec.ts:104`、`data/file-list-sort-filter.spec.ts:37`。
- 门禁档位：改 `frontend/e2e/helpers/**` 判**全量 e2e**（`scripts/affected-rules.mjs:114`）；`frontend/e2e/data/**` 按目录名落 `data` 模块档（`:119`）。所以本刀**收口是一次全量档**，前面各步用单文件档自证。
- 池档 slot 内是 `--workers=1`（`scripts/e2e_pool.mjs:215`），serial 档是 `workers: min(6, cpus/2)` + `fullyParallel`（`frontend/playwright.config.ts:63/:69`）。设计稿 §2.4 已判定接受这个差异，本刀不加互斥。
- 起全量池之前必查两件事（本机既有事故）：① `netstat` 确认 slot 基址端口 `21001+`/`22001+` 没被别的会话或孤儿进程占着；② 空闲**提交内存**低于预算（本机 8.0 GB）时任何并行度都不该开跑，先清进程或换时段，**不要**用降 `--slots` 硬扛。
- 全程不 push（`origin` 是公开仓库）。
- **计数形状**：`--list` 与实跑都会连带 `setup` 项目（`fixtures/auth.setup.ts`）那两条
  `authenticate as admin` / `authenticate as user`，因为业务项目声明了 `dependencies: ['setup']`
  （`frontend/playwright.config.ts:123`）。所以基线标题文件是 **11 行**（9 业务 + 2 setup），
  单跑汇总行会是 `Running <业务数+2> tests`。判据一律取「**业务用例名逐条在、零 `failed`**」，
  不取总数 —— 两侧同现的 2 条对集合差没有影响。
- **标题闸的盲区（Task 1 评审实测指出，本刀必须补）**：`--list` 只暴露用例标题，
  `test.describe.serial(...)` 从 serial 改成非 serial、`{ tag: ['@p2','@data'] }` 被改、
  `timeout`/`retries` 漂移，**标题行一个字都不变** ⇒ 集合差照样绿。所以每次搬运除了标题闸，
  还要 grep 对账这两行的**原文**（命令见 Task 2 Step 4 / Task 3 Step 6），逐字相同才算「纯搬运」。

## 文件结构（本刀完成后）

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/e2e/helpers/apiClient.ts` | 带 token 的一次读/写请求（浏览器侧 `fetch`） | 新建 |
| `frontend/e2e/helpers/djangoShell.ts` | 从 e2e 进程跑 `manage.py shell -c` 的逃生舱 | 新建 |
| `frontend/e2e/helpers/repairCenterFlow.ts` | 「数据修复」入口的两个点击序列 | 新建 |
| `frontend/e2e/data/duplicate-keep.spec.ts` | 重复项选保留的界面层 T3（5 条） | 新建 |
| `frontend/e2e/data/repair-center.spec.ts` | 修复中心其余一致性动作的 T3（4 条） | 缩减 |
| `frontend/e2e/data/disk-usage-chip.spec.ts` | 占用 chip 的 T3 | 换 import |
| `frontend/test/unit/dupKeep.spec.ts`、`dupKeepWiring.spec.ts` | 只改注释里的文件指向 | 注释订正 |
| `tasks/b4a-titles.mjs` | 用例标题集合闸（临时工具，gitignore 区） | 新建 |

---

### Task 1: 三个共享助手落地，并让 `disk-usage-chip` 成为第一个消费者

为什么第一个消费者是 `disk-usage-chip` 而不是 `repair-center`：它只用 `apiGet` 一处（`:170`），改完单跑就是「helper 版与局部版等价」的最小证明；拿 9 条用例的 repair-center 当第一证，红了分不清是抽取错还是搬运错。

**Files:**
- Create: `frontend/e2e/helpers/apiClient.ts`
- Create: `frontend/e2e/helpers/djangoShell.ts`
- Create: `frontend/e2e/helpers/repairCenterFlow.ts`
- Create: `tasks/b4a-titles.mjs`
- Modify: `frontend/e2e/data/disk-usage-chip.spec.ts:2`、`:32-45`
- Test: `frontend/e2e/data/disk-usage-chip.spec.ts`（既有用例即回归）

**Interfaces:**
- Produces：`apiGet(page: Page, url: string): Promise<{status: number, body: any}>`、`apiPost(page: Page, url: string, body: unknown): Promise<{status: number, body: any}>`、`shellDjango(code: string): void`、`openRepairCenter(page: Page): Promise<void>`
- Consumes：`../fixtures/test-data` 的 `PROJECT_ROOT`（已由该模块导出，`repair-center.spec.ts:5` 就在 import 它）

- [ ] **Step 1: 写标题集合闸（后面每个 Task 都拿它对账，所以它必须第一个存在）**

Create `tasks/b4a-titles.mjs`：

```js
// tasks/b4a-titles.mjs — 用例标题集合闸（纯搬运的机械证明，不靠眼看 diff）
// Run（仓库根）: node tasks/b4a-titles.mjs data/repair-center.spec.ts [data/duplicate-keep.spec.ts ...]
// 输出排序后的标题全集，一行一条。搬运前后各取一次，diff 必须为空。
import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'frontend')
const targets = process.argv.slice(2).map((f) => `e2e/${f}`)
if (!targets.length) {
  console.error('用法: node tasks/b4a-titles.mjs <相对 e2e 的 spec 路径> ...')
  process.exit(2)
}

const out = execSync(
  `npx playwright test ${targets.join(' ')} --list --reporter=json`,
  { cwd: FRONTEND, encoding: 'utf-8', maxBuffer: 128e6 },
)
const j = JSON.parse(out.slice(out.indexOf('{')))

const titles = []
const walk = (suite) => {
  for (const spec of suite.specs ?? []) titles.push(spec.title)
  for (const inner of suite.suites ?? []) walk(inner)
}
for (const fileSuite of j.suites ?? []) walk(fileSuite)

console.log(titles.sort().join('\n'))
```

- [ ] **Step 2: 落基线标题清单**

Run（仓库根）：

```bash
node tasks/b4a-titles.mjs data/repair-center.spec.ts > tasks/b4a_titles_baseline.txt
wc -l < tasks/b4a_titles_baseline.txt
```

Expected: **11 行** —— 2026-11-15 现测：9 条业务用例，加上 `--list` 连带列出的 `setup` 项目两条（`authenticate as admin` / `authenticate as user`）。不是 11 就停下 —— 后面每一步都拿这份对账。
顺手现读一次 vitest 留底（Task 4 要比数）：`cd frontend && npx vitest run > ../tasks/b4a_vitest_before.log 2>&1`。

- [ ] **Step 3: 建 `apiClient.ts`（函数体逐字来自 `repair-center.spec.ts:38-61`）**

Create `frontend/e2e/helpers/apiClient.ts`：

```ts
import { type Page } from '@playwright/test'

/**
 * 浏览器侧带 token 的一次读/写请求。返回 `{status, body}` 而不是 throw ——
 * 调用方要拿状态码当断言对象（`expect(imp.status).toBe(201)`），
 * 改成抛异常就等于把断言搬进 helper，用例再也看不到状态码。
 *
 * 唯一来源纪律：此前 `repair-center.spec.ts` 与 `disk-usage-chip.spec.ts` 各存一份同形副本，
 * 后者的注释原话是「出现第三份时就把它搬进 `e2e/helpers/`，别再往 spec 里复制」。
 * 本文件就是那次落地；刀一 拆出的 `duplicate-keep.spec.ts` 是第三个消费者。
 * 其余形态不同的 fetch 封装（返回已裁剪的对象、或走 `page.request`）**不在收编范围**，
 * 合并它们会改掉用例语义 —— 见设计稿 §2.1 与 §4。
 */

export function apiGet(page: Page, url: string) {
  return page.evaluate(async (u) => {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`/api/v1${u}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    return { status: res.status, body: await res.json() }
  }, url)
}

export function apiPost(page: Page, url: string, body: unknown) {
  return page.evaluate(async ({ u, b }) => {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`/api/v1${u}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(b),
    })
    return { status: res.status, body: await res.json() }
  }, { u: url, b: body })
}
```

- [ ] **Step 4: 建 `djangoShell.ts`（体逐字来自 `:22` 与 `:29-36`）**

Create `frontend/e2e/helpers/djangoShell.ts`：

```ts
import { execSync } from 'node:child_process'
import path from 'node:path'
import { PROJECT_ROOT } from '../fixtures/test-data'

const PYTHON = process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

/**
 * 执行 Django shell 代码（代码内只用单引号，外层双引号包裹兼容 cmd）。
 *
 * 与 `e2e/global-setup.ts:15-35` 的 `runDjango` **刻意不合并**：后者跑的是子命令
 * （migrate / seed_users / seed_test_data）、显式注入 `LQDP_SYSTEM_CONFIG_FILE`、
 * 且失败必须抛（静默继续 = 残库假绿）；本函数跑 `shell -c`，且**由调用方决定要不要吞错**
 * （`repair-center.spec.ts` 的 afterEach 刻意 `try/catch` 不阻塞用例，`cleanupDup` 则
 * `console.error` 出声）。把两种失败策略并成一个函数，等于替调用方改了它的判据。
 */
export function shellDjango(code: string) {
  execSync(`"${PYTHON}" manage.py shell -c "${code}"`, {
    cwd: PROJECT_ROOT,
    encoding: 'utf-8',
    timeout: 60_000,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
}
```

- [ ] **Step 5: 建 `repairCenterFlow.ts`（体逐字来自 `:171-175`）**

Create `frontend/e2e/helpers/repairCenterFlow.ts`：

```ts
import { expect, type Page } from '@playwright/test'

/**
 * 打开「数据修复」并点「开始检查」。
 *
 * 前提：当前页已在 `/data` —— 导航不归它，由各 spec 的 `beforeEach` 走
 * `helpers/nav` 的 `gotoApp`。它原来住在 `describe` 内部（`repair-center.spec.ts:171`），
 * 拆文件后两半都要用，留在任一半里就是往 spec 里复制第二份。
 * 第二个点击带 `timeout: 10_000` 是原值，别调小：对话框打开与检查请求在同一次交互里。
 */
export async function openRepairCenter(page: Page) {
  await page.locator('button').filter({ hasText: '数据修复' }).first().click()
  await expect(page.getByRole('button', { name: '开始检查' })).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: '开始检查' }).click()
}
```

- [ ] **Step 6: 把 `disk-usage-chip` 的局部副本换成 import**

Modify `frontend/e2e/data/disk-usage-chip.spec.ts`：删除 `:32-45`（那段「这是本仓第二份同名副本…」的注释连同函数），并在 import 段（`:8` 之后）加一行：

```ts
import { apiGet } from '../helpers/apiClient'
```

同时把 `:2` 的 `import { test, expect, type Page } from '@playwright/test'` 改成 `import { test, expect } from '@playwright/test'` —— 该文件里 `Page` 只出现在被删掉的 `apiGet` 签名上（现查：`:37`），留下未使用的类型导入会被 `lint:e2e` 的 `noUnusedLocals`（`frontend/tsconfig.e2e.json:15`）当场报 TS6133。

- [ ] **Step 7: 跑类型闸**

Run: `cd frontend && npm run lint:e2e`
Expected: 零条 `error TS`。（这一步是本仓的机械闸之一：e2e 不在 `npm run build` 的覆盖面里，只有 `lint:e2e` 会抓未使用导入与失去调用者的助手。）

- [ ] **Step 8: 跑第一个消费者的真实用例**

Run: `cd frontend && npx playwright test e2e/data/disk-usage-chip.spec.ts`
Expected: **业务用例名逐条在，且红集合 ⊆ 基线红集合**（汇总含 setup 两条，形状是 `Running <业务数+2> tests`，
见 Global Constraints）。基线红集合 = `disk-usage-chip` 的 case3「上传一个文件后以 fresh=1 重拉…」那条
`not.toHaveText`（2026-11-15 台账已定性为**存量红**：载荷 2 MiB 跨不动 GB 档 10.49 MB 步长，
与该用例 `:149` 注释预告的响法一致，且与 apiGet 的提供者无关）。红了就是 helper 版与局部版不等价 —— **不许改用例迁就 helper**，回头 diff 函数体。

- [ ] **Step 9: Commit**

```bash
git add frontend/e2e/helpers/apiClient.ts frontend/e2e/helpers/djangoShell.ts \
        frontend/e2e/helpers/repairCenterFlow.ts frontend/e2e/data/disk-usage-chip.spec.ts
git commit -m "test(e2e): 抽出 apiClient/djangoShell/repairCenterFlow 三件共享助手并让占用 chip 先落地"
```

`tasks/b4a-titles.mjs` **刻意不进 add 列表**：`.gitignore:162` 是 `/tasks/*`，整个 `tasks/` 除
`e2e-nightly/LATEST.md` 外都不入库。这跟仓里既有的 `tasks/probe_*.py` 同性质 —— 闸是本机取证工具，
不是交付物；写进台账时说明它在 `tasks/` 下、换机器需重写即可。

---

### Task 2: `repair-center.spec.ts` 切到 helper（只改「谁调用」，一行判据都不动）

**Files:**
- Modify: `frontend/e2e/data/repair-center.spec.ts:1-6`（import 段）、`:22`（`PYTHON`）、`:29-61`（三件助手）、`:171-175`（`openRepairCenter`）
- Test: 同文件既有用例 + 标题集合闸

**Interfaces:**
- Consumes: Task 1 的 `apiGet`、`apiPost`、`shellDjango`、`openRepairCenter`（签名见 Task 1 Produces）

- [ ] **Step 1: 证明闸本身可用（改前基线已存）**

Run: `cat tasks/b4a_titles_baseline.txt | wc -l`
Expected: `11`（见 Global Constraints 计数形状：9 业务 + setup 两条）。不是 11 就停下。

- [ ] **Step 2: 删局部助手，加 import**

在 `frontend/e2e/data/repair-center.spec.ts` 里：

删除这些行（内容已在 Task 1 逐字搬走）：`:22`（`const PYTHON = ...`）、`:29-36`（`shellDjango` 及其注释）、`:38-45`（`apiGet`）、`:48-61`（`apiPost`）、`:171-175`（`describe` 内的 `openRepairCenter`）。

把 import 段改成（`:1-6`）：

```ts
import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { ACCOUNTS, DATA_DIR, PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { apiGet, apiPost } from '../helpers/apiClient'
import { shellDjango } from '../helpers/djangoShell'
import { openRepairCenter } from '../helpers/repairCenterFlow'
```

**勘误（Task 2 评审提出，已按实测回写）**：本步 import 段实际应保留 `type Page` —— 删掉四个局部助手之后，
`Page` 仍被**留下的** dup 专属助手用着（Task 3 才搬走它们，实测 `:59` `seedDuplicatePair`、`:77` `dupEndState`、
`:89` `dupRemainingBatches` 三处形参）。照本步原文删 `type Page` 会 TS2304，与本步 Step 3「零 error TS」自相矛盾。
Task 3 Step 1/Step 4 已把这层双向耦合写死。**已完成的历史步骤不再重放**，此段仅供后来人对照。

要点：`execSync`（原 `:4`）与 `PROJECT_ROOT`（原 `:5` 里的一项）在删掉 `PYTHON`/`shellDjango` 后**在本文件里没有别的用处**（现查：`execSync` 仅 `:30`，`PROJECT_ROOT` 仅 `:22`/`:31`），必须一起摘掉，否则 `lint:e2e` 报 TS6133。`path`/`fs`/`ACCOUNTS`/`DATA_DIR`/`PRIMARY_SAMPLE_FILE`/`gotoApp` 全都还有别的用处，保留。

- [ ] **Step 3: 类型闸**

Run: `cd frontend && npm run lint:e2e`
Expected: 零条 `error TS`。

- [ ] **Step 4: 标题集合必须与基线逐字相等**

Run:

```bash
node tasks/b4a-titles.mjs data/repair-center.spec.ts > tasks/b4a_titles_t2.txt
diff tasks/b4a_titles_baseline.txt tasks/b4a_titles_t2.txt && echo TITLES_IDENTICAL
```

Expected: `diff` 无输出且打印 `TITLES_IDENTICAL`。有差异 = 搬运中丢/改了某条用例标题，当场回查，别往下走。

标题闸看不见 serial 与 tag（Global Constraints 那条盲区），同一步再对账这两行的**原文**：

```bash
grep -n "test.describe.serial\|tag: \['@p2', '@data'\]" frontend/e2e/data/repair-center.spec.ts
```

Expected: 与 Task 1 之前现读的那一行逐字相同（serial 声明在 `:152`、标签是 `{ tag: ['@p2', '@data'] }`，
中间只允许行号因上面的删除而左移）。

- [ ] **Step 5: 单文件真跑**

Run: `cd frontend && npx playwright test e2e/data/repair-center.spec.ts`
Expected: repair-center 的 **9 条业务用例名逐条在**，且红集合 ⊆ 基线红集合（本文件此刻的基线红集合是**空**，
Task 1 没跑过它 ⇒ 第一次跑就给它立基线）。汇总会是 `11 passed` 形状（多两条 setup）。
**若出现红**：先做 HEAD 对照轮（同一命令在 `git stash` 之外用 `git show HEAD:<file>` 落临时探针文件跑，
跑完删除），定性成存量红还是本刀引入的，只有后者才进入修代码；结论与两条命令一起写进台账。
有 `skipped` 时逐条核对原因必须是样例数据缺失 `PRIMARY_SAMPLE_FILE`，不得是断言失败。

- [ ] **Step 6: 记录本次改动集的判档（用 `--dry-run`，不许真跑）**

Run: `node scripts/e2e_affected.mjs --dry-run`（落 `tasks/b4a_affected_t2.log`）
Expected: `decide:` 行会因 `frontend/e2e/helpers/` 命中 `GLOBAL` 而判全量 e2e + 后端；`RESULT:` 行带
`dry-run` 字样。**为什么这里不许真跑**：这脚本没有 `--help` 分支，未知参数一律当默认**直接开跑整条判据链**
（`docs/tasks/lessons.md` 2026-11-15 新记那条），而真跑 = 起一次全量池 + 后端全套，那是 Task 5 的活。
**裁定**：批内一律 `--dry-run` 留判据行，真跑全量档集中在 Task 5 一次做完并覆盖整刀（设计稿 §3.7 的排法，
与批3a「收口判全量 ⇒ 上面几轮是它的超集」同形）。把 `decide:`/`RESULT:` 两行原样贴进台账。

- [ ] **Step 7: Commit**

```bash
git add frontend/e2e/data/repair-center.spec.ts
git commit -m "refactor(e2e): repair-center 改用三件共享助手，取数通路逐字不变"
```

---

### Task 3: 拆出 `duplicate-keep.spec.ts`

行数归属已现查确认（用词边界匹配逐个数过调用点）：`seedDuplicatePair`/`dupEndState`/`dupRemainingBatches`/`cleanupDup`/`dupDirs`/`DUP_PREFIX`/`DUP_CONTENT` 的调用点**全部落在重复项 5 条用例之内**，留下的 4 条一次都不碰 ⇒ 它们整体搬走，不进 helper。反向也确认过：`openRepairCenter` 同时被留下侧（`:185/:208/:245/:289/:580`）与搬走侧（`:371/:411/:445/:517/:565`）调用 ⇒ 只能进 helper（Task 1 已做）。

**Files:**
- Create: `frontend/e2e/data/duplicate-keep.spec.ts`
- Modify: `frontend/e2e/data/repair-center.spec.ts`（删除重复项一族）
- Test: 两个文件的既有用例 + 标题集合闸（这次比的是**并集**）

**Interfaces:**
- Consumes: Task 1 的 `apiGet`/`apiPost`/`shellDjango`/`openRepairCenter`；`../fixtures/test-data` 的 `ACCOUNTS`/`DATA_DIR`；`../helpers/nav` 的 `gotoApp`
- Produces: `frontend/e2e/data/duplicate-keep.spec.ts`，`test.describe.serial` 标题「重复项选保留」，标签 `['@p2', '@data']`

- [ ] **Step 1: 建新文件骨架**

Create `frontend/e2e/data/duplicate-keep.spec.ts`，内容如下（两处 `PASTE` 标记在 Step 2/3 用原文替换）。
`type Page` 必须带：搬过来的三个助手签名里就是 `page: Page`（现查源文件 `:59` `seedDuplicatePair`、
`:77` `dupEndState`、`:89` `dupRemainingBatches`），漏了它 `lint:e2e` 直接 TS2304。

```ts
import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { ACCOUNTS, DATA_DIR } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { apiGet, apiPost } from '../helpers/apiClient'
import { shellDjango } from '../helpers/djangoShell'
import { openRepairCenter } from '../helpers/repairCenterFlow'

/**
 * 重复项选保留的界面层（T3）。从 `repair-center.spec.ts` 拆出来，理由只有一个：
 * 那份文件 591/600 行已到闸口（`scripts/line-limit.mjs:18`），而 §5.4 续删、UX-1 锁定态、
 * FIX-1 的「刷新不吞勾选」对照用例都还要往这一族加判据 —— 先拆再加，别为凑行数砍判据。
 * 设计稿：`docs/superpowers/specs/2026-11-15-batch4a-e2e-split-and-username-guard-design.md` §2。
 */

// 后端落盘位置跟着进程走：非 slot = `<仓库根>/test/e2e-data`，slot = 该 slot 自己的 data_dir。
// 这一行与 repair-center.spec.ts 里的那条逐字相同，刻意**不抽**：它只是对既有 fixture 常量的
// 一次拼装，不是行为复制（同仓那条「三条相似行好过过早抽象」）。
const ADMIN_BATCH_DIR = path.join(DATA_DIR, 'media', 'data', ACCOUNTS.admin.username, 'batch')

const ts = Date.now()

// PASTE-HELPERS: repair-center.spec.ts 里从 `const DUP_PREFIX = ...` 起、
//                到 `cleanupDup` 函数收尾 `}`（含各自的原注释）整段，逐字粘在这里。

test.describe.serial('重复项选保留', { tag: ['@p2', '@data'] }, () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page, '/data')
  })

  // PASTE-CASES: repair-center.spec.ts 里从那段「重复项选保留（批3a · 第 3 项 + 终审 F2）五条用例」
  //              的 docblock 起，到 `截断提示：总数 > 展示数才渲染进卡片，反向不渲染 [B3A-F2NOTE]`
  //              那条用例的收尾 `  })` 为止的整段，逐字粘在这里。
})
```

两个必须留意的取舍：

- **为什么必须自带 `beforeEach`**：`openRepairCenter` 只做两次点击、不导航，原来这个前置由
  `repair-center.spec.ts` 的 `beforeEach` 统一提供。拆出去不带上它，5 条用例会在没有 `/data`
  页面的情况下找「数据修复」按钮 —— 那是等待超时红，不是判据红。
- **为什么 `PRIMARY_SAMPLE_FILE` 不在 import 里**：现查它的调用点只有 `:178/:180/:183/:236/:239`
  （全在留下的那 4 条里）。多带一个未使用的 import 会被 `lint:e2e` 的 `noUnusedLocals` 报 TS6133。

- [ ] **Step 2: 粘 PASTE-HELPERS**

在 `frontend/e2e/data/repair-center.spec.ts` 里按锚点定位整段并原样复制：起 `const DUP_PREFIX = `
（Task 2 后它的行号已左移，**按锚点找，别按本计划的行号**），止 `cleanupDup` 的收尾 `}`
（其上是 `for (const dir of dirs) fs.rmSync(dir, { recursive: true, force: true })`）。
**只改缩进，不改任何字面量。** 段内 `apiPost`/`apiGet`/`shellDjango` 的调用形态不动，靠新文件顶部
的 import 接上。`shellDjango` 在新文件里的用处只有一处（`cleanupDup` 内那条按 `filename` 删行的
`DataFile.objects.filter(...)`），别把 `cleanupDup` 换成 API 清理 —— 那是行为改写，不在本刀。

**锚点自查**：这一段拆前占 `:63-150`，应为 **88 行**（含注释）。粘完数一下新文件这一段，
差超过 ±5 行就是锚点找错（多半是把 `openRepairCenter` 或 `REPAIR_FILE` 一起带过来了 —— 那两个不属于这一族）。

- [ ] **Step 3: 粘 PASTE-CASES**

同文件按锚点复制整段：起 `  /**` + `   * 重复项选保留（批3a · 第 3 项 + 终审 F2）五条用例。`，
止 `[B3A-F2NOTE]` 那条用例的收尾 `  })`。这段含 M19–M25 与 F 系列的变异反证 docblock，
它是判据的一部分（写明哪句断言杀哪颗变异），**一个字都不许删、不许压缩**。

**锚点自查**：这一段拆前占 `:302-576`，应为 **275 行**，且必须恰好包含 5 个 `test(` 调用
（自查：`grep -c "^  test(" <<<粘贴段` 得 5）。数不对就是漏了 `[B3A-F2A]` 或把留下的
`修复后本批次问题全部消失` 也带过来了 —— 后者属于留下的 4 条。

- [ ] **Step 4: 从 `repair-center.spec.ts` 删掉这两段**

删除 Step 2 与 Step 3 复制走的整段（现在它们在新文件里）。然后核对留下的部分：
`BATCH`、`REPAIR_FILE`、`orphanDir`、`afterEach`、`PRIMARY_SAMPLE_FILE` 仍在用，一个都不许顺手删。

反向也要核：`type Page` 在 Task 2 之后**只**被 `seedDuplicatePair`/`dupEndState`/`dupRemainingBatches`
三个函数用着（Task 2 的实现者正是因为这个才没摘它，实测见 `:59`/`:77`/`:89`）。这三段一旦被搬走，
`repair-center.spec.ts` 里 `Page` 就**重新变成零用处** ⇒ 必须把 `:1` 改回
`import { test, expect } from '@playwright/test'`，否则 TS6133。搬完现查一次再定：

```bash
grep -n ": Page\|type Page" frontend/e2e/data/repair-center.spec.ts
```

Expected: 摘除前它会列出那三处（搬走后应为空 ⇒ 摘 `:1`）。

- [ ] **Step 5: 类型闸**

Run: `cd frontend && npm run lint:e2e`
Expected: 零条 `error TS`。这一步同时兜住两种典型搬运残留 —— 旧文件里失去调用者的 import（TS6133）、
新文件里漏掉的 import（TS2304）。

- [ ] **Step 6: 标题并集与基线相等（本刀的核心闸）**

Run:

```bash
node tasks/b4a-titles.mjs data/repair-center.spec.ts data/duplicate-keep.spec.ts \
  > tasks/b4a_titles_t3.txt
diff tasks/b4a_titles_baseline.txt tasks/b4a_titles_t3.txt && echo UNION_IDENTICAL
```

Expected: `diff` 无输出且打印 `UNION_IDENTICAL`。

再对账 serial/tag —— 这是拆文件最怕丢的两行（丢了不影响任何标题，但清理顺序契约与池的 project 归属就变了）：

```bash
grep -n "test.describe.serial\|tag: \['@p2', '@data'\]" frontend/e2e/data/repair-center.spec.ts frontend/e2e/data/duplicate-keep.spec.ts
```

Expected: **两处**各有一条 serial 声明 + 一条 `{ tag: ['@p2', '@data'] }`（留下的一半与拆出的一半各自完整），
且新文件那条的标题是「重复项选保留」。这一步的语义是「4 + 5 = 拆前的 9，一条不多一条不少，
标题逐字相同」。任何差异都说明有用例被漏搬，或某条断言在搬运中被动了名。

- [ ] **Step 7: 两个文件各自单跑**

Run: `cd frontend && npx playwright test e2e/data/repair-center.spec.ts`
Expected: 业务 4 条**零 `failed`**，其中 2 条会 `skipped` —— 它们是 `test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE))`
守卫的那两条（`:178`/`:236`），而本机现测 `Data/SampleData` **不存在**（`/Data/` 被 `.gitignore:145` 整目录挡掉，
属本机私有料）。所以形状是 `2 passed + 2 skipped`（外加 setup 两条）。**这 2 条 skip 不是回归**，2026-11-15
Task 2 已实测确认；把它当异常去补料或删守卫都是越域。

Run: `cd frontend && npx playwright test e2e/data/duplicate-keep.spec.ts`
Expected: 业务 **5 条全通过、零 `failed`**（汇总 `7 passed`，含 setup 两条）。这 5 条**都不带** 
PRIMARY_SAMPLE_FILE 守卫（现查：该常量的守卫只出现在 `:178`/`:236` 两条留下的用例里）⇒ 不该出现 skip；
出现 skip 就是搬错了用例或动了守卫。

分开设两步的原因：Task 3 之后「哪一半红了」必须能一句话回答；两半合起来跑的红点归因不了。

- [ ] **Step 8: 提交**

```bash
git add frontend/e2e/data/duplicate-keep.spec.ts frontend/e2e/data/repair-center.spec.ts
git commit -m "test(e2e): 重复项一族拆出 duplicate-keep.spec.ts，助手指向 helpers"
```

---

### Task 4: 修掉会因此变假的指向

现查全仓对 `repair-center.spec.ts` 的**非自身**引用只有三处，逐条判过要不要动：

| 位置 | 现文 | 处置 |
|---|---|---|
| `frontend/test/unit/dupKeep.spec.ts:9` | 「卡片渲染由 T3（`repair-center.spec.ts`）钉」 | 改成 `duplicate-keep.spec.ts`（拆后卡片渲染在那份里） |
| `frontend/test/unit/dupKeepWiring.spec.ts:4` | 「`repair-center.spec.ts` 钉的是…」 | 同上 |
| `frontend/e2e/data/disk-usage-chip.spec.ts:33` | 「与 `repair-center.spec.ts:36` 同一种拿法」 | Task 1 Step 6 已连同这段注释一起删掉那个函数，无需再动 |
| `frontend/e2e/helpers/djangoShell.ts:13` | 把「`repair-center.spec.ts` 的 `afterEach`」与「`cleanupDup`」并列为同文件的两种吞错示例 | **Task 3 评审新增**：`cleanupDup` 现已住在 `duplicate-keep.spec.ts` ⇒ 那句「同文件」失准，改成点名两个文件（纯注释，不触判据）|

**Files:**
- Modify: `frontend/test/unit/dupKeep.spec.ts:9`、`frontend/test/unit/dupKeepWiring.spec.ts:4`

**Interfaces:**
- Consumes: Task 3 的产出文件名 `frontend/e2e/data/duplicate-keep.spec.ts`

- [ ] **Step 1: 改两处注释**

把两份文件里指向 `repair-center.spec.ts` 的那句改成指向 `duplicate-keep.spec.ts`，其余文字一字不动
（这两句是 T2 层「我为什么不在这层钉」的理由，改文件名的同时不能改口径）。

- [ ] **Step 2: 证明没有残留假话**

Run: `grep -rn "repair-center" frontend/test/unit frontend/e2e/data/duplicate-keep.spec.ts`
Expected: `frontend/test/unit/` 下**零命中**；`duplicate-keep.spec.ts` 里允许**两处**真话引用 —— 头部来历那句
（`:11`）与 `ADMIN_BATCH_DIR` 上方「与 `repair-center.spec.ts` 里的那条逐字相同」那句（`:19`，Task 3 刻意
两边各留一行、不抽 helper 的说明，实测两行确实逐字相同）。**判据是「引用是否为真」，不是「引用条数为 1」**。

- [ ] **Step 3: vitest 全绿（源码绊线不许被牵红）**

Run: `cd frontend && npx vitest run`
Expected: 与拆前**同数量**的 `Test Files passed` / `Tests passed`。对照数是 **Task 1 Step 2** 落的
`tasks/b4a_vitest_before.log`（改注释这一步理论上不该动任何 vitest 数字，动了就是绊线被牵红）。

- [ ] **Step 4: 提交**

```bash
git add frontend/test/unit/dupKeep.spec.ts frontend/test/unit/dupKeepWiring.spec.ts
git commit -m "docs(test): 重复项 T2 的 T3 指向随拆文件改到 duplicate-keep"
```

---

### Task 5: 收口档（一次全量，覆盖整刀）+ 台账

**Files:**
- Modify: `docs/tasks/todo.md`（新增刀一条目）
- 落盘：`tasks/b4a_final_*.log`

- [ ] **Step 1: 起池前的两条本机检查（都不是可选）**

Run: `netstat -ano | grep -E ":(2100[1-9]|2200[1-9])[[:space:]]" | grep LISTENING`
Expected: **空**。非空 ⇒ 有别的会话活池或孤儿进程占着 slot 端口（本仓 e2e 八类红因之一）。
先确认归属再动，**不许**杀不属于本会话的进程（同机的 IDE `test-server`、ASUS `ROGLiveService`
都不是池进程）。

Run:

```bash
powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object FreeVirtualMemory,TotalVirtualMemorySize | Format-List"
```

Expected: 空闲**提交**内存 ≥ 8.0 GB（本机预算）。低于预算 ⇒ 这一轮不该开跑；先清进程或换时段，
**不要**用降 `--slots` 硬扛（`--slots=2` 实测照样在 1240s 掉 slot 后端）。

- [ ] **Step 2: 全量池**

Run: `node scripts/e2e_pool.mjs --slots=4`（后台跑，输出落 `tasks/b4a_final_pool.log`）
Expected 判据行：`unexpected 0`、结论 `MEASURED`；红集合为空，或逐条独占复跑转绿。
拆出的 `duplicate-keep.spec.ts` 会自动进池 —— `scripts/e2e_pool.mjs:158-161` 用
`playwright --list` 枚举，没有硬编码清单 —— **文件数应比基线多 1**，这一格就是「新文件真的落进池」的实证。

- [ ] **Step 3: 后端全套**

Run: `CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test`
（落 `tasks/b4a_final_backend.log`）
Expected: `OK`，且 `grep -cE "^(FAIL|ERROR):"` 为 **0**。本刀零后端改动 ⇒ 这条是回归兜底，不是新覆盖。

- [ ] **Step 4: vitest + 行数闸 + lint + build**

```bash
cd frontend && npx vitest run > ../tasks/b4a_final_vitest.log 2>&1
cd frontend && npx vitest run test/unit/lineLimit.spec.ts > ../tasks/b4a_final_linelimit.log 2>&1
cd frontend && npm run lint:e2e > ../tasks/b4a_final_lint.log 2>&1
cd frontend && npm run build > ../tasks/b4a_final_build.log 2>&1
```

Expected: vitest 全绿，且 `Test Files` / `Tests` 两个数与 **Task 1 Step 2** 落的
`tasks/b4a_vitest_before.log` 逐字相同（本刀没加也没删任何 vitest 用例）；lineLimit `Tests 15 passed`
（**不给任何文件加豁免**）；`lint:e2e` 零 `error TS`；`npm run build` 打印 `✓ built`。

- [ ] **Step 5: 现量行数并写进台账（不许引用本计划的估算）**

Run: `wc -l frontend/e2e/data/repair-center.spec.ts frontend/e2e/data/duplicate-keep.spec.ts`
Expected: 两个数都显著低于 600；并记下拆前 591 这个数作为对照。

- [ ] **Step 6: affected 收口判档**

Run: `node scripts/e2e_affected.mjs --base master --dry-run`（落 `tasks/b4a_final_affected_dry.log`）
Expected: `decide: 全量 e2e…` + `RESULT: PASS · dry-run` ⇒ Step 2 的全量池与 Step 3 的后端全套
是这次改动集所需门禁的**超集**。**注意**：这脚本没有 `--help` 分支，未知参数会当默认直接开跑整条判据链
（本仓 lessons 2026-11-15 新记那条），探参数只能读源码或用 `--dry-run`。

- [ ] **Step 7: 台账条目**

在 `docs/tasks/todo.md` 追加刀一条目，按批3a/批3b 的形状写：

- 状态、base 与 tip（**按并入那一刻**写，不要预写未来的 master 值）；
- 收口各档的**判据行原文**（取判据行，不取退出码）；
- 三档测试数现读：本刀 **T1 0 / T2 0 / T3 新增 0**，9 条既有 T3 用例改文件归属（4 留 + 5 搬），
  等价性由 `tasks/b4a_titles_*.txt` 的集合相等证明；
- 遗留：§2.4 的 serial 跨文件并发差异（判定接受，红了回那一节）、fetch 变体统一、`page.request` 通路统一；
- 一句「本刀不触发介绍书」——未改任何页签/列名/按钮/判定口径，CLAUDE.md 维护时机 ② 不命中。

- [ ] **Step 8: 提交**

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 批4 刀一 收口台账（标题集合等价闸与全量档判据行）"
```

- [ ] **Step 9: 并入本地 master（要用户点头，本刀不自行 FF）**

先 `git merge-base --is-ancestor master feature/batch4a-e2e-dup-split` 验 FF 可行，再走
`git branch -f master feature/batch4a-e2e-dup-split`（纯快进、零工作树变动，
共享工作树纪律见 `docs/tasks/todo.md:184` 与设计稿 §6），**不 push**（`origin` 是公开仓库）。
删过程分支需要先切 HEAD，那一步单独问。

---

## 遗留（不在本计划内，各有归属）

1. **serial 档的跨文件并发**（设计稿 §2.4）：本刀判定接受。若 serial 轮出现 `database is locked`
   或重复组计数漂移，回那一节做文件间互斥，**不许**改成削判据。
2. **其余 fetch 变体统一**（§2.1 非目标、§4）。
3. **`page.request` 通路统一**：`cleanup.ts:34-47` 那条更干净的路子，属独立工单。
4. **刀三 FIX-1 对照用例的落点**：加进 `duplicate-keep.spec.ts` 还是 `data` 侧别处，刀三 自己定 ——
   本刀只是把余量还出来。


# e2e slot 池并行化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 e2e 全量轮从 19.7min（386 例 / workers=1 串行）压到 10 分钟级，且不删一条判据。

**Architecture:** 新增 `scripts/e2e_pool.mjs` 编排器：先在 TEMP 预铸一份模板库+种子 media，按实测时长做 LPT 分区，起 N 个「1 进程 = 1 worker = 1 slot」的 Playwright 子进程；每 slot 有独立 SQLite 副本、独立 `data_dir`（media 用硬链镜像）、独立前后端端口对、独立 `SECRET_KEY` 与 Redis db index。纯逻辑（分区/端口/清单/统计）落在可单测的 `pool-core.mjs`（T2 层），Playwright 侧只读一份 `slot.json` 契约。

**Tech Stack:** Node 24 ESM（`*.mjs`）、Playwright Test 1.60（blob/json reporter + `merge-reports`）、vitest 5（node 环境，无 jsdom）、Django 5 SQLite(WAL)、Windows `fs.linkSync` 硬链。

**Spec:** `docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md` —— 每条任务的判据来自它，执行时两份一起读。

## Global Constraints

- 一条断言都不删、不 `skip`、不放大超时来换时间（spec §1）。
- 每个 slot 进程内固定 `--workers=1`：现有 helper 全部按串行调校，一行不改（spec §3）。
- slot 数默认 4，`E2E_SLOTS`/`--slots` 可调，上限 6；每 slot 预算 ≈1GB RAM（机器 32GB / 28 逻辑核）。
- 端口对基址：backend `8101+i`、frontend `3101+i`；不足即 fail fast，**绝不静默复用别人在跑的服务**。
- `LQDP_SKIP_STORAGE_MIGRATION=1` 是 slot 模式的硬前提：不带它而把 `data_dir` 指向 TEMP 会让
  `apply_system_config` 走「搬走并删源」的 `_migrate`（`apps/common/system_config.py:389-391`），毁掉仓库根
  `db.sqlite3` 与 `media/`。**禁止用「故意不带这个开关跑一次」来证明它承重**（spec §4.1 / §11）。
- 不做 per-slot 用户名（spec §4.2）：owner-scoped 列表 + 副本库已经隔离。
- 路径口径统一：`pool-core`/`merged.json`/`durations` 全部用 **相对 testDir 的裸路径**（`analysis/serial-overlap.spec.ts`），
  只有拼给 Playwright CLI 时才加 `e2e/` 前缀。
- 测试文件放 `test/` 下；临时脚本/日志放 `tasks/`；正式文档放 `docs/`。
- 单文件 ≤600 行。
- 每个任务结束即 `git commit`（逐文件显式 `git add`，禁 `git add -A`；共享工作区，禁裸 `git stash`）。
- e2e 与后端 pytest 仍不并跑（本轮维持）；跑完释放自己起的所有端口。
- Windows 下调 `npx`/`npm` 一律走 `execSync(..., { shell: true })`（`execFileSync('npx', …)` 在无 shell 时会 ENOENT/127）。

## 文件地图

| 动作 | 路径 | 职责 |
|---|---|---|
| Create | `frontend/e2e/helpers/pool-core.mjs` | 纯函数：`autoSlots` / `allocatePortBlock` / `partitionFiles` / `assertSafeRelPath` / `buildSlotManifest` / `slotEnv` / `mergeRunStats`。无 fs、无子进程 |
| Test | `frontend/test/unit/e2ePoolCore.spec.ts` | 上面每个纯函数的 T2 单测（vitest，node 环境） |
| Create | `frontend/e2e/helpers/slot.ts` | 读 `slot.json` 契约 → 导出 `CURRENT_SLOT` 与 slot-aware 路径；无 slot 时逐字回落今天 |
| Modify | `frontend/e2e/fixtures/test-data.ts:10-31` | `E2E_SYSTEM_CONFIG_FILE` / `AUTH_DIR` / `DOWNLOAD_DIR` 改为从 `helpers/slot` 转出（原名不变，调用方零改动） |
| Modify | `frontend/playwright.config.ts:10-22`、`76-128`、`130-170` | slot 模式：不重写全局 config、storageState 用 slot 目录、webServer 注入 3 条 env 且 `reuseExistingServer:false`、可跳过重复 build |
| Modify | `frontend/e2e/global-setup.ts:36-53` | slot 模式跳过 migrate/seed（模板已铸），只清 slot 的 `.downloads` |
| Create | `scripts/e2e_pool.mjs` | 编排器：模板构建 → slot 目录（拷库 + 硬链镜像）→ 分区 → 并发 spawn → 统计合并 → blob 出 HTML |
| Modify | `frontend/e2e/batch/batch-phase.spec.ts:27`<br>`frontend/e2e/data/repair-center.spec.ts:17` | `PROJECT_ROOT/media/...` → `DATA_DIR/media/...` |
| Create | `frontend/e2e/helpers/nightly-gates.mjs` | `THRESHOLDS` + `evaluateGates(rep, slots)` 纯函数（放 vitest root 内，脚本反向引用） |
| Test | `frontend/test/unit/e2eNightlyGates.spec.ts` | 阈值判定单测 |
| Modify | `scripts/e2e_nightly.mjs`（阈值与起跑） | 接池 + 读 `merged.json` |
| Modify | `scripts/e2e_affected.mjs:238-299` | 复用同一个池跑受影响文件 |
| Modify | `frontend/package.json:16-27` | 加 `test:e2e:pool` |

---

## P0 — 前置实测（不改产品/测试代码）

### Task 1: TEMP 模板库 + 硬链镜像 + WAL 拷贝的可行性与耗时

编排器的每条前提都在这里验：`data_dir` 指 TEMP 时 `SKIP_STORAGE_MIGRATION` 是否真的零副作用、`seed_test_data`
能否在 TEMP 目标下播种、SQLite 的 `db.sqlite3-wal/-shm` 会不会让「只拷主文件」丢数据、硬链镜像要多久、
以及删镜像里的文件会不会伤到模板。

**Files:**
- Create: `tasks/e2e-slot-probe/probe-template.mjs`（临时探针，不入库）

**Interfaces:**
- Produces: 数字表（模板构建秒数 / 拷库秒数 / 硬链秒数 / sidecar 现状 / seeded 行数）→ 写进 `docs/reference/e2e-tier-triage.md` 文末与 spec §9-P0

- [ ] **Step 1: 写探针脚本**

```js
// tasks/e2e-slot-probe/probe-template.mjs
// 只读仓库、只写 %TEMP%\lqdp-e2e-probe-template。绝不 rmtree 仓库根。
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const PY = process.env.PYTHON_BIN || path.join(ROOT, '.venv', 'Scripts', 'python.exe')
const PROBE = path.join(os.tmpdir(), 'lqdp-e2e-probe-template')
const say = (...a) => console.log(...a)
const ms = (t0) => ((performance.now() - t0) / 1000).toFixed(1) + 's'

fs.rmSync(PROBE, { recursive: true, force: true })
fs.mkdirSync(path.join(PROBE, 'temp'), { recursive: true })
const cfg = path.join(PROBE, 'system-config.json')
fs.writeFileSync(cfg, JSON.stringify({ data_dir: PROBE, temp_dir: path.join(PROBE, 'temp') }), 'utf-8')

// 关键：不带 LQDP_SKIP_STORAGE_MIGRATION 就 **不跑** —— 它会走 _migrate 搬走并删仓库根 db+media。
// 该结论只做代码走读（apps/common/system_config.py:385-391），不做破坏性实测。
const env = {
  ...process.env, LQDP_SYSTEM_CONFIG_FILE: cfg, LQDP_SKIP_STORAGE_MIGRATION: '1',
  SECRET_KEY: 'e2e-probe-not-used', PYTHONIOENCODING: 'utf-8',
}
const dj = (args) => execFileSync(PY, ['manage.py', ...args], {
  cwd: ROOT, env, encoding: 'utf-8', timeout: 900_000, maxBuffer: 128e6,
})
const last = (s) => s.trim().split('\n').filter(Boolean).slice(-1)[0]

let t = performance.now()
say('migrate:', last(dj(['migrate', '--noinput'])), ms(t))
t = performance.now(); dj(['seed_users']); say('seed_users:', ms(t))
t = performance.now(); say('seed_test_data --refresh:', ms(t), last(dj(['seed_test_data', '--refresh'])))

// 仓库根没被动过（探针自检，防自己变成那个事故）
say('仓库根 db 仍在:', fs.existsSync(path.join(ROOT, 'db.sqlite3')), '| media 目录仍在:', fs.existsSync(path.join(ROOT, 'media')))

// WAL sidecar 现状 + checkpoint 后才拷贝
const dbSrc = path.join(PROBE, 'db.sqlite3')
for (const suffix of ['', '-wal', '-shm']) {
  if (fs.existsSync(dbSrc + suffix)) say('sidecar', suffix || '(main)', fs.statSync(dbSrc + suffix).size, 'bytes')
}
t = performance.now()
dj(['shell', '-c', "from django.db import connection as c; c.connection.cursor().execute('PRAGMA wal_checkpoint(TRUNCATE)'); print('checkpointed')"])
say('wal_checkpoint(TRUNCATE):', ms(t))

for (const suffix of ['-wal', '-shm']) { const p = dbSrc + suffix; if (fs.existsSync(p)) fs.rmSync(p) }
const dbDst = path.join(PROBE, 'copy', 'db.sqlite3')
fs.mkdirSync(path.dirname(dbDst), { recursive: true })
t = performance.now(); fs.copyFileSync(dbSrc, dbDst); say('拷库:', ms(t), fs.statSync(dbSrc).size, 'bytes')
say('副本行数:', last(dj(['shell', '-c', 'from apps.datafiles.models import DataFile as D; print("rows="+str(D.objects.count()))'])))

// 硬链镜像：模板 media → slot media
const mediaSrc = path.join(PROBE, 'media')
const mediaDst = path.join(PROBE, 'slot', 'media')
fs.rmSync(path.join(PROBE, 'slot'), { recursive: true, force: true })
const count = (d) => fs.readdirSync(d, { withFileTypes: true }).reduce((n, e) =>
  n + (e.isDirectory() ? count(path.join(d, e.name)) : 1), 0)
const mirror = (src, rel = '') => {
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    const from = path.join(src, e.name), to = path.join(mediaDst, rel, e.name)
    if (e.isDirectory()) { fs.mkdirSync(to, { recursive: true }); mirror(from, path.join(rel, e.name)) }
    else fs.linkSync(from, to)
  }
}
t = performance.now(); fs.mkdirSync(mediaDst, { recursive: true }); mirror(mediaSrc)
say('硬链镜像 media:', ms(t), '文件数:', count(mediaSrc))

// 删除语义：摘掉镜像里一个文件，模板同名文件必须还在
const firstFile = (d) => {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (e.isDirectory()) { const r = firstFile(path.join(d, e.name)); if (r) return r }
    else return path.join(d, e.name)
  }
  return null
}
const one = firstFile(mediaSrc)
const mirrored = path.join(mediaDst, path.relative(mediaSrc, one))
say('镜像 nlink(删除前)=', fs.statSync(mirrored).nlink)
fs.unlinkSync(mirrored)
say('删镜像后模板文件仍在:', fs.existsSync(one))
say('DONE')
```

- [ ] **Step 2: 跑探针并记录**

Run: `node tasks/e2e-slot-probe/probe-template.mjs`
Expected: 一路打到 `DONE`；`仓库根 db 仍在: true`、`删镜像后模板文件仍在: true`、副本查询无异常。
**闸门**：若 `seed_test_data` 在 TEMP 目标下失败或耗时 >60s ⇒ 停下，把结论写回 spec §10 并重议模板策略，不得继续 Task 4。

- [ ] **Step 3: 数字进台账**

把 4 个秒数 + sidecar 现状追加到 `docs/reference/e2e-tier-triage.md` 文末「slot 池 P0 实测」小节，并在 spec §9-P0 后补一行「已实测：…」。探针脚本留在 `tasks/`（不入库）。

- [ ] **Step 4: Commit**

```bash
git add docs/reference/e2e-tier-triage.md docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md
git commit -m "docs(e2e): slot 池 P0 实测数字 —— 模板/硬链/拷库耗时与 WAL sidecar 现状"
```

---

## P1 — 池骨架，先证明「N=1 与今天等价」

### Task 2: `pool-core.mjs` 纯函数（TDD）

**Files:**
- Create: `frontend/e2e/helpers/pool-core.mjs`
- Test: `frontend/test/unit/e2ePoolCore.spec.ts`

**Interfaces:**
- Produces（Task 4 逐字消费这些名字）:
  - `autoSlots(totalMs: number, cap?: number): number`
  - `allocatePortBlock(n: number, isTaken: (port: number) => boolean, baseBackend?: number, baseFrontend?: number): {backend:number, frontend:number}[]`
  - `partitionFiles(files: string[], durationsMs: Record<string, number>, n: number): string[][]`
  - `assertSafeRelPath(p: string): string`
  - `buildSlotManifest({ index, ports, slotRoot, templateRoot, redisDb, secretKey }): SlotManifest`
  - `slotEnv(manifest: SlotManifest, baseEnv?: Record<string,string>): Record<string,string>`
  - `mergeRunStats(reports: SlotReport[]): MergedStats`
  - 常量 `SLOT_BACKEND_BASE=8101` `SLOT_FRONTEND_BASE=3101` `DEFAULT_SLOTS=4` `MAX_SLOTS=6` `SLOT_TARGET_MS=240_000`

`SlotManifest` 字段（跨 JS/TS 契约，改一边必须改另一边）：
`index, backendPort, frontendPort, dataDir, tempDir, dbPath, mediaDir, systemConfigFile, slotFile, authDir, downloadsDir, blobDir, jsonOut, logFile, templateDbPath, templateMediaDir, redisDb, secretKey`

- [ ] **Step 1: 写失败的测试**

```ts
// frontend/test/unit/e2ePoolCore.spec.ts
import { describe, expect, it } from 'vitest'
import {
  SLOT_BACKEND_BASE, SLOT_FRONTEND_BASE, DEFAULT_SLOTS, SLOT_TARGET_MS,
  autoSlots, allocatePortBlock, partitionFiles, assertSafeRelPath, buildSlotManifest, slotEnv, mergeRunStats,
} from '../../e2e/helpers/pool-core.mjs'

describe('autoSlots', () => {
  it('按每 slot ≤SLOT_TARGET_MS 反推，不超 cap、不少于 1', () => {
    expect(SLOT_TARGET_MS).toBe(240_000)
    expect(autoSlots(60_000)).toBe(1)
    expect(autoSlots(1_056_000)).toBe(DEFAULT_SLOTS)   // 今天的串行总量 → 4
    expect(autoSlots(1_056_000, 6)).toBe(5)
    expect(autoSlots(0)).toBe(1)
  })
})

describe('allocatePortBlock', () => {
  it('全空闲时取基址连续块', () => {
    expect(SLOT_BACKEND_BASE).toBe(8101)
    expect(SLOT_FRONTEND_BASE).toBe(3101)
    expect(allocatePortBlock(3, () => false)).toEqual([
      { backend: 8101, frontend: 3101 }, { backend: 8102, frontend: 3102 }, { backend: 8103, frontend: 3103 },
    ])
  })
  it('后端被占 → 整块前移', () => {
    const block = allocatePortBlock(3, (p) => p === 8102)
    expect(block.map((b) => b.backend)).toEqual([8104, 8105, 8106])
    expect(block.map((b) => b.frontend)).toEqual([3104, 3105, 3106])
  })
  it('前端被占也会整块让开', () => {
    const block = allocatePortBlock(2, (p) => p === 3102)
    expect(block.map((b) => b.backend)).toEqual([8103, 8104])
    expect(block.map((b) => b.frontend)).toEqual([3103, 3104])
  })
  it('扫不到块就抛，绝不静默复用别人在跑的服务', () => {
    expect(() => allocatePortBlock(4, () => true)).toThrow(/端口块不足/)
  })
})

describe('partitionFiles', () => {
  const d = { 'a.spec.ts': 100, 'b.spec.ts': 90, 'c.spec.ts': 10, 'd.spec.ts': 10 }
  it('LPT：重的文件不堆同一桶', () => {
    const buckets = partitionFiles(['a.spec.ts', 'b.spec.ts', 'c.spec.ts', 'd.spec.ts'], d, 2)
    expect(buckets.map((b) => b.length).sort()).toEqual([2, 2])
    expect(buckets.find((b) => b.includes('a.spec.ts'))).not.toContain('b.spec.ts')
  })
  it('缺时长按 0 算；桶多于文件时留空桶', () => {
    const buckets = partitionFiles(['a.spec.ts', 'z.spec.ts'], { 'a.spec.ts': 50 }, 4)
    expect(buckets.filter((b) => b.length === 0).length).toBe(2)
  })
  it('桶内按文件名升序 → 同分区表下组合可复现', () => {
    const [only] = partitionFiles(['b.spec.ts', 'a.spec.ts'], {}, 1)
    expect(only).toEqual(['a.spec.ts', 'b.spec.ts'])
  })
  it('n<1 直接抛', () => { expect(() => partitionFiles(['a'], {}, 0)).toThrow(/≥ 1/) })
})

describe('assertSafeRelPath', () => {
  it('放过正常相对路径', () => {
    expect(assertSafeRelPath('e2e/analysis/serial-overlap.spec.ts'))
      .toBe('e2e/analysis/serial-overlap.spec.ts')
  })
  it('拒绝 shell 元字符与空格（Windows 走 shell:true，必须自己把关）', () => {
    for (const bad of ['a b.ts', 'a&b.ts', 'a|b.ts', 'a"b.ts', "a'b.ts", 'a>b.ts', 'a<b.ts', 'a^b.ts', 'a;b.ts', 'a,b.ts']) {
      expect(() => assertSafeRelPath(bad)).toThrow(/不安全/)
    }
  })
})

describe('buildSlotManifest + slotEnv', () => {
  const m = buildSlotManifest({
    index: 2, ports: { backend: 8103, frontend: 3103 },
    slotRoot: 'C:\\t\\slot2', templateRoot: 'C:\\t\\template', redisDb: 12, secretKey: 'slot-2-secret',
  })
  it('slot 路径全部落在 slot 根下', () => {
    expect(m.dataDir).toBe('C:\\t\\slot2')
    expect(m.systemConfigFile).toContain('slot2')
    expect(m.dbPath).toContain('db.sqlite3')
    expect(m.authDir).toContain('.auth')
    expect(m.downloadsDir).toContain('.downloads')
    expect(m.slotFile).toContain('slot.json')
    expect(m.templateDbPath).toContain('template')
  })
  it('env 带齐承重变量：清单、config、迁移禁用、密钥、redis db、端口、token、CI', () => {
    const env = slotEnv(m, {})
    expect(env.LQDP_E2E_SLOT_FILE).toBe(m.slotFile)
    expect(env.LQDP_SYSTEM_CONFIG_FILE).toBe(m.systemConfigFile)
    expect(env.LQDP_SKIP_STORAGE_MIGRATION).toBe('1')
    expect(env.SECRET_KEY).toBe('slot-2-secret')
    expect(env.SFTP_SESSION_REDIS_URL).toBe('redis://localhost:6379/12')
    expect(env.E2E_PORT).toBe('8103')
    expect(env.E2E_FRONTEND_PORT).toBe('3103')
    expect(env.LQDP_ACCESS_TOKEN_MINUTES).toBe('720')
    expect(env.CI).toBe('1')
  })
})

describe('mergeRunStats', () => {
  it('墙钟取最长 slot（并发），效率=Σ通过时长/墙钟', () => {
    const merged = mergeRunStats([
      { specs: 100, passCount: 99, passMs: 300_000, wallMs: 320_000, stats: { expected: 99, unexpected: 1, flaky: 2, skipped: 0 } },
      { specs: 100, passCount: 100, passMs: 280_000, wallMs: 310_000, stats: { expected: 100, unexpected: 0, flaky: 1, skipped: 0 } },
    ])
    expect(merged.specs).toBe(200)
    expect(merged.wallMs).toBe(320_000)
    expect(merged.passMs).toBe(580_000)
    expect(merged.efficiency).toBeCloseTo(1.8125, 4)
    expect(merged.perSpecMs).toBeCloseTo(2914.57, 1)   // 580000 / (99+100)
    expect(merged.slots).toBe(2)
    expect(merged.stats).toEqual({ expected: 199, unexpected: 1, flaky: 3, skipped: 0 })
  })
  it('空输入不炸（全 slot 都 INFRA 时）', () => {
    expect(mergeRunStats([]).efficiency).toBe(0)
    expect(mergeRunStats([]).specs).toBe(0)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run test/unit/e2ePoolCore.spec.ts`
Expected: FAIL —— `Failed to load …/e2e/helpers/pool-core.mjs`（文件还不存在）

- [ ] **Step 3: 实现 pool-core**

```js
// frontend/e2e/helpers/pool-core.mjs
// slot 池的纯逻辑：无 fs、无子进程、无 Playwright —— 全部可在 vitest(node) 下断言。
// 消费方有两个：scripts/e2e_pool.mjs（编排）与 frontend/e2e/helpers/slot.ts（harness 读清单）。
import path from 'node:path'

export const SLOT_BACKEND_BASE = 8101
export const SLOT_FRONTEND_BASE = 3101
export const DEFAULT_SLOTS = 4
export const MAX_SLOTS = 6
export const SLOT_TARGET_MS = 240_000

export function autoSlots(totalMs, cap = DEFAULT_SLOTS) {
  return Math.max(1, Math.min(cap, Math.ceil((totalMs || 0) / SLOT_TARGET_MS)))
}

/** 连续 n 对端口；扫不到就抛（宁可拒绝启动，也不复用别人在跑的服务） */
export function allocatePortBlock(n, isTaken, baseBackend = SLOT_BACKEND_BASE, baseFrontend = SLOT_FRONTEND_BASE) {
  for (let shift = 0; shift < 40; shift++) {
    const startBackend = baseBackend + shift * n
    const startFrontend = baseFrontend + shift * n
    const block = Array.from({ length: n }, (_, i) => ({ backend: startBackend + i, frontend: startFrontend + i }))
    if (block.every((p) => !isTaken(p.backend) && !isTaken(p.frontend))) return block
  }
  throw new Error(`端口块不足：需要 ${n} 对连续端口（基址 ${baseBackend}/${baseFrontend}，已试 40 个块）`)
}

/** LPT：实测时长降序投进当前最轻的桶；同权重以文件名字序定，使跨运行组合尽量稳定 */
export function partitionFiles(files, durationsMs, n) {
  if (n < 1) throw new Error('slot 数 n 必须 ≥ 1')
  const buckets = Array.from({ length: n }, () => ({ ms: 0, files: [] }))
  const order = [...files].sort((a, b) => (durationsMs[b] ?? 0) - (durationsMs[a] ?? 0) || a.localeCompare(b))
  for (const file of order) {
    let lightest = buckets[0]
    for (const bucket of buckets) if (bucket.ms < lightest.ms) lightest = bucket
    lightest.files.push(file)
    lightest.ms += durationsMs[file] ?? 0
  }
  return buckets.map((b) => b.files.sort((a, c) => a.localeCompare(c)))
}

// Windows 下 spawn 走 shell:true，路径必须自己把关（这些串会直接进命令行）
const UNSAFE = /["'\s&|^<>()!*$[\];,{}\\]/
export function assertSafeRelPath(p) {
  if (UNSAFE.test(p)) throw new Error(`路径不安全（含 shell 元字符/空格）: ${p}`)
  return p
}

export function buildSlotManifest({ index, ports, slotRoot, templateRoot, redisDb, secretKey }) {
  return {
    index,
    backendPort: ports.backend,
    frontendPort: ports.frontend,
    dataDir: slotRoot,
    tempDir: path.join(slotRoot, 'temp'),
    dbPath: path.join(slotRoot, 'db.sqlite3'),
    mediaDir: path.join(slotRoot, 'media'),
    systemConfigFile: path.join(slotRoot, 'system-config.json'),
    slotFile: path.join(slotRoot, 'slot.json'),
    authDir: path.join(slotRoot, '.auth'),
    downloadsDir: path.join(slotRoot, '.downloads'),
    blobDir: path.join(slotRoot, 'blob'),
    jsonOut: path.join(slotRoot, 'results.json'),
    logFile: path.join(slotRoot, 'run.log'),
    templateDbPath: path.join(templateRoot, 'db.sqlite3'),
    templateMediaDir: path.join(templateRoot, 'media'),
    redisDb,
    secretKey,
  }
}

/** 每 slot 的进程环境。CI=1 → forbidOnly 生效、retries=2、reuseExistingServer 关闭 */
export function slotEnv(manifest, baseEnv = process.env) {
  return {
    ...baseEnv,
    LQDP_E2E_SLOT_FILE: manifest.slotFile,
    LQDP_SYSTEM_CONFIG_FILE: manifest.systemConfigFile,
    LQDP_SKIP_STORAGE_MIGRATION: '1',
    LQDP_ACCESS_TOKEN_MINUTES: '720',
    SECRET_KEY: manifest.secretKey,
    SFTP_SESSION_REDIS_URL: `redis://localhost:6379/${manifest.redisDb}`,
    E2E_PORT: String(manifest.backendPort),
    E2E_FRONTEND_PORT: String(manifest.frontendPort),
    CI: '1',
  }
}

/** N 份 per-slot JSON 的统计合并。墙钟是并发的 ⇒ 取最长 slot，而不是求和 */
export function mergeRunStats(reports) {
  let specs = 0, passCount = 0, passMs = 0, wallMs = 0
  const stats = { expected: 0, unexpected: 0, flaky: 0, skipped: 0 }
  for (const r of reports) {
    specs += r.specs ?? 0
    passCount += r.passCount ?? 0
    passMs += r.passMs ?? 0
    wallMs = Math.max(wallMs, r.wallMs ?? 0)
    for (const k of Object.keys(stats)) stats[k] += r.stats?.[k] ?? 0
  }
  return {
    specs, passCount, passMs, wallMs, stats,
    perSpecMs: passCount ? passMs / passCount : 0,
    efficiency: wallMs ? passMs / wallMs : 0,
    slots: reports.length,
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run test/unit/e2ePoolCore.spec.ts`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/e2e/helpers/pool-core.mjs frontend/test/unit/e2ePoolCore.spec.ts
git commit -m "test(e2e): slot 池纯逻辑落 T2 层 —— LPT 分区/端口块/slot 清单/并发统计合并"
```

### Task 3: Playwright 侧读 slot 契约（无 slot 时零行为变化）

**Files:**
- Create: `frontend/e2e/helpers/slot.ts`
- Modify: `frontend/e2e/fixtures/test-data.ts:10-31`
- Modify: `frontend/playwright.config.ts:10-22`、`76-128`、`130-170`
- Modify: `frontend/e2e/global-setup.ts:36-53`
- Test: `frontend/test/unit/slotPaths.spec.ts`

**Interfaces:**
- Consumes: Task 2 的 `SlotManifest` 字段名（逐字）
- Produces: `CURRENT_SLOT`、`SYSTEM_CONFIG_FILE`、`AUTH_DIR`、`DOWNLOAD_DIR`、`DATA_DIR`、`ADMIN_STATE`、`USER_STATE`、`LEGACY_SYSTEM_CONFIG_FILE`

- [ ] **Step 1: 写 `frontend/e2e/helpers/slot.ts`**

```ts
// 编排器与 harness 之间唯一的桥：读一份 slot.json，其余路径全部经这里。
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export interface SlotManifest {
  index: number; backendPort: number; frontendPort: number
  dataDir: string; tempDir: string; dbPath: string; mediaDir: string
  systemConfigFile: string; slotFile: string; authDir: string; downloadsDir: string
  blobDir: string; jsonOut: string; logFile: string
  templateDbPath: string; templateMediaDir: string
  redisDb: number; secretKey: string
}

function readSlot(): SlotManifest | null {
  const file = process.env.LQDP_E2E_SLOT_FILE
  if (!file) return null
  // 明确给了清单文件却读不到/缺字段 ⇒ 编排器与 harness 版本不匹配，必须硬失败而不是回落默认
  const raw = JSON.parse(fs.readFileSync(file, 'utf-8')) as SlotManifest
  for (const key of ['systemConfigFile', 'authDir', 'downloadsDir', 'dataDir'] as const) {
    if (!raw[key]) throw new Error(`slot.json 缺字段 ${key}: ${file}`)
  }
  return raw
}

export const CURRENT_SLOT = readSlot()

/** 无 slot 时的一切默认 = 今天的行为；本文件不得改变非 slot 路径 */
export const LEGACY_SYSTEM_CONFIG_FILE = path.join(os.tmpdir(), 'lqdp-e2e-system-config.json')
export const SYSTEM_CONFIG_FILE = CURRENT_SLOT?.systemConfigFile ?? LEGACY_SYSTEM_CONFIG_FILE
export const AUTH_DIR = CURRENT_SLOT?.authDir ?? path.join(__dirname, '..', '.auth')
export const DOWNLOAD_DIR = CURRENT_SLOT?.downloadsDir ?? path.join(__dirname, '..', '.downloads')
export const DATA_DIR = CURRENT_SLOT?.dataDir ?? path.resolve(__dirname, '..', '..', '..', '..')
export const ADMIN_STATE = path.join(AUTH_DIR, 'admin.json')
export const USER_STATE = path.join(AUTH_DIR, 'user.json')
```

`DATA_DIR` 的 legacy 值：`frontend/e2e/helpers/` 上溯 4 级 = 仓库根，与 `fixtures/test-data.ts:8` 的 `PROJECT_ROOT` 同值 —— Step 2 的单测钉住这条等价性。

- [ ] **Step 2: 写失败的路径单测**

```ts
// frontend/test/unit/slotPaths.spec.ts
import { describe, expect, it } from 'vitest'
import path from 'node:path'
import { DATA_DIR, LEGACY_SYSTEM_CONFIG_FILE, SYSTEM_CONFIG_FILE } from '../../e2e/helpers/slot'
import { E2E_SYSTEM_CONFIG_FILE, PROJECT_ROOT } from '../../e2e/fixtures/test-data'

describe('slot-aware 路径在无 slot 时等于历史默认', () => {
  it('DATA_DIR 回落仓库根（两处 media 硬编码用例靠它）', () => {
    expect(path.resolve(DATA_DIR)).toBe(path.resolve(PROJECT_ROOT))
  })
  it('config 文件路径两处一致，仍指 lqdp-e2e-system-config.json', () => {
    expect(SYSTEM_CONFIG_FILE).toBe(LEGACY_SYSTEM_CONFIG_FILE)
    expect(E2E_SYSTEM_CONFIG_FILE).toBe(LEGACY_SYSTEM_CONFIG_FILE)
  })
})
```

Run: `cd frontend && npx vitest run test/unit/slotPaths.spec.ts`
Expected: FAIL —— `test-data.ts` 还没有从 slot 转出（或 slot.ts 未被引用）

- [ ] **Step 3: test-data.ts 改转出（导出名不变）**

删掉 `E2E_SYSTEM_CONFIG_FILE`（17-20 行）、`AUTH_DIR`/`ADMIN_STATE`/`USER_STATE`（26-28）、`DOWNLOAD_DIR`（31）这几段本地 `path.join`，在原位置换成：

```ts
// 路径全部经 helpers/slot：有 slot 清单时用 slot 目录，否则与本文件历史上的写法逐字相同。
export {
  SYSTEM_CONFIG_FILE as E2E_SYSTEM_CONFIG_FILE,
  AUTH_DIR,
  DOWNLOAD_DIR,
  ADMIN_STATE,
  USER_STATE,
} from '../helpers/slot'
```

- [ ] **Step 4: playwright.config.ts 三处**

① 顶部（10-22 行那段无条件 `fs.writeFileSync`）换成按 slot 分支：

```ts
import { CURRENT_SLOT, SYSTEM_CONFIG_FILE as E2E_SYSTEM_CONFIG_FILE, ADMIN_STATE } from './e2e/helpers/slot'

if (CURRENT_SLOT) {
  // 编排器已写好 system-config.json（data_dir + temp_dir 指 slot）与 slot.json，这里只认不重写。
  process.env.LQDP_SYSTEM_CONFIG_FILE = CURRENT_SLOT.systemConfigFile
  process.env.LQDP_SKIP_STORAGE_MIGRATION = '1'
} else {
  fs.writeFileSync(E2E_SYSTEM_CONFIG_FILE, JSON.stringify({ data_dir: PROJECT_ROOT }), 'utf-8')
  process.env.LQDP_SYSTEM_CONFIG_FILE = E2E_SYSTEM_CONFIG_FILE
}
```

② 四个 project 的 `storageState: path.join(__dirname, 'e2e', '.auth', 'admin.json')` → `storageState: ADMIN_STATE`（`use.baseURL` 不动，它已读 `E2E_FRONTEND_PORT`）。

③ webServer：

```ts
reuseExistingServer: !process.env.CI && !CURRENT_SLOT,
timeout: USE_DEV_SERVER || process.env.E2E_SKIP_BUILD === '1' ? 120_000 : 300_000,
command: USE_DEV_SERVER
  ? 'npm run dev'
  : process.env.E2E_SKIP_BUILD === '1' ? 'npm run preview' : 'npm run build && npm run preview',
env: {
  ...process.env,
  LQDP_SYSTEM_CONFIG_FILE: E2E_SYSTEM_CONFIG_FILE,
  LQDP_ACCESS_TOKEN_MINUTES: '720',
  // slot 模式才注入这 3 条；非 slot 一律不加，保持今天的行为面
  ...(CURRENT_SLOT && {
    LQDP_SKIP_STORAGE_MIGRATION: '1',
    SECRET_KEY: CURRENT_SLOT.secretKey,
    SFTP_SESSION_REDIS_URL: `redis://localhost:6379/${CURRENT_SLOT.redisDb}`,
  }),
},
```

（后端那条 `webServer` 的 `reuseExistingServer`/`command` 不变，只有 env 与前端那条的 command 需要动。）

- [ ] **Step 5: global-setup.ts 加 slot 分支**

```ts
import { CURRENT_SLOT } from './helpers/slot'

async function globalSetup() {
  if (CURRENT_SLOT) {
    // 库与种子由 scripts/e2e_pool.mjs 预铸（模板 → 每 slot 一份拷贝 + 硬链镜像）。
    // 这里再 migrate/seed 等于把已就位的 slot 库重跑一遍播种，纯浪费且会双重写入。
    console.log(`[globalSetup] slot=${CURRENT_SLOT.index} 跳过 migrate/seed（模板库已就位）`)
  } else {
    runDjango('migrate --noinput')
    runDjango('seed_users')
    runDjango('seed_test_data --refresh')
  }
  try {
    fs.rmSync(DOWNLOAD_DIR, { recursive: true, force: true })
    fs.mkdirSync(DOWNLOAD_DIR, { recursive: true })
  } catch (e: any) {
    console.warn(`[globalSetup] 清理 .downloads 失败（忽略）: ${e.message}`)
  }
}
```

- [ ] **Step 6: 验证非 slot 路径零行为变化**

```bash
cd frontend && npm run lint:e2e && npx vitest run test/unit/slotPaths.spec.ts
npx playwright test --list --reporter=json 2>/dev/null | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const j=JSON.parse(s.slice(j0=>0));let n=0;const w=x=>{for(const y of x.suites||[])w(y);n+=(x.specs||[]).filter(t=>!(t.projectIds||[]).includes('setup')).length};for(const x of j.suites||[])w(x);console.log('specs:',n)})"
```
Expected: `lint:e2e` 0 error；两条单测 PASS；`specs: 386`（收集数不变 ⇒ 只动了路径没动判据）。

- [ ] **Step 7: 提交**

```bash
git add frontend/e2e/helpers/slot.ts frontend/e2e/fixtures/test-data.ts frontend/playwright.config.ts frontend/e2e/global-setup.ts frontend/test/unit/slotPaths.spec.ts
git commit -m "refactor(e2e): slot 清单成为路径单一来源 —— 无 slot 时逐字回落今天"
```

### Task 4: `scripts/e2e_pool.mjs` 编排器 + N=1 等价验收

**Files:**
- Create: `scripts/e2e_pool.mjs`
- Modify: `frontend/package.json`（scripts 加一行）

**Interfaces:**
- Consumes: Task 2 全部导出、Task 3 的 `slot.json` 契约与 `E2E_SKIP_BUILD`
- Produces: CLI `node scripts/e2e_pool.mjs [--slots=N|auto] [--only-slot=i] [--dry-run] [--keep-slots] [-- <file...>]`；
  产物 `merged.json` = `MergedStats` + `files: Record<裸路径, number /*通过毫秒*/>` + `partial?: boolean`

- [ ] **Step 1: 写编排器（完整文件，不留半成品）**

```js
#!/usr/bin/env node
/**
 * e2e_pool — 并行全量的唯一入口：预铸 TEMP 模板 → LPT 分区 → N 个「1 进程=1 worker=1 slot」
 * 的 Playwright 子进程 → 自算统计合并 + 官方 merge-reports 出 HTML。
 * 判据见 docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md
 */
import { execFileSync, execSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  MAX_SLOTS, allocatePortBlock, assertSafeRelPath, autoSlots, buildSlotManifest, mergeRunStats,
  partitionFiles, slotEnv,
} from '../frontend/e2e/helpers/pool-core.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = path.join(ROOT, 'frontend')
const PY = process.env.PYTHON_BIN || path.join(ROOT, '.venv', 'Scripts', 'python.exe')
const TEMPLATE = process.env.LQDP_E2E_TEMPLATE_DIR || path.join(os.tmpdir(), 'lqdp-e2e-template')
const SLOTS_ROOT = path.join(os.tmpdir(), 'lqdp-e2e-slots')
const PORT_SPAN = 60
const log = (...a) => console.log('[pool]', ...a)

const argv = process.argv.slice(2)
const flag = (name, dflt) => { const i = argv.indexOf(`--${name}`); return i < 0 || i + 1 >= argv.length ? dflt : argv[i + 1] }
const has = (name) => argv.includes(`--${name}`)
const dashDash = argv.indexOf('--')
/** 统一成相对 testDir 的裸路径；Playwright CLI 侧再加 e2e/ 前缀 */
const bare = (p) => p.replace(/^e2e[\\/]/, '')
const FILES = dashDash < 0 ? [] : argv.slice(dashDash + 1).map(bare)

const netBlock = {}
const taken = (port) => netBlock[port] === true

function dj(args, env) {
  return execFileSync(PY, ['manage.py', ...args], {
    cwd: ROOT, env: { ...env, PYTHONIOENCODING: 'utf-8' }, encoding: 'utf-8', timeout: 900_000, maxBuffer: 128e6,
  })
}

/** 模板：库 + 种子 media 全在 TEMP。带 SKIP_STORAGE_MIGRATION ⇒ 仓库根 db/media 一律不碰 */
function buildTemplate() {
  fs.mkdirSync(path.join(TEMPLATE, 'temp'), { recursive: true })
  const cfg = path.join(TEMPLATE, 'system-config.json')
  fs.writeFileSync(cfg, JSON.stringify({ data_dir: TEMPLATE, temp_dir: path.join(TEMPLATE, 'temp') }), 'utf-8')
  const env = { ...process.env, LQDP_SYSTEM_CONFIG_FILE: cfg, LQDP_SKIP_STORAGE_MIGRATION: '1', SECRET_KEY: 'e2e-template-not-used' }
  const t0 = Date.now()
  dj(['migrate', '--noinput'], env)
  dj(['seed_users'], env)
  dj(['seed_test_data', '--refresh'], env)
  // WAL：只拷主文件会丢 -wal 里的内容 ⇒ 先 TRUNCATE checkpoint 落盘，再清 sidecar
  dj(['shell', '-c', "from django.db import connection as c; c.connection.cursor().execute('PRAGMA wal_checkpoint(TRUNCATE)'); print('ok')"], env)
  for (const suffix of ['-wal', '-shm']) { const p = path.join(TEMPLATE, 'db.sqlite3' + suffix); if (fs.existsSync(p)) fs.rmSync(p) }
  log(`模板就绪 ${((Date.now() - t0) / 1000).toFixed(1)}s → ${TEMPLATE}`)
}

/** 每 slot：清空自建目录 → 拷库 → 硬链镜像 media → 写 config → 写 slot.json */
function prepareSlot(m) {
  fs.rmSync(m.dataDir, { recursive: true, force: true })   // 只删自己造的 slot 目录
  for (const dir of [m.tempDir, m.authDir, m.downloadsDir, m.blobDir]) fs.mkdirSync(dir, { recursive: true })
  fs.copyFileSync(m.templateDbPath, m.dbPath)
  const mirror = (src, rel = '') => {
    for (const e of fs.readdirSync(src, { withFileTypes: true })) {
      const from = path.join(src, e.name), to = path.join(m.mediaDir, rel, e.name)
      if (e.isDirectory()) { fs.mkdirSync(to, { recursive: true }); mirror(from, path.join(rel, e.name)) }
      else fs.linkSync(from, to)
    }
  }
  fs.mkdirSync(m.mediaDir, { recursive: true })
  if (fs.existsSync(m.templateMediaDir)) mirror(m.templateMediaDir)
  fs.writeFileSync(m.systemConfigFile, JSON.stringify({ data_dir: m.dataDir, temp_dir: m.tempDir }), 'utf-8')
  fs.writeFileSync(m.slotFile, JSON.stringify(m, null, 2), 'utf-8')
}

/** 最近一轮夜跑的 per-file 通过时长，给 LPT 定权；拿不到就退化为等文件数 */
function latestDurations() {
  const base = path.join(ROOT, 'tasks', 'e2e-nightly')
  if (!fs.existsSync(base)) return {}
  const dirs = fs.readdirSync(base).filter((d) => /^\d{4}-\d{2}-\d{2}/.test(d)).sort().reverse()
  for (const d of dirs) {
    for (const name of ['merged.json', 'results.json']) {
      const p = path.join(base, d, name)
      if (!fs.existsSync(p)) continue
      try {
        const j = JSON.parse(fs.readFileSync(p, 'utf-8'))
        if (name === 'merged.json' && j.files) return j.files
        if (name === 'results.json') {
          const out = {}
          const walk = (s) => {
            for (const x of s.suites ?? []) walk(x)
            for (const sp of s.specs ?? []) {
              if ((sp.projectIds ?? []).includes('setup')) continue
              let ms = 0
              for (const t of sp.tests ?? []) for (const r of t.results ?? []) if (r.status === 'passed') ms += r.duration
              out[sp.file] = (out[sp.file] ?? 0) + ms
            }
          }
          for (const s of j.suites ?? []) walk(s)
          if (Object.keys(out).length) return out
        }
      } catch { /* 坏 JSON 就往下找一轮 */ }
    }
  }
  return {}
}

function allFiles() {
  const out = execSync('npx playwright test --list --reporter=json', {
    cwd: FRONTEND, encoding: 'utf-8', maxBuffer: 128e6, shell: true,
  })
  const j = JSON.parse(out.slice(out.indexOf('{')))
  const files = new Set()
  const walk = (s) => {
    for (const x of s.suites ?? []) walk(x)
    for (const sp of s.specs ?? []) if (sp.file) files.add(sp.file)
  }
  for (const s of j.suites ?? []) walk(s)
  return [...files]
}

/** slot 数：auto 按 LPT 总量反推；显式数字夹到 [1, MAX_SLOTS] */
function parseSlots(raw, totalMs) {
  if (raw === undefined || raw === 'auto') return autoSlots(totalMs)
  const n = Number(raw)
  if (!Number.isInteger(n) || n < 1) throw new Error(`--slots 需为 ≥1 整数或 auto，收到 ${raw}`)
  return Math.min(n, MAX_SLOTS)
}

async function prefetchPorts() {
  const ports = []
  for (let i = 0; i < PORT_SPAN; i++) ports.push(8101 + i, 3101 + i)
  await Promise.all([...new Set(ports)].map(async (p) => {
    netBlock[p] = await new Promise((res) => {
      const s = net.connect(p, '127.0.0.1')
      s.setTimeout(150)
      s.on('connect', () => { s.destroy(); res(true) })
      s.on('error', () => res(false))
      s.on('timeout', () => { s.destroy(); res(false) })
    })
  }))
}

function runSlot(m, files, timeoutMs) {
  const out = fs.openSync(m.logFile, 'w')
  const argList = files.map((f) => assertSafeRelPath(`e2e/${f}`)).join(' ')
  const cmd = `npx playwright test ${argList} --workers=1 --reporter=blob,json --blob-report="${m.blobDir}"`
  fs.writeSync(out, `$ ${cmd}\n(cwd=${FRONTEND}) (port ${m.backendPort}/${m.frontendPort})\n\n`)
  return new Promise((resolve) => {
    const child = spawn(cmd, {
      cwd: FRONTEND, shell: true, stdio: ['ignore', out, out],
      env: { ...slotEnv(m, process.env), E2E_SKIP_BUILD: '1', PLAYWRIGHT_JSON_OUTPUT_NAME: m.jsonOut },
    })
    const killer = setTimeout(() => { try { child.kill('SIGKILL') } catch {} }, timeoutMs)
    child.on('close', (code) => { clearTimeout(killer); fs.closeSync(out); resolve(code ?? 1) })
  })
}

function statsOf(jsonPath) {
  if (!fs.existsSync(jsonPath)) return null
  let j
  try { j = JSON.parse(fs.readFileSync(jsonPath, 'utf-8')) } catch { return null }
  let specs = 0, passCount = 0, passMs = 0
  const files = {}
  const walk = (s) => {
    for (const x of s.suites ?? []) walk(x)
    for (const sp of s.specs ?? []) {
      if ((sp.projectIds ?? []).includes('setup')) continue
      specs++
      for (const t of sp.tests ?? []) for (const r of t.results ?? []) if (r.status === 'passed') {
        passCount++; passMs += r.duration
        files[sp.file] = (files[sp.file] ?? 0) + r.duration
      }
    }
  }
  for (const s of j.suites ?? []) walk(s)
  return { specs, passCount, passMs, wallMs: j.stats?.duration ?? 0, stats: j.stats ?? {}, files }
}

async function main() {
  await prefetchPorts()
  const durations = latestDurations()
  const files = FILES.length ? FILES : allFiles()
  const totalMs = files.reduce((a, f) => a + (durations[f] ?? 0), 0)
  const buckets = partitionFiles(files, durations, parseSlots(flag('slots', 'auto'), totalMs)).filter((b) => b.length)
  log(`文件 ${files.length} · 加权总量 ${(totalMs / 1000).toFixed(0)}s · 计划 slot ${buckets.length}`)
  if (has('dry-run')) {
    buckets.forEach((b, i) => log(`slot${i}: ${b.length} 文件 · ${(b.reduce((a, f) => a + (durations[f] ?? 0), 0) / 1000).toFixed(0)}s`))
    return 0
  }

  buildTemplate()
  execSync('npm run build', { cwd: FRONTEND, stdio: 'ignore', shell: true })

  const ports = allocatePortBlock(buckets.length, taken)
  const manifests = ports.map((p, i) => buildSlotManifest({
    index: i, ports: p, slotRoot: path.join(SLOTS_ROOT, `slot${i}`), templateRoot: TEMPLATE,
    redisDb: 12 + i, secretKey: `e2e-slot-${i}-${process.pid}`,
  }))
  manifests.forEach(prepareSlot)

  const only = flag('only-slot', null)
  const timeoutMs = Number(flag('timeout-min', '25')) * 60_000
  const started = Date.now()
  const codes = await Promise.all(manifests.map((m, i) =>
    (only !== null && Number(only) !== i) ? Promise.resolve(0) : runSlot(m, buckets[i], timeoutMs)))
  const spanMs = Date.now() - started

  const reports = manifests.map((m) => statsOf(m.jsonOut)).filter(Boolean)
  const merged = mergeRunStats(reports)
  merged.files = reports.reduce((acc, r) => {
    for (const [f, ms] of Object.entries(r.files)) acc[f] = (acc[f] ?? 0) + ms
    return acc
  }, {})
  merged.wallMs = spanMs
  merged.slotsPlanned = buckets.length
  if (only !== null) merged.partial = true

  const outDir = process.env.LQDP_E2E_OUTDIR || path.join(ROOT, 'tasks', 'e2e-pool', 'latest')
  fs.mkdirSync(outDir, { recursive: true })
  fs.writeFileSync(path.join(outDir, 'merged.json'), JSON.stringify(merged, null, 2), 'utf-8')

  try {
    execSync(`npx playwright merge-reports ${manifests.map((m) => `"${m.blobDir}"`).join(' ')} --reporter=html`,
      { cwd: FRONTEND, stdio: 'inherit', shell: true })
  } catch (e) { log('HTML 合并失败（统计不受影响）:', e.message) }

  codes.forEach((c, i) => { if (c !== 0) log(`slot${i} EXIT=${c} → ${manifests[i].logFile}`) })
  log(`用例 ${merged.specs} · 墙钟 ${(spanMs / 60000).toFixed(1)}min · 单价 ${(merged.perSpecMs / 1000).toFixed(2)}s/例`
    + ` · 效率 ${merged.efficiency.toFixed(2)}（目标 ≥${(0.7 * buckets.length).toFixed(1)}）`
    + ` · unexpected ${merged.stats.unexpected} · flaky ${merged.stats.flaky}`)
  if (!has('keep-slots')) manifests.forEach((m) => fs.rmSync(m.dataDir, { recursive: true, force: true }))
  return codes.some((c) => c !== 0) ? 1 : merged.stats.unexpected > 0 ? 1 : 0
}

main().then((code) => process.exit(code)).catch((e) => { console.error('[pool] 失败:', e.message); process.exit(1) })
```

`frontend/package.json` 的 scripts 里加一行（放在 `test:e2e:affected` 之后）：

```json
    "test:e2e:pool": "node ../scripts/e2e_pool.mjs",
```

- [ ] **Step 2: dry-run 只看分区**

Run: `cd frontend && npm run test:e2e:pool -- --slots=auto --dry-run`
Expected: `文件 74 · 加权总量 ≈1000s · 计划 slot 4`，并列出每桶文件数与桶权重秒数。此路径不建模板、不 spawn。

- [ ] **Step 3: N=1 全量等价（本任务的验收线）**

Run: `node scripts/e2e_pool.mjs --slots=1 --keep-slots`
Expected: `用例 386`；`unexpected ≤1`（今天那条产品侧硬红 `smoke/pages`「数据分析 正常加载」，spec §7）；`flaky ≤5`；
`tasks/e2e-pool/latest/merged.json` 生成。

- [ ] **Step 4: 与今天的串行对照 per-file 用例数与红集合**

```bash
node -e "
const a=require('./tasks/e2e-pool/latest/merged.json');
const b=require('./tasks/e2e-nightly/2026-10-14-1108/results.json');
const base={};const red=new Set();
const w=(s)=>{for(const x of s.suites||[])w(x);for(const sp of s.specs||[]){if((sp.projectIds||[]).includes('setup'))continue;
  base[sp.file]=(base[sp.file]||0)+sp.tests.length
  for(const t of sp.tests||[])if((t.results||[]).some(r=>r.status==='failed'))red.add(sp.file)}}
for(const s of b.suites||[])w(s)
const poolFiles=Object.keys(a.files)
console.log('baseline specs:',Object.values(base).reduce((x,y)=>x+y,0),'| pool specs:',a.specs)
console.log('pool 覆盖但 baseline 没有:',poolFiles.filter(f=>!base[f]))
console.log('baseline 有但 pool 没跑到:',Object.keys(base).filter(f=>!a.files[f]))
"
```
Expected: `pool specs: 386` 且两个差集都为空（若非空，必须点名解释是哪次提交带来的文件增减，否则不许继续）。
红集合差异记到 `docs/reference/e2e-tier-triage.md`（N=1 应只带那条已知产品侧硬红）。

- [ ] **Step 5: 提交**

```bash
git add scripts/e2e_pool.mjs frontend/package.json docs/reference/e2e-tier-triage.md
git commit -m "feat(e2e): slot 池编排器 —— TEMP 预铸模板 + 硬链镜像 + LPT 分区 + N 进程合并统计"
```

---

## P2 — 并行与隔离性正证

### Task 5: 两处硬编码 media 路径改 slot-aware

**Files:**
- Modify: `frontend/e2e/batch/batch-phase.spec.ts:27`
- Modify: `frontend/e2e/data/repair-center.spec.ts:17`

**Interfaces:**
- Consumes: Task 3 的 `DATA_DIR`（经 `fixtures/test-data` 转出）

- [ ] **Step 1: 改两处常量，并把 `DATA_DIR` 加进入口 import**

```ts
// batch-phase.spec.ts:27
const BATCH_BASE_DIR = path.join(DATA_DIR, 'media', 'data', 'admin', 'batch')
// repair-center.spec.ts:17
const ADMIN_BATCH_DIR = path.join(DATA_DIR, 'media', 'data', ACCOUNTS.admin.username, 'batch')
```

- [ ] **Step 2: 单 slot 跑这两个文件，并与今天对照**

Run: `node scripts/e2e_pool.mjs --slots=1 --keep-slots -- e2e/batch/batch-phase.spec.ts e2e/data/repair-center.spec.ts`
Expected: 两文件全绿，且与 `cd frontend && npx playwright test e2e/batch/batch-phase.spec.ts e2e/data/repair-center.spec.ts --workers=1` 结果一致。
若池只跑了其中一个文件 ⇒ FILES 透传有 bug，先修再继续。

- [ ] **Step 3: 提交**

```bash
git add frontend/e2e/batch/batch-phase.spec.ts frontend/e2e/data/repair-center.spec.ts
git commit -m "fix(e2e): 批次目录改从 DATA_DIR 推导 —— 为 slot 独立 data_dir 让路"
```

### Task 6: 隔离性正证 + N=2 → N=4

**Files:**
- Modify: `docs/reference/e2e-tier-triage.md`（并行实测与归因账目）

**Interfaces:**
- Consumes: `merged.json`（Task 4 形状）、`--only-slot`（单 slot 原地复跑）

- [ ] **Step 1: 正证——同一对历史互踩文件，分不同 slot 与同 slot 各跑一次**

`settings/settings.spec.ts` 的「恢复默认」会洗全部 `UserSetting`，历史上把 `fonts.spec` 从 0 红打到 5 红：

```bash
node scripts/e2e_pool.mjs --slots=2 --keep-slots -- e2e/settings/settings.spec.ts e2e/settings/fonts.spec.ts
node scripts/e2e_pool.mjs --slots=1 --keep-slots -- e2e/settings/settings.spec.ts e2e/settings/fonts.spec.ts
```
Expected：前者两个 slot 各持一份库副本 ⇒ 两文件都绿 = **slot 隔离成立**。
后者同 slot：绿 = 现有快照-还原本身够；红 = **同 slot 内跨文件污染**，必须逐条归因（不许靠拆到不同 slot 蒙过去，真实分区里组合会变）。
两条结论原文写进 `docs/reference/e2e-tier-triage.md`，并注明「正证不依赖改坏源码」。

- [ ] **Step 2: N=2 全量**

Run: `LQDP_E2E_OUTDIR=tasks/e2e-nightly/<date>-pool2 node scripts/e2e_pool.mjs --slots=2`
记录：墙钟、单价、效率、unexpected、flaky。

- [ ] **Step 3: N=4 全量**

Run: `LQDP_E2E_OUTDIR=tasks/e2e-nightly/<date>-pool4 node scripts/e2e_pool.mjs --slots=4`
**判据**：`效率 ≥ 2.8`（=0.7×4）且墙钟 ≤10min。不达标就分两条查：桶拖尾（看 `merged.json` 的 `files` 分布）
vs 资源争用（看各 `slot<i>/run.log` 有无超时/OOM/`ERR_CONNECTION_REFUSED`）。

- [ ] **Step 4: 逐条归因并行后新增的红**

每个新 unexpected 先做隔离复跑区分顺序污染与真红：`node scripts/e2e_pool.mjs --slots=1 --keep-slots -- e2e/<该文件>`；
再按 spec §3 的三类形状定性质。**不改产品代码，除非红与产品行为矛盾**（那种情况写进待用户拍板清单）。

- [ ] **Step 5: 提交**

```bash
git add docs/reference/e2e-tier-triage.md
git commit -m "docs(e2e): slot 池 N=2/N=4 实测与隔离性正证 —— 效率、单价、残余红归因"
```

---

## P3 — 门禁收口

### Task 7: 夜间轮接池 + 阈值按并行重标定

**Files:**
- Create: `frontend/e2e/helpers/nightly-gates.mjs`
- Test: `frontend/test/unit/e2eNightlyGates.spec.ts`
- Modify: `scripts/e2e_nightly.mjs`（阈值段 28-37、起跑段 ~220、统计读取改 `merged.json`）

**Interfaces:**
- Consumes: `merged.json`
- Produces: `THRESHOLDS`、`evaluateGates(rep, slots): string[]`（返回阻塞原因，空数组=放行）

- [ ] **Step 1: 写失败测试**

```ts
// frontend/test/unit/e2eNightlyGates.spec.ts
import { describe, expect, it } from 'vitest'
import { THRESHOLDS, evaluateGates } from '../../e2e/helpers/nightly-gates.mjs'

describe('并行夜跑闸口', () => {
  const healthy = { specs: 386, wallMs: 8 * 60_000, perSpecMs: 3000, efficiency: 3.0, stats: { unexpected: 0, flaky: 1 } }
  it('健康轮不阻塞', () => { expect(evaluateGates(healthy, 4)).toEqual([]) })
  it('墙钟 > 12min 阻塞（目标闸门与挂死探测同一条）', () => {
    expect(evaluateGates({ ...healthy, wallMs: 13 * 60_000 }, 4).join()).toMatch(/墙钟/)
  })
  it('效率 < 0.7×N 判「并行在空转」', () => {
    expect(evaluateGates({ ...healthy, efficiency: 2.0 }, 4).join()).toMatch(/效率/)
    expect(evaluateGates({ ...healthy, efficiency: 2.9 }, 4)).toEqual([])
  })
  it('单价阈值随 slot 数放宽，不会把并发争用误报成退化', () => {
    expect(THRESHOLDS.perSpecMs).toBe(6000)
    expect(evaluateGates({ ...healthy, perSpecMs: 5200 }, 4)).toEqual([])
    expect(evaluateGates({ ...healthy, perSpecMs: 6100 }, 4).join()).toMatch(/单价/)
  })
  it('用例数与 flaky 阈值不变', () => {
    expect(evaluateGates({ ...healthy, specs: 451 }, 4).join()).toMatch(/用例数/)
    expect(evaluateGates({ ...healthy, stats: { unexpected: 0, flaky: 6 } }, 4).join()).toMatch(/flake/)
  })
})
```

Run: `cd frontend && npx vitest run test/unit/e2eNightlyGates.spec.ts`
Expected: FAIL —— `nightly-gates.mjs` 不存在

- [ ] **Step 2: 实现阈值模块**

```js
// frontend/e2e/helpers/nightly-gates.mjs
// 并行后「单价」会因争用上升而墙钟下降，所以退化主信号改成墙钟 + 效率；单价阈值按 N 放宽。
export const THRESHOLDS = {
  wallMs: 12 * 60_000,
  perSpecMs: 6_000,          // 串行实测 2.89s；并发下先放 6s，Task 6 实测后收紧
  specs: 450,
  flakes: 5,
  efficiencyFloorFactor: 0.7,
}

export function evaluateGates(rep, slots) {
  const b = []
  if (rep.wallMs > THRESHOLDS.wallMs) b.push(`墙钟 ${(rep.wallMs / 60000).toFixed(1)}min > ${THRESHOLDS.wallMs / 60000}min`)
  if (rep.perSpecMs > THRESHOLDS.perSpecMs) b.push(`单价 ${(rep.perSpecMs / 1000).toFixed(2)}s/例 > ${THRESHOLDS.perSpecMs / 1000}s/例`)
  if (rep.specs > THRESHOLDS.specs) b.push(`用例数 ${rep.specs} > ${THRESHOLDS.specs}`)
  if ((rep.stats?.flaky ?? 0) > THRESHOLDS.flakes) b.push(`flake ${rep.stats.flaky} > ${THRESHOLDS.flakes}`)
  const floor = THRESHOLDS.efficiencyFloorFactor * slots
  if ((rep.efficiency ?? 0) < floor) b.push(`效率 ${(rep.efficiency ?? 0).toFixed(2)} < ${floor.toFixed(1)}（0.7×${slots} slot）—— 并行在空转，查拖尾或争用`)
  return b
}
```

- [ ] **Step 3: 改 `e2e_nightly.mjs`**

- 阈值常量删掉，改 `import { THRESHOLDS, evaluateGates } from '../frontend/e2e/helpers/nightly-gates.mjs'`
- 起跑：`spawnSync('node scripts/e2e_pool.mjs --slots=' + (process.env.E2E_SLOTS ?? 'auto'), { cwd: ROOT, stdio:'inherit', shell:true })`，
  并用 `LQDP_E2E_OUTDIR` 指到本轮目录；原来 `CI:'1'` 的单进程 spawn 分支删掉（池内部注入 CI）。
- 统计读取：从 `merged.json` 取 `specs/wallMs/perSpecMs/efficiency/stats`；`LATEST.md` 表头加两列 `slot` 与 `效率`。
- `partial === true`（`--only-slot`）时只记不判。
- **INFRA 轮判 VOID**：起跑前用 `npx playwright test --list --reporter=json` 现取预期用例数，
  若 `merged.specs < 预期` 或有 slot `EXIT≠0` 且其 `results.json` 缺失 ⇒ 本轮记 `VOID (infra)`、
  不进时间序列，并列出这些 slot 的 `run.log` 路径（沿用 `LATEST.md` 里 2026-10-14 那行的处理方式：指标不可信就不许当结论）。

- [ ] **Step 4: 用既有 JSON 验算，不重跑全量**

Run: `node scripts/e2e_nightly.mjs --report-only tasks/e2e-pool/latest/merged.json`
Expected: 打印 5 项判定结果（沿用脚本原有 `--report-only` 通路）。若 Task 6 实测单价远低于 6s，就在这里收紧常量并重跑本验算。

- [ ] **Step 5: 提交**

```bash
git add frontend/e2e/helpers/nightly-gates.mjs frontend/test/unit/e2eNightlyGates.spec.ts scripts/e2e_nightly.mjs
git commit -m "feat(e2e): 夜间轮接 slot 池 —— 阈值按并行重标定（墙钟12min/效率0.7N/单价6s）"
```

### Task 8: 快门禁走同一个池

**Files:**
- Modify: `scripts/e2e_affected.mjs:238-299`

**Interfaces:**
- Consumes: `node scripts/e2e_pool.mjs --slots=auto -- <files…>`

- [ ] **Step 1: 替换执行通路，保留选例与兜底逻辑**

```js
/** 统一走池：文件少时 autoSlots 自然退回 1（≈今天，无额外启动开销） */
function runPool(filesArg = '', passthrough = '') {
  const cmd = `"${process.execPath}" scripts/e2e_pool.mjs --slots=auto${passthrough ? ' ' + passthrough : ''}${filesArg ? ' -- ' + filesArg : ''}`
  log(cmd)
  return spawnSync(cmd, { cwd: ROOT, stdio: 'inherit', shell: true }).status ?? 1
}
```

把 245 / 296 / 298 / 299 行的四处 `run('npx playwright test …')` 换成 `runPool(paths, TAIL)` 形式（`--project=P0` 这类透传参数放 `passthrough`）。
**不动**：`NO AFFECTED TESTS` 输出、`MAX_MODULES_BEFORE_FULL` 升级全量、`GLOBAL` 兜底、后端 pytest 前置检查（285 行那段）。

- [ ] **Step 2: 验快门禁不退化**

Run: `cd frontend && npm run lint:e2e && npm run test:e2e:affected`
Expected: 打印实际走池的秒数且 <5min；无受影响用例时仍打印 `NO AFFECTED TESTS`。
若模板构建把预算吃掉（>5min）⇒ 加 `--reuse-template`：模板存在且新于 `apps/` 与 `Data/SampleData` 时跳过 `buildTemplate()`，并在 Step 3 补一条对应单测。

- [ ] **Step 3: 提交**

```bash
git add scripts/e2e_affected.mjs
git commit -m "feat(e2e): 快门禁复用 slot 池 —— autoSlots 小集合自然退回单进程"
```

### Task 9: 文档、rules 与 lessons 收口

**Files:**
- Modify: `docs/tasks/todo.md`、`docs/tasks/lessons.md`、`.claude/CLAUDE.md:70`（后者 gitignore，只对本机生效）

- [ ] **Step 1: lessons 追加两条（现象→根因→规则，压到最短）**

① `LQDP_SKIP_STORAGE_MIGRATION` 与 `_migrate` 的「搬走并删源」：把 `data_dir` 指向别处又想要只读副本时，
不带这个开关会删掉仓库根 `db.sqlite3` 与 `media/`；判据 `apps/common/system_config.py:385-391`。
② 并行化的隔离边界要枚举到「缓存键里的 user_id」：每份库副本 admin 的 PK 都是 1，Redis 一旦起来
`sftp:conn:<user_id>` 就 4 slot 串号（`apps/sftp/cache.py:43,116`）；降级 LocMem 时不暴露，所以必须在设计期查。

- [ ] **Step 2: 更新门禁口径**

`.claude/CLAUDE.md` 的「门禁节奏」那行改成实测数字（墙钟 ≤12min 判定、单价阈值 6s@≤4 slot、效率 ≥0.7N、
`E2E_SLOTS`/`--slots` 是唯一并行度旋钮），并记 N=1/2/4 的实测值。
**不要**把规则正文复制进 `AGENTS.md`（会造成双份漂移，那正是 AGENTS.md 开头明令避免的）。

- [ ] **Step 3: 提交**

```bash
git add docs/tasks/todo.md docs/tasks/lessons.md
git commit -m "docs(tasks): slot 池并行化账目 —— 实测数字、两条可复用教训、门禁阈值"
```

### Task 10: 终验收

- [ ] **Step 1: 连续两轮 N=4**

Run: `node scripts/e2e_pool.mjs --slots=4`（连续两次）
Expected: 两次都 `用例 386`、`墙钟 ≤10min`、`效率 ≥2.8`、`unexpected ≤1`、`flaky ≤5`，
且两轮 `merged.json` 的红集合**完全一致**（有出入就不算收口，回到 Task 6 Step 4 归因）。

- [ ] **Step 2: 端口与进程清场**

```bash
netstat -ano | grep -E ':(81[0-9][0-9]|31[0-9][0-9])' | grep LISTENING
```
Expected: 无输出。有输出说明 slot 的 webServer 没收回 —— 先查 PID 与属主再决定，**绝不停别的会话的进程**。

- [ ] **Step 3: 结果回填 spec 与 memory**

spec 追加「## 12. 实测结果」：N=1/2/4 的墙钟·单价·效率·与串行的红集合差异。
数字与 §2 推演不符就如实写并回改 §7 阈值，不做乐观解释。同时更新项目 memory 的
`project-e2e-tier-gates`（并行模型、阈值新值、效率信号）与 `project-e2e-run-reliability`（slot 跑法与端口块）。

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
 * 拆出前该文件实测 551/600 行、逼近闸口（`scripts/line-limit.mjs:18`；设计稿引的 591 是
 * Task 2 之前的 E1 快照，本句按拆出前实测订正），而 §5.4 续删、UX-1 锁定态、
 * FIX-1 的「刷新不吞勾选」对照用例都还要往这一族加判据 —— 先拆再加，别为凑行数砍判据。
 * 设计稿：`docs/superpowers/specs/2026-11-15-batch4a-e2e-split-and-username-guard-design.md` §2。
 */

// 后端落盘位置跟着进程走：非 slot = `<仓库根>/test/e2e-data`，slot = 该 slot 自己的 data_dir。
// 这一行与 repair-center.spec.ts 里的那条逐字相同，刻意**不抽**：它只是对既有 fixture 常量的
// 一次拼装，不是行为复制（同仓那条「三条相似行好过过早抽象」）。
const ADMIN_BATCH_DIR = path.join(DATA_DIR, 'media', 'data', ACCOUNTS.admin.username, 'batch')

const ts = Date.now()

const DUP_PREFIX = `DUP-E2E-${ts}`
const DUP_CONTENT = [
  '[CTA8280F]',
  'TestFileName,BPD60320.pts',
  '[Data]',
  'col1,col2',
  'mm,mm',
  '0,0',
  '1,1',
  '1,1',
  '1,1',
].join('\n')

/** 某个 tag 的两只批次目录固定路径。清理端按它确定性兜底 —— 不依赖播种是否走完。 */
function dupDirs(tag: string): [string, string] {
  return [
    path.join(ADMIN_BATCH_DIR, `${DUP_PREFIX}-${tag}-A`),
    path.join(ADMIN_BATCH_DIR, `${DUP_PREFIX}-${tag}-B`),
  ]
}

/**
 * 同名同大小的两份文件 = 一个重复组两只成员。分装两个批次目录，因为终态判据
 * 要按 `batch_name` 认「留下的是哪一份」—— 同一目录会同名覆盖成一只物理文件。
 * 先导入 A 再导入 B ⇒ A 的 id 最小、created_at 最早 ⇒ 默认与「最早导入」都落在 -A，
 * 「最新导入」落在 -B。
 * ⚠ 必须**在 try 内**调用：中途抛（mkdir/写盘/import 任一步）时已落盘的目录与已注册的行
 * 由调用方 finally 里的 `cleanupDup(name, ...dupDirs(tag))` 兜底。返工轮发现 4①：
 * 旧写法把播种放在 try 外，一抛就绕过了全部清理，脏数据级联进下一条的 N=3/「1 个」。
 */
async function seedDuplicatePair(page: Page, dupName: string, tag: string) {
  const [dirA, dirB] = dupDirs(tag)
  for (const dir of [dirA, dirB]) {
    fs.mkdirSync(dir, { recursive: true })
    fs.writeFileSync(path.join(dir, dupName), DUP_CONTENT)
  }
  for (const name of [`${DUP_PREFIX}-${tag}-A`, `${DUP_PREFIX}-${tag}-B`]) {
    const imp = await apiPost(page, '/batch-dirs/import/', { dir_name: name })
    expect(imp.status).toBe(201)
  }
  return { dirA, dirB, batchA: `${DUP_PREFIX}-${tag}-A`, batchB: `${DUP_PREFIX}-${tag}-B` }
}

/**
 * 终态串：`数量|批次名`。合成一条而不是两条断言 —— 「只剩 1 条」与「剩下的是 -B」
 * 分开写时，第一条会先红并把第二条吃掉（vitest/Playwright 都是首条失败即抛），
 * 而那正是本条要修的缺陷的形状：旧用例只断「剩 1 条」，选的是哪条没人钉。
 */
async function dupEndState(page: Page, dupName: string): Promise<string> {
  const { body } = await apiGet(page, '/files/?page_size=9999')
  const list: any[] = Array.isArray(body) ? body : (body.results ?? [])
  const rows = list.filter((f: any) => f.filename === dupName)
  return `${rows.length}|${rows[0]?.batch_name ?? '—'}`
}

/**
 * 终态批次名清单（排序后比对）：`names` 里每个文件各剩一条时，留下的必须正好是指定的那几份。
 * 按 `batch_name` 认、不按 id 认、不按行序认 —— 后两者都把「后端 order_by('id')」那条契约
 * 又依赖了一遍，而那是 T1 的判据，界面判据不该跟着它一起塌。
 */
async function dupRemainingBatches(page: Page, names: string[]): Promise<string[]> {
  const { body } = await apiGet(page, '/files/?page_size=9999')
  const list: any[] = Array.isArray(body) ? body : (body.results ?? [])
  return list
    .filter((f: any) => names.includes(f.filename))
    .map((f: any) => f.batch_name)
    .sort()
}

/**
 * 清理：**先删 DB 行，再删盘目录**（返工轮发现 4② —— 旧顺序先 rmSync 再把 SQLite
 * 失败空 catch 吞掉，一旦删除失败就留下「有记录无文件」的孤立行，而第 4 条用例恰好
 * 断言该卡片 hidden —— 清理器自己造出了它要拦的缺陷形状）。
 * 现在删除失败不静默：console.error 进运行日志，残留行由第 4 条当场拦红。
 * dupName 要插进 shellDjango 的 SQL 串：本仓取值是固定前缀 + Date.now()，
 * 但按教训「拼 SQL 要有闸」先拦引号/反斜杠。
 */
async function cleanupDup(dupName: string, ...dirs: string[]) {
  if (/['\\]/.test(dupName)) {
    throw new Error(`dupName 含引号/反斜杠，拒绝拼入 shellDjango：${dupName}`)
  }
  try {
    shellDjango(`DataFile.objects.filter(owner__username='admin', filename='${dupName}').delete()`)
  } catch (err) {
    console.error(`[cleanupDup] ${dupName} 的 DB 行删除失败（可能留下孤立记录，第 4 条会拦）：${err}`)
  }
  for (const dir of dirs) fs.rmSync(dir, { recursive: true, force: true })
}

test.describe.serial('重复项选保留', { tag: ['@p2', '@data'] }, () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page, '/data')
  })

  /**
   * 重复项选保留（批3a · 第 3 项 + 终审 F2）五条用例。
   *
   * 分工：`utils/dupKeep.ts` 的派生文案与裁决在 T2（16 例）、`keep_ids` 上行 /
   * `remaining_groups` 下行的接线在 `dupKeepWiring.spec.ts`（9 例，源码派生守卫）。
   * **这五条只钉界面这一层**： radio 真渲染得出、`data-keep` 真跟着选择翻、
   * 点下去之后**磁盘上少的是哪一只**。前两层全绿都不证明这三件事。
   *
   * 判据异源：终态一律按 `batch_name` 认（`dupEndState` / `dupRemainingBatches`），
   * 不引 `utils/dupKeep.ts` 的任何函数 —— 复用同一个实现只会证明那段代码等于自己。
   * 磁盘侧 `fs.existsSync` 把「用户看不见的那一半」也钉上：DB 行删了但物理文件还在，
   * 是这类「不可撤销删除」最贵的失效形状，而它不在任何响应里。
   * （口径收窄，返工轮发现 7：此前 **0 处**的只限 `existsSync` 形态的磁盘判据 ——
   * 磁盘**内容**判据早有，如 `e2e/exports/html-report.spec.ts:33-36` 读回导出 HTML、
   * `e2e/sftp/search.spec.ts:363-365` 读回 CSV 查 BOM；其余 `existsSync` 只当 skip
   * 守卫用，如 `e2e/data/combine.spec.ts:60`。）
   *
   * 隐含前提（返工轮发现 8，此前未写明）：本 slot 的种子数据贡献 **0 个重复组**。
   * `toContainText('2 个')` 与按钮上的 `按选择删除 1 个` 都以它为前提 ——
   * 种子一旦哪天自带重复，这两句的数字就开始漂（且 serial 下一条跟着漂）。
   *
   * ⚠ **这一族的默认档是真后端 + 真磁盘**：`page.route().fulfill()` 会整个替换响应，后端语义
   * 的变异在浏览器层根本红不了（批2 F3 的教训）。唯一例外是下面 `[B3A-F2NOTE]` —— 它只钉
   * 「截断提示这句话有没有被渲染进卡片」这一件**纯前端**事实，一句后端归因都不给。
   * 变异反证（每轮换完手工写回原字节、
   * `git diff` 核对归零；M19-M21 首测 2026-11-15，M25/M23/M24 与用例 3 单跑为返工轮实测。
   * ⚠ 编号订正：返工轮原把下面那颗「applyStrategy 硬编码 earliest」记成 **M22**，与
   * `utils/dupKeep.spec.ts` 那边已用过的 M22（`resolveKeepIds` 只上报 touched）撞号，
   * 现改称 **M25**；`ec458bc` 的 commit 正文仍写 M22，以这里为准。）：
   * - **M19** `_duplicate_files.py:140`+`:148` 两处 `keep` 取成恒默认 ⇒ 第 2 条红
   *   （末尾那句 `dupEndState` 轮询：Expected `1|…-PICK-B` / Received `1|…-PICK-A`），
   *   第 1 条仍绿 —— 恒默认在「没改选」时本来就是对的，只有改选那条分得开。
   *   第 3 条 `--grep=B3A-T8C3` **单跑也红**（终态 `dupRemainingBatches` 拿到
   *   `[K1-A, K2-A, K3-A]` ≠ 期望的 `[K1-A, K2-B, K3-B]`）⇒ 用例 3 对后端逐组映射
   *   是**独立承重**，不再是「等价推断」。
   * - **M20** `:141` 的 `pending` 回到 `files[1:]` 硬编码 ⇒ 第 2 条红
   *   （同那句轮询，Expected `1|…-PICK-B` / Received `2|…-PICK-B`：`in_bulk` 拿不到那只 -A，
   *   一行都没删。回执那句「已删除 0 个」形状上仍匹配正则，所以红点落在终态而不是 toast）。
   * - **M21** `DuplicateFilesCard.vue:61` 的 `:data-keep` 三元反过来 ⇒ 第 1 条红
   *   （两条 `toHaveAttribute` 里的第一支：Expected `keep` / Received `delete`）。
   *   此时「保留/将删除」两支文案照旧通顺，正是这句要拦的「画错行但文案对得上」——
   *   按文案筛的定位器在这里是系统性盲区。
   * - **M25** `DuplicateFilesCard.vue:159` 的 `applyStrategy()` 无视 `strategy.value`、
   *   内部硬编码 `'earliest'` ⇒ 第 3 条红（④ 段 K2/K3 落 -A，那两条「策略落到较新那份」
   *   当场红）。旧版用例 3 策略就选「最早导入」，对这颗变异**整条失明**（三档全绿，
   *   返工轮发现 2）—— 2 成员组里 earliest 恒等于默认，选它等于没选。
   * - **M23** `utils/dupKeep.ts` 的 `applyStrategyToUntouched` 不滤 `choice.has`、
   *   把策略盖到所有组 ⇒ 第 3 条红（K1 被挪去 -B，④ 段那两条 K1 的 `data-keep` 红）。
   * - **M24** `DuplicateFilesCard.vue:85` 的 `:disabled` 去掉 `!deleteConfirmed ||` ⇒
   *   第 1 条红（勾同意框**之前**那句 `toBeDisabled()`；旧版三条都先勾再断，从没钉过
   *   勾之前的闸门，返工轮发现 3）。
   *
   * 一条**单击点不出、两击点得出**的界面状态（返工轮据发现 1 订正，两条都是实测）：
   * 在**已选中**的 radio 上再点一次，DOM 不发 `change`，EP `use-radio.mjs:18-23` 的
   * setter（`:21` 转 `radioGroup.changeEvent`，只由 `radio.vue` 那条原生 onChange 链驱动）
   * 不触发 ⇒ 单击「点默认那份」不留任何痕迹（首版用例 3 就红在这里，不是推理）；
   * 但 `pick()` 是**无条件** `choice.set(key, id)`（`DuplicateFilesCard.vue:154-156`，
   * 不比较新旧值）⇒ 「点 -B、再点回 -A」这两击都会发 change，第二击把该组标成**已改选**
   * 且值落回默认。即「用户确认就要默认这份」界面可表达，用例 3 的现形状就建在这上面。
   * 与之相邻但**不同**的那条边界仍然成立：`groups.length - choice.size` 与
   * `filter(!choice.has)` 两式的分歧需要 `choice` 里存在**切片外的陈旧键**，
   * 界面点不出来（`watch` 在 groups 刷新时整体清零）⇒ 那一式只由源码绊线拦，
   * **不许写成「由 T3 覆盖」**。
   */
  test('重复文件：不改选时默认保留最早导入那一份', async ({ page }) => {
    const dupName = `dup_def_${ts}.csv`
    try {
      // 播种在 try **内**（发现 4①）：中途抛也由 finally 按 dupDirs 确定性回收目录与行。
      const pair = await seedDuplicatePair(page, dupName, 'DEF')
      await openRepairCenter(page)
      const card = page.locator('[data-testid="duplicate-files-card"]')
      await expect(card).toBeVisible({ timeout: 15_000 })
      await expect(card).toContainText(dupName)
      // 弱判据（12 成员的组也匹配），承重的是下面的行数与 data-keep；
      // 且它隐含「slot 种子贡献 0 个重复组」这个前提（见上面 docblock，发现 8）。
      await expect(card).toContainText('2 个')

      const group = card.locator('[data-testid="dup-group"]').filter({ hasText: dupName })
      const rowA = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchA })
      const rowB = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchB })
      await expect(rowA, '两个批次目录各成一行').toHaveCount(1)
      await expect(rowB).toHaveCount(1)
      // 结构钩子，不按颜色/文案筛：画错行的「保留」在文案上照样通顺。
      await expect(rowA).toHaveAttribute('data-keep', 'keep')
      await expect(rowB).toHaveAttribute('data-keep', 'delete')

      // 同意闸本身就是判据（发现 3 / M24）：勾之前按钮必须 disabled。
      // 摘掉 `:disabled="!deleteConfirmed || …"`（DuplicateFilesCard.vue:85）后
      // 三条旧用例照样全绿 —— 每条都先勾再断，闸门从没被钉过。
      await expect(card.locator('button').filter({ hasText: '按选择删除' })).toBeDisabled()
      await card.locator('.el-checkbox').click()
      await expect(card.locator('button').filter({ hasText: '按选择删除 1 个' })).toBeVisible()
      await card.locator('button').filter({ hasText: '按选择删除' }).click()
      await expect(page.getByText(/已删除 \d+ 个重复文件/).first()).toBeVisible({ timeout: 20_000 })

      await expect
        .poll(() => dupEndState(page, dupName), { timeout: 15_000 })
        .toBe(`1|${pair.batchA}`)
      expect(fs.existsSync(path.join(pair.dirA, dupName)), '保留那份的磁盘文件必须还在').toBe(true)
      expect(fs.existsSync(path.join(pair.dirB, dupName)), '未保留那份必须从磁盘消失').toBe(false)
    } finally {
      await cleanupDup(dupName, ...dupDirs('DEF'))
    }
  })

  test('重复文件：改选保留项后留下的是被选那一份（缺陷第 3 项的正解）', async ({ page }) => {
    const dupName = `dup_pick_${ts}.csv`
    try {
      const pair = await seedDuplicatePair(page, dupName, 'PICK')
      await openRepairCenter(page)
      const card = page.locator('[data-testid="duplicate-files-card"]')
      await expect(card).toBeVisible({ timeout: 15_000 })
      const group = card.locator('[data-testid="dup-group"]').filter({ hasText: dupName })
      const rowA = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchA })
      const rowB = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchB })

      await rowB.locator('.el-radio').click()
      await expect(rowB).toHaveAttribute('data-keep', 'keep')
      await expect(rowA).toHaveAttribute('data-keep', 'delete')

      await card.locator('.el-checkbox').click()
      await card.locator('button').filter({ hasText: '按选择删除' }).click()
      await expect(page.getByText(/已删除 \d+ 个重复文件/).first()).toBeVisible({ timeout: 20_000 })

      // 旧行为（硬编码留 id 最小）会在这里红：留下的批次名是 -A。
      await expect
        .poll(() => dupEndState(page, dupName), { timeout: 15_000 })
        .toBe(`1|${pair.batchB}`)
      expect(fs.existsSync(path.join(pair.dirB, dupName)), '被选那一份的磁盘文件必须还在').toBe(true)
      expect(fs.existsSync(path.join(pair.dirA, dupName)), '默认那条必须真的被删走').toBe(false)
    } finally {
      await cleanupDup(dupName, ...dupDirs('PICK'))
    }
  })

  test('重复文件：一键策略只覆盖未改选的组，手改那组原样保留 [B3A-T8C3]', async ({ page }) => {
    const tags = ['K1', 'K2', 'K3']
    const names = tags.map((t) => `dup_strategy_${ts}_${t}.csv`)   // 三个不同文件名 = 三个组
    try {
      const pairs: Array<{ dirA: string; dirB: string; batchA: string; batchB: string }> = []
      for (let i = 0; i < tags.length; i++) {
        pairs.push(await seedDuplicatePair(page, names[i], tags[i]))
      }
      await openRepairCenter(page)
      const card = page.locator('[data-testid="duplicate-files-card"]')
      await expect(card).toBeVisible({ timeout: 15_000 })
      const applyBtn = card.locator('[data-testid="dup-apply-strategy"]')
      const rowsOf = (i: number) => {
        const g = card.locator('[data-testid="dup-group"]').filter({ hasText: names[i] })
        return {
          a: g.locator('[data-testid="dup-keep-row"]').filter({ hasText: pairs[i].batchA }),
          b: g.locator('[data-testid="dup-keep-row"]').filter({ hasText: pairs[i].batchB }),
        }
      }

      // ① 三组都未改选 ⇒ N=3
      await expect(applyBtn).toHaveText(/应用到未改选的 3 组/)

      // ② 手改 K1 并**落回默认**：两击，先点 -B、再点 -A。两条实测事实（首版就红在第一条）：
      //    a) 已选中的 radio 上**单击**不发 DOM change —— EP use-radio.mjs:18-23 的 setter
      //       （:21 转 radioGroup.changeEvent）只由 radio.vue 那条原生 onChange 链驱动，
      //       ⇒ 「直接点默认那份」标记不出「已改选」。
      //    b) 但 pick() 是无条件 choice.set（DuplicateFilesCard.vue:154-156，不比新旧值）
      //       ⇒ 第二击（-B → -A）照常发 change，把该组标成已改选、值落回默认 -A。
      //    所以 K1 停在「用户确认要默认这份」的形状上 —— 这是本条能同时杀两颗变异的前提：
      //    改选值(=默认 -A) ≠ 策略(最新 -B)，两个方向的分歧各有一句断言承重。
      const k1 = rowsOf(0)
      await k1.b.locator('.el-radio').click()
      await k1.a.locator('.el-radio').click()

      // ③ N 数的是「被点过的组」，与落在哪份无关 ⇒ 两击后必须恰好降 1（3→2）。
      //    Vue 对 ref(new Map()) 的深追踪失效时这里是唯一会红的地方（N 不动、按钮不 disable）。
      await expect(applyBtn).toHaveText(/应用到未改选的 2 组/)

      // ④ 策略选「最新导入」（≠ 默认 earliest）再一键应用。一步同时杀两颗变异：
      //    K2/K3 必须落到 -B —— 钉「applyStrategy 无视 strategy.value 硬编码 earliest」
      //    （M25，DuplicateFilesCard.vue:159；旧版策略选 earliest，2 成员组里恒等于默认，
      //    对该变异整条失明）；K1 必须留在 -A —— 钉「策略覆盖已改选的组」（M23 的界面面）。
      await card.locator('.dup-strategy .el-radio').filter({ hasText: '最新导入' }).click()
      await expect(k1.a, '应用前中间态：K1 两击后已改选，值 = 默认 -A').toHaveAttribute('data-keep', 'keep')
      await expect(k1.b).toHaveAttribute('data-keep', 'delete')
      await applyBtn.click()
      await expect(applyBtn).toBeDisabled()                    // N 归零
      await expect(k1.a, 'K1 已改选：策略不许越界将其挪去 -B').toHaveAttribute('data-keep', 'keep')
      await expect(k1.b).toHaveAttribute('data-keep', 'delete')
      for (let i = 1; i < 3; i++) {
        await expect(rowsOf(i).b, `${tags[i]} 组应被策略落到最新导入的 -B（≠ 默认）`)
          .toHaveAttribute('data-keep', 'keep')
      }

      // ⑤ 删 3 后终态按批次名认：K1 留手改确认的 -A，K2/K3 留策略的 -B。
      //    后端 M19（keep 恒取 files[0].id）让这句红（--grep 单跑实测）⇒ 本条独立承重。
      await card.locator('.el-checkbox').click()
      await card.locator('button').filter({ hasText: '按选择删除 3 个' }).click()
      await expect(page.getByText(/已删除 3 个重复文件/).first()).toBeVisible({ timeout: 20_000 })
      const want = [pairs[0].batchA, pairs[1].batchB, pairs[2].batchB].sort()
      await expect.poll(() => dupRemainingBatches(page, names), { timeout: 15_000 }).toEqual(want)
    } finally {
      // 确定性兜底：播种中途抛也按 dupDirs 把 3 组 6 目录与 3 个文件名全清一遍
      // （rmSync force / 按名删行，对不存在的目录与不存在的行是 no-op）。
      for (let i = 0; i < tags.length; i++) {
        await cleanupDup(names[i], ...dupDirs(tags[i]))
      }
    }
  })

  /**
   * 终审 F2 的谎话控件（旧标签「未改选的组默认保留」+ 两颗 radio ⇒ 读起来像「默认跟着 radio 走」，
   * 而 `keepIdForGroup` 压根不读 `strategy`）。本条同时钉：标签文本、alert 那句真相、以及
   * 「拨了没点应用 ⇒ 未改选组仍留最早」的**磁盘终态**（F2-a 红在标签那句，F2-b 红在 data-keep 与终态）。
   */
  test('拨了策略没点应用 ⇒ 未改选的组仍留最早（标签不许承诺默认）[B3A-F2A]', async ({ page }) => {
    const dupName = `dup_lbl_${ts}.csv`
    try {
      const pair = await seedDuplicatePair(page, dupName, 'LBL')
      await openRepairCenter(page)
      const card = page.locator('[data-testid="duplicate-files-card"]')
      await expect(card).toBeVisible({ timeout: 15_000 })
      const label = card.locator('.dup-strategy-label')
      await expect(label).toHaveText('一键策略（只作用未改选的组）')
      await expect(label).not.toContainText('默认保留')
      // 两句必须**不是同一句**：真相归 alert（默认恒为最早），标签只划这颗策略的作用范围。
      await expect(card.locator('.el-alert').filter({ hasText: '未改选的组默认保留最早' })).toHaveCount(1)
      const group = card.locator('[data-testid="dup-group"]').filter({ hasText: dupName })
      const rowA = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchA })
      const rowB = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchB })
      await card.locator('.dup-strategy .el-radio').filter({ hasText: '最新导入' }).click()
      await expect(rowA, '拨了策略没点应用：未改选组的保留项不许动').toHaveAttribute('data-keep', 'keep')
      await expect(rowB).toHaveAttribute('data-keep', 'delete')
      // 这颗 radio 不该把任何组标成「已改选」——N 仍是 1，否则标签那句「只作用未改选的组」又是假的
      await expect(card.locator('[data-testid="dup-apply-strategy"]')).toHaveText(/应用到未改选的 1 组/)
      await card.locator('.el-checkbox').click()
      await card.locator('button').filter({ hasText: '按选择删除 1 个' }).click()
      await expect(page.getByText(/已删除 \d+ 个重复文件/).first()).toBeVisible({ timeout: 20_000 })
      await expect.poll(() => dupEndState(page, dupName), { timeout: 15_000 }).toBe(`1|${pair.batchA}`)
      expect(fs.existsSync(path.join(pair.dirA, dupName)), '留下的必须是磁盘上最早那份 -A').toBe(true)
      expect(fs.existsSync(path.join(pair.dirB, dupName)), '最新那份 -B 必须被删走').toBe(false)
    } finally {
      await cleanupDup(dupName, ...dupDirs('LBL'))
    }
  })

  test('截断提示：总数 > 展示数才渲染进卡片，反向不渲染 [B3A-F2NOTE]', async ({ page }) => {
    // ⚠ 这条**只钉前端渲染**：`fulfill` 整个替换了 GET 响应，所以它不证明任何后端语义
    //   （批2 lesson 2026-11-14「反证要在判据够得着的那一层跑」）。50 组切片的真实语义在 T1
    //   （`test/backend/test_duplicate_keep_selection.py`），这里只是把 `:truncated-note` 那根
    //   线头钉住 —— 摘掉它 T1/T2/T3 此前都无牙（grep truncated-note 在 e2e/test = 0 命中）。
    // 字段名取自 GET 的真形状：`duplicate_group_count` = 总组数、`duplicate_groups` = 展示切片。
    const payload = (n: number, total: number) => ({
      orphaned_db_count: 0, orphaned_db: [], orphaned_disk_count: 0, orphaned_disk: [],
      missing_product_code_count: 0, missing_product_code: [],
      duplicate_group_count: total,
      duplicate_groups: Array.from({ length: n }, (_, i) => ({
        filename: `dup_mock_${i}_${ts}.csv`, file_size: 500,
        files: [1, 2].map((k) => ({
          id: 900000 + i * 10 + k, filename: `dup_mock_${i}_${ts}.csv`, file_size: 500,
          file_type: 'batch', batch_name: `MOCK-${k}`, sub_batch: '',
          created_at: `2026-0${k}-01T00:00:00+00:00`,
        })),
      })),
    })
    let body = payload(3, 5) // 假 id ⇒ 本条绝不 POST（POST 会走真后端，400 是后端的判据）
    await page.route('**/api/v1/consistency-check/**', (r) => r.fulfill({ json: body }))
    await openRepairCenter(page)
    const card = page.locator('[data-testid="duplicate-files-card"]')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(card).toContainText('共 5 组重复，本批处理前 3 组，其余 2 组本批不处理')
    body = payload(2, 2) // 总数 == 展示数 ⇒ 这句话必须消失
    // ⚠ 底部那颗「重新检查」只是 `result = null`（ConsistencyCheckDialog.vue:106），**不发请求**；
    //   新载荷由第二次「开始检查」那一发吃到（route 的回调读的是上面那个 `let body`）。
    await page.getByRole('button', { name: '重新检查' }).click()
    await page.getByRole('button', { name: '开始检查' }).click()
    await expect(card).toContainText(`dup_mock_1_${ts}`) // 卡片仍在（下条的「没有」才不是「整卡没了」）
    await expect(card).not.toContainText('本批不处理')
  })
})

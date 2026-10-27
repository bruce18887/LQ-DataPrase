/**
 * 600 行硬约束的判定内核（纯函数，零 IO）。
 *
 * 规则正文与**适用面**的唯一可读界定在 `.claude/CLAUDE.md` 的「600 行约束的适用面」一节；
 * IO 壳（`git ls-files` + 读文件）与全仓断言在 `frontend/test/unit/lineLimit.spec.ts`
 * —— 那是 T2 档（`npm run test:unit`，约 0.7s、不开浏览器），CI 的 vitest 步骤已经在跑它。
 *
 * 为什么判据要与 IO 分开：本仓同一形状栽过两次（`docs/reference/testing-gates.md` §1
 * 「门禁打印的命令必须就是执行的命令」、§3「IO 壳仍没有单测」）。把「怎么算违规」摊成纯函数，
 * 才能用对照组钉死；IO 那半只剩 git 与 fs，坏了会在同一条断言上红。
 *
 * 豁免账的来历（别当成"漏建"）：`docs/tasks/todo.md`「留给拍板」第 6 条把这条约束拆成
 * 两个取向 —— 拆文件 / 挂绊线。2026-10-27 按用户指示只落**绊线**，五个存量超限文件
 * 全部按精确行数冻进下面那份账，拆分动作留给各自工单。
 */

/** 阈值：与 `.claude/CLAUDE.md` 正文同一个数，别再在第三处写。 */
export const LINE_LIMIT = 600

/**
 * 适用面的 git pathspec —— 只有这三类扩展名。
 * 刻意含 `*.ts`：todo.md 第 6 条当时的普查命令写的是 `'*.py' '*.vue'`，
 * 于是 `frontend/e2e/data/view-data.spec.ts`（1802）与 `data.spec.ts`（1042）
 * 从头到尾没进过任何人的视野（"前端反倒一处没有"就是这么来的）。
 */
export const SCOPE_PATHSPECS = ['*.py', '*.ts', '*.vue']

/**
 * 存量豁免账：**精确行数**冻结。
 * 记精确数而不是"在名单里就算过"，是因为只认名单的话，超限文件可以无上限地继续长
 * —— `tests_jobs.py` 2026-10-18 新建后一路往里加例，长到 846 全程没人量过（todo.md 第 6 条①）。
 * 再多一行 → `kind: 'grew'` → 报红。
 */
export const EXEMPT = [
  {
    path: 'apps/datafiles/tests.py',
    lines: 1968,
    reason:
      '2026-09-02 批次 3 已按主题拆过一轮（那条把同族 tests.py 从 2468 行拆开），' +
      '剩余部分要先量跨类 fixture 依赖（类之间互借道具、有 class 子(父) 继承），' +
      '验收口径 = 用例 ID 逐条 diff 为空且总数不变 —— 属独立工单，不由本闸拦当下改动。',
  },
  {
    path: 'apps/jobs/tests_jobs.py',
    lines: 846,
    reason:
      '2026-10-18（9c05ea5）新建，之后作业化持续往里加例，长到 846 没人量过（todo.md 第 6 条①）。' +
      '现成接缝是 class：8 个 class / 39 个 def test_，按主题拆成 tests_jobs_<主题>.py 即可。',
  },
  {
    path: 'frontend/e2e/data/data.spec.ts',
    lines: 1042,
    reason:
      '查看数据页的历史用例堆叠。拆它要连着改定位器，且 e2e 用例数是 `nightly-gates.mjs` ' +
      '退化阈值（THRESHOLDS.specs）的口径来源，属独立工单。',
  },
  {
    path: 'frontend/e2e/data/view-data.spec.ts',
    lines: 1802,
    reason:
      '同目录里最大的一份，且是 e2e 存量红清单的锚（多处待办正引用它的行号）。' +
      '与 data.spec.ts 同族，留给同一批拆分工单。',
  },
  {
    path: 'test/backend/test_sftp_search_engine_stream.py',
    lines: 642,
    reason:
      '2026-09-21（1e26839）进来时就能被扫到，但 2026-10-15 那份架构评审只点名了 apps/ 侧，' +
      '`test/backend/` 整棵没逐个量（todo.md 第 6 条②）。现成接缝是 class：15 个 class / 51 个方法。',
  },
]

/**
 * 行数口径：按 `\n` 切分后去掉末尾空串（末尾换行不算一行）。
 * 与 `wc -l` 在本仓 778 个 in-scope 文件上**逐字相同**（spec 里钉着这条对照），
 * 所以对 Windows（core.autocrlf=true，工作树是 CRLF）和 Linux CI 都同值。
 */
export function countLines(text) {
  const arr = text.split('\n')
  if (arr.length > 0 && arr[arr.length - 1] === '') arr.pop()
  return arr.length
}

/**
 * 按路径给出 owner。本仓没有 CODEOWNERS，也没有入库钩子，
 * 所以 owner 只能从目录结构推 —— 推出的是「该改哪一层」，不是「该找哪个人」。
 * 认不出来的形状也返回顶层目录，红字永远不会给一个空 owner。
 */
export function ownerOf(rel) {
  const seg = rel.split('/')
  const top = seg[0]
  if (top === 'apps') return `Django app \`apps/${seg[1] ?? '?'}\`（后端业务层）`
  if (top === 'config') return 'Django 配置层 `config/`'
  if (top === 'test') return '后端测试树 `test/`（T1 契约层）'
  if (top === 'frontend') {
    if (seg[1] === 'e2e') return `Playwright 用例 \`frontend/e2e/${seg[2] ?? ''}\`（T3 浏览器层）`
    if (seg[1] === 'test') return '前端纯函数测试 `frontend/test/unit/`（T2 层）'
    if (seg[1] === 'src') {
      if (seg[2] === 'pages') return `前端页面 \`frontend/src/pages/${seg[3] ?? ''}\``
      if (seg[2] === 'components') return '前端共享组件 `frontend/src/components/`'
      return `前端 \`frontend/src/${seg[2] ?? ''}\` 层`
    }
    return `前端工程根配置 \`frontend/${seg[1] ?? ''}\``
  }
  if (top === 'electron') return 'Electron 主进程 `electron/`'
  if (top === 'scripts') return '打包期与门禁工具 `scripts/`'
  return `${top}/（按路径未归类，owner 取顶层目录）`
}

/**
 * 是不是测试文件 —— 决定给哪一条拆分建议，也是「业务侧 0 件」那条断言的口径来源。
 * 导出它，是为了让 spec 用内核自己的分类去断言，而不是在测试里再抄一份判据（三份字面量必然漂移）。
 */
export function isTestFile(rel) {
  const base = rel.split('/').pop() ?? ''
  if (rel.startsWith('test/')) return true
  if (rel.startsWith('frontend/e2e/')) return true
  if (rel.startsWith('frontend/test/')) return true
  if (/^tests[^/]*\.py$/.test(base)) return true
  if (/^test_[^/]*\.py$/.test(base)) return true
  if (/\.spec\.ts$/.test(base)) return true
  return false
}

/**
 * 拆分建议按文件形状给，每条都带上本仓**已经踩过的坑**——
 * 只说"拆小一点"等于让下一个人重新踩。
 */
export function splitHint(rel) {
  const test = isTestFile(rel)
  if (rel.endsWith('.vue')) {
    return [
      '拆 SFC：`<script setup>` 里的图表/表格逻辑抽 composable，模板抽子组件。',
      '样式那半先收敛到 CSS token 再数行 —— R7① 禁止页面级 night 覆盖，' +
        '把双主题块搬进新文件只是换个地方堆 !important。',
      '改完必须 `npm run build`（vue-tsc -b + vite build），根目录 `npx vue-tsc --noEmit` 是空检查（R8①）。',
    ].join('\n    ')
  }
  if (test && rel.endsWith('.py')) {
    return [
      '按主题拆，现成接缝一般是 class —— 但**先量跨类 fixture 依赖**再分组：',
      '类之间互借道具（`_patched_view`、`METADATA/_frame`）与 `class 子(父)` 继承，' +
        '只按相邻行分组会 NameError（教训见 2026-09-02 批次 3）。',
      '验收口径不是"跑起来没报错"：拆分前后**唯一用例 ID 集合逐条 diff 为空且总数不变**。',
      '⚠ 新文件**不得 `import pytest`** —— CI 只装 `requirements/base.txt`，里面没有 pytest。',
      '⚠ 往 `test/backend/` 的**新子目录**里放文件要补 `__init__.py`，否则 DiscoverRunner 从不收集，' +
        '用例静默消失而门禁全绿（testing-gates.md §6）。',
    ].join('\n    ')
  }
  if (test) {
    return [
      '按主题拆 spec：用例分组本来就按页面区块走，搬进同目录的兄弟文件即可；' +
        '共用的等待与定位器先抽进 `frontend/e2e/helpers/`。',
      'e2e 不在 `npm run build` 的 include 覆盖内，删用例留下的死 import **只有 `npm run lint:e2e` 能发现**' +
        '（testing-gates.md §5），拆完必须跑它。',
      '⚠ 别顺手放宽 `nightly-gates.mjs` 的 `THRESHOLDS.specs`：用例总数是退化判据的分子，' +
        '拆文件不该改变它。',
    ].join('\n    ')
  }
  return [
    '按职责下沉：视图文件先拆 service/纯函数，别把 ViewSet 平铺成 mixin。',
    '⚠ 2026-10-16 的实测教训：把 ViewSet 按 600 行拆成 mixin，`_load_df_from_request` ' +
      '在每个视图模块里是**各自独立的绑定**，一拆两半只 patch 旧模块的测试立刻打真 loader' +
      '（当时 25 条用例从 200/400 变 500）。',
    '做法照 `apps/analysis/test_support.py::patch_df_loader`：patch 目标**扫包动态收集消费者**，' +
      '不要硬写模块名 —— 「一个函数被 N 个模块 import」的 N 必须由代码算，不能由人列。',
  ].join('\n    ')
}

function exemptBy(exempt) {
  const map = new Map()
  for (const e of exempt) {
    if (map.has(e.path)) throw new Error(`豁免账里 ${e.path} 写了两次`)
    map.set(e.path, e)
  }
  return map
}

/**
 * 求违规集合。入参是「已选好适用面并数好行」的条目，本函数不碰磁盘。
 * 两种红：
 *  - `new`  —— 不在豁免账里的超限文件（新增文件、或把适用面外挪进来的文件）
 *  - `grew` —— 在账里但比登记的精确行数更长（豁免不等于免检）
 */
export function findViolations(entries, { limit = LINE_LIMIT, exempt = EXEMPT } = {}) {
  const ledger = exemptBy(exempt)
  const out = []
  for (const { path, lines } of entries) {
    const frozen = ledger.get(path)
    if (lines <= limit) continue
    if (!frozen) {
      out.push({ path, lines, limit, kind: 'new', frozenLines: null })
    } else if (lines > frozen.lines) {
      out.push({ path, lines, limit, kind: 'grew', frozenLines: frozen.lines })
    }
  }
  return out.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
}

/**
 * 反向判据：豁免账里的文件已经不超限（被拆掉了）或已从树上消失，就是**陈旧豁免**。
 * 不拦这条，账只会单向膨胀 —— 拆完不销账，下一个人无从知道名单还能不能再缩。
 */
export function findStaleExemptions(entries, { limit = LINE_LIMIT, exempt = EXEMPT } = {}) {
  const seen = new Map(entries.map((e) => [e.path, e.lines]))
  const out = []
  for (const frozen of exempt) {
    const now = seen.get(frozen.path)
    if (now === undefined) out.push({ path: frozen.path, why: '树上已不存在（改名/删除后名单没销）' })
    else if (now <= limit) out.push({ path: frozen.path, why: `现测 ${now} 行已不超 ${limit}，应从豁免账删除` })
    else if (now < frozen.lines)
      out.push({ path: frozen.path, why: `登记 ${frozen.lines} 行、现测 ${now} 行：变短了要同步下调登记值` })
  }
  return out
}

/** 红字：一次给出文件、行数、owner、建议的下一步与销账路径。 */
export function formatViolation(v) {
  const head =
    v.kind === 'grew'
      ? `❌ ${v.path}  ${v.lines} 行 > 阈值 ${v.limit}；豁免账登记的是 ${v.frozenLines} 行` +
        ` —— 在已豁免的基础上又长了 ${v.lines - v.frozenLines} 行`
      : `❌ ${v.path}  ${v.lines} 行 > 阈值 ${v.limit}（不在豁免账里）`
  const owner = `   owner: ${ownerOf(v.path)}`
  const hint = `   拆分建议:\n    ${splitHint(v.path)}`
  const howto =
    '   要豁免而不是拆：把精确行数写进 scripts/line-limit.mjs 的 EXEMPT 并附理由（哪次工单、为什么不由本闸拦），' +
    '\n   同时确认它属于适用面内的哪一类（见 .claude/CLAUDE.md「600 行约束的适用面」）。'
  return `${head}\n${owner}\n${hint}\n${howto}`
}

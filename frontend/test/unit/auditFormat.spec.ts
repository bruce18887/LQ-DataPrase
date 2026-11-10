/**
 * T2：审计页两个格式化器（`utils/audit.ts` 的 `formatAuditTime` / `auditDetailJson`）。
 *
 * 它们原先长在 `pages/admin/AuditLogPage.vue` 里。搬进纯层的理由不是「组件太胖」，是这两段的
 * 判据本来就没法在浏览器里便宜地写：时间列要的是**本地时区的定长字符串**，展开行要的是
 * 「贴的是整份原文、且原文没有被第二道打码改动过」—— 两边都只能拿值来比，而 e2e 里比这串
 * 数字要先把机器时区也算进期望值，那就是把判据焊在跑测试的那台机器上。
 *
 * 时区在这份文件里是被**钉住**的（`process.env.TZ = 'Asia/Shanghai'`，与 `config/settings/base.py:258`
 * 的 `TIME_ZONE` 同一个值）：`formatAuditTime` 用本地 getter，后端 `_parse_day_bound` 按 Django 时区
 * 取整日边界，这两条线一致才是「日期筛完、这一列显示的时刻落在同一天」。钉死之后换机器不用重测，
 * 也不用在读代码的人脑子里装一台 UTC 机器。
 *
 * 本文件还管着另外两族判据（都不是格式化器，但家只能在这里）：
 * ① `buildAuditQuery` 对「控件清空」那三种形状（`''` / `null` / `undefined`）的收口；
 * ② 对 `AuditLogPage.vue` **剥掉整行注释之后**的源码扫描 —— 那一页是 Task 13 要照抄的样板，
 *    先钉住它绑的是常量而不是等值字面量。
 * 两族都塞不进 `test/unit/audit.spec.ts`：那份实测 594 行，再加一条腿就撞上 600 硬线
 * （那道闸的判据是同目录的 `lineLimit.spec.ts`）。
 *
 * 跑：cd frontend && npx vitest run test/unit/auditFormat.spec.ts
 */
import { readFileSync } from 'node:fs'
import { afterAll, describe, expect, it } from 'vitest'

import {
  AUDIT_PLACEHOLDER,
  auditDetailJson,
  buildAuditQuery,
  defaultAuditFilters,
  formatAuditTime,
  summarizeDetail,
} from '../../src/utils/audit'

const ORIGINAL_TZ = process.env.TZ
process.env.TZ = 'Asia/Shanghai'
afterAll(() => {
  // threads 池会把同一个 worker 交给下一个测试文件，TZ 不还得让它带着 Asia/Shanghai 跑别的判据。
  if (ORIGINAL_TZ === undefined) delete process.env.TZ
  else process.env.TZ = ORIGINAL_TZ
})

describe('formatAuditTime：本地时区的 YYYY-MM-DD HH:mm:ss', () => {
  it('整点/跨日/亚秒都按钉住的时区折成秒级定长串（DRF 交回来的就是带偏移的 ISO）', () => {
    const cases: Array<[string, string]> = [
      ['2026-03-05T00:00:00Z', '2026-03-05 08:00:00'],
      ['2026-12-31T16:00:01Z', '2027-01-01 00:00:01'],
      ['2026-01-01T23:59:59Z', '2026-01-02 07:59:59'],
      ['2026-03-05T08:00:00.123456+08:00', '2026-03-05 08:00:00'],
    ]
    for (const [raw, want] of cases) {
      expect(formatAuditTime(raw), raw).toBe(want)
    }
  })

  it('形状判据：秒一位都不能少（同一分钟内的两次登录失败靠它区分）', () => {
    // 断的是**长度与分隔位**而不是正则碰运气：把 pad 删掉、把秒那一段删掉，本条都要红。
    const text = formatAuditTime('2026-03-05T00:00:00Z')
    expect(text).toHaveLength('YYYY-MM-DD HH:mm:ss'.length)
    expect(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text), text).toBe(true)
  })

  it('空值给占位符，认不出的一律原样交回而不是抛或显示 NaN-NaN-NaN', () => {
    expect(formatAuditTime('')).toBe(AUDIT_PLACEHOLDER)
    // new Date('不是时间') 是 Invalid Date；走到 Number.isNaN 那一支就得把原文递回界面，
    // 让管理员看得见「后端给的是这么个东西」，而不是吞成占位符或一串 NaN。
    expect(formatAuditTime('不是时间')).toBe('不是时间')
  })
})

describe('auditDetailJson：展开行贴的是整份原文', () => {
  it('对象折成可读 JSON，且 JSON.parse 回来与原始值逐字段相等（判的是「没被格式化改动过」）', () => {
    const detail = { changed_fields: ['email', 'role'], values: { role: 'administrator' }, locked_until: null }
    const text = auditDetailJson(detail)
    expect(text).toContain('\n')
    expect(text).toContain('  ')
    expect(JSON.parse(text)).toEqual(detail)
  })

  it('空对象 / null / undefined 给占位符（detail 是 JSONField default=dict，越界形状由后端那道闸管）', () => {
    for (const raw of [{}, null, undefined]) {
      expect(auditDetailJson(raw), String(raw)).toBe(AUDIT_PLACEHOLDER)
    }
  })

  it('反向自证：这一格刻意**不**打码 —— 键名命中口令启发式的值照样原样贴出来，打码只归摘要那一行', () => {
    // 「敢不打码」的依据不在本文件，而在写路径那道闸：test/unit/audit.spec.ts 的
    // 「裸贴 JSON 的展开行」describe 刮 apps/accounts/views.py 与 apps/common/views.py 里每个
    // detail= 的任意深度键名，命中 /pass|token|secret/i 即红。所以有人把这里"修成打码"就是
    // 把取证页的原文换成一份二次加工 —— 那条 describe 会红，本条也会红。
    const detail = { password: 'hunter2', role: 'user' }
    const expanded = auditDetailJson(detail)
    expect(expanded, '展开行一旦跟着打码，取证时就拿不到原文了（这道分工是有意的）').toContain('hunter2')
    expect(JSON.parse(expanded)).toEqual(detail)
    // 同一份 detail 交给摘要那条路必须打码：两道闸的分工在这里对上，别把它读成「两边都漏」。
    expect(summarizeDetail(detail)).toBe('password=•••，role=user')
  })
})

describe('组件里不许再长出第二份格式化器（搬家的账要有人盯）', () => {
  const PAGE = '../../src/pages/admin/AuditLogPage.vue'
  const src = () => readFileSync(new URL(PAGE, import.meta.url), 'utf8')

  it('模板只从 utils/audit 取这两个函数，且页面自身不再定义同名本地实现或自抄占位符', () => {
    const body = src()
    for (const name of ['formatAuditTime', 'auditDetailJson']) {
      expect(body, `${PAGE} 没有从 utils/audit 引 ${name}`).toContain(`  ${name},`)
      expect(new RegExp(`function ${name}\\b`).test(body), `${PAGE} 又定义了一份本地 ${name}`).toBe(false)
    }
    expect(body, `${PAGE} 自抄了一份占位符字面量`).not.toMatch(/const PLACEHOLDER\s*=/)
    expect(body).toContain('AUDIT_PLACEHOLDER')
  })
})

describe('控件清空后的三种形状都在纯层收口（可空性不是组件的事）', () => {
  // 这一腿判的还是 `buildAuditQuery`，与 test/unit/audit.spec.ts 里那族同源；放进来只因为那份文件
  // 已经 594/600 行。别把它读成「格式化器的判据」，搬家账目在文件头。
  it('el-select 清空交回的是 undefined（既不是空串也不是 null）：event 不发键，也不许抛', () => {
    // EP 2.14.0 的实测形状与出处都写在 utils/audit.ts 的 `AuditFilters` 注释里（单选 clearable 的
    // select 发的是 `useEmptyValues(props)` 的 valueOnClear，没给默认值 ⇒ undefined）。
    // 把纯层的 trimText 退回 `filters.event.trim()`，这一记就是 TypeError —— 而它在页面上的症状
    // 是「点了查询什么都不发」（抛在 load() 的 try 里被 catch 咽掉），浏览器侧看不出来。
    for (const event of [undefined, null, '']) {
      expect(buildAuditQuery({ ...defaultAuditFilters(), event }), `event=${String(event)}`)
        .toEqual({ page: 1, page_size: 50 })
    }
    // 反向：收口不等于一律回空串 —— 带空白的真值还得原样发出去（去空格本来就是纯层的活）。
    expect(buildAuditQuery({ ...defaultAuditFilters(), event: ' login_success ' }).event)
      .toBe('login_success')
  })
})

/**
 * 审计页的**常量绑定**扫描（复审点出来的形状：e2e 那一腿把候选数字硬断成 ['20','50','100']，
 * 于是「把页面抄得更死」也能把它修绿 —— 那是错的修法：Task 13 要照抄的就是这一页，
 * 页面里长出第二份 50/100/150 的字面量，Task 9 刚消灭的那批副本会原地复活，而且这份没有绊线）。
 *
 * 判据两条：正向 —— 代码行必须留着三个常量名；反向 —— 代码行不许出现等值字面量
 * （`maxlength="150"` 或 `[20, 50, 100]`）。**先剥整行注释**（`codeOf`，同 roleLabelHygiene.spec.ts:36）：
 * 这一页的注释本来就在讲这两个常量，不剥的话正向腿恒绿，整条判据只是在读注释。
 *
 * 已知边界（写在这里而不是假装不存在）：正向腿判的是「本文件引了这个名字」，import 行也算 ——
 * 所以「只 import 不使用」这一记它抓不到。那一记由 e2e 的 ③（看得见的候选数字 + 发得出去的
 * page_size=100）与本文件的字面量禁令夹住，三者叠起来才闭合。
 */
describe('审计页绑的是常量，不是等值字面量（Task 13 要照抄这一页）', () => {
  const PAGE = '../../src/pages/admin/AuditLogPage.vue'
  const rawPage = () => readFileSync(new URL(PAGE, import.meta.url), 'utf8')
  /** 整行注释不参与判定：行首的 `//`、`/*`、`*`、`<!--`。 */
  const codeOf = (text: string): string =>
    text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')
  const page = () => codeOf(rawPage())

  const CONST_NAMES = ['AUDIT_PAGE_SIZE_DEFAULT', 'AUDIT_PAGE_SIZE_MAX', 'USERNAME_QUERY_MAX']
  const missingConst = (code: string): string[] => CONST_NAMES.filter((n) => !code.includes(n))
  /** 等值字面量的两种形状，返回命中的描述（顺序固定，方便自证那条比集合）。 */
  const literals = (code: string): string[] => [
    ...( /maxlength=["']150["']/.test(code) ? ['maxlength 字面量 150'] : []),
    ...( /\[\s*20\s*,\s*50\s*,\s*100\s*\]/.test(code) ? ['[20, 50, 100] 字面量数组'] : []),
  ]

  it('正向：三个常量名都在代码行里（引了没用到抓不到，边界见上面那段）', () => {
    expect(missingConst(page()), `${PAGE} 的代码行里少了这些常量`).toEqual([])
  })

  it('反向：代码行里没有等值字面量 —— 把常量换回数字就是把 Task 9 消灭的第二副本搬回来', () => {
    expect(literals(page()), `${PAGE} 抄死了与常量等值的字面量，绊线就看不见后端把数挪走`).toEqual([])
  })

  it('自证①：把三个常量按等值字面量替换，两条判据必须同时红（否则它们看不见这一记改动）', () => {
    let swapped = page()
    for (const [name, lit] of [['AUDIT_PAGE_SIZE_DEFAULT', '50'], ['AUDIT_PAGE_SIZE_MAX', '100'], ['USERNAME_QUERY_MAX', '150']] as const) {
      swapped = swapped.replace(new RegExp(`\\b${name}\\b`, 'g'), lit)
    }
    expect(swapped, '探针没改动源码，等于什么都没测').not.toBe(page())
    expect(missingConst(swapped)).toEqual(CONST_NAMES)
    expect(literals(swapped)).toEqual(['maxlength 字面量 150', '[20, 50, 100] 字面量数组'])
  })

  it('自证②：剥注释这一步真的有牙 —— 只在注释里提名字、代码行抄字面量的假页面必须两记都报', () => {
    const fake = [
      '<!-- 这里本该绑 AUDIT_PAGE_SIZE_DEFAULT / AUDIT_PAGE_SIZE_MAX / USERNAME_QUERY_MAX -->',
      'const pageSizes = [20, 50, 100]',
      '<el-input :maxlength="150" />',
    ].join('\n')
    // 不剥注释就会让正向腿假绿（三个名字都"在"）—— 危险方向是反的：注释留着、代码删掉时，
    // 未剥的判据静默放行，而这条判据存在的全部理由就是拦住那种漂移。
    expect(CONST_NAMES.every((n) => fake.includes(n)), '假页面没在注释里点名三个常量').toBe(true)
    expect(missingConst(codeOf(fake)), '剥完注释还认得到名字 ⇒ 判据其实是在读注释').toEqual(CONST_NAMES)
    expect(literals(codeOf(fake))).toEqual(['maxlength 字面量 150', '[20, 50, 100] 字面量数组'])
  })

  it('反向探针（必须绿）：pageSizes 改名、import 并成一行、属性换序、候选只剩两个，都不算抄死', () => {
    const probes: Array<[string, string]> = [
      ['pageSizes 改名', page().replace(/\bpageSizes\b/g, 'sizeOptions')],
      ['import 并成一行', page().replace(/  AUDIT_PAGE_SIZE_DEFAULT,\r?\n  AUDIT_PAGE_SIZE_MAX,/, '  AUDIT_PAGE_SIZE_DEFAULT, AUDIT_PAGE_SIZE_MAX,')],
      ['el-input 属性换序', page().replace(/(placeholder="[^"]*")(\r?\n\s*)(clearable)/, '$3$2$1')],
      ['候选只剩两个（仍然绑常量）', page().replace('[20, AUDIT_PAGE_SIZE_DEFAULT, AUDIT_PAGE_SIZE_MAX]', '[20, AUDIT_PAGE_SIZE_DEFAULT]')],
    ]
    for (const [name, mutated] of probes) {
      expect(mutated, `探针「${name}」没改动源码，等于什么都没测`).not.toBe(page())
      expect(missingConst(mutated), `探针「${name}」下正向腿变了（判据焊在版式上了）`).toEqual([])
      expect(literals(mutated), `探针「${name}」下反向腿变了（判据过拟合）`).toEqual([])
    }
  })
})

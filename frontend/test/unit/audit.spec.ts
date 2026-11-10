/**
 * T2：审计页三件纯函数（`utils/audit.ts`）——事件标签、筛选转 query、detail 单行摘要。
 *
 * 这一层是 Task 11 那页的全部非渲染逻辑，判据分两类，缺一类都会留出一条安静的假绿：
 *
 * ① **与后端源码双向钉**。事件码清单住在 `apps/accounts/audit.py` 的 `AUDIT_EVENTS`，
 *    分页边界与查询参数名住在 `apps/accounts/views.py`，username 列宽住在 `apps/accounts/models.py`；
 *    跨语言没有共享类型，前端这几份是**第二副本**，只能刮源码保鲜。后端加码而标签表没跟上 ⇒ 红；
 *    前端多贴一个后端不会产生的码 ⇒ 也红；后端挪走 `page_size` 上限而这里还在往旧上限夹 ⇒ 也红；
 *    后端把 `date_from` 改名成别的而这里照发旧名 ⇒ 也红（那一条最阴：DRF 不认识就当没填，
 *    页面拿到一份看着完整的时间线，一声不吭）。
 *    刮取器一律「找不到/形状不认识就抛」，绝不返回空集合：空集合会让等式两边同时变空、
 *    整条绊线恒绿。本文件末尾的「抽取器自证」钉的就是这件事。
 * ② **异源的值判据**。标签按 `码 → 中文` 逐对钉字面量（`SPEC_LABELS`），而不是遍历实现里那张表
 *    自己跟自己比——后者杀不掉任何回归。数字同理：`SPEC_NUMBERS` 抄的是 spec §5.2/§6 的原文。
 *
 * 跑：cd frontend && npx vitest run test/unit/audit.spec.ts（node 环境、零 DOM、不开浏览器）
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
  AUDIT_EVENT_LABELS,
  AUDIT_PAGE_SIZE_DEFAULT,
  AUDIT_PAGE_SIZE_MAX,
  auditEventLabel,
  buildAuditQuery,
  defaultAuditFilters,
  summarizeDetail,
  USERNAME_QUERY_MAX,
} from '../../src/utils/audit'

const REPO_ROOT = new URL('../../../', import.meta.url)
const read = (rel: string) => readFileSync(new URL(rel, REPO_ROOT), 'utf8')

const AUDIT_PY = 'apps/accounts/audit.py'
const VIEWS_PY = 'apps/accounts/views.py'
const MODELS_PY = 'apps/accounts/models.py'

/**
 * `AUDIT_EVENTS = (\n    'a',\n    'b',\n)` → 码清单（纯函数：入参是源码文本，好自证）。
 * CRLF 与 LF 都认：本机工作树实测 `.py` 是 CRLF（`git config core.autocrlf` = true），
 * CI 的 checkout 是 LF，而 `$` 锚点会被夹在中间的 `\r` 顶掉 —— 只认一种制式的那一侧，
 * 绊线在另一台机器上会恒绿。
 * 逐行硬要求「一个单引号码 + 逗号」，出现别的行形（注释挤进块里、改成单行写法）当场抛：
 * 静默少刮一个码等于把绊线改松，方向反了。
 */
function extractEventCodes(src: string): string[] {
  const block = /^AUDIT_EVENTS = \(\r?\n([\s\S]*?)^\)/m.exec(src)
  if (!block) throw new Error(`${AUDIT_PY}: 找不到 AUDIT_EVENTS 那个块（块首必须顶格、每项独占一行）`)
  const lines = block[1].split(/\r?\n/).filter((l) => l.trim() !== '')
  if (!lines.length) throw new Error(`${AUDIT_PY}: AUDIT_EVENTS 块是空的，绊线两边会同时变空集合`)
  return lines.map((l) => {
    const m = /^'([a-z_]+)',$/.exec(l.trim())
    if (!m) throw new Error(`${AUDIT_PY}: AUDIT_EVENTS 块里出现不认识的行 ${JSON.stringify(l)}，刮取器会漏码`)
    return m[1]
  })
}

/** 顶层整数常量 `NAME = 123`（只认顶格：缩进里的那个是别的东西的副本）；抓不到就抛，理由同上。 */
function extractIntConst(src: string, name: string, file: string): number {
  const m = new RegExp(`^${name} = (\\d+)\\r?$`, 'm').exec(src)
  if (!m) throw new Error(`${file}: 找不到形如「${name} = 整数」的顶层常量`)
  return Number(m[1])
}

/** username 快照列宽只认模型字段：`audit.py` 的 `USERNAME_MAX_LENGTH` 是它的派生值，刮派生值等于抄两份。 */
function extractColumnWidth(src: string, column: string, file: string): number {
  const m = new RegExp(`^[ \\t]*${column} = models\\.CharField\\(max_length=(\\d+)`, 'm').exec(src)
  if (!m) throw new Error(`${file}: 找不到形如「${column} = models.CharField(max_length=N」的字段定义`)
  return Number(m[1])
}

/**
 * `AuditEventListView` 那段类体里所有 `params.get('名'` → 这个端点**真读**的查询参数名。
 *
 * 只刮这个类体，不刮整份 `views.py`：别的视图也读 `query_params`（`search`/`type`/`ordering`
 * 那些），整份一起刮会把「本端点收哪些名」宽成一个谁都不看的集合，后端把 `date_from` 改成
 * `from_date` 也照样在集合外面——方向反了。类体切到下一个顶格 `class` 或文件末尾。
 * 找不到类、或一个名字都没刮到，一律抛：返回空集合等于让下面那条双向判线恒绿，同 `extractEventCodes`。
 */
function extractAuditParamNames(src: string): string[] {
  const start = src.search(/^class AuditEventListView\b/m)
  if (start < 0) throw new Error(`${VIEWS_PY}: 找不到顶格的 class AuditEventListView，参数名绊线没有比对对象`)
  const rest = src.slice(start + 1)
  const next = rest.search(/^class /m)
  const body = next < 0 ? rest : rest.slice(0, next)
  const names = [...new Set([...body.matchAll(/params\.get\('([a-z_]+)'/g)].map((m) => m[1]))]
  if (!names.length) throw new Error(`${VIEWS_PY}: AuditEventListView 类体里一个 params.get('名') 都没刮到`)
  return names
}

/**
 * 刮取都在用例**内部**调用，绝不在模块顶层跑：顶层抛错会让 vitest 把整个文件报成一次
 * 收集失败（整文件 0 例），而 house style 是「读源码可以顶层，判定必须在 it 里」
 * （`portWiring.spec.ts` 顶层只 read、parse 在 it 内；`roleLabelHygiene.spec.ts` 连 parse
 * 都在 it 内）。形状变了要红的是**那一条**判据，名字里带着「AUDIT_EVENTS 的块形」这句话。
 */
const backendCodes = () => extractEventCodes(read(AUDIT_PY))
const backendPageSizeDefault = () => extractIntConst(read(VIEWS_PY), 'AUDIT_PAGE_SIZE_DEFAULT', VIEWS_PY)
const backendPageSizeMax = () => extractIntConst(read(VIEWS_PY), 'AUDIT_PAGE_SIZE_MAX', VIEWS_PY)
const backendUsernameWidth = () => extractColumnWidth(read(MODELS_PY), 'actor_username', MODELS_PY)

/** 异源判据：spec §5.2 那十个码与其中文标签，顺序照 audit.py（比较一律先 sort，后端换顺序不该红）。 */
const SPEC_LABELS: Record<string, string> = {
  login_success: '登录成功',
  login_failure: '登录失败',
  account_locked: '账号锁定',
  account_unlocked: '账号解锁',
  password_changed: '自助修改密码',
  password_reset: '管理员重置密码',
  user_created: '创建账号',
  user_updated: '更新账号',
  user_deleted: '删除账号',
  system_paths_changed: '存储路径变更',
}

/** 异源判据：spec §6 那两个分页数 + spec §5.1 的 username 列宽。 */
const SPEC_NUMBERS = { pageSizeDefault: 50, pageSizeMax: 100, usernameWidth: 150 }

/** 异源判据：spec §6 那张参数表里本端点自己读的五个名字（分页自带的 `page` 不在源码里，另说）。 */
const SPEC_PARAM_NAMES = ['date_from', 'date_to', 'event', 'page_size', 'username']

/**
 * 摘要判据所站的六个 detail 形状：键与嵌套逐条从写路径的 `detail=` 抄来，值取夹具。
 * 同一码在不同分支上形状不同时只取一形（`login_failure` 有四种，这里用 `bad_password` 那形）。
 * 剩下四个码不在这张表里：`login_success`/`password_changed`/`account_unlocked` 根本不写
 * detail（`audit._insert` 兜成 `{}`，摘要给占位符），`system_paths_changed` 那份「前后两串
 * 路径 + 布尔」最长，单独钉在下面那条 120 预算用例里。
 */
const REAL_DETAILS: Record<string, Record<string, unknown>> = {
  login_failure: { reason: 'bad_password', remaining_attempts: 3 },
  account_locked: { retry_after_minutes: 15, locked_until: '2026-11-10T09:12:31+08:00' },
  password_reset: { lockout_cleared: true },
  user_created: { role: 'user', is_active: true },
  user_updated: { changed_fields: ['is_active', 'role'], values: { is_active: false, role: 'administrator' } },
  user_deleted: { role: 'administrator' },
}

describe('审计事件标签', () => {
  it('标签表逐字等于规格那十对：键与中文都是判据', () => {
    expect(AUDIT_EVENT_LABELS).toEqual(SPEC_LABELS)
  })

  it('与后端 AUDIT_EVENTS 双向同集合，并报出动的是哪一侧', () => {
    const codes = backendCodes()
    const extra = Object.keys(AUDIT_EVENT_LABELS).filter((c) => !codes.includes(c))
    const missing = codes.filter((c) => !Object.hasOwn(AUDIT_EVENT_LABELS, c))
    // 两条各管一个方向，合起来就是同集合，不需要第三条「排序后逐字相等」。
    expect(extra, `标签表写了后端不会产生的码 ${extra.join('/')}：后端删过事件码，改标签表，本测试不用动`).toEqual([])
    expect(missing, `后端加了 ${missing.join('/')} 而标签表没跟上：audit.py 加码必须同时补这里`).toEqual([])
  })

  it('每个码经 auditEventLabel 给出的还是那句中文（查表通路本身也要过一遍）', () => {
    for (const code of Object.keys(SPEC_LABELS)) {
      expect(auditEventLabel(code), `auditEventLabel('${code}')`).toBe(SPEC_LABELS[code])
    }
  })

  it('没登记过的码回退原码本身、不抛错（旧行：迁移前写入的、或码名写错被记录下来的）', () => {
    // 后面三个是原型名：查表若走 `labels[event] ?? event`，`'toString'` 会从原型上取到一个
    // Function 并原样递回（`??` 只挡 null/undefined），页面就把「function toString(){…}」
    // 显示成事件名。后端对未登记的码只留 warning、不拒写，所以这种字符串真会进表。
    for (const code of ['legacy_token_login', 'user_renamed', 'LOGIN_SUCCESS', '',
                        'toString', 'constructor', '__proto__']) {
      const label = auditEventLabel(code)
      expect(typeof label, `auditEventLabel(${JSON.stringify(code)}) 的类型`).toBe('string')
      expect(label, `auditEventLabel(${JSON.stringify(code)})`).toBe(code)
    }
  })
})

describe('defaultAuditFilters：一页进来的样子', () => {
  it('条件全空、页码 1、每页条数取后端默认', () => {
    expect(defaultAuditFilters()).toEqual({
      event: '', username: '', dateFrom: '', dateTo: '',
      page: 1, pageSize: SPEC_NUMBERS.pageSizeDefault,
    })
  })

  it('每次调用给出新对象（Task 11 要把它塞进 ref 里改，共享一份就得互相踩）', () => {
    const a = defaultAuditFilters()
    a.username = 'admin'
    expect(defaultAuditFilters().username).toBe('')
  })
})

describe('buildAuditQuery：只发后端接受的东西', () => {
  it('空筛选只发分页两键', () => {
    expect(buildAuditQuery(defaultAuditFilters())).toEqual({ page: 1, page_size: 50 })
  })

  it('只发非空条件；纯空白的 username / event 都不算条件', () => {
    const q = buildAuditQuery({
      ...defaultAuditFilters(),
      event: 'password_reset', username: '  ', dateFrom: '2026-11-01', dateTo: '',
    })
    expect(q).toEqual({ event: 'password_reset', date_from: '2026-11-01', page: 1, page_size: 50 })
    // event 与 username 同一口径：Task 11 的下拉给不出空白值，但「空白 event 递给后端」换到的
    // 是一句 400（后端只认 AUDIT_EVENTS 里那十个），所以这里也先去空格再决定发不发。
    expect(buildAuditQuery({ ...defaultAuditFilters(), event: '  ' })).toEqual({ page: 1, page_size: 50 })
  })

  it('username 去掉首尾空格再发（后端 icontains 不会替你去，粘来的名字带个空格就搜不到）', () => {
    expect(buildAuditQuery({ ...defaultAuditFilters(), username: '  admin \t' }).username).toBe('admin')
  })

  it('日期：完整的补零后发，真半截的不发 —— 静默丢条件比 400 坏得多', () => {
    // 后端 `strptime('%Y-%m-%d')` 现量收得下 `2026-1-5` 这种不补零的写法，所以「前端线更严」
    // 不等于「后端会拒」：更严的那一侧自己把条件吞掉，用户拿到的是一份看着像全量的行集，
    // 而这正是本文件对超长 username 拒绝「悄悄截一半」的同一个理由。
    const canonical: Array<[string, string]> = [
      ['2026-11-09', '2026-11-09'],
      ['2026-11-1', '2026-11-01'],
      ['2026-1-5', '2026-01-05'],
      ['2026-11-09 ', '2026-11-09'],
    ]
    for (const [raw, want] of canonical) {
      expect(buildAuditQuery({ ...defaultAuditFilters(), dateFrom: raw }).date_from, `dateFrom=${JSON.stringify(raw)}`).toBe(want)
      expect(buildAuditQuery({ ...defaultAuditFilters(), dateTo: raw }).date_to, `dateTo=${JSON.stringify(raw)}`).toBe(want)
    }
    // 只有缺位的（没有日、写成 ISO/斜杠、空白）才不发：那种输入连「哪一天」都没说完。
    for (const raw of ['', '   ', '2026-11', '11-09', '2026/11/09', '20261109', '2026-11-09T00']) {
      expect(buildAuditQuery({ ...defaultAuditFilters(), dateFrom: raw }).date_from, `dateFrom=${JSON.stringify(raw)}`).toBeUndefined()
      expect(buildAuditQuery({ ...defaultAuditFilters(), dateTo: raw }).date_to, `dateTo=${JSON.stringify(raw)}`).toBeUndefined()
    }
  })

  it('日期只校验形状不校验历法：2 月 30 日照发，让后端那句 400 当唯一一道闸', () => {
    // 前端再造一遍日历就是第二份历法实现，两份不一致时坏的方向是「后端收得下的日期被前端吞掉」，
    // 用户在页面上看着日期填对了却查不到东西。后端判据：test_audit_api.py::BadParamTests。
    expect(buildAuditQuery({ ...defaultAuditFilters(), dateFrom: '2026-02-30' }).date_from).toBe('2026-02-30')
  })

  it('页码：下限 1、向下取整、非有限数回落 1（后端把非法页码判成 404，不是 400）', () => {
    const page = (raw: number) => buildAuditQuery({ ...defaultAuditFilters(), page: raw }).page
    for (const [raw, want] of [[1, 1], [3, 3], [0, 1], [-7, 1], [2.7, 2], [NaN, 1], [Infinity, 1]] as const) {
      expect(page(raw), `page=${raw}`).toBe(want)
    }
  })

  it('page_size 无论填什么都落在后端接受域内 —— 超限夹到上限、非法回落默认，绝不原样递给 400', () => {
    const max = backendPageSizeMax()
    const size = (raw: number) => buildAuditQuery({ ...defaultAuditFilters(), pageSize: raw }).page_size
    const cases: Array<[number, number]> = [
      [50, 50], [1, 1], [100, 100],
      [101, SPEC_NUMBERS.pageSizeMax], [9999, SPEC_NUMBERS.pageSizeMax], [-5, 1], [0, 1],
      [2.5, 2], [NaN, SPEC_NUMBERS.pageSizeDefault], [Infinity, SPEC_NUMBERS.pageSizeDefault],
    ]
    for (const [raw, want] of cases) expect(size(raw), `pageSize=${raw}`).toBe(want)
    // 上面那张表逐条钉「为什么是这个值」，这条钉恒等式：任何输入都出不了那道闸。
    // 上界取 backendPageSizeMax()（刮来的）而不是 SPEC_NUMBERS（抄来的）：后端哪天把上限挪小，
    // 这条要在「前端夹出来的值」本身上红，而不是只红在副本比对上。
    for (const [raw] of cases) {
      const sent = Number(size(raw))
      expect(Number.isInteger(sent), `pageSize=${raw} 发出的不是整数：后端 int() 会 400`).toBe(true)
      expect(sent, `pageSize=${raw} 发出的值出界：后端判 400`).toBeGreaterThanOrEqual(1)
      expect(sent, `pageSize=${raw} 发出的值出界：后端判 400`).toBeLessThanOrEqual(max)
    }
  })

  it('超长的 username 原样发出，前端不截：截出来的是一份看着合理的假答案集', () => {
    // 库里存的快照本身截到列宽，所以超长搜索词谁都匹配不到；前端截到列宽再发就把「什么都没有」
    // 换成「那个前缀匹配到的那些行」，取证页上这是谎。后端那句 400 才是老实的回答。
    const long = 'x'.repeat(backendUsernameWidth() + 1)
    expect(buildAuditQuery({ ...defaultAuditFilters(), username: long }).username).toBe(long)
  })
})

describe('summarizeDetail：表格单行的摘要', () => {
  it('空 detail、null、非对象、数组一律给占位符（detail 是 JSONField default=dict，数组属于越界形状）', () => {
    for (const raw of [{}, null, undefined, 'x', 5, [], [{ a: 1 }], true]) {
      expect(summarizeDetail(raw), `summarizeDetail(${JSON.stringify(raw)})`).toBe('—')
    }
  })

  it('后端真实写进去的六种 detail 各钉一句', () => {
    expect(summarizeDetail(REAL_DETAILS.login_failure)).toBe('reason=bad_password，remaining_attempts=3')
    expect(summarizeDetail(REAL_DETAILS.account_locked)).toBe('retry_after_minutes=15，locked_until=2026-11-10T09:12:31+08:00')
    expect(summarizeDetail(REAL_DETAILS.password_reset)).toBe('lockout_cleared=true')
    expect(summarizeDetail(REAL_DETAILS.user_created)).toBe('role=user，is_active=true')
    expect(summarizeDetail(REAL_DETAILS.user_updated)).toBe('changed_fields=is_active/role，values={"is_active":false,"role":"administrator"}')
    expect(summarizeDetail(REAL_DETAILS.user_deleted)).toBe('role=administrator')
  })

  it('null / undefined 写成「空」而不是 null：审计页给管理员看的，不是给 JSON 看的', () => {
    expect(summarizeDetail({ data_dir: null, temp_dir: undefined })).toBe('data_dir=空，temp_dir=空')
  })

  it('空数组写成「空」：changed_fields=[] 渲染成 key= 看着像渲染坏了', () => {
    expect(summarizeDetail({ changed_fields: [] })).toBe('changed_fields=空')
  })

  it('键名命中口令启发式的一律只留键名，且包含误伤在内也照打（宁可少看一个计数，不可多看一个口令）', () => {
    expect(summarizeDetail({ password: 'secret123', new_password: 'secret123' })).toBe('password=•••，new_password=•••')
    expect(summarizeDetail({ bypass_count: 3, tokens_used: 12 })).toBe('bypass_count=•••，tokens_used=•••')
  })

  it('打码递归进嵌套：user_updated 的 detail 有嵌套 values，序列化器哪天多个可写口令字段就落在这里', () => {
    const text = summarizeDetail({ changed_fields: ['role'], values: { password: 'secret123' } })
    expect(text).not.toContain('secret123')
    expect(text).toBe('changed_fields=role，values={"password":"•••"}')
    expect(summarizeDetail({ a: { b: { c: { pass_hash: 'secret123' } } } })).toBe('a={"b":{"c":{"pass_hash":"•••"}}}')
    expect(summarizeDetail({ list: [{ token: 'secret123' }, { role: 'user' }] })).toBe('list={"token":"•••"}/{"role":"user"}')
    // changed_fields 装的是字段名而不是值：对字段名打码会把「有人改过 password」这件正是要取证的事抹掉。
    expect(summarizeDetail({ changed_fields: ['password'] })).toBe('changed_fields=password')
  })

  it('键名启发式抓不住「值里含口令而键名不含」：把边界钉住，别让它假装自己是防线', () => {
    // 真正的闸是后端：写入侧白名单 views.py 的 AUDITABLE_FIELDS 按构造排除口令字段，
    // detail 因此压根不该出现口令值。本函数是第二道兜底，只认键名。
    expect(summarizeDetail({ note: '重置为 secret123' })).toBe('note=重置为 secret123')
  })

  it('嵌套值不可 JSON 化（循环引用）时不抛错，给一个省略号', () => {
    const circular: Record<string, unknown> = {}
    circular.self = circular
    expect(() => summarizeDetail(circular)).not.toThrow()
    expect(summarizeDetail(circular)).toBe('self=…')
  })

  it('120 字预算的边界：120 原样、121 起截到正好 120 并以 … 收尾，前面的键一个不少', () => {
    const at = summarizeDetail({ a: 'x'.repeat(118) })
    const over = summarizeDetail({ a: 'x'.repeat(119) })
    expect(at).toBe(`a=${'x'.repeat(118)}`)
    expect(at.length).toBe(120)
    expect(over.length).toBe(120)
    expect(over.endsWith('…'), '截断必须留标记：静默砍尾等于把数据藏起来').toBe(true)
    expect(over).toBe(`a=${'x'.repeat(117)}…`)
    const twoKeys = summarizeDetail({ first_key: '甲'.repeat(60), second_key: '乙'.repeat(60) })
    expect(twoKeys.length).toBe(120)
    expect(twoKeys.startsWith('first_key=甲'), '截断只砍尾巴：靠前的键不许整个消失').toBe(true)
  })

  it('最长的一行真实 detail（system_paths_changed 带前后两串 Windows 路径）的摘要是一个已知串', () => {
    const detail = {
      before: { data_dir: 'C:\\Users\\Administrator\\LQ-DataPrase', temp_dir: null },
      after: {
        data_dir: 'C:\\Users\\Administrator\\LQ-DataPrase',
        temp_dir: 'C:\\Users\\Administrator\\LQ-DataPrase\\tmp',
      },
      restart_required: true,
    }
    expect(summarizeDetail(detail)).toBe(
      'before={"data_dir":"C:\\\\Users\\\\Administrator\\\\LQ-DataPrase","temp_dir":null}，a'
      + 'fter={"data_dir":"C:\\\\Users\\\\Administrato…',
    )
  })
})

describe('与后端参数名同源：名字错一位，后端就当这个条件没填', () => {
  /** 填满 / 半截日期 / 空白三种输入各发一次，收集前端可能发出的键名全集（从实现取，不抄字面量）。 */
  const emittedNames = (): string[] => {
    const filled = {
      event: 'login_success', username: 'flt-admin',
      dateFrom: '2026-11-01', dateTo: '2026-11-09', page: 2, pageSize: 50,
    }
    const cases = [
      defaultAuditFilters(),
      filled,
      { ...filled, dateFrom: '2026-11-1', dateTo: '' },
      { ...filled, event: '   ', username: '' },
    ]
    const seen = new Set<string>()
    for (const f of cases) for (const k of Object.keys(buildAuditQuery(f))) seen.add(k)
    return [...seen].sort()
  }

  it('前端发得出的名字后端逐个真读，后端真读的名字前端也一个不发漏（DRF 对不认识的参数静默忽略）', () => {
    const emitted = emittedNames()
    // `page` 由 PageNumberPagination 自己读（`page_query_param` 的默认名），类体里不会出现
    // `params.get('page')`，所以只能点名交进去；它改名的判据在 T1：
    // `test_audit_api.py::PaginationTests` 的整页走查发的就是 `?page=N`。
    const backendAccepts = [...new Set([...extractAuditParamNames(read(VIEWS_PY)), 'page'])].sort()
    // 整份相等就是双向判据：前端多发一个后端读不到的名字 ⇒ 红；后端新加一个名字而筛选栏没跟上 ⇒ 也红。
    expect(emitted, `名字两边对不上：前端发 ${emitted.join('/')}，后端 AuditEventListView 读 ${backendAccepts.join('/')}（前者 = 那份条件被静默忽略）`).toEqual(backendAccepts)
  })
})

describe('与后端数字同源：前端那三份副本必须与源码一致', () => {
  it('分页两数与 username 列宽逐字等于 spec，也逐字等于后端源码刮来的值', () => {
    const pageSizeDefault = backendPageSizeDefault()
    const pageSizeMax = backendPageSizeMax()
    const usernameWidth = backendUsernameWidth()
    expect(SPEC_NUMBERS).toEqual({ pageSizeDefault, pageSizeMax, usernameWidth })
    expect(AUDIT_PAGE_SIZE_DEFAULT).toBe(pageSizeDefault)
    expect(AUDIT_PAGE_SIZE_MAX).toBe(pageSizeMax)
    expect(USERNAME_QUERY_MAX).toBe(usernameWidth)
  })

  it('后端自己那两个数也得自洽：默认值必须落在它自己声明的接受域里（否则夹到上限也是 400）', () => {
    const dflt = backendPageSizeDefault()
    expect(dflt).toBeGreaterThanOrEqual(1)
    expect(dflt).toBeLessThanOrEqual(backendPageSizeMax())
  })
})

describe('抽取器自证（否则上面的双向绊线是在比空集合）', () => {
  const BLOCK = (codes: string[]) => `AUDIT_EVENTS = (\n${codes.map((c) => `    '${c}',`).join('\n')}\n)\n`

  it('真实源码刮得出十码，且与异源那张表的键同集合', () => {
    expect([...backendCodes()].sort()).toEqual(Object.keys(SPEC_LABELS).sort())
  })

  it('后端加一个码，刮取器就得刮到第十一个（绊线会红的前提是它看得见）', () => {
    const mutated = extractEventCodes(BLOCK([...Object.keys(SPEC_LABELS), 'api_token_created']))
    expect(mutated).toHaveLength(Object.keys(SPEC_LABELS).length + 1)
    expect(mutated.filter((c) => !Object.hasOwn(SPEC_LABELS, c))).toEqual(['api_token_created'])
  })

  it('块里挤进注释、改成单行写法、块不在、块是空的，四种都当场抛而不是安静少刮', () => {
    expect(() => extractEventCodes(BLOCK(['login_success', '旧码：迁移前写入'])))
      .toThrow(/不认识的行/)
    expect(() => extractEventCodes('AUDIT_EVENTS = (\n)\n'))
      .toThrow(/是空的/)
    expect(() => extractEventCodes("AUDIT_EVENTS = ('login_success', 'login_failure')\n"))
      .toThrow(/找不到/)
    expect(() => extractEventCodes('AUDIT_EVENTS: tuple = tuple(x for x in y)\n'))
      .toThrow(/找不到/)
    expect(() => extractIntConst('PAGE_SIZE_MAX = "100"\n', 'PAGE_SIZE_MAX', 'x.py')).toThrow(/找不到/)
    expect(() => extractIntConst('    AUDIT_PAGE_SIZE_MAX = 100\n', 'AUDIT_PAGE_SIZE_MAX', 'x.py'))
      .toThrow(/找不到/)
    expect(() => extractColumnWidth('actor = models.IntegerField()', 'actor_username', 'x.py'))
      .toThrow(/找不到/)
  })

  it('参数名刮取：真实 views.py 刮出的就是 spec §6 那五个，且只刮本端点那段类体', () => {
    expect([...extractAuditParamNames(read(VIEWS_PY))].sort()).toEqual(SPEC_PARAM_NAMES)
    const snippet = [
      'class AuditEventListView(ListAPIView):',
      '    def get_queryset(self):',
      '        params = self.request.query_params',
      "        event = params.get('event', '')",
      "        date_from = _parse_day_bound(params.get('date_from', ''))",
      '',
      'class DataFileListView(ListAPIView):',
      '    def get_queryset(self):',
      "        params = self.request.query_params",
      "        qs = qs.filter(name__icontains=params.get('search', ''))",
      '',
    ].join('\n')
    // 下一个类读的 `search` 不许算进本端点的接受域：宽集合会让「前端多发了一个没人读的名字」恒绿。
    expect(extractAuditParamNames(snippet)).toEqual(['event', 'date_from'])
    const renamed = snippet.replace("params.get('date_from'", "params.get('from_date'")
    expect(extractAuditParamNames(renamed)).toEqual(['event', 'from_date'])
    expect(() => extractAuditParamNames('class OtherView(View):\n    pass\n')).toThrow(/找不到顶格的 class AuditEventListView/)
    expect(() => extractAuditParamNames('class AuditEventListView(View):\n    queryset = None\n')).toThrow(/一个 params\.get/)
  })

  it('同一份源码换 CRLF 写法，刮出来的码与数一个不少（判据不许只在某一种检出制式上成立）', () => {
    const lf = BLOCK(Object.keys(SPEC_LABELS))
    const crlf = lf.replace(/\n/g, '\r\n')
    expect(extractEventCodes(crlf)).toEqual(extractEventCodes(lf))
    expect(extractEventCodes(crlf)).toHaveLength(Object.keys(SPEC_LABELS).length)
    expect(extractIntConst('AUDIT_PAGE_SIZE_MAX = 100\r\n', 'AUDIT_PAGE_SIZE_MAX', 'x')).toBe(100)
    expect(extractColumnWidth('    actor_username = models.CharField(max_length=150)\r\n', 'actor_username', 'x')).toBe(150)
  })
})

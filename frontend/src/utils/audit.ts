/**
 * 审计页（Task 11）的三件纯逻辑：事件标签、筛选转 query、detail 单行摘要。
 *
 * 事件码清单住在后端 `apps/accounts/audit.py` 的 `AUDIT_EVENTS`，分页边界与查询参数名住在
 * `apps/accounts/views.py`，username 快照列宽住在 `apps/accounts/models.py`。跨语言没有
 * 共享类型，下面这几份数字与标签就是**第二副本**，而副本不会自己保鲜：保鲜由
 * `test/unit/audit.spec.ts` 刮那三份源码来钉（后端挪一个数、加一个码、改一个参数名而这里
 * 没跟上就红）。别把「反正测试会红」当成免改理由——红的是判据，产品文案仍然贴着旧标签。
 */

export const AUDIT_EVENT_LABELS: Record<string, string> = {
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

/** 事件码的唯一清单在后端；这里只抄它管得着的三件事：码、中文标签、未知码怎么显示。
 *  查表必须走 own-property：`AUDIT_EVENT_LABELS['toString']` 会从原型上取到一个 Function，
 *  而 `??` 只挡 null/undefined —— 未登记的码（后端只留 warning、不拒写，所以它真会进表）
 *  若撞上原型名，页面就会把「function toString(){…}」当事件名显示出来。 */
export const auditEventLabel = (event: string): string =>
  Object.hasOwn(AUDIT_EVENT_LABELS, event) ? AUDIT_EVENT_LABELS[event] : event

/**
 * 表单里的日期两格：EP 的 date-picker 清空时交回的是 `null` 而不是空串，所以契约里就得让它可为
 * null —— 可空性在纯层收口，组件不再自己维护第二份「页面态」类型，也不再有个 `queryFilters()`
 * 把 null 折成 `''`：那一层是第三次拷贝，折叠写漏一格的症状不是报错，而是 `null.trim()` 抛在
 * `load()` 的 try 里被 catch 咽掉（判据见 test/unit/audit.spec.ts 的 null 腿）。
 *
 * 三件控件清空时给的回执**不一样**（逐条对着本仓装的 element-plus 2.14.0 源码量过，别照官方
 * 文档想当然）：`el-input` 交回 `''`（input.vue_…_lang.mjs:302-307 的 `clear()`），
 * `el-date-picker` 交回 `null`（time-picker/src/common/picker.vue_…_lang.mjs:47 给
 * `useEmptyValues(props, null)`、:161-167 的 `onClear` 走 `emitInput(该值)`，而
 * use-common-picker.mjs:17-23 的 `emitInput` 对假值「不套 valueFormat、原样发出」；单选日期
 * 那一侧的 panel-date-pick 没有注册 `handleClear`，所以没有另一条通路），
 * `el-select`（单选、clearable）交回的既不是 `''` 也不是 `null`，而是 **`undefined`**
 * （select/src/useSelect.mjs:315-321 的 `deleteSelected` 发的是 `valueOnClear.value`，而 :60
 * 调的是 `useEmptyValues(props)` —— 没给默认值，hooks/use-empty-values/index.mjs:48-54 一路落空
 * 就返回 `undefined`）。这就是 `event` 与两格日期同为「可空」、`username` 却是 `string` 的理由；
 * 纯层那把 `trimText` 对三种都收口，别指望组件里的 v-model 替我们分辨。
 */
export interface AuditFilters {
  event: string | null | undefined
  username: string
  dateFrom: string | null
  dateTo: string | null
  page: number
  pageSize: number
}

/** `views.py` 的 `AUDIT_PAGE_SIZE_DEFAULT` / `AUDIT_PAGE_SIZE_MAX`：接受域是 1–100，超限是 400 而不是静默夹。 */
export const AUDIT_PAGE_SIZE_DEFAULT = 50
export const AUDIT_PAGE_SIZE_MAX = 100

/**
 * `models.py` 的 `actor_username.max_length`（后端 `audit.USERNAME_MAX_LENGTH` 由它现推）。
 * 本模块只把它交给 Task 11 当输入框的 maxlength：搜索词本身不许长到后端收不下，
 * 而不是在转 query 时悄悄截——库里存的快照就截到这个宽度，截半句再搜会得到
 * 「前缀能匹配上的那些行」，在取证页上这是一份看着合理的假答案。
 */
export const USERNAME_QUERY_MAX = 150

/** 表格一格里只放一行：120 是给「不折行、不撑破列宽」定的预算，看全量交给展开行的裸 JSON。
 *  这里的按键名打码只是摘要那一行的第二道兜底；裸 JSON 敢摆上界面靠的是**写路径**那道闸：
 *  test/unit/audit.spec.ts 的 detail 键名 describe 刮每个 detail= 的任意深度键名，命中启发式即在 T2 红。 */
const DETAIL_SUMMARY_MAX = 120

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
/** 后端 `strptime('%Y-%m-%d')` 连 `2026-1-5` 都收（现量），只认两位是前端的线，不是后端的。 */
const LOOSE_DATE_RE = /^(\d{4})-(\d{1,2})-(\d{1,2})$/

/**
 * 文本条件的收口：三件控件清空后交回的形状不一样（`''` / `null` / `undefined`，逐条见
 * `AuditFilters` 上面那段），纯层一律收成「空串 = 不发这个条件」。
 * 不在这里区分 null 与 undefined：区分了也没事可做 —— 两种都意味着管理员把那一格清了。
 */
const trimText = (raw: string | null | undefined): string => (raw ?? '').trim()

/**
 * 把日期收成后端线里的 `YYYY-MM-DD`：完整的补零（`2026-1-5` → `2026-01-05`），
 * 真半截的（`2026-11`）与清空后的 `null` 都交回空串 = 不发这个条件。
 * 不这么做的后果不是「后端报 400」而是**静默丢条件**：用户填了 `2026-1-5`，前端不发日期，
 * 于是拿到一份看着像「全部事件」的结果 —— 取证页上一份合理但错的行集，比一个错误提示坏得多。
 */
const normalizeDay = (raw: string | null): string => {
  const value = trimText(raw)
  if (DATE_RE.test(value)) return value
  const m = LOOSE_DATE_RE.exec(value)
  if (!m) return ''
  return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`
}

/** 键名启发式（不是内容扫描）：值里含口令而键名不含 pass/token/secret 时抓不住，那道闸在后端白名单。 */
const SECRET_KEY_RE = /pass|token|secret/i

const REDACTED = '•••'
const EMPTY_TEXT = '空'
const ELLIPSIS = '…'
/** 「这一格没东西」的显示值：审计页的空列（操作者、目标、IP）与两个格式化器共用，别在组件里再抄一份。 */
export const AUDIT_PLACEHOLDER = '—'

export const defaultAuditFilters = (): AuditFilters => ({
  event: '',
  username: '',
  dateFrom: '',
  dateTo: '',
  page: 1,
  pageSize: AUDIT_PAGE_SIZE_DEFAULT,
})

/** 非法页码交给 DRF 分页是 404（`NotFound`），所以这里只管把值收成合法整数，不猜「用户想去第几页」。 */
const normalizePage = (page: number): number =>
  Number.isFinite(page) ? Math.max(1, Math.trunc(page)) : 1

/** 夹进后端接受域，而不是回落默认：用户挑 200 条/页时给他 100 条，比发一个必 400 的请求有用。 */
const normalizePageSize = (size: number): number => {
  if (!Number.isFinite(size)) return AUDIT_PAGE_SIZE_DEFAULT
  return Math.min(AUDIT_PAGE_SIZE_MAX, Math.max(1, Math.trunc(size)))
}

export function buildAuditQuery(filters: AuditFilters): Record<string, string | number> {
  const query: Record<string, string | number> = {
    page: normalizePage(filters.page),
    page_size: normalizePageSize(filters.pageSize),
  }
  const event = trimText(filters.event)
  if (event) query.event = event
  const username = trimText(filters.username)
  if (username) query.username = username
  const dateFrom = normalizeDay(filters.dateFrom)
  if (dateFrom) query.date_from = dateFrom
  const dateTo = normalizeDay(filters.dateTo)
  if (dateTo) query.date_to = dateTo
  return query
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return EMPTY_TEXT
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.length ? value.map(renderValue).join('/') : EMPTY_TEXT
  try {
    // replacer 对每一层键都走一遍，所以嵌套的口令字段也一起打码；循环引用在这行抛，交给下面兜住。
    return JSON.stringify(value, (key, nested) => (key && SECRET_KEY_RE.test(key) ? REDACTED : nested))
  } catch {
    return ELLIPSIS
  }
}

/** detail 的单行摘要。后端今天写进去的十个 detail 全是 dict，但那是**调用点**的纪律：
 *  `JSONField(default=dict)` 只管缺省、不约束类型，`audit._insert()` 那句 `detail or {}`
 *  也会照收一个非空的 list —— 所以这里的非对象分支不是「不会走到」。 */
export function summarizeDetail(detail: unknown): string {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return AUDIT_PLACEHOLDER
  const parts = Object.entries(detail).map(([key, value]) =>
    SECRET_KEY_RE.test(key) ? `${key}=${REDACTED}` : `${key}=${renderValue(value)}`,
  )
  if (!parts.length) return AUDIT_PLACEHOLDER
  const text = parts.join('，')
  return text.length > DETAIL_SUMMARY_MAX ? `${text.slice(0, DETAIL_SUMMARY_MAX - 1)}${ELLIPSIS}` : text
}

/**
 * 时间列给到秒：审计页要在同一分钟内区分两笔事件（连续三次登录失败就是这么留下的），
 * 所以不用 utils/format 的 formatTime（那是 MM-DD HH:mm 的短形态，给列表行用）。
 *
 * 走的是**浏览器本地时区**的 getter，与后端那条 `-created_at` 倒序、以及 `_parse_day_bound`
 * 按 `TIME_ZONE` 取的整日边界不是同一根线：本机 dev 的 TZ 与 Django 的 Asia/Shanghai 一致，
 * 所以看着是一回事；把部署机挪到别的时区，日期筛选与这一列就会各说各话。判据见
 * `test/unit/auditFormat.spec.ts`（它把 TZ 钉成 Asia/Shanghai 来量这条线，换机器不用重测）。
 */
export function formatAuditTime(value: string): string {
  if (!value) return AUDIT_PLACEHOLDER
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/**
 * 展开行给的是**未打码**的原始 detail。裸 JSON 敢摆上界面，靠的是后端写路径那道闸：
 * test/unit/audit.spec.ts 刮 apps/accounts/views.py 与 apps/common/views.py 里每个 detail=
 * 字典的**任意深度**键名（整棵树，嵌套键也照样贴出来），断言没有一个命中口令/令牌/密钥启发式
 * （判据在写入侧，不在这里）。
 * 摘要那一行的按键名打码是第二道兜底，管不到这一格 —— 别把它当成已经打码了。
 */
export function auditDetailJson(detail: Record<string, unknown> | null | undefined): string {
  if (!detail || typeof detail !== 'object' || !Object.keys(detail).length) return AUDIT_PLACEHOLDER
  return JSON.stringify(detail, null, 2)
}

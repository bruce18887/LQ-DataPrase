import api from './index'

/**
 * 审计时间线的客户端（`GET /api/v1/auth/audit-events/`，只读）。
 *
 * 下面七个字段名是审计面的**第五份跨语言第二副本**（前四份：事件码、分页两数、
 * username 列宽、查询参数名，都由 `test/unit/audit.spec.ts` 刮后端源码钉住）。
 * 唯一事实来源是 `apps/accounts/serializers.py` 的 `AuditEventSerializer.Meta.fields`，
 * 那份清单改名而这里没跟上时，页面渲染出来的是**空白列**而不是错误 —— 所以那颗绊线
 * 刮的是本文件的 interface 与序列化器两边做双向集合相等，不 import 类型：TS 的类型在
 * 运行时不存在，import 进来的东西没法拿来跟 Python 侧比。
 *
 * `actor` / `target` 两个外键刻意不在响应里（快照列已经带「当时是谁」，外键在账号删掉之后
 * 是 None）；整表 read-only：审计行只由 `apps/accounts/audit.record()` 追加，这里因此
 * 不提供任何写通路。
 */
export interface AuditEventRow {
  id: number
  created_at: string
  event: string
  actor_username: string
  target_username: string
  ip_address: string | null
  detail: Record<string, unknown>
}

/** DRF `PageNumberPagination` 的信封形状（`page_size` 由查询串给，上限见 utils/audit）。 */
export interface AuditPage {
  count: number
  next: string | null
  previous: string | null
  results: AuditEventRow[]
}

export const auditApi = {
  /** 参数由 `utils/audit.buildAuditQuery` 归一化后给出，本层不再加工：
   *  非法值在后端是 400（统一信封）/ 404（非法页码），静默改写会把「填错了」变成「什么都没有」。
   *  `params` 不给默认值 —— 唯一的调用点（AuditLogPage.vue 的 load()）总是递一份归一化后的对象，
   *  默认参数只会让「忘记转 query、直接打全量」这条错路看起来能跑。 */
  listEvents(params: Record<string, string | number>) {
    return api.get<AuditPage>('/auth/audit-events/', { params })
  },
}

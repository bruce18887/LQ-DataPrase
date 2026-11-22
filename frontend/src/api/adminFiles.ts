import api from './index'
import type { FileUsage } from './datafiles'

/**
 * 管理员跨用户只读面（`GET /api/v1/admin/files/users/`）的客户端。
 *
 * 唯一事实来源是 `apps/datafiles/views/admin_usage_views.py` 的返回 dict 与
 * `apps/accounts/permissions.py` 的 `FEATURE_PERMISSIONS['data_view_all']`
 * （只有 administrator）——字段改名而这里没跟上时页面渲染的是空白列而不是错误，
 * 所以形状由 T1 的 `test/backend/test_admin_files_api.py::AdminUserUsageListTests`
 * 逐键钉着（`ROW_FIELDS`），本层不做二次加工、也不吞错误：失败交给 axios 拦截器。
 *
 * `usage` 可能是 `null`：用户名拼不出安全的数据目录时后端**拒绝计算**而不是谎报 0
 * （口径见 storage_usage.py）。页面因此必须把 null 读成「--」。
 */
export interface AdminUserUsage {
  id: number
  username: string
  display_name: string
  role: string
  is_active: boolean
  usage: FileUsage | null
}

export interface AdminUserUsagePage {
  results: AdminUserUsage[]
}

export const adminFilesApi = {
  /** 只列启用账号、按 id 升序（后端钉的次序，前端不重排）。 */
  listUsers() {
    return api.get<AdminUserUsagePage>('/admin/files/users/')
  },
}

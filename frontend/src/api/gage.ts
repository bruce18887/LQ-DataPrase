import api from './index'
import { getExportTimeoutMs } from '../utils/exportTimeout'

/** 槽位分配：site 即槽位编号（S1→1 … S8→8），只导出该工位的数据。 */
export interface GageAssignment {
  file_id: number
  site: number
}

export const gageApi = {
  /** silent：错误消息由调用方解析 Blob 后展示（后端详情比通用提示更具体）。 */
  async generateSummary(assignments: GageAssignment[], onlyBin1?: boolean, ignoreNoLimit?: boolean) {
    // 同 batchApi.generateReport：上限由「导出超时」设置定，不走 api/index.ts 的 30s 默认值。
    const timeout = await getExportTimeoutMs()
    return api.post('/gage/generate_summary/', {
      assignments,
      only_bin1: onlyBin1,
      ignore_no_limit: ignoreNoLimit,
    }, { responseType: 'blob', silent: true, timeout })
  },
}

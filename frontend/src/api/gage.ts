import api from './index'

/** 槽位分配：site 即槽位编号（S1→1 … S8→8），只导出该工位的数据。 */
export interface GageAssignment {
  file_id: number
  site: number
}

export const gageApi = {
  /** silent：错误消息由调用方解析 Blob 后展示（后端详情比通用提示更具体）。 */
  generateSummary(assignments: GageAssignment[], onlyBin1?: boolean, ignoreNoLimit?: boolean) {
    return api.post('/gage/generate_summary/', {
      assignments,
      only_bin1: onlyBin1,
      ignore_no_limit: ignoreNoLimit,
    }, { responseType: 'blob', silent: true })
  },
}

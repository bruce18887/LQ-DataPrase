import api from './index'
import { getExportTimeoutMs } from '../utils/exportTimeout'

export const buyoffApi = {
  identifyCommonItems(fileIds: number[]) {
    return api.post('/buyoff/identify_common_items/', { file_ids: fileIds })
  },
  async generateForm(fileIds: number[], onlyBin1?: boolean, roleMap?: Record<string, number | null>) {
    // 同 batchApi.generateReport：blob 导出的上限由「导出超时」设置定，不走 30s 默认值。
    const timeout = await getExportTimeoutMs()
    return api.post('/buyoff/generate_form/', { file_ids: fileIds, only_bin1: onlyBin1, role_map: roleMap }, { responseType: 'blob', timeout })
  },
}

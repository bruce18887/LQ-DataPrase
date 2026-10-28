import api from './index'
import { getExportTimeoutMs } from '../utils/exportTimeout'

export const batchApi = {
  listBatches() {
    return api.get('/batch-report/list_batches/')
  },
  getBatchYieldData(batchName: string) {
    return api.get('/batch-report/batch_yield_data/', { params: { batch_name: batchName } })
  },
  async generateReport(fileIds: number[]) {
    // 系统设置里的「导出超时」必须真的管住这条：整批报表是全 app 最慢的同步生成之一，
    // 不传就走 api/index.ts 的 30s 默认值 ⇒ 用户把上限调到 600 秒也照样在半路被掐断。
    const timeout = await getExportTimeoutMs()
    return api.post('/batch-report/generate_report/', { file_ids: fileIds }, { responseType: 'blob', timeout })
  },
}

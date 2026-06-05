import api from './index'

export const batchApi = {
  listBatches() {
    return api.get('/batch-report/list_batches/')
  },
  getBatchYieldData(batchName: string) {
    return api.get('/batch-report/batch_yield_data/', { params: { batch_name: batchName } })
  },
  generateReport(fileIds: number[]) {
    return api.post('/batch-report/generate_report/', { file_ids: fileIds }, { responseType: 'blob' })
  },
}

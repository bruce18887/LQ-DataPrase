import api from './index'

export const batchApi = {
  scanDirectory(directory: string) {
    return api.post('/batch-report/scan_directory/', { directory })
  },
  generateReport(fileIds: number[]) {
    return api.post('/batch-report/generate_report/', { file_ids: fileIds }, { responseType: 'blob' })
  },
  importFiles(directory: string) {
    return api.post('/batch-report/import_files/', { directory })
  },
  listBatches() {
    return api.get('/batch-report/list_batches/')
  },
}

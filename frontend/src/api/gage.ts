import api from './index'

export const gageApi = {
  generateSummary(fileIds: number[], onlyBin1?: boolean, ignoreNoLimit?: boolean) {
    return api.post('/gage/generate_summary/', {
      file_ids: fileIds,
      only_bin1: onlyBin1,
      ignore_no_limit: ignoreNoLimit,
    }, { responseType: 'blob' })
  },
}

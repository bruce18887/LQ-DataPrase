import api from './index'

export const buyoffApi = {
  identifyCommonItems(fileIds: number[]) {
    return api.post('/buyoff/identify_common_items/', { file_ids: fileIds })
  },
  generateForm(fileIds: number[], onlyBin1?: boolean) {
    return api.post('/buyoff/generate_form/', { file_ids: fileIds, only_bin1: onlyBin1 }, { responseType: 'blob' })
  },
}

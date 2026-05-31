import api from './index'

export const analysisApi = {
  getDashboard(fileId: number) {
    return api.get('/dashboard/summary/', { params: { file_id: fileId } })
  },
  getHistogram(fileId: number, params: string[]) {
    return api.post('/analysis/histogram/', { file_id: fileId, params })
  },
  getWaferMap(fileId: number, param?: string) {
    return api.post('/analysis/wafer_map/', { file_id: fileId, param })
  },
  getSerialDistribution(fileId: number, param: string) {
    return api.post('/analysis/serial_distribution/', { file_id: fileId, param })
  },
  getCorrelation(fileId: number, paramX: string, paramY: string) {
    return api.post('/analysis/correlation/', { file_id: fileId, param_x: paramX, param_y: paramY })
  },
  getMultiLotData(fileIds: number[], param: string) {
    return api.post('/analysis/multi_lot/', { file_ids: fileIds, param })
  },
  getCorrelationMatrix(fileId: number, params?: string[], method?: string) {
    return api.post('/analysis/correlation_matrix/', {
      file_id: fileId,
      params: params || undefined,
      method: method || 'pearson'
    })
  },
  getBinTrend(fileIds: number[]) {
    return api.post('/analysis/bin_trend/', { file_ids: fileIds })
  },
  getBoxPlot(fileId: number, params: string[], groupBy?: string) {
    return api.post('/analysis/boxplot/', {
      file_id: fileId,
      params,
      group_by: groupBy
    })
  },
  getParamTrend(fileIds: number[], param: string) {
    return api.post('/analysis/param_trend/', {
      file_ids: fileIds,
      param
    })
  },
  getYieldTrend(fileIds: number[]) {
    return api.post('/analysis/yield_trend/', { file_ids: fileIds })
  },
  getQQPlot(fileId: number, param: string) {
    return api.post('/analysis/qqplot/', { file_id: fileId, param })
  },
  getZonalYield(fileId: number, param?: string) {
    return api.post('/analysis/zonal_yield/', { file_id: fileId, param })
  },
  getUph(fileId: number, testTimeCol?: string, manualTestTimeSec?: number) {
    const payload: any = { file_id: fileId }
    if (testTimeCol) payload.test_time_col = testTimeCol
    if (manualTestTimeSec != null) payload.manual_test_time_sec = manualTestTimeSec
    return api.post('/analysis/uph/', payload)
  },
}

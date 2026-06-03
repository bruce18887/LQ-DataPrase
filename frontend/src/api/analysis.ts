import api from './index'

export const analysisApi = {
  getDashboard(fileId: number) {
    return api.get('/summary/', { params: { file_id: fileId } })
  },
  getHistogram(fileId: number, params: string[]) {
    return api.get('/analysis/histogram/', { params: { file_id: fileId, params } })
  },
  getWaferMap(fileId: number, param?: string) {
    return api.get('/analysis/wafer_map/', { params: { file_id: fileId, param } })
  },
  getSerialDistribution(fileId: number, param: string) {
    return api.get('/analysis/serial_distribution/', { params: { file_id: fileId, param } })
  },
  getCorrelation(fileId: number, paramX: string, paramY: string) {
    return api.get('/analysis/correlation/', { params: { file_id: fileId, param_x: paramX, param_y: paramY } })
  },
  getMultiLotData(fileIds: number[], param: string) {
    return api.get('/analysis/multi_lot/', { params: { file_ids: fileIds, param } })
  },
  getCorrelationMatrix(fileId: number, params?: string[], method?: string) {
    const query: Record<string, any> = { file_id: fileId }
    if (params && params.length) query.params = params
    if (method) query.method = method
    return api.get('/analysis/correlation_matrix/', { params: query })
  },
  getBinTrend(fileIds: number[]) {
    return api.get('/analysis/bin_trend/', { params: { file_ids: fileIds } })
  },
  getBoxPlot(fileId: number, params: string[], groupBy?: string) {
    const query: Record<string, any> = { file_id: fileId, params }
    if (groupBy) query.group_by = groupBy
    return api.get('/analysis/boxplot/', { params: query })
  },
  getParamTrend(fileIds: number[], param: string) {
    return api.get('/analysis/param_trend/', { params: { file_ids: fileIds, param } })
  },
  getYieldTrend(fileIds: number[]) {
    return api.get('/analysis/yield_trend/', { params: { file_ids: fileIds } })
  },
  getQQPlot(fileId: number, param: string) {
    return api.get('/analysis/qqplot/', { params: { file_id: fileId, param } })
  },
  getZonalYield(fileId: number, param?: string) {
    return api.get('/analysis/zonal_yield/', { params: { file_id: fileId, param } })
  },
  getUph(fileId: number, testTimeCol?: string, manualTestTimeSec?: number) {
    const query: Record<string, any> = { file_id: fileId }
    if (testTimeCol) query.test_time_col = testTimeCol
    if (manualTestTimeSec != null) query.manual_test_time_sec = manualTestTimeSec
    return api.get('/analysis/uph/', { params: query })
  },
}

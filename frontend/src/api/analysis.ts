import api from './index'

export const analysisApi = {
  getDashboard(fileId: number) {
    return api.get('/summary/', { params: { file_id: fileId } })
  },
  getHistogram(fileId: number, params: string[], iqrMultiplier?: number) {
    const query: Record<string, any> = { file_id: fileId, params }
    if (iqrMultiplier != null) query.iqr_multiplier = iqrMultiplier
    return api.get('/analysis/histogram/', { params: query })
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
    return api.get('/statistics/correlation_matrix/', { params: query })
  },
  getBinTrend(fileIds: number[]) {
    return api.get('/statistics/bin_trend/', { params: { file_ids: fileIds } })
  },
  getBoxPlot(fileId: number, params: string[], groupBy?: string, dataOnlyBin1?: boolean,
             iqrMultiplier?: number) {
    const query: Record<string, any> = { file_id: fileId, params }
    if (groupBy) query.group_by = groupBy
    if (dataOnlyBin1) query.data_only_bin1 = dataOnlyBin1
    // 敏感度（IQR 倍数）：后端箱线图的 whisker 此前写死 1.5*iqr，调敏感度后
    // 同屏直方图/QQ/序列/散点都变了、只有箱线图没变。
    if (iqrMultiplier != null) query.iqr_multiplier = iqrMultiplier
    return api.get('/statistics/boxplot/', { params: query })
  },
  getParamTrend(fileIds: number[], param: string) {
    return api.get('/statistics/param_trend/', { params: { file_ids: fileIds, param } })
  },
  getQQPlot(fileId: number, param: string) {
    return api.get('/analysis/qqplot/', { params: { file_id: fileId, param } })
  },
  getZonalYield(fileId: number, param?: string) {
    return api.get('/statistics/zonal_yield/', { params: { file_id: fileId, param } })
  },
  getUph(fileId: number, testTimeCol?: string, manualTestTimeSec?: number) {
    const query: Record<string, any> = { file_id: fileId }
    if (testTimeCol) query.test_time_col = testTimeCol
    if (manualTestTimeSec != null) query.manual_test_time_sec = manualTestTimeSec
    return api.get('/analysis/uph/', { params: query })
  },
}

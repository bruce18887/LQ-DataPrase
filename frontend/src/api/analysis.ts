import api from './index'

// 仅保留有调用点的 helper：getHistogram/getWaferMap(GET)/getSerialDistribution/
// getCorrelation/getMultiLotData/getCorrelationMatrix/getBinTrend/getParamTrend/
// getQQPlot 全项目 0 调用（页面实际都直接 api.post），且它们走 GET+query 序列化
// 路径，与页面 POST 路径是两套未经验证的契约——单侧改动另一侧不会跟随，属
// 契约漂移温床（2026-09-05 审查 5.8 / 契约#6），删除。
export const analysisApi = {
  getDashboard(fileId: number) {
    return api.get('/summary/', { params: { file_id: fileId } })
  },
  /** 晶圆图主路径：POST 带 color_by（按结果/Site/分区），端点两种方法都收 */
  postWaferMap(payload: Record<string, any>) {
    return api.post('/analysis/wafer_map/', payload)
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

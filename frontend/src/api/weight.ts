import api from './index'
import { getExportTimeoutMs } from '../utils/exportTimeout'
import type { WeightDocDto } from '../pages/weight/weightChartOption'

export interface WeightParseRequest { filename: string; text: string }
export interface WeightExportRequest extends WeightParseRequest {
  visible_group_indexes: number[]
  show_mean: boolean
  palette: string[]
  mean_color: string
}

export const weightApi = {
  parse(body: WeightParseRequest) {
    return api.post<WeightDocDto>('/weight/parse/', body)
  },
  /** silent：解析失败比通用提示更具体（行号在 detail 里），由调用方组织文案。 */
  async export(body: WeightExportRequest) {
    // 这条也是同步出片的接口 ⇒ 归「导出超时」设置管，不走 30s 默认值。
    const timeout = await getExportTimeoutMs()
    return api.post('/weight/export/', body, { responseType: 'blob', silent: true, timeout })
  },
}

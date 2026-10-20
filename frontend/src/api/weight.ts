import api from './index'
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
  export(body: WeightExportRequest) {
    return api.post('/weight/export/', body, { responseType: 'blob', silent: true })
  },
}

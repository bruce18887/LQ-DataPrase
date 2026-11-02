/**
 * 相关性矩阵的参数封顶说明（B2 前端落地）。
 *
 * 后端 `correlation_matrix` 把参数集封顶在 50 个（矩阵是 N×N，格子随参数数平方膨胀），
 * 响应另带 `total_params`（本来要算的全部）与 `truncated`。用户点「全选」时前端选的
 * 远多于 50，卡片上必须说清实际只算了前 50 项，否则看起来像算了全部。
 */

interface CorrelationPayload {
  truncated?: boolean
  total_params?: number
  params?: string[]
}

export function matrixCapSuffix(data?: CorrelationPayload | null): string {
  if (!data?.truncated) return ''
  const { total_params: total, params } = data
  if (typeof total !== 'number' || !Array.isArray(params)) return ''
  return `参数超上限，已按列序取前 ${params.length} 项（本应 ${total} 项）`
}

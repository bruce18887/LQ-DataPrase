import type { AxiosError } from 'axios'

/** 与后端 parser.TEXT_LIMIT 同值：前端先挡是为了「点了立刻有话」，后端那道守卫仍要过（R3②）。 */
export const TEXT_CHAR_LIMIT = 2_000_000

export function describeWeightError(e: unknown): string {
  const err = e as AxiosError<{ code?: string; detail?: any }>
  const d = err?.response?.data
  if (d?.code === 'no_declaration') return '文件里没有找到 double 权重声明'
  if (d?.code === 'weight_length_mismatch' && d.detail)
    return `第 ${d.detail.line} 行 ${d.detail.name}：声明长度 ${d.detail.declared}，实际数值 ${d.detail.actual}`
  if (d?.code === 'weight_bad_number' && d.detail)
    return `第 ${d.detail.line} 行有无法解析的数值「${d.detail.token}」`
  if (d?.code === 'weight_too_large')
    return `文件超出可处理范围（${d.detail?.which ?? ''} 上限 ${d.detail?.limit ?? ''}）`
  return (err?.message ?? '权重文件处理失败')
}

/** 导出 lane 的响应体是 Blob（`responseType:'blob'` + `silent`），先解成 JSON 再复用同一套文案。 */
export async function describeExportError(e: unknown): Promise<string> {
  const err = e as { response?: { data?: unknown } }
  if (err?.response?.data instanceof Blob) {
    try {
      return describeWeightError({ response: { data: JSON.parse(await err.response.data.text()) } })
    } catch {
      return '导出失败，请稍后重试'        // 解不出 JSON 就是真·网络/服务异常
    }
  }
  return describeWeightError(e)
}

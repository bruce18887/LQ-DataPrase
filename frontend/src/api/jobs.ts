/**
 * `/api/v1/jobs/` 客户端：提交、查状态、取文件、取消。
 *
 * 提交这一发**刻意用 arraybuffer** 而不是默认 JSON：后端在进程池建不起来时会降级成
 * 「同一份响应直接回文件流」（`apps/jobs/views.py._sync_fallback`，带
 * `X-Job-Fallback: 1`）。那种响应不是 JSON，用 responseType:'json' 会在解析阶段就抛，
 * 于是桌面档 spawn 失败时用户看到的是「导出报错」而不是「照样下载到了文件」。
 * 这里把两种形态都原样交出去，由 `jobPolling.classifySubmit` 判定走哪条。
 */
import api from './index'

export type JobKind =
  | 'export_excel'
  | 'export_batch_charts'
  | 'export_html_report'
  | 'sftp_download'

export type JobState = 'pending' | 'running' | 'done' | 'error' | 'cancelled'

export interface JobStatus {
  id: number
  kind: JobKind
  status: JobState
  progress: number
  error: string
  result_name: string
  created_at: string
}

export interface SubmitResponse {
  status: number
  /** 202 时是解析好的 JSON；200（同步降级）时是 Blob。 */
  data: unknown
  headers: Record<string, string>
}

/** 文件名解析交给 `utils/download`，这里只负责把字节变成 Blob。 */
export async function submitJob(kind: JobKind, payload: Record<string, unknown>):
  Promise<SubmitResponse> {
  const resp = await api.post(`/jobs/${kind}/`, payload, {
    responseType: 'arraybuffer',
    // 提交必须快：后端只做「校验 + 建行 + 投池」，正常应在 200ms 内返回（方案 §3 验收线）。
    // 这里不给长超时，长超时会把「后端卡住」伪装成「还在导」。
  })
  const contentType = String(resp.headers?.['content-type'] ?? '')
  const body: unknown = contentType.includes('json')
    ? JSON.parse(new TextDecoder('utf-8').decode(new Uint8Array(resp.data as ArrayBuffer)))
    : new Blob([resp.data as ArrayBuffer], { type: contentType || 'application/octet-stream' })
  return { status: resp.status, data: body, headers: resp.headers as Record<string, string> }
}

export async function getJob(id: number): Promise<{ status: number; data: unknown }> {
  try {
    // silent：轮询失败必须只有一条 toast。不标的话拦截器先弹 formatError 那句，
    // pollDecision 判 failed 后 useJobExport 再弹 jobFailureView 那句 —— 两条文案
    // 不同，index.ts 的 2 秒同名去重闸拦不住这种「同义不同字」。
    const resp = await api.get<JobStatus>(`/jobs/${id}/`, { silent: true })
    return { status: resp.status, data: resp.data }
  } catch (err: any) {
    // 轮询期间拿到错误码也要交给判定函数（404 = 作业没了，属于终态，不能继续转）
    return { status: err?.response?.status ?? 0, data: err?.response?.data ?? null }
  }
}

export async function downloadJob(id: number): Promise<{
  data: Blob; headers: Record<string, string>
}> {
  const resp = await api.get(`/jobs/${id}/download/`, {
    responseType: 'blob',
    timeout: 10 * 60 * 1000,
  })
  return { data: resp.data as Blob, headers: resp.headers as Record<string, string> }
}

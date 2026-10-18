/**
 * 作业轮询的**纯决策**：给定「提交响应」或「一次轮询响应」，界面下一步该做什么。
 *
 * 刻意不 import vue / axios：这样它能进 T2（毫秒级）而不是必须开浏览器。
 * 真正的 await/setTimeout 循环在 `useJobExport.ts` 里，那边只负责「什么时候问一次」，
 * 「问到了算什么」全部在这里 —— 判据集中在一处才测得动。
 */

/** 起始轮询间隔（spec §6：1s 起）。 */
export const POLL_BASE_MS = 1000
/** 连续无变化多少次之后降到慢节奏。 */
export const POLL_SLOW_AFTER = 3
/** 慢节奏间隔。 */
export const POLL_SLOW_MS = 2000
/** 轮询上限：超过就放弃等待（spec §6 的 5 分钟），**不许无限轮询**。 */
export const POLL_MAX_MS = 5 * 60 * 1000

export type SubmitVerdict =
  | { kind: 'poll'; jobId: number }
  | { kind: 'sync-fallback' }
  | { kind: 'error'; message: string }

export type PollVerdict =
  | { kind: 'wait'; delay: number; unchangedStreak: number; progress: number }
  | { kind: 'ready'; progress: number; resultName: string }
  | { kind: 'failed'; progress: number; error: string }
  | { kind: 'giveup'; progress: number }

/** 连续无变化 `streak` 次之后该等多久。 */
export function nextPollDelay(streak: number): number {
  const s = Number.isFinite(streak) ? Math.max(0, streak) : 0
  return s > POLL_SLOW_AFTER ? POLL_SLOW_MS : POLL_BASE_MS
}

/**
 * 提交响应怎么解读。
 *
 * 200 是**同步降级**：后端建不起进程池时（PyInstaller 环境异常）会直接在同一份响应里
 * 回文件流并带 `X-Job-Fallback: 1`（`apps/jobs/views.py` 的 `_sync_fallback`）。
 * 把 200 也当作业处理的话，桌面档一旦 spawn 失败就变成「点了没反应」。
 */
export function classifySubmit(resp: { status: number; data: unknown }): SubmitVerdict {
  if (resp.status === 202) {
    const body = (resp.data ?? {}) as Record<string, unknown>
    const jobId = Number(body.job_id)
    if (Number.isFinite(jobId) && jobId > 0) return { kind: 'poll', jobId }
    // 202 却没有 job_id = 后端契约被破坏；当作 id=undefined 去轮询会转满 5 分钟
    return { kind: 'error', message: '作业已提交但没拿到作业号' }
  }
  if (resp.status === 200) return { kind: 'sync-fallback' }
  return { kind: 'error', message: formatJobFailure(resp.data as Record<string, unknown>) }
}

/** 一次轮询响应怎么解读。 */
export function pollDecision(
  resp: { status: number; data: unknown },
  state: { lastProgress: number; unchangedStreak: number; startedAt?: number; now: number },
): PollVerdict {
  // 拿不到状态（404/500/被删）就是终态：进度条继续转只会让人以为还在跑
  if (resp.status !== 200) {
    return { kind: 'failed', progress: state.lastProgress, error: '取不到作业状态' }
  }

  const job = (resp.data ?? {}) as Record<string, unknown>
  const status = String(job.status ?? '')
  const progress = clampPercent(job.progress)

  if (status === 'done') {
    return { kind: 'ready', progress: 100, resultName: String(job.result_name ?? '') }
  }
  if (status === 'error' || status === 'cancelled') {
    return { kind: 'failed', progress, error: formatJobFailure(job) }
  }

  // pending / running / 认不出的状态都继续等，但超过上限必须放弃
  if (state.startedAt !== undefined && state.now - state.startedAt > POLL_MAX_MS) {
    return { kind: 'giveup', progress }
  }
  const unchangedStreak = progress === state.lastProgress ? state.unchangedStreak + 1 : 0
  return { kind: 'wait', delay: nextPollDelay(unchangedStreak), unchangedStreak, progress }
}

/** 失败文案：优先用后端那句人话（重试按钮提示的就是它），没有也不能显示 undefined。 */
export function formatJobFailure(job?: Record<string, unknown> | null): string {
  const backend = job && typeof job.error === 'string' ? job.error.trim() : ''
  if (backend) return backend
  const code = job && typeof job.code === 'string' ? job.code : ''
  return code ? `导出失败（${code}）` : '导出失败'
}

function clampPercent(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}

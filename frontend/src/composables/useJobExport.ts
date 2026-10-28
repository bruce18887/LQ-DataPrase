/**
 * 作业化导出的执行循环：提交 → 轮询 → 下载。
 *
 * 「下一步该做什么」全部委托给 `jobPolling`（纯函数、T2 测），这里只做三件事：
 * 发请求、按判定 sleep、把进度写进 ref 给界面看。
 *
 * 与旧的 `await api.post(..., {responseType:'blob'})` 相比，界面上多出来的只有
 * `progress` 这一个数；文件名的口径没变（仍旧解析 Content-Disposition，
 * 作业路径额外允许用 `job.result_name` 兜底）。
 */
import { onScopeDispose, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { downloadJob, getJob, submitJob, type JobKind } from '../api/jobs'
import { classifySubmit, formatJobFailure, jobFailureView, pollDecision, submitFailureMessage, type JobFailureReason } from './jobPolling'
import {
  downloadBlob,
  extractFilenameFromContentDisposition,
} from '../utils/download'

export interface RunJobOptions {
  /** 失败时不弹全局 toast（调用方自己给文案，沿用旧 axios `silent` 的语义）。 */
  silent?: boolean
  /** 提交失败/作业失败时的额外回调（调用方据此给定制文案）。 */
  onError?: (message: string, reason: JobFailureReason) => void
  /** 轮询到 done 之后、真正下载之前的提示位（批量导出用来计数）。 */
  onDone?: (fileName: string) => void
}

/**
 * 失败原因必须可区分：旧的同步导出只有一种「请求失败」，作业化之后至少三种
 * ——提交就被拒（参数/权限）、作业跑到一半失败、以及前端不再等了（后端还在跑）。
 * 类型定义与「怎么显示」都在 `jobPolling.ts`（纯函数，T2 测得到）。
 */
export interface JobRunResult {
  ok: boolean
  reason?: JobFailureReason
  message?: string
}

export function useJobExport() {
  const exporting = ref(false)
  /** 0–100。同步降级路径不会走到中间值，直接 0 → 100。 */
  const progress = ref(0)
  /** 给界面文案用：排队 / 进行中 / 放弃等待。 */
  const phase = ref<'idle' | 'pending' | 'running' | 'gaveup'>('idle')

  // 组件卸载时必须停轮询：否则旧标签页的请求会继续写这个已销毁实例的 ref
  let stopped = false

  async function sleep(ms: number): Promise<void> {
    if (stopped) return
    await new Promise((resolve) => setTimeout(resolve, ms))
  }

  async function run(kind: JobKind, payload: Record<string, unknown>,
                     options: RunJobOptions = {}): Promise<JobRunResult> {
    exporting.value = true
    progress.value = 0
    phase.value = 'pending'

    /** 统一的失败出口：`silent` 时不弹默认 toast，文案交给调用方（它同样走 `jobFailureView`）。 */
    const fail = (reason: JobFailureReason, message = ''): JobRunResult => {
      const view = jobFailureView(reason, message)
      if (!options.silent) ElMessage[view.level](view.text)
      options.onError?.(view.text, reason)
      return { ok: false, reason, message: view.text }
    }

    try {
      const submit = await submitJob(kind, payload)
      const verdict = classifySubmit(submit)

      if (verdict.kind === 'error') {
        // verdict.message 已是成品文案（classifySubmit 里 202 无 job_id 与
        // formatJobFailure(resp.data) 两条都组好了）。这里原先再套一层
        // formatJobFailure(verdict)，而它只读 verdict.error / verdict.code 两个键 ——
        // SubmitVerdict 的 error 分支根本没这两个键 ⇒ 恒落「导出失败」，后端那句
        // 人话（400 的具体原因）被吞掉。
        return fail('submit-error', submitFailureMessage(verdict))
      }

      if (verdict.kind === 'sync-fallback') {
        // 后端建不起进程池：它已经把文件算好塞进这一份响应里了
        const blob = submit.data as Blob
        const fname = extractFilenameFromContentDisposition(submit.headers?.['content-disposition'])
          ?? `${kind}.${kind === 'export_html_report' ? 'html' : 'xlsx'}`
        downloadBlob(blob, fname)
        progress.value = 100
        options.onDone?.(fname)
        return { ok: true }
      }

      const jobId = verdict.jobId
      const startedAt = Date.now()
      let lastProgress = -1
      let streak = 0

      for (;;) {
        if (stopped) return { ok: false, reason: 'gave-up', message: '页面已切换，停止等待' }
        const now = Date.now()
        const decision = pollDecision(await getJob(jobId), {
          lastProgress, unchangedStreak: streak, startedAt, now,
        })

        if (decision.kind === 'giveup') {
          phase.value = 'gaveup'
          // 不是失败：后端还在跑，只是前端不该无限转圈。文案用默认那句（不提「导出中心」，
          // 前端现在没有那个页面）
          return fail('gave-up')
        }
        if (decision.kind === 'failed') {
          return fail('job-failed', decision.error || formatJobFailure())
        }
        if (decision.kind === 'ready') {
          const file = await downloadJob(jobId)
          const fname = extractFilenameFromContentDisposition(file.headers?.['content-disposition'])
            || (decision.resultName ?? '')
            || `${kind}.xlsx`
          downloadBlob(file.data, fname)
          progress.value = 100
          options.onDone?.(fname)
          return { ok: true }
        }

        progress.value = decision.progress
        phase.value = decision.progress > 0 ? 'running' : 'pending'
        lastProgress = decision.progress
        streak = decision.unchangedStreak
        await sleep(decision.delay)
      }
    } catch (err: any) {
      // 传输层错误：4xx/5xx 的全局 toast 由 axios 拦截器负责（silent 时它也不弹），
      // 这里只保证不卡住按钮态，并把原因交回调用方。
      return fail('download-failed', err?.message ?? '导出失败')
    } finally {
      exporting.value = false
      phase.value = 'idle'
    }
  }

  onScopeDispose(() => { stopped = true })

  return { exporting, progress, phase, run }
}

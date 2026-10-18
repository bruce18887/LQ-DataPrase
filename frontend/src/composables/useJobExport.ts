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
import { classifySubmit, formatJobFailure, pollDecision } from './jobPolling'
import {
  downloadBlob,
  extractFilenameFromContentDisposition,
} from '../utils/download'

export interface RunJobOptions {
  /** 提交失败/作业失败时的额外回调（调用方据此恢复按钮态或提示重选文件）。 */
  onError?: (message: string) => void
  /** 轮询到 done 之后、真正下载之前的提示位（批量导出用来计数）。 */
  onDone?: (fileName: string) => void
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
                     options: RunJobOptions = {}): Promise<boolean> {
    exporting.value = true
    progress.value = 0
    phase.value = 'pending'
    try {
      const submit = await submitJob(kind, payload)
      const verdict = classifySubmit(submit)

      if (verdict.kind === 'error') {
        const message = formatJobFailure(verdict as Record<string, unknown>)
        ElMessage.error(message)
        options.onError?.(message)
        return false
      }

      if (verdict.kind === 'sync-fallback') {
        // 后端建不起进程池：它已经把文件算好塞进这一份响应里了
        const blob = submit.data as Blob
        const fname = extractFilenameFromContentDisposition(submit.headers?.['content-disposition'])
          ?? `${kind}.${kind === 'export_html_report' ? 'html' : 'xlsx'}`
        downloadBlob(blob, fname)
        progress.value = 100
        options.onDone?.(fname)
        return true
      }

      const jobId = verdict.jobId
      const startedAt = Date.now()
      let lastProgress = -1
      let streak = 0

      for (;;) {
        if (stopped) return false
        const now = Date.now()
        const decision = pollDecision(await getJob(jobId), {
          lastProgress, unchangedStreak: streak, startedAt, now,
        })

        if (decision.kind === 'giveup') {
          phase.value = 'gaveup'
          // 不是失败：后端还在跑，只是前端不该 indefinitely 转圈
          ElMessage.info('导出仍在进行，可稍后在导出中心查看结果')
          return false
        }
        if (decision.kind === 'failed') {
          ElMessage.error(decision.error || formatJobFailure())
          options.onError?.(decision.error)
          return false
        }
        if (decision.kind === 'ready') {
          const file = await downloadJob(jobId)
          const fname = extractFilenameFromContentDisposition(file.headers?.['content-disposition'])
            || (decision.resultName ?? '')
            || `${kind}.xlsx`
          downloadBlob(file.data, fname)
          progress.value = 100
          options.onDone?.(fname)
          return true
        }

        progress.value = decision.progress
        phase.value = decision.progress > 0 ? 'running' : 'pending'
        lastProgress = decision.progress
        streak = decision.unchangedStreak
        await sleep(decision.delay)
      }
    } catch (err: any) {
      // 4xx/5xx 的错误 toast 由 axios 拦截器统一弹，这里只保证不卡住按钮态
      const message = err?.message ?? '导出失败'
      options.onError?.(message)
      return false
    } finally {
      exporting.value = false
      phase.value = 'idle'
    }
  }

  onScopeDispose(() => { stopped = true })

  return { exporting, progress, phase, run }
}

/**
 * T2：作业化导出的**轮询决策**（`src/composables/jobPolling.ts`）。
 *
 * 这块必须是纯函数，理由和 clientConfig 一样：它是「后端状态 → 界面行为」的唯一判据，
 * 而它坏了的表现是「进度条永远转 / 悄悄不下载」——那种东西在浏览器里既慢又难断言。
 * T3 只留一条接线证明（点导出→进度→拿到文件），逐状态组合全在这里测。
 *
 * 三条设计口径：
 * 1. **202 才轮询，200 是同步降级**：进程池建不起来时后端直接回文件流
 *    （`apps/jobs/views.py._sync_fallback`，带 `X-Job-Fallback: 1`）。
 *    前端若把 200 也当作业处理，桌面档一旦 spawn 失败就变成「点了没反应」。
 * 2. 节奏按 spec §6：1s 起，连续 3 次进度没变才降到 2s，最长 5 分钟后放弃轮询。
 * 3. `error`/`cancelled` 都是终态，必须停止轮询并把后端文案交出去（重试要用同一份参数重 POST）。
 */
import { describe, expect, it } from 'vitest'

import {
  POLL_BASE_MS,
  POLL_MAX_MS,
  classifySubmit,
  formatJobFailure,
  nextPollDelay,
  pollDecision,
} from '../../src/composables/jobPolling'

describe('nextPollDelay：1s 起，连续 3 次无变化才降到 2s', () => {
  it('前 3 次不变仍然 1s（spec §6 的「连续 3 次」是严格大于）', () => {
    expect(nextPollDelay(0)).toBe(POLL_BASE_MS)
    expect(nextPollDelay(1)).toBe(POLL_BASE_MS)
    expect(nextPollDelay(3)).toBe(POLL_BASE_MS)
  })

  it('第 4 次起降到 2s', () => {
    expect(nextPollDelay(4)).toBe(2000)
    expect(nextPollDelay(10)).toBe(2000)
  })

  it('负数输入不炸（防御：streak 由外部累计，脏值只当 0）', () => {
    expect(nextPollDelay(-5)).toBe(POLL_BASE_MS)
  })
})

describe('classifySubmit：202 轮询 / 200 同步降级 / 其它算失败', () => {
  it('202 带 job_id → 轮询', () => {
    expect(classifySubmit({ status: 202, data: { job_id: 7, status: 'pending' } }))
      .toEqual({ kind: 'poll', jobId: 7 })
  })

  it('202 但没有 job_id → 失败（后端契约被破坏时不许当作 id=undefined 去轮询）', () => {
    expect(classifySubmit({ status: 202, data: {} }).kind).toBe('error')
  })

  it('200 → 同步降级：直接把响应体当文件交给下载，不发第二次请求', () => {
    const r = classifySubmit({ status: 200, data: new Blob(['x']) })
    expect(r.kind).toBe('sync-fallback')
  })

  it('4xx/5xx → 失败', () => {
    for (const status of [400, 401, 404, 409, 500]) {
      expect(classifySubmit({ status, data: { code: 'x' } }).kind).toBe('error')
    }
  })
})

describe('pollDecision：什么时候继续等、什么时候收工', () => {
  const at = (elapsed: number) => ({ now: 1000 + elapsed })

  it('running 且进度前进 → 继续等，streak 归零', () => {
    expect(pollDecision(
      { status: 200, data: { status: 'running', progress: 40, error: '' } },
      { lastProgress: 20, unchangedStreak: 2, ...at(0) },
    )).toEqual({ kind: 'wait', delay: POLL_BASE_MS, unchangedStreak: 0, progress: 40 })
  })

  it('running 且进度不变 → streak+1，节奏按 streak 决定', () => {
    // 整体断言而不是逐个取属性：PollVerdict 是联合类型，取 `d.delay` 会让
    // `vue-tsc -b`（webServer 的 build 会连 test/unit 一起检）直接报错。
    expect(pollDecision(
      { status: 200, data: { status: 'running', progress: 40, error: '' } },
      { lastProgress: 40, unchangedStreak: 3, ...at(0) },
    )).toEqual({ kind: 'wait', delay: 2000, unchangedStreak: 4, progress: 40 })
  })

  it('done → 可以去取文件', () => {
    expect(pollDecision(
      { status: 200, data: { status: 'done', progress: 100, result_name: 'a.xlsx' } },
      { lastProgress: 60, unchangedStreak: 1, ...at(0) },
    )).toEqual({ kind: 'ready', progress: 100, resultName: 'a.xlsx' })
  })

  it('error 与 cancelled 都是终态（进度条不能继续转）', () => {
    for (const status of ['error', 'cancelled']) {
      expect(pollDecision(
        { status: 200, data: { status, progress: 30, error: '进程重启，作业中断' } },
        { lastProgress: 20, unchangedStreak: 0, ...at(0) },
      )).toMatchObject({ kind: 'failed', progress: 30 })
    }
    // 后端那句人话必须原样交出去（重试按钮提示的就是它）
    const failed = pollDecision(
      { status: 200, data: { status: 'error', progress: 30, error: '进程重启，作业中断' } },
      { lastProgress: 20, unchangedStreak: 0, ...at(0) },
    )
    expect(failed.kind === 'failed' && failed.error).toContain('进程重启')
  })

  it('轮询状态拿到 404（作业被别人删了/越权）→ 终态，别再转', () => {
    expect(pollDecision(
      { status: 404, data: {} },
      { lastProgress: 50, unchangedStreak: 0, ...at(0) },
    ).kind).toBe('failed')
  })

  it('未知状态按「继续等」处理，但超过上限必须放弃 —— 不许无限轮询', () => {
    const waiting = pollDecision(
      { status: 200, data: { status: 'queued?' } },
      { lastProgress: 0, unchangedStreak: 0, ...at(0) },
    )
    expect(waiting.kind).toBe('wait')

    const gaveUp = pollDecision(
      { status: 200, data: { status: 'running', progress: 50 } },
      { lastProgress: 50, unchangedStreak: 9, startedAt: 0, now: POLL_MAX_MS + 1 },
    )
    expect(gaveUp.kind).toBe('giveup')
  })

  it('上限是 5 分钟（spec §6 的口径，写死在这里以免被顺手改掉）', () => {
    expect(POLL_MAX_MS).toBe(5 * 60 * 1000)
  })
})

describe('formatJobFailure：把后端 error 变成能看的一句话', () => {
  it('有后端文案就用后端的（重试按钮要用的就是这个原因）', () => {
    expect(formatJobFailure({ error: '全部失败：a.csv: reset' })).toContain('a.csv')
  })

  it('没有文案时给通用句，不能显示 undefined', () => {
    const text = formatJobFailure({ error: '' })
    expect(text).toBeTruthy()
    expect(text).not.toContain('undefined')
  })
})

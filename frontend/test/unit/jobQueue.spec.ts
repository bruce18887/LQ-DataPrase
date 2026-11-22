/**
 * T2：作业排队展示 + 等待上限与后端超时对齐（`src/composables/jobPolling.ts`）。
 *
 * 为什么要测这两个纯函数：
 * 1. **上限**：前端原先写死 5 分钟，而 `export_batch_charts` 的后端超时是 1 小时
 *    （`apps/jobs/executor.KIND_RUNNERS`）。写死的 5 分钟会让长作业在「后端还在跑」
 *    的时候先被前端放弃 —— 用户看到的是「停止等待」，文件却已经算出来了。
 *    上限必须来自后端下发的 `timeout_seconds`（Task 10 恒出现于作业 payload）。
 * 2. **排队**：`queue_position` 只有详情/202 带、列表不带，前端只做展示，
 *    因此这里只钉「字段 → 文案」的映射，不去断言 DOM。
 *
 * 归一化口径（钉住一种，别让调用方各写一套）：
 * `Math.max(0, Math.floor(Number(n)))`，非有限值（缺字段/`null`/`'abc'`/`NaN`）当 0。
 * 负值当 0（「前面 -1 个」是脏数据，不是「下一个」）；小数向下取整
 * （位置是按条数数的，半个作业没意义）。
 */
import { describe, expect, it } from 'vitest'

import {
  POLL_BASE_MS,
  POLL_MAX_MS,
  pollDecision,
  pollTimeoutMs,
  queuePositionText,
} from '../../src/composables/jobPolling'

describe('pollTimeoutMs：等待上限跟随后端 timeout_seconds', () => {
  it('3600s → 3660000（多给 60s 收尾余量，后端超时那一刻文件往往已经落盘）', () => {
    expect(pollTimeoutMs({ timeout_seconds: 3600 })).toBe(3_660_000)
  })

  it('四类 kind 的真实值各取一遍（1800/3600/1800/7200）', () => {
    expect(pollTimeoutMs({ timeout_seconds: 1800 })).toBe(1_860_000)
    expect(pollTimeoutMs({ timeout_seconds: 7200 })).toBe(7_260_000)
  })

  it('0 / null / 缺失 → 回退 POLL_MAX_MS（遗留作业没有 timeout 表项）', () => {
    expect(pollTimeoutMs({ timeout_seconds: 0 })).toBe(POLL_MAX_MS)
    expect(pollTimeoutMs({ timeout_seconds: null })).toBe(POLL_MAX_MS)
    expect(pollTimeoutMs({})).toBe(POLL_MAX_MS)
    expect(pollTimeoutMs(null)).toBe(POLL_MAX_MS)
    expect(pollTimeoutMs(undefined)).toBe(POLL_MAX_MS)
  })

  it('负值 → POLL_MAX_MS（不能算出一个负数上限）', () => {
    expect(pollTimeoutMs({ timeout_seconds: -60 })).toBe(POLL_MAX_MS)
  })

  it('非数字串 → POLL_MAX_MS；数字串按数值处理（与 clampPercent 同一读法）', () => {
    expect(pollTimeoutMs({ timeout_seconds: 'abc' })).toBe(POLL_MAX_MS)
    expect(pollTimeoutMs({ timeout_seconds: '600' })).toBe(660_000)
  })
})

describe('pollDecision：maxMs 覆盖默认 5 分钟上限', () => {
  const at = (elapsed: number, maxMs?: number) => ({
    lastProgress: 10, unchangedStreak: 0, startedAt: 0, now: elapsed, maxMs,
  })
  const running = { status: 200, data: { status: 'running', progress: 10 } }

  it('未给 maxMs 时按 POLL_MAX_MS（存量行为不变）', () => {
    expect(pollDecision(running, at(POLL_MAX_MS)).kind).toBe('wait')
    expect(pollDecision(running, at(POLL_MAX_MS + 1)).kind).toBe('giveup')
  })

  it('给了 maxMs 就按它判：恰好到线仍等，过线才放弃（判据是严格大于）', () => {
    expect(pollDecision(running, at(3_660_000, 3_660_000)).kind).toBe('wait')
    expect(pollDecision(running, at(3_660_001, 3_660_000)).kind).toBe('giveup')
  })

  it('maxMs 比默认更小时更早放弃（同一个 now，默认上限下还是 wait）', () => {
    expect(pollDecision(running, at(60_001)).kind).toBe('wait')
    expect(pollDecision(running, at(60_001, 60_000)).kind).toBe('giveup')
  })
})

describe('queuePositionText：0 不显示，其余给一句话', () => {
  it('0 → null（下一个就轮到我，不是「前面 0 个」这种噪声）', () => {
    expect(queuePositionText(0)).toBeNull()
  })

  it('正数 → 排队中 · 前面 N 个', () => {
    expect(queuePositionText(3)).toBe('排队中 · 前面 3 个')
    expect(queuePositionText(1)).toBe('排队中 · 前面 1 个')
  })

  it('负值 / 小数 / 非数字按同一归一化口径处理', () => {
    expect(queuePositionText(-2)).toBeNull()
    expect(queuePositionText(2.7)).toBe('排队中 · 前面 2 个')
    expect(queuePositionText(Number.NaN)).toBeNull()
  })
})

describe('wait verdict 带 queuePosition（从作业 payload 读）', () => {
  const waitVerdict = (job: Record<string, unknown>) => pollDecision(
    { status: 200, data: { status: 'running', progress: 0, ...job } },
    { lastProgress: 0, unchangedStreak: 0, startedAt: 0, now: 0 },
  )

  it('缺字段 → 0（列表 payload 不带 queue_position；轮询走详情，但防御仍要留）', () => {
    expect(waitVerdict({})).toEqual({
      kind: 'wait', delay: POLL_BASE_MS, unchangedStreak: 1, progress: 0, queuePosition: 0,
    })
  })

  it('正常整数原样交出', () => {
    const v = waitVerdict({ queue_position: 3 })
    expect(v.kind === 'wait' && v.queuePosition).toBe(3)
  })

  it('负值 / 小数 / 脏串按非负整数归一，不会把 NaN 传进模板', () => {
    const pos = (queue_position: unknown) => {
      const v = waitVerdict({ queue_position })
      return v.kind === 'wait' ? v.queuePosition : -1
    }
    expect(pos(-2)).toBe(0)
    expect(pos(2.7)).toBe(2)
    expect(pos('4')).toBe(4)
    expect(pos('abc')).toBe(0)
    expect(pos(null)).toBe(0)
  })
})

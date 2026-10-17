import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { useSiteStats } from '../../src/pages/analysis/composables/useSiteStats'

/**
 * T2：Site 统计表的数据来源判据（2026-10-17 起它是直方图响应的派生值，不再有独立请求）。
 *
 * 要钉住的是两件容易静默退化掉的事：
 * ① 站点表数值**只来自** `histogram.results[p].site_stats`（后端与
 *    `/statistics/site_stats/` 的逐字段等价由 `apps/analysis/tests_param_switch_load.py` 管）；
 * ② 「该文件没有 Site 列」这句提示还在。合并前它来自端点的 400，合并后来自
 *    `site_stats` 为 null —— 没人断言的话，退化形状是「卡片安静地显示暂无数据」，
 *    用户看不出是文件没 Site 列还是数据没加载。
 */

const ROWS = [
  { Site: 'Site1', Yield: '99.508%(1626)', FailCount: '8(0.493%)', FailCountNum: 8 },
  { Site: 'ALL Site', Yield: '99.508%(1626)', FailCount: '8(0.493%)', FailCountNum: 8 },
]

describe('useSiteStats 派生自直方图响应', () => {
  it('有 site_stats 时逐字透传，不加工', () => {
    const histResult = ref<any>({ site_stats: ROWS, mean: 1.0 })
    const { siteStats, siteStatsError } = useSiteStats(histResult)
    expect(siteStats.value).toEqual(ROWS)
    expect(siteStatsError.value).toBe('')
  })

  it('响应里没有 site_stats 键（后端 clean_data 会剔掉 null）⇒ 内联提示而非静默空表', () => {
    const histResult = ref<any>({ mean: 1.0 })
    const { siteStats, siteStatsError } = useSiteStats(histResult)
    expect(siteStats.value).toEqual([])
    expect(siteStatsError.value).toBe('该文件没有 Site 列，无法进行站点统计')
  })

  it('site_stats 显式为 null ⇒ 同一条提示', () => {
    const histResult = ref<any>({ site_stats: null })
    expect(useSiteStats(histResult).siteStatsError.value)
      .toBe('该文件没有 Site 列，无法进行站点统计')
  })

  it('还没拿到响应（切文件/清空参数的早退态）⇒ 空表且不出错误，避免误导', () => {
    const histResult = ref<any>(null)
    const { siteStats, siteStatsError } = useSiteStats(histResult)
    expect(siteStats.value).toEqual([])
    expect(siteStatsError.value).toBe('')
  })

  it('换参数后 histResult 落地即跟随，不残留上一个测试项的行', () => {
    const histResult = ref<any>({ site_stats: ROWS })
    const { siteStats } = useSiteStats(histResult)
    expect(siteStats.value).toHaveLength(2)
    histResult.value = { site_stats: [ROWS[0]] }
    expect(siteStats.value).toEqual([ROWS[0]])
    histResult.value = null
    expect(siteStats.value).toEqual([])
  })
})

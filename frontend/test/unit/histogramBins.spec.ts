/**
 * T2：直方图 bin 裁剪口径（2D 与 3D 共用）。
 *
 * 钉住的是「两图同屏不得各说各话」这一条根（specs/2026-11-04 §8），四条承重：
 * ① 只有 clip 藏柱体——exclude 改的是统计口径、off 什么都不改（把 exclude 写成也过滤，
 *    同屏 2D 与 3D 会与统计卡的 filtered 口径同时错位）；
 * ② RDL 扩展只在 RDL 且规格限齐备时发生，且是**放宽**（把 CL 也放宽，自定义限就白设了）；
 * ③ 边界病态到一格不剩时回退全部（旧 2D 守卫，回退丢了会画空图）；
 * ④ 后端 NaN→JSON null 的边界按「那一侧不裁」处理（R4②）——旧内联写法 `c >= null`
 *    会被 JS 悄悄当 `c >= 0`，本批把这一处**有意改掉**，spec §8 的「逐字节不变」在此让位。
 */
import { describe, expect, it } from 'vitest'

import { activeBinIndices, type BinClipSource } from '../../src/pages/analysis/composables/histogramBins'

/** 26 个中心：underflow + 24 正常 + overflow，与后端 binning.build_bin_grid 同形 */
const CENTERS = Array.from({ length: 26 }, (_, i) => -1 + i * 0.1)

function src(over: Partial<BinClipSource> = {}): BinClipSource {
  return {
    binCenters: CENTERS,
    handlingMode: 'off',
    outlierInfo: null,
    rangeType: 'RDL',
    ...over,
  }
}

describe('activeBinIndices — 只有 clip 动柱体', () => {
  it('off → 全部 26 格都在', () => {
    expect(activeBinIndices(src())).toEqual(CENTERS.map((_, i) => i))
  })

  it('exclude → 与 off 逐字相同（它只切统计口径，不藏柱）', () => {
    const withOutliers = activeBinIndices(src({
      handlingMode: 'exclude',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    }))
    expect(withOutliers).toEqual(CENTERS.map((_, i) => i))
  })

  it('clip + 有异常值 → 只留 [lower, upper] 闭区间内的中心', () => {
    const kept = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    }))
    expect(kept).toEqual(CENTERS.map((c, i) => (c >= 0.2 && c <= 0.8 ? i : -1)).filter((i) => i >= 0))
    expect(kept.length).toBeLessThan(CENTERS.length)
    // underflow（第 0 格 = -1）与 overflow（第 25 格 = 1.5）必须被裁掉
    expect(kept).not.toContain(0)
    expect(kept).not.toContain(25)
  })

  it('clip 但后端说没有异常值 → 不过滤（has_outliers 是前置条件）', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: false, lower_bound: 0.2, upper_bound: 0.8 },
    }))).toEqual(CENTERS.map((_, i) => i))
  })
})

describe('RDL 放宽：原始 Limit 线内的数据不该被当异常值隐藏', () => {
  // 下面三条测的是**纯函数契约**，不是线上载荷形状：后端对每个档位都已用同一对 rdl
  // 展过界（outliers.py:78-83），真实 outlier_info 的 lower_bound 早就是 min(IQR, LSL)。
  // 夹具因此刻意造一对「只含 IQR」的窄边界，让这一支有牙——把它删掉只会让这三条红，
  // 生产上看不出差别（实现里那条注释写明了恒等）。
  it('RDL 且两个规格限齐备 → 边界并上规格限（比纯 IQR 宽）', () => {
    const iqrOnly = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    }))
    const widened = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
      lowerLimit: 0, upperLimit: 1,
    }))
    expect(widened.length).toBeGreaterThan(iqrOnly.length)
    expect(iqrOnly.every((i) => widened.includes(i))).toBe(true)
  })

  it.each(['CL', 'DR', 'S3', 'S4', 'S6'] as const)(
    '%s 不放宽（放宽只属于 RDL；CL 的自定义限、σ/DR 的宽窗都是用户要的窗口）',
    (rangeType) => {
      expect(activeBinIndices(src({
        handlingMode: 'clip', rangeType,
        outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
        lowerLimit: 0, upperLimit: 1,
      }))).toEqual(activeBinIndices(src({
        handlingMode: 'clip', rangeType,
        outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
      })))
    },
  )

  it('RDL 但缺一个规格限 → 不放宽（旧实现要求两个都非 null）', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
      lowerLimit: 0, upperLimit: null,
    }))).toHaveLength(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    })).length)
  })
})

describe('病态与 null 守卫', () => {
  it('边界反了（lower > upper）→ 回退全部，不画空图', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 9, upper_bound: -9 },
    }))).toEqual(CENTERS.map((_, i) => i))
  })

  it('bound 为 null（后端 NaN→JSON null）→ 那一侧不裁，而不是当成 0', () => {
    const kept = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: null, upper_bound: 0.8 },
    }))
    // 下侧不裁 ⇒ underflow（-1）仍在；`c >= null` 那套旧行为会把负中心全裁掉
    expect(kept).toContain(0)
    expect(kept).not.toContain(25)
  })

  it('bound 字段整个缺失（undefined）→ 与 null 同义，那一侧不裁', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, upper_bound: 0.8 },
    }))).toEqual(CENTERS.map((c, i) => (c <= 0.8 ? i : -1)).filter((i) => i >= 0))
  })

  it('后端没发 bin（空数组）→ 空下标，不走「回退全部」（回退退的是原样空集，别在这里造出 [0..n)）', () => {
    expect(activeBinIndices(src({ binCenters: [] }))).toEqual([])
  })
})

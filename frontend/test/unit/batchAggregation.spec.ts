import { describe, expect, it } from 'vitest'

import type { BatchAggPhase, BatchUph } from '../../src/utils/batchAggregation'
import {
  aggregateBinSiteTable,
  aggregateSiteYield,
  aggregateUph,
} from '../../src/utils/batchAggregation'

// 本文件钉的是「与 apps/batch_report/aggregation.py 同构」这条注释承诺（见源文件头）。
// 双源算法漂移只在阶段过滤路径上暴露，浏览器里要造出多文件多阶段数据成本极高。

function uph(over: Partial<BatchUph> = {}): BatchUph {
  return {
    uph: 0,
    avg_test_time: 0,
    total_tested: 0,
    total_time_seconds: 0,
    source: 'file',
    by_site: [],
    site_count: 0,
    warnings: [],
    ...over,
  }
}

describe('aggregateSiteYield', () => {
  it('跨阶段累加 pass/total，良率保留两位', () => {
    const phases: BatchAggPhase[] = [
      { stage: 'FT', site_total: { '1': 100, '2': 50 }, site_pass: { '1': 90, '2': 40 } },
      { stage: 'QA', site_total: { '1': 100 }, site_pass: { '1': 80 } },
    ]
    expect(aggregateSiteYield(phases, ['1', '2'])).toEqual([
      { site: '1', pass: 170, total: 200, yield: 85 },
      { site: '2', pass: 40, total: 50, yield: 80 },
    ])
  })

  it('全阶段无数据的站点整行丢弃，而不是画 0%', () => {
    const phases: BatchAggPhase[] = [{ stage: 'FT', site_total: { '1': 10 }, site_pass: { '1': 9 } }]
    expect(aggregateSiteYield(phases, ['1', '9'])).toEqual([
      { site: '1', pass: 9, total: 10, yield: 90 },
    ])
  })

  it('缺字段与字符串数字都按 0/强转容错', () => {
    const phases: BatchAggPhase[] = [
      { stage: 'FT' },
      { stage: 'QA', site_total: { '1': '8' as unknown as number }, site_pass: { '1': '6' as unknown as number } },
    ]
    expect(aggregateSiteYield(phases, ['1'])).toEqual([
      { site: '1', pass: 6, total: 8, yield: 75 },
    ])
  })
})

describe('aggregateBinSiteTable', () => {
  it('Pass bin 恒排最前、其余数字升序，末行 Total 且 all_site 为行和', () => {
    const phases: BatchAggPhase[] = [
      {
        stage: 'FT',
        bin_info: [
          { name: '1', value: 10, pct: '', sites: { '1': 6, '2': 4 } },
          { name: '3', value: 5, pct: '', sites: { '1': 5 } },
        ],
      },
      { stage: 'QA', bin_info: [{ name: '1', value: 2, pct: '', sites: { '1': 2 } }] },
    ]
    expect(aggregateBinSiteTable(phases, ['1', '2'])).toEqual({
      bin_site_columns: ['1', '2'],
      bin_table_data: [
        { bin: 'Bin 1', '1': 8, '2': 4, all_site: 12 },
        { bin: 'Bin 3', '1': 5, '2': 0, all_site: 5 },
        { bin: 'Total', '1': 13, '2': 4, all_site: 17 },
      ],
    })
  })

  it('非数字 bin 名保留原样，并排在数字 bin 之后', () => {
    const phases: BatchAggPhase[] = [
      {
        stage: 'FT',
        bin_info: [
          { name: 'OPEN', value: 1, pct: '', sites: { '1': 1 } },
          { name: '2', value: 3, pct: '', sites: { '1': 3 } },
        ],
      },
    ]
    const { bin_table_data } = aggregateBinSiteTable(phases, ['1'])
    expect(bin_table_data.map((r) => r.bin)).toEqual(['Bin 2', 'Bin OPEN', 'Total'])
  })

  it('无 bin 或无站点列时返回空表结构', () => {
    const phases: BatchAggPhase[] = [{ stage: 'FT', bin_info: [] }]
    expect(aggregateBinSiteTable(phases, ['1'])).toEqual({
      bin_table_data: [],
      bin_site_columns: [],
    })
    expect(aggregateBinSiteTable([], [])).toEqual({ bin_table_data: [], bin_site_columns: [] })
  })
})

describe('aggregateUph', () => {
  it('批次 UPH 用总测数/总时长重算，站点 UPH 由 3600*tested/serial 反推', () => {
    const phases: BatchAggPhase[] = [
      {
        stage: 'FT',
        uph: uph({
          total_tested: 100,
          total_time_seconds: 360,
          avg_test_time: 2,
          by_site: [
            { site: '2', tested: 40, uph: 800 },
            { site: '1', tested: 60, uph: 900 },
          ],
          warnings: ['时钟跳变'],
        }),
      },
    ]
    const out = aggregateUph(phases)
    expect(out.uph).toBe(1000)
    expect(out.avg_test_time).toBe(2)
    expect(out.total_tested).toBe(100)
    expect(out.total_time_seconds).toBe(360)
    expect(out.source).toBe('batch')
    expect(out.site_count).toBe(2)
    // 站点按数字升序，不是输入顺序
    expect(out.by_site).toEqual([
      { site: '1', tested: 60, uph: 900 },
      { site: '2', tested: 40, uph: 800 },
    ])
    expect(out.warnings).toEqual(['时钟跳变'])
  })

  it('站点数排序按数值而非字典序（10 排在 2 之后）', () => {
    const phases: BatchAggPhase[] = [
      {
        stage: 'FT',
        uph: uph({
          total_tested: 30,
          total_time_seconds: 60,
          avg_test_time: 1,
          by_site: [
            { site: '10', tested: 10, uph: 600 },
            { site: '2', tested: 20, uph: 600 },
          ],
        }),
      },
    ]
    expect(aggregateUph(phases).by_site.map((s) => s.site)).toEqual(['2', '10'])
  })

  it('缺 UPH 数据的文件计入「部分汇总」警告，重复警告合并为一条', () => {
    const dup = uph({ total_tested: 0, warnings: ['无时间戳'] })
    const phases: BatchAggPhase[] = [
      { stage: 'FT', uph: dup },
      { stage: 'QA', uph: dup },
      { stage: 'DB' },
    ]
    expect(aggregateUph(phases).warnings).toEqual([
      '无时间戳',
      '3 个文件缺少 UPH 数据，批次 UPH 为部分汇总',
    ])
  })

  it('全空时返回零值结构而不是 NaN/Infinity', () => {
    expect(aggregateUph([{ stage: 'FT' }])).toMatchObject({
      uph: 0,
      avg_test_time: 0,
      total_tested: 0,
      by_site: [],
      site_count: 0,
    })
  })
})

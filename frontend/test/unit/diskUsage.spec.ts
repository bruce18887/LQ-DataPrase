// frontend/test/unit/diskUsage.spec.ts
import { describe, expect, it } from 'vitest'

import type { FileUsage } from '../../src/api/datafiles'
import {
  usageBytesText,
  usageChipText,
  usageBreakdownRows,
  usageMismatchLine,
  usageOutsideLine,
  usageScannedText,
} from '../../src/utils/diskUsage'

const base = (over: Partial<FileUsage> = {}): FileUsage => ({
  data_dir: 'C:/x/media/data/admin',
  bytes: 0,
  unique_bytes: 0,
  file_count: 0,
  by_type: {},
  db_count: 0,
  db_bytes: 0,
  db_bytes_in_root: 0,
  db_outside_root_count: 0,
  db_outside_root_bytes: 0,
  mismatch_over_threshold: false,
  mismatch_diff_bytes: 0,
  scanned_at: '2026-11-14T06:07:08.123456+00:00',
  ...over,
})

describe('usageBytesText', () => {
  // formatSize 的 0 → '--' 是 format.spec.ts:23-25 钉住的既有契约（那边「没大小」与
  // 「0 字节」同形是可以的），但空目录是本功能的合法状态：这里必须分开。
  it('null/undefined 才是占位符，0 是 0 B', () => {
    expect(usageBytesText(null)).toBe('--')
    expect(usageBytesText(undefined)).toBe('--')
    expect(usageBytesText(0)).toBe('0 B')
  })

  it('四档边界与 formatSize 的前三档逐字一致', () => {
    expect(usageBytesText(1023)).toBe('1023 B')
    expect(usageBytesText(1024)).toBe('1.0 KB')
    expect(usageBytesText(1536)).toBe('1.5 KB')
    expect(usageBytesText(1024 * 1024 - 1)).toBe('1024.0 KB')
    expect(usageBytesText(1024 * 1024)).toBe('1.0 MB')
  })

  // GB 档是本功能新增的：formatSize 最高只到 MB，改它要动既有调用点的显示（2026-11-14 现数：
  // 导入 utils 版的 7 个文件、共 9 处调用），不属本批。判据见本文件 usageBytesText 那三档。
  it('≥1GiB 进 GB 档并保留两位', () => {
    expect(usageBytesText(1024 * 1024 * 1024)).toBe('1.00 GB')
    expect(usageBytesText(1024 * 1024 * 1024 - 1)).toBe('1024.0 MB')
    expect(usageBytesText(1.5 * 1024 * 1024 * 1024)).toBe('1.50 GB')
  })

  it('非有限值（NaN/±Infinity）不产生 NaN 字样', () => {
    expect(usageBytesText(Number.NaN)).toBe('--')
    // 这两条不是装饰：把守卫 `!Number.isFinite(bytes)` 换成**同极性**的
    // `Number.isNaN(bytes)`（只拦 NaN）时，NaN 那条连同其余 14 条**全部照样绿**，
    // 只有这两条红 —— `+Infinity` 一路穿到 GB 档 ⇒ `'Infinity GB'`，
    // `-Infinity` 穿到 B 档 ⇒ `'-Infinity B'`（各压一档，所以两条都要留）。
    // 实测：1 failed / 14 passed。
    // 另一极性 `!Number.isNaN(bytes)` 是更粗暴的坏实现（所有有限值都变 `--`，
    // 11 条同时红），它杀不动「只有 Infinity 能杀」这件事，所以不作为本条的理由。
    expect(usageBytesText(Number.POSITIVE_INFINITY)).toBe('--')
    expect(usageBytesText(Number.NEGATIVE_INFINITY)).toBe('--')
  })
})

describe('usageChipText', () => {
  it('没拿到数据时返回 null（调用方 v-if 决定 chip 出不出现）', () => {
    expect(usageChipText(null)).toBeNull()
  })

  it('文案形态：磁盘占用 X · N 个文件', () => {
    expect(usageChipText(base({ bytes: 1288490188, file_count: 3412 })))
      .toBe('磁盘占用 1.20 GB · 3,412 个文件')
  })

  it('空目录也出一句完整的话，而不是「磁盘占用 -- · 0 个文件」', () => {
    expect(usageChipText(base())).toBe('磁盘占用 0 B · 0 个文件')
  })

  it('千位分隔走 toLocaleString（与仓内既有写法同形）', () => {
    expect(usageChipText(base({ bytes: 10, file_count: 1234567 })))
      .toBe('磁盘占用 10 B · 1,234,567 个文件')
  })
})

describe('usageBreakdownRows', () => {
  it('已知键映射中文标签，未知键原样显示，按体积从大到小', () => {
    const rows = usageBreakdownRows(base({
      by_type: {
        single: { bytes: 1024, count: 1 },
        batch: { bytes: 2048, count: 2 },
        staging: { bytes: 4096, count: 3 },
      },
    }))
    expect(rows.map((r) => r.label)).toEqual(['staging', '批次', '单文件'])
    expect(rows[0]).toEqual({ label: 'staging', sizeText: '4.0 KB', countText: '3 个文件' })
  })

  // 本仓第二次踩同一个坑（第一次见 utils/audit.ts:24-29 与其 test/unit/audit.spec.ts:160-170）。
  // 一级目录名可以是任意字符串（_scan_tree 按路径第一段建桶，见 storage_usage.py:111-112、:138-163），
  // 而 `TYPE_LABELS[key] ?? key` 里 `??` 只挡 null/undefined：constructor/toString/hasOwnProperty
  // 会从原型取到 Function、__proto__ 取到 Object.prototype，原样递回就成了非字符串的 label，
  // UsageRow.label 标 string 骗过 TS、不报错，浮层把「function toString(){…}」当桶名显示出来。
  // 这几个键与上面 staging 那条不同类：staging 是「未知普通键」（本来就能原样显示），
  // 它们是「原型键」（本来会被静默换成非字符串）。
  it('原型名键（constructor/toString/hasOwnProperty/__proto__）的 label 必须是字符串键本身', () => {
    const keys = ['constructor', 'toString', 'hasOwnProperty', '__proto__']
    // Object.fromEntries 走 CreateDataProperty，能把 __proto__ 造成本身可枚举的自有键
    // （对象字面量与 obj[k]= 都不行——会触发 __proto__ setter 改原型）。
    const rows = usageBreakdownRows(
      base({ by_type: Object.fromEntries(keys.map((k) => [k, { bytes: 1024, count: 1 }])) }),
    )
    expect(rows).toHaveLength(keys.length)
    for (const r of rows) expect(typeof r.label, JSON.stringify(r.label)).toBe('string')
    expect(rows.map((r) => r.label).sort()).toEqual([...keys].sort())
  })

  it('根目录散文件的空串键显示为「根目录散文件」', () => {
    const rows = usageBreakdownRows(base({ by_type: { '': { bytes: 5, count: 1 } } }))
    expect(rows).toEqual([{ label: '根目录散文件', sizeText: '5 B', countText: '1 个文件' }])
  })

  it('没有文件或还没扫时返回空数组（浮层靠它决定显不显空态）', () => {
    expect(usageBreakdownRows(base())).toEqual([])
    expect(usageBreakdownRows(null)).toEqual([])
  })
})

describe('usageOutsideLine', () => {
  it('目录外记录为 0 时不显（遗留装机才有）', () => {
    expect(usageOutsideLine(base())).toBeNull()
    expect(usageOutsideLine(base({ db_outside_root_count: 7, db_outside_root_bytes: 3072 })))
      .toBe('另有 7 条记录的文件不在数据目录内（3.0 KB）')
  })
})

describe('usageMismatchLine', () => {
  it('未超阈值不显差值行', () => {
    expect(usageMismatchLine(base())).toBeNull()
    // 反证 M8 加的第三条：后端 `_mismatch` 返回的是 `ratio > 阈值, diff` 两个独立量，
    // 「有差值但没过阈值」是真实状态（差 1% 就这么显示）。只钉上面两条的话，
    // flag 与 diff 在夹具里同起同落，把判据从「看阈值」改成「看差值非 0」都测不出来。
    expect(usageMismatchLine(base({ mismatch_over_threshold: false, mismatch_diff_bytes: 12345 })))
      .toBeNull()
    expect(usageMismatchLine(base({ mismatch_over_threshold: true, mismatch_diff_bytes: 123456789 })))
      .toBe('清单与磁盘不一致（差 117.7 MB）：清单里的文件大小是导入当时的快照，此后不刷新')
  })
})

describe('usageScannedText', () => {
  it('scanned_at 缺失或不可解析时返回 null，不显空串', () => {
    expect(usageScannedText(base({ scanned_at: '' }))).toBeNull()
    expect(usageScannedText(base({ scanned_at: 'not-a-date' }))).toBeNull()
    expect(usageScannedText(null)).toBeNull()
  })

  it('值只有时间本身（带时分秒、24 小时制、无「统计时间」前缀）', () => {
    // ⚠ 分工：`usageScannedText` 返回的是**浮层某一行的 value**，而那一行的 label
    // 由调用方（Task 7 的 `el-descriptions-item label="统计时间"`）给。返回值再自带
    // 前缀就会读成「统计时间：统计时间 2026-11-14 …」。
    // 钉到「时分秒」这一分量是本条的承重改动：scanned_at 存在的唯一理由，就是把
    // ≤30s 的分桶 TTL 缓存（storage_usage.py:21-22、:35）暴露给用户。只钉日期形状的话，
    // 把 toLocaleString 换成 toLocaleDateString（丢掉时分秒）会让这一行「说谎说成当天最新」
    // 而所有用例照绿 —— 时钟分量必须显式钉住（异源法沿用 format.spec.ts:42 的不钉精确串、
    // :50-59 的 hour-cycle 边界思路，分隔符仍用 [-/] 两类都收，防 ICU/Node-vs-Chromium 漂）。
    // 夹具取一个偏晚的时刻（本例独有，不动 base() 的共享默认），让 12 小时制的「下午」露馅。
    const text = usageScannedText(base({ scanned_at: '2026-11-14T23:07:08+00:00' }))
    expect(text).toMatch(/^\d{4}[-/]\d{1,2}[-/]\d{1,2}/)
    expect(text).toMatch(/\d{1,2}:\d{2}:\d{2}/)
    expect(text).not.toMatch(/[上下]午/)
    expect(text).not.toMatch(/统计时间/)
  })
})

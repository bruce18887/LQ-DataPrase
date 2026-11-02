import { describe, expect, it } from 'vitest'

import {
  groupFileCount,
  groupFilesCapHint,
  sumFileCount,
  type BatchGroup,
} from '../../src/pages/data/composables/useBatchGroupStats'

/**
 * B6 前端落地：`/batch-dirs/` 每批 `files` 封顶 500，`files_truncated` 是**被省略的条数**。
 * 页面上三处计数（批次头、tab 角标、删除确认）必须用「已列出 + 被省略」的真实总数，
 * 否则 >500 的批次会静默少报（汇总条的大小/行数无法补齐——后端没给省略行的
 * file_size/row_count，所以只如实说明明细被截断，不冒充全量）。
 */

function group(over: Partial<BatchGroup> = {}): BatchGroup {
  return {
    name: 'LOT-1',
    files: [{ id: 1 }, { id: 2 }],
    subBatchNames: [],
    ...over,
  } as BatchGroup
}

describe('groupFileCount', () => {
  it('缺省 truncated 时等于已列出行数（旧形状不炸）', () => {
    expect(groupFileCount(group())).toBe(2)
  })

  it('真实总数 = 已列出 + 被省略', () => {
    expect(groupFileCount(group({ files: new Array(500).fill({}), truncated: 12 })))
      .toBe(512)
  })

  it('truncated=0 不改变计数', () => {
    expect(groupFileCount(group({ truncated: 0 }))).toBe(2)
  })
})

describe('sumFileCount', () => {
  it('跨批次求和把每批省略数都算进来', () => {
    const groups = [
      group({ name: 'A', files: new Array(500).fill({}), truncated: 21 }),
      group({ name: 'B', files: [{ id: 9 }] }),
    ]
    expect(sumFileCount(groups)).toBe(522)
  })

  it('空列表是 0，不是 undefined', () => {
    expect(sumFileCount([])).toBe(0)
  })
})

describe('groupFilesCapHint', () => {
  it('未截断时不给提示（空串，模板据此不渲染）', () => {
    expect(groupFilesCapHint(group())).toBe('')
    expect(groupFilesCapHint(group({ truncated: 0 }))).toBe('')
  })

  it('截断时说清三件事：共几个、列了几个、省略几个', () => {
    const g = group({ files: new Array(500).fill({}), truncated: 12 })
    expect(groupFilesCapHint(g)).toBe('共 512 个文件，明细仅列出前 500 个，另有 12 个未列出')
  })
})

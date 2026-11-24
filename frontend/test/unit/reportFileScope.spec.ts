import { describe, expect, it } from 'vitest'
import { filterReportFiles } from '../../src/utils/reportFileScope'
import type { DataFile } from '../../src/types'

function file(id: number, combinationId: number | null): DataFile {
  return {
    id,
    combination_id: combinationId,
    filename: `${id}.csv`,
    format_type: 'FT',
    file_type: 'single',
    batch_name: '',
    row_count: 0,
    col_count: null,
    program_name: '',
    status: 'ready',
    created_at: '',
  }
}

describe('filterReportFiles', () => {
  const files = [file(1, 3), file(2, 4), file(3, null)]

  it('按组合收敛候选', () => {
    expect(filterReportFiles(files, 3).map(f => f.id)).toEqual([1])
  })

  it('未指定组合时返回全部', () => {
    expect(filterReportFiles(files, null).map(f => f.id)).toEqual([1, 2, 3])
    expect(filterReportFiles(files, undefined).map(f => f.id)).toEqual([1, 2, 3])
  })

  it('保留原数组顺序且不修改输入', () => {
    expect(filterReportFiles(files, 3)).toEqual([files[0]])
    expect(files.map(f => f.id)).toEqual([1, 2, 3])
  })
})

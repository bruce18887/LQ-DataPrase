import { describe, expect, it } from 'vitest'
import {
  buildFileOptions,
  fileRank,
  matchFile,
  metaText,
  normalizeQuery,
  sortFiles,
} from '../../src/components/common/fileSelectModel'
import type { DataFile } from '../../src/types'

function file(id: number, filename: string, extra: Partial<DataFile> = {}): DataFile {
  return {
    id,
    filename,
    format_type: 'FT',
    file_type: 'single',
    batch_name: '',
    row_count: 0,
    col_count: null,
    program_name: '',
    status: 'ready',
    created_at: '',
    ...extra,
  }
}

describe('fileSelectModel', () => {
  it('normalizeQuery 去空白并转小写', () => {
    expect(normalizeQuery('  AbC ')).toBe('abc')
  })

  it('matchFile 命中 filename / program_name / batch_name，大小写不敏感', () => {
    const f = file(1, 'Alpha.csv', { program_name: 'P1', batch_name: 'B2' })
    expect(matchFile(f, 'alpha')).toBe(true)
    expect(matchFile(f, 'p1')).toBe(true)
    expect(matchFile(f, 'b2')).toBe(true)
    expect(matchFile(f, 'zzz')).toBe(false)
    expect(matchFile(f, '')).toBe(true)
  })

  it('fileRank 前缀 0 / 包含 1 / 其它 2', () => {
    expect(fileRank(file(1, 'Alpha'), 'al')).toBe(0)
    expect(fileRank(file(1, 'xAlpha'), 'al')).toBe(1)
    expect(fileRank(file(1, 'Beta'), 'al')).toBe(2)
  })

  it('sortFiles 无关键词保持原序；有关键词按 rank + localeCompare', () => {
    const files = [file(1, 'b'), file(2, 'A1'), file(3, 'A2')]
    expect(sortFiles(files, '', []).map((f) => f.id)).toEqual([1, 2, 3])
    expect(sortFiles(files, 'a', []).map((f) => f.id)).toEqual([2, 3, 1])
  })

  it('sortFiles 已选按选中顺序置顶，且其余项不重复', () => {
    const files = [file(1, 'one'), file(2, 'two'), file(3, 'three')]
    expect(sortFiles(files, '', [3, 1]).map((f) => f.id)).toEqual([3, 1, 2])
  })

  it('buildFileOptions 映射 value/label 并保留 file', () => {
    const files = [file(7, 'seven')]
    expect(buildFileOptions(files, '', [])).toEqual([
      { value: 7, label: 'seven', file: files[0] },
    ])
  })

  it('metaText 组合 program · format · 行数 · 大小 · 时间，空值跳过', () => {
    const f = file(1, 'a.csv', {
      program_name: 'P',
      format_type: 'FT',
      row_count: 12,
      file_size: 2048,
      created_at: '2026-11-21T10:00:00+08:00',
    })
    expect(metaText(f)).toContain('P · FT · 12 行')
    expect(metaText(file(2, 'b.csv'))).toBe('FT · 0 行')
  })
})

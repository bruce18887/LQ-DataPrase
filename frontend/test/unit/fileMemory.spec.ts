/**
 * 文件选择记忆（T2，node 环境）。
 *
 * 承重判据：
 *  ① pickFallbackFile 是纯决策——记忆仍在列表就用记忆（不是最新），失效才回退首项；
 *     这是「记住上次选择而非默认最新」的核心，且保证跨账号/删文件后优雅回退（R5）。
 *  ② remember/recall 按 scope 分键往返、键名前缀稳定（改名等于清零所有用户记忆）；
 *     null/undefined/空数组清除记忆。
 *  ③ recall 对坏数据（非数字/非法 JSON/非数组）容错回退，不抛。
 *
 * 存储 IO 边界 mock 成 Map（同 chartLayout.spec.ts mock safeStorage 的形状），
 * 真实 fileMemory 逻辑（JSON 解析/校验/决策）全部被测到；safeStorage 本体另有
 * localStorageHygiene.spec.ts 钉「src 只经 safeStorage 摸 localStorage」。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

const store = vi.hoisted(() => new Map<string, string>())
vi.mock('../../src/utils/safeStorage', () => ({
  safeGetItem: (k: string) => store.get(k) ?? null,
  safeSetItem: (k: string, v: string) => { store.set(k, v) },
  safeRemoveItem: (k: string) => { store.delete(k) },
}))

import {
  rememberFile, recallFileId, recallFileIds, pickFallbackFile,
} from '../../src/pages/analysis/composables/fileMemory'

beforeEach(() => store.clear())

describe('pickFallbackFile — 回退决策（纯函数）', () => {
  const list = [{ id: 10 }, { id: 20 }, { id: 30 }]
  it('空列表返回 null', () => {
    expect(pickFallbackFile([], 10)).toBeNull()
  })
  it('记忆仍在列表 → 用记忆，而不是最新首项', () => {
    expect(pickFallbackFile(list, 20)).toBe(20)
  })
  it('记忆失效（不在列表，如删文件/换账号）→ 回退首项最新', () => {
    expect(pickFallbackFile(list, 99)).toBe(10)
  })
  it('无记忆（null）→ 回退首项最新', () => {
    expect(pickFallbackFile(list, null)).toBe(10)
  })
})

describe('rememberFile / recall — 按 scope 分键往返', () => {
  it('单选写读往返', () => {
    rememberFile('single', 42)
    expect(recallFileId('single')).toBe(42)
  })
  it('四个 scope 互不影响', () => {
    rememberFile('single', 1)
    rememberFile('wafer', 2)
    rememberFile('correlation', 3)
    expect(recallFileId('single')).toBe(1)
    expect(recallFileId('wafer')).toBe(2)
    expect(recallFileId('correlation')).toBe(3)
  })
  it('键名带 analysis.lastFile. 前缀（改名等于清零所有用户记忆）', () => {
    rememberFile('single', 7)
    expect(store.get('analysis.lastFile.single')).toBe('7')
  })
  it('多选写读往返，保持选中顺序', () => {
    rememberFile('multi', [5, 3, 9])
    expect(recallFileIds('multi')).toEqual([5, 3, 9])
  })
  it('null / undefined / 空数组 → 清除记忆', () => {
    rememberFile('single', 7)
    rememberFile('single', null)
    expect(recallFileId('single')).toBeNull()

    rememberFile('multi', [1, 2])
    rememberFile('multi', [])
    expect(recallFileIds('multi')).toEqual([])

    rememberFile('wafer', 9)
    rememberFile('wafer', undefined)
    expect(recallFileId('wafer')).toBeNull()
  })
})

describe('recall — 坏数据容错回退，不抛', () => {
  it('单选读到非数字 JSON（字符串/数组）→ null', () => {
    store.set('analysis.lastFile.single', '"abc"')
    expect(recallFileId('single')).toBeNull()
    store.set('analysis.lastFile.single', '[1,2]')
    expect(recallFileId('single')).toBeNull()
  })
  it('单选读到非法 JSON 串 → null', () => {
    store.set('analysis.lastFile.single', '{bad')
    expect(recallFileId('single')).toBeNull()
  })
  it('多选过滤非数字元素，保留有限数字', () => {
    store.set('analysis.lastFile.multi', '[1,"x",2,null,3]')
    expect(recallFileIds('multi')).toEqual([1, 2, 3])
  })
  it('多选读到非数组 → []', () => {
    store.set('analysis.lastFile.multi', '5')
    expect(recallFileIds('multi')).toEqual([])
  })
  it('缺席键 → null / []', () => {
    expect(recallFileId('nope')).toBeNull()
    expect(recallFileIds('nope')).toEqual([])
  })
})
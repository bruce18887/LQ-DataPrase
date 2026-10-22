/**
 * T2（docs/reference/testing-gates.md §2，node 环境、零 DOM）：IRM 块预算接线。
 *
 * `blockCap.spec.ts` 已经钉过两个纯函数本身，这里只钉**接线**：
 * ① 窄文件的验收锚点（今天的行为不许被「优化」掉）；
 * ② 列数→块大小→块数这条链在组件侧真的连上了（205 / 4 是用发货常数验算过的组合值）；
 * ③ purge 的销毁守卫 —— 生产那条 `AG Grid: warning #26 … has been destroyed` 就是缺它，
 *    e2e 侧的承重用例是 `frontend/e2e/data/view-data.spec.ts` 的「关闭标签时不触发…#26」。
 * ④ colCount 变化必须**实时**反映到 blockSize/maxBlocks（用 ref 快照就会把上一份文件的
 *    大块尺寸带进千列文件，那正是 oom 的形状）。
 *
 * 205 = `floor(CELL_PER_BLOCK_MAX / 1728)`、4 = `floor(CELL_RETAIN_BUDGET / (205×1728))`
 * （1,728 = 种子文件 BPD93204_FT1_ETS163550 的实测列数，单价与常数推导见
 * docs/reference/renderer-memory-baseline-2026-10-22.md §6）。常数若重校，按那份文档
 * 重新推这几个数字，不要顺手改成「看起来也能过」的值。
 */
import { describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'

import type { GridApi } from 'ag-grid-community'
import type { DataFile } from '../../src/types'
import { useIrmSizing } from '../../src/pages/data/composables/useIrmSizing'
import { CELL_RETAIN_BUDGET, MAX_BLOCKS } from '../../src/pages/data/components/browser/blockCap'

/** 只带预算要用的两个字段，其余按 DataFile 的形状糊过去（T2 不需要完整实体） */
function file(id: number, colCount: number | null): DataFile {
  return { id, col_count: colCount } as unknown as DataFile
}

/** 造一个只记录 purge 次数的假 GridApi（`gridAlive` 守卫的全部职责就是挡这个调用） */
function fakeGridApi() {
  const purgeInfiniteCache = vi.fn()
  return { api: { purgeInfiniteCache } as unknown as GridApi, purgeInfiniteCache }
}

/** 一条接线场景：给定文件列表与 grid 引用，取回 composable 与 props */
function setup(files: DataFile[], fileId: number | null, api = fakeGridApi()) {
  const props = reactive({ fileId, files })
  const gridApi = ref<GridApi | null>(api.api)
  return { props, gridApi, ...useIrmSizing({ props, gridApi }), ...api }
}

describe('useIrmSizing 的分块尺寸', () => {
  it('窄文件锚点：142 列 × 设置 100 ⇒ 块大小 100、驻留仍是今天的 20 块', () => {
    const s = setup([file(1, 142)], 1)
    s.applyBlockSize(100)
    expect(s.blockSize.value).toBe(100)
    // 这条是验收判据：把 maxBlocksInCache 改成「不分列数一律压低」就会红在这里
    expect(s.maxBlocks.value).toBe(MAX_BLOCKS)
  })

  it('千列文件：设置 500 被钳到 205，驻留块数降到 4，且用户原值留着供提示比对', () => {
    const s = setup([file(1, 1728)], 1)
    s.applyBlockSize(500)
    expect(s.blockSize.value).toBe(205)
    expect(s.maxBlocks.value).toBe(4)
    // 提示的显示条件就是「落地值 ≠ 用户设的值」，所以原值必须留在 settingsPageSize
    expect(s.settingsPageSize.value).toBe(500)
    // 驻留上限不越预算（205 行 × 1,728 列 × 4 块）
    expect(s.blockSize.value * 1728 * s.maxBlocks.value).toBeLessThanOrEqual(CELL_RETAIN_BUDGET)
  })

  it('列数未知时预算完全不介入（对照组：压低就会静默改掉所有文件的分页）', () => {
    const noCol = setup([file(1, null)], 1)
    noCol.applyBlockSize(500)
    expect(noCol.blockSize.value).toBe(500)
    expect(noCol.maxBlocks.value).toBe(MAX_BLOCKS)

    const notInList = setup([file(1, 1728)], 999)
    notInList.applyBlockSize(500)
    expect(notInList.colCount.value).toBeNull()
    expect(notInList.blockSize.value).toBe(500)
  })

  it('设置域外的值一律忽略：49/501/非整数/NaN/null 都留默认 100', () => {
    // 对照组：删掉 Number.isInteger ⇒ '50.5' 会被接受；删掉上下界 ⇒ 49/501 会被接受
    for (const raw of [49, 501, '50.5', 'abc', null, undefined, Number.NaN, {}]) {
      const s = setup([file(1, 142)], 1)
      s.applyBlockSize(raw)
      expect(s.settingsPageSize.value, `raw=${String(raw)}`).toBe(100)
      expect(s.blockSize.value, `raw=${String(raw)}`).toBe(100)
    }
    const ok = setup([file(1, 142)], 1)
    ok.applyBlockSize('200') // 字符串数字是设置接口的正常形状，必须接受
    expect(ok.settingsPageSize.value).toBe(200)
  })

  it('换文件实时重算：窄→宽不能把上一份文件的 500 行大块带进千列文件', () => {
    const files = [file(1, 142), file(2, 1728)]
    const s = setup(files, 1)
    s.applyBlockSize(500)
    expect(s.blockSize.value).toBe(500)
    // 同一标签内用横幅切文件（`watch(() => props.fileId)` 那条通路）改的是 props.fileId
    s.props.fileId = 2
    expect(s.colCount.value).toBe(1728)
    expect(s.blockSize.value, '块大小必须跟着列数走，否则 500×1728 的块照旧把内存打爆').toBe(205)
    expect(s.maxBlocks.value).toBe(4)
    s.props.fileId = null
    expect(s.colCount.value).toBeNull()
    expect(s.blockSize.value).toBe(500)
  })

  it('驻留块数永不为 0（ag-grid 把 0 读成「不限制」）', () => {
    const s = setup([file(1, 500_000)], 1)
    s.applyBlockSize(500)
    expect(s.maxBlocks.value).toBeGreaterThanOrEqual(1)
  })
})

describe('useIrmSizing 的 purge 销毁守卫', () => {
  it('grid 未就绪 / 已卸载 ⇒ 一次都不碰；就绪后照常清缓存', () => {
    const s = setup([file(1, 142)], 1)
    // 就绪前（gridApi 还是 null 的那种情形另说，这里 api 已给但没 markGridAlive）
    s.purgeCacheIfAlive()
    expect(s.purgeInfiniteCache).not.toHaveBeenCalled()

    s.markGridAlive()
    s.purgeCacheIfAlive()
    expect(s.purgeInfiniteCache).toHaveBeenCalledTimes(1)

    // 卸载后：这就是生产 #26 的那一步，没有 markGridDead 就会打在已销毁实例上
    s.markGridDead()
    s.purgeCacheIfAlive()
    expect(s.purgeInfiniteCache).toHaveBeenCalledTimes(1)
  })

  it('gridApi 为 null（空态标签，ag-grid 压根没挂载）时不 purge、不抛', () => {
    const props = reactive({ fileId: null as number | null, files: [] as DataFile[] })
    const gridApi = ref<GridApi | null>(null)
    const s = useIrmSizing({ props, gridApi })
    s.markGridAlive()
    expect(() => s.purgeCacheIfAlive()).not.toThrow()
    expect(s.colCount.value).toBeNull()
    expect(s.blockSize.value).toBe(100)
  })

  it('applyBlockSize 只改设置值，不顺手 purge（块大小变化由 ag-grid 自己 resetCache）', () => {
    const s = setup([file(1, 1728)], 1)
    s.markGridAlive()
    s.applyBlockSize(500)
    expect(s.blockSize.value).toBe(205)
    expect(s.purgeInfiniteCache).not.toHaveBeenCalled()
  })
})

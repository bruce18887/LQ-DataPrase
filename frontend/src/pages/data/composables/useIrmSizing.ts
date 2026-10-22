/**
 * IRM（ag-grid 无限滚动）的分块尺寸与驻留预算 —— 从 DataBrowserAgGrid.vue 拆出来，
 * 因为那个文件已到 600 行上限（项目硬性约定：单个 .vue ≤ 600 行）。
 *
 * 存在理由（2026-10-22 生产 oom，`Renderer process gone: oom (exitCode=-536870904)`）：
 * `/api/v1/browse/` 单页 100 行在 1,728 列的文件里是 2.97 MB，`zipBrowserRows` 又把每行
 * 拼成含全部列的对象；写死的 `maxBlocksInCache=20` × 最多 4 个常驻标签 ⇒ 渲染进程被推到
 * 上限。驻留单价 3.38e-5 MiB/格 由 Task 1 探针实测，常数与推导见
 * docs/reference/renderer-memory-baseline-2026-10-22.md §6，判据本体在 blockCap.ts。
 *
 * 本 composable 只管「两个数怎么来 + 什么时候才能碰 grid」：不发请求、不注册生命周期钩子
 * （钩子留在组件里，语义各是：就绪=活、卸载=死、非激活=清缓存），列数取自已经传进组件的
 * `props.files`（元素带 `col_count`，`DataManagement.vue:59` 就传了 ⇒ 零新增请求、零新增 prop）。
 */
import { computed, ref, type Ref } from 'vue'
import type { GridApi } from 'ag-grid-community'
import type { DataFile } from '../../../types'
import { effectiveBlockSize, maxBlocksInCache } from '../components/browser/blockCap'

/** 与设置页同款的出厂默认每页行数；也是账号设置拉不到时的兜底值 */
const PAGE_SIZE_DEFAULT = 100

/**
 * 设置页「默认每页行数」的可取范围（= TableSettingsForm 下拉端点 / 序列化器校验域）。
 *
 * ⚠ 与 `blockCap.ts` 导出的同名常数是**两件事**（那边是内存钳位域），刻意各留一份、
 * 不 import 不合并：合并会静默改掉设置页的取值域（Task 3 定下的口径）。
 */
const BLOCK_SIZE_MIN = 50
const BLOCK_SIZE_MAX = 500

/**
 * @param props 组件的 props（响应式对象，直接透传即可 —— computed 会按 `props.fileId`
 *              / `props.files` 建依赖，不需要额外传 getter）
 * @param gridApi 由 `useBinCellMenu` 的 onGridReady 赋值的 api 引用
 */
export function useIrmSizing(opts: {
  props: { fileId: number | null; files: DataFile[] }
  gridApi: Ref<GridApi | null>
}) {
  const { props, gridApi } = opts

  /**
   * grid 是否还是活的。**唯一**置位点是 onGridReady（`markGridAlive`），清除点是 onUnmounted
   * （`markGridDead`）—— 这两点之前是缺的：`gridApi` 由 `useBinCellMenu.ts:39-41` 赋值后
   * **从不置空**，于是「挂载期间发出的异步请求回来后打 purge」会命中已销毁实例，
   * 控制台报 `AG Grid: warning #26 Grid API function purgeInfiniteCache() cannot be
   * called as the grid has been destroyed.`（生产日志 2026-10-22 实测两条）。
   *
   * 之所以做成 ref 而不是闭包里的 `let`：调用方还要用它守 `ensureIndexVisible` 这类
   * 同样会撞 #26 的 api 调用，光有 purgeCacheIfAlive() 挡不住。
   */
  const gridAlive = ref(false)

  /** 账号设置里用户选的「默认每页行数」原值；只用于判断实际有没有被压低（提示文案靠它） */
  const settingsPageSize = ref(PAGE_SIZE_DEFAULT)

  /**
   * 当前文件的列数：来自已传入的文件列表，零新增请求、零新增 prop。
   * 未知（文件还没解析出 col_count，或列表里查不到这个 id）时**预算完全不介入** ——
   * 按某个默认列数估算会在 col_count 还没到位时静默压低所有文件的分页大小。
   */
  const colCount = computed<number | null>(
    () => props.files.find((f) => f.id === props.fileId)?.col_count ?? null,
  )

  /**
   * 实际每块行数 = 用户设置被「单块格数预算」按列数压低。
   *
   * 用 computed 而不是 ref 是承重的：切文件（同一标签内用横幅换 fileId）会让 colCount 突变，
   * 若块大小停在上一份文件的值上，窄→宽就变成「500 行 × 千列」的块，而 ag-grid 恰好会因为
   * `cacheBlockSize` 属性变化而 resetCache（见下），所以这里必须让它跟着列数走。
   */
  const blockSize = computed(() => effectiveBlockSize(settingsPageSize.value, colCount.value))

  /**
   * 驻留块数上限。和 blockSize 一样是 computed：它由 `blockSize × colCount` 反推，
   * 所以「块更大 ↔ 块更少」始终让总驻留格数留在预算内。
   * 返回值恒 ≥1：ag-grid 把 0 当「不限制」（`maxBlocksProvided = maxBlocksInCache > 0`）。
   *
   * ⚠ **已知缺口**（spec §3 第 1 条「不要指望热更新 prop」的具体化，Task 7 收口拍板）：
   * `maxBlocksInCache` 只在 InfiniteCache **重建**时快照进 `cacheParams`
   * （`main.esm.mjs:55765`，驱逐读的是 `this.params.maxBlocksInCache` `:55481`），
   * 而 ag-grid 只对 `cacheBlockSize` 挂了 `resetCache` 监听（`:55683`）。于是
   * 「同一标签内用横幅把文件从窄换到宽、且设置 ≤ 205 行」这一条路上 `blockSize` 不变
   * ⇒ 不重建 cache ⇒ 活的 cache 仍按旧的 20 块驱逐（1,728 列 × 100 行 × 20 块 ≈ 117 MiB）。
   * 补法是换 `datasource` 身份逼 `setDatasource → reset → resetCache`（spec §3 认的入口），
   * 但它必须 `flush: 'post'` 才赶得上 gos 的新值，会和 `reload()` 那次 purge 叠成
   * 每次切文件双发 page=1 —— 与本计划 Task 5（请求去重）正面冲突，故留到收口一并定。
   */
  const maxBlocks = computed(() => maxBlocksInCache(blockSize.value, colCount.value))

  function markGridAlive() {
    gridAlive.value = true
  }

  function markGridDead() {
    gridAlive.value = false
  }

  /**
   * 只在 grid 还活着时清块缓存。所有 purge 入口（reload / onDeactivated）都必须走这里，
   * 不要直接 `gridApi.value?.purgeInfiniteCache()` —— `?.` 只挡 null，挡不住已销毁实例。
   */
  function purgeCacheIfAlive() {
    if (!gridAlive.value || !gridApi.value) return
    gridApi.value.purgeInfiniteCache()
  }

  /**
   * 套用账号的每页行数：先校验设置域（越界/非整数一律忽略，留默认），压低由 computed 做。
   *
   * 这里**不再** purgeInfiniteCache：块大小变化的正确生效路径是响应式 prop
   * `:cacheBlockSize="blockSize"` —— ag-grid 的 InfiniteRowModel 监听该属性并直接
   * `resetCache()`（`ag-grid-community/dist/package/main.esm.mjs` 的
   * `addManagedPropertyListener("cacheBlockSize", () => this.resetCache())`），新块边界与
   * `maxBlocksInCache` 都在那一刻重新快照（`cacheParams` 在 resetCache 里现取）。
   * 证据：`e2e/settings/page-size.spec.ts` 断言「设置 200 后第二次请求是 page=2」，
   * 没重快照的话页码会算回 page=1、那条等待必然超时。
   * 反过来 `api.purgeInfiniteCache()` **不会**重读 `cacheParams`（它只清 InfiniteCache
   * 里的块），所以旧写法那句 purge 是多余的，留着还会多打一次 `/browse/`。
   */
  function applyBlockSize(raw: unknown) {
    const n = Number(raw)
    if (!Number.isInteger(n) || n < BLOCK_SIZE_MIN || n > BLOCK_SIZE_MAX) return
    settingsPageSize.value = n
  }

  return {
    colCount,
    settingsPageSize,
    blockSize,
    maxBlocks,
    /** 只读出口：置位/清除只能走 markGridAlive / markGridDead */
    gridAlive: computed(() => gridAlive.value),
    applyBlockSize,
    markGridAlive,
    markGridDead,
    purgeCacheIfAlive,
  }
}

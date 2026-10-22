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
 * `props.files`（元素带 `col_count`，`DataManagement.vue:59` 就传了 ⇒ **就 col_count 这一处**
 * 零新增请求、零新增 prop；`active` 那条 prop 是 D4「非激活标签释放」在 v-show 结构下
 * 唯一的信号来源，与本句无关，别把它读成「本文件没加过 prop」）。
 */
import { computed, ref, type Ref } from 'vue'
import type { GridApi, IDatasource } from 'ag-grid-community'
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
   * ⚠ 它**只覆盖「组件卸载」这一种死法**：`DataBrowserAgGrid.vue:60,65-66` 用
   * `v-if="!fileId"` / `v-else` 挂载 grid，所以清空横幅的文件选择（`ActiveFileBanner.vue` 的
   * `clearable` → emit `null`）与后端 404（`DataManagement.vue:233-235` `onFileMissing`）
   * 都只销毁 grid 本身、组件仍挂载 ⇒ `gridAlive` 留 true、`gridApi` 指向已销毁实例。
   * 那一半由 ag-grid 自己的事实源 `api.isDestroyed()` 补齐（见 `liveGridApi`）。
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
   * ⚠ **它只在 InfiniteCache 重建时快照**（spec §3 第 1 条「不要指望热更新 prop」的具体化）：
   * `maxBlocksInCache` 只在 `resetCache()` 里进 `cacheParams`
   * （`ag-grid-community/dist/package/main.esm.mjs:55750-55776`，注释原文
   * 「so if user changes any, they will be used next time we create a new cache」`:55761-55763`），
   * 驱逐读的是那份快照（`:55481-55482`），而 ag-grid 只给 `datasource` 与 `cacheBlockSize`
   * 挂了属性监听（`:55682-55683`）—— `api.purgeInfiniteCache()` 走
   * `:55861 → InfiniteRowModel.purgeCache :55841 → InfiniteCache.purgeCache :55585-55594`，
   * 只 `removeBlockFromCache` + `onCacheUpdated`，**不**重建快照。
   * ⇒ 「只换 maxBlocks、不换 blockSize」必须另找重建入口：组件把 `datasource` 做成
   * 按 `(fileId, blockSize, maxBlocks)` 换身份的 computed，走
   * `setDatasource → reset → resetCache`（`:55704-55710`、`:55727-55737`），
   * 顺带把整叠块丢掉 ⇒ `reload()` 的换文件分支不再需要 purge（多留一次就是多一次 page=1）。
   * 端到端判据：`e2e/data/view-data.spec.ts` 的「窄→宽同标签切换…能看见驱逐」。
   */
  const maxBlocks = computed(() => maxBlocksInCache(blockSize.value, colCount.value))

  function markGridAlive() {
    gridAlive.value = true
  }

  /**
   * 包一层「按 (fileId, 块大小, 驻留块数) 换身份」的 datasource。组件侧
   * `computed(() => keyedDatasource(browseSource))` ⇒ 三个数任一变化就交给 ag-grid 一个新对象。
   *
   * 为什么非得换身份（Important 2，同标签窄→宽是**生产主路径**）：
   * `maxBlocksInCache` 只在 `resetCache()` 里快照进 `cacheParams`
   * （`main.esm.mjs:55750-55776`），驱逐读的是那份快照（`:55481-55482`），而属性监听只有
   * `datasource` 与 `cacheBlockSize` 两条（`:55682-55683`；`rowHeight` 那条只补
   * `cacheParams.rowHeight`）。`purgeInfiniteCache()` 走
   * `InfiniteRowModel.purgeCache → InfiniteCache.purgeCache`（`:55585-55594`），
   * 只 `removeBlockFromCache` + `onCacheUpdated`，**不**重建快照。于是「设置 ≤ 205 ⇒
   * 窄宽两块大小同为 100、只有块数从 20 变 8」这条路上封顶完全不生效
   * （1,728 列 × 100 行 × 20 块 ≈ 117 MiB 照旧驻留）。
   *
   * 换身份走 `addManagedPropertyListener("datasource", …)` → `setDatasource` →
   * `reset` → `resetCache`（`:55682`、`:55704-55710`、`:55727-55737`）：块全丢 **且** 快照重取。
   * 时序上不需要 `flush: 'post'`（前一份报告说需要，是错的）：
   * ① `updateGridOptions` 先把**全部**值写进 `gridOptions`（`:28371-28387`），
   *    之后才逐条派发属性事件（`:28390-28393`）⇒ `datasource` 监听跑起来时
   *    `gos.get("maxBlocksInCache")` 已是新值；
   * ② Vue 包装器把同一 tick 的多个 prop 变更合进一个 `l` 对象、一次
   *    `_processOnChange`（`ag-grid-vue3/dist/main.mjs:1182-1188` → `:2278-2295`
   *    → `GridOptionsSvc` `:28318-28322`）。
   * 代价与收益：`setDatasource` 已经把整叠块丢了 ⇒ 换文件时 `reload()` 里那次
   * `purgeInfiniteCache()` 变成多余，删掉它才是「同一块少打一次 `/browse/`」（Task 5 的形状）。
   * 判据：`e2e/data/view-data.spec.ts` 的「窄→宽…能看见驱逐」（T3，只有真浏览器 + 真 ag-grid
   * 能观察到第二次 page=1）；本文件那两条 T2 只钉守卫，钉不了这条。
   */
  function keyedDatasource(source: IDatasource): IDatasource {
    // 读一遍才登记依赖；值本身用不上（Vue 比的是返回对象的身份）
    void `${props.fileId}|${blockSize.value}|${maxBlocks.value}`
    return { ...source }
  }

  function markGridDead() {
    gridAlive.value = false
  }

  /**
   * 还能接调用的 grid 引用：三道闸缺一不算活。
   * ① `gridAlive` —— onGridReady 之前（首块前的任何异步续体）；
   * ② `gridApi` 非 null —— 空态标签压根没挂 ag-grid（`v-if="!fileId"`）；
   * ③ `!api.isDestroyed()` —— grid 先于组件被销毁（清横幅 / 404），此时①②都还是「真」的。
   * ③ 是 ag-grid 自己给的事实源：`CommunityCoreModule.apiFunctions.isDestroyed`
   * （`main.esm.mjs:38391`）返回 `gridDestroySvc.destroyCalled`（`:14756-14758`），
   * 也正是 warning #26 文案里点名要用的那个方法（`:38793`）。
   */
  function liveGridApi(): GridApi | null {
    const api = gridApi.value
    if (!gridAlive.value || !api || api.isDestroyed()) return null
    return api
  }

  /**
   * 所有「打已就绪 grid」的调用（purge、`ensureIndexVisible` …）唯一的入口。
   * 不要绕过它写 `gridApi.value?.xxx()` —— `?.` 只挡 null，挡不住已销毁实例，
   * 也挡不住「onGridReady 还没跑」那一段。
   */
  function withLiveGrid(fn: (api: GridApi) => void) {
    const api = liveGridApi()
    if (!api) return
    fn(api)
  }

  /**
   * 只在 grid 还活着时清块缓存。所有 purge 入口（reload / onDeactivated / watch(active)）
   * 都必须走这里，理由同 `withLiveGrid`。
   */
  function purgeCacheIfAlive() {
    withLiveGrid((api) => api.purgeInfiniteCache())
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
    applyBlockSize,
    markGridAlive,
    markGridDead,
    /** 打已就绪 grid 的唯一入口（ensureIndexVisible 这类 api 调用必须走它，别自己判 gridAlive） */
    withLiveGrid,
    purgeCacheIfAlive,
    /** 换身份的 datasource 包装：见其注释 */
    keyedDatasource,
  }
}

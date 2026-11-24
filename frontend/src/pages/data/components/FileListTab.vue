<template>
  <div class="file-list-tab">
    <!-- Toolbar -->
    <FileListToolbar
      :total="total"
      :selected-count="selectedIds.length"
      :usage="usage"
      :hidden-filter="hiddenFilter"
      :combinations="combinations"
      :combination-id="combinationFilter"
      @combination-change="onCombinationFilterChange"
      @assign-click="openImportDialog"
      @search="onSearch"
      @hidden-filter-change="onHiddenFilterChange"
      @upload-click="showUpload = !showUpload"
      @fix-click="showConsistencyCheck = true"
      @bulk-delete="onBulkDelete"
      @combine-click="onCombine"
    />

    <!-- Upload Area -->
    <FileUploadArea
      :visible="showUpload"
      :active="active"
      :combinations="combinations"
      @upload-success="onUploadSuccess"
    />

    <!-- File Table（表头内嵌筛选：产品/格式/文件名/程序/标签；服务端分页筛选） -->
    <FileListTable
      ref="tableRef"
      :files="files"
      :loading="loading"
      :filters="filters"
      :product-codes="productCodes"
      :format-types="formatTypes"
      :all-tags="allTags"
      @view-file="viewFile"
      @row-click="onRowClick"
      @delete-file="deleteFile"
      @toggle-hidden="onToggleHidden"
      @sort-change="onSortChange"
      @selection-change="onSelectionChange"
      @tags-changed="loadAllTags"
    />

    <!-- Active filter chips -->
    <div v-if="hasActiveFilters" class="active-filters">
      <span class="filter-hint">
        已启用 {{ activeFilterCount }} 项表头筛选
        <el-button size="small" text type="primary" @click="clearFilters">清除全部</el-button>
      </span>
    </div>

    <!-- Pagination -->
    <div class="list-pagination">
      <el-pagination
        v-if="total > pageSize"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        background
        @current-change="onPageChange"
      />
    </div>

    <!-- Consistency Check Dialog -->
    <ConsistencyCheckDialog
      v-model:visible="showConsistencyCheck"
      :usage="usage"
      @done="onConsistencyDone"
    />

    <!-- 组合为批次（新建 / 追加到已有批次） -->
    <CombineBatchDialog
      v-model:visible="showCombineDialog"
      :selected-count="selectedIds.length"
      :batch-options="combineBatchNames"
      :combinations="combinations"
      @submit="onCombineSubmit"
    />

    <ImportOptionsDialog
      v-model:visible="importDialogVisible"
      :combinations="combinations"
      :selected-count="selectedIds.length"
      @submit="assignCombination"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch, onActivated } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datafilesApi, type FileUsage } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'
import { useCoalescedCall } from '../../../composables/useCoalescedCall'
import FileListToolbar, { type HiddenFilter } from './FileListToolbar.vue'
import FileUploadArea from './FileUploadArea.vue'
import ConsistencyCheckDialog from './ConsistencyCheckDialog.vue'
import CombineBatchDialog from './CombineBatchDialog.vue'
import ImportOptionsDialog from './ImportOptionsDialog.vue'
import FileListTable, { type FileFilters } from './FileListTable.vue'
import { useCombinationSelection } from '../composables/useCombinationSelection'

withDefaults(defineProps<{
  active?: boolean
}>(), {
  active: true,
})

const emit = defineEmits<{
  'view-file': [id: number, filename: string]
  'row-click': [id: number, filename: string]
  'total-change': [total: number]
}>()

const filesStore = useFilesStore()

// ── Core state ──────────────────────────────────────────────────────
const files = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20

const usage = ref<FileUsage | null>(null)
const productCodes = ref<string[]>([])
const formatTypes = ref<string[]>([])
const allTags = ref<string[]>([])
const selectedIds = ref<number[]>([])
const tableRef = ref<InstanceType<typeof FileListTable>>()

const {
  combinations, combinationFilter, importDialogVisible, loadCombinations,
  onCombinationFilterChange, openImportDialog, assignCombination,
} = useCombinationSelection({
  selectedIds,
  onFilterChange() {
    currentPage.value = 1
    tableRef.value?.clearSelection()
    loadFiles()
  },
  async onAssigned() {
    tableRef.value?.clearSelection()
    selectedIds.value = []
    await loadFiles()
    filesStore.notifyFilesChanged()
  },
})

// Current global keyword search (toolbar)
const currentSearch = ref('')

// 隐藏状态筛选（服务端生效）：'all' = 含隐藏；'visible' = 缺省只返回未隐藏；'hidden' = 只看已隐藏。
// 与表头筛选同属用户驱动的列表变化 ⇒ 切换时先 clearSelection（见 onSortChange 上方那段约定）。
const hiddenFilter = ref<HiddenFilter>('all')

function onHiddenFilterChange(value: HiddenFilter) {
  hiddenFilter.value = value
  currentPage.value = 1
  tableRef.value?.clearSelection()
  loadFiles()
}

// ── 表头筛选（服务端生效：20 条/页必须后端过滤；状态由 FileListTable 读写） ──
const filters = reactive<FileFilters>({
  filename: '',
  productCode: '',
  formatType: '',
  program: '',
  tag: '',
})

const activeFilterCount = computed(
  () => Object.values(filters).filter((v) => v !== '').length,
)
const hasActiveFilters = computed(() => activeFilterCount.value > 0)

// 表头排序：默认最新上传在前（与服务端 ordering 一致，default-sort 显示箭头）
const ordering = ref('-created_at')

// Upload / dialog toggles
const showUpload = ref(false)
const showConsistencyCheck = ref(false)

/**
 * 表头排序变化（服务端排序：20 条/页必须后端排，不能本地 sort）
 *
 * 勾选策略（与 `FileListTable.vue:25` 的 `reserve-selection` 配套）——
 * EP 2.14 的 `store/index.mjs` 在 `setData` 里是
 * `if (reserveSelection) assertRowKey(); else if (dataInstanceChanged) clearSelection();
 * else cleanSelection()`：勾了 `reserve-selection` 就走第一条，**后两条一起被短路**。
 * 被跳过的正是「换了数组实例 ⇒ 全清」与「按 row-key 把已不在 data 里的行踢出选中集并
 * emit `selection-change`」这两件事，于是「写后刷新」（`filesVersion` watch /
 * `onUploadSuccess` / `onConsistencyDone`）能保住选中行 —— 这是 FIX-1 要保留的行为。
 * 但同一个短路也会让**用户驱动的列表变化**（搜索 / 筛选 / 翻页 / 排序）留下的
 * `selectedIds` 指向已经不在当前列表里的行，批量删除就会删到看不见的文件。
 * 所以凡是由用户的视图操作引发的 `loadFiles()`，一律先显式 `clearSelection()`
 * （`selectedIds` 由 `selection-change` 跟着归零）。写后刷新那三条**不要**加。
 * 兜底收敛在 `reconcileSelection()`（`loadFiles` 的 finally）：它只在「有选中 id 不在
 * 当前列表里」时清选，写后刷新一行不动，覆盖失败清空与翻页/重排两种漏网。
 */
function onSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  if (!prop || !order) {
    ordering.value = '-created_at' // 取消排序 → 回默认最新在前
  } else {
    const sign = order === 'descending' ? '-' : ''
    ordering.value = `${sign}${prop}`
  }
  currentPage.value = 1
  tableRef.value?.clearSelection()
  loadFiles()
}

function clearFilters() {
  filters.filename = ''
  filters.productCode = ''
  filters.formatType = ''
  filters.program = ''
  filters.tag = ''
  currentPage.value = 1
  tableRef.value?.clearSelection()
  loadFiles()
}

// ── Data loading ────────────────────────────────────────────────────

/**
 * 勾选只允许覆盖当前页可见行：刷新后选中 id 若已不在列表里（失败清空/翻页重排），立即清选。
 *
 * `reserve-selection` 短路了 EP 的 `clearSelection()` / `cleanSelection()`（见
 * `onSortChange` 上方），而 `selectedIds` 只由 `selection-change` 重写 ⇒ 列表变空或整页
 * 换掉时 EP 不 emit，勾选就会悬在看不见的行上（工具栏继续显示 `批量删除 (N)`，点下去删的
 * 是用户已经看不到的文件）。这是**唯一**的兜底收敛点：只在「有选中 id 不在当前列表里」
 * 时才动手，写后刷新（FIX-1）与挨个清选（EP 自己会 emit 空集）都不受影响。
 *
 * 必须在 `files.value` 之后同步跑：`clearSelection()` 在旧选择非空时 emit `[]`
 * （EP `store/watcher.mjs` 里的 `selectedMap` 是从 `selection` 派生的，清完不会复活）。
 */
function reconcileSelection() {
  const visible = new Set(files.value.map((f: any) => f.id))
  if (selectedIds.value.some((id) => !visible.has(id))) {
    tableRef.value?.clearSelection()
  }
}

async function loadFiles() {
  loading.value = true
  try {
    const { data } = await datafilesApi.listFiles({
      page: currentPage.value,
      search: currentSearch.value,
      file_type: 'single',
      product_code: filters.productCode,
      format_type: filters.formatType,
      filename__icontains: filters.filename,
      program_name__icontains: filters.program,
      tag: filters.tag,
      combination_id: combinationFilter.value ?? undefined,
      include_hidden: hiddenFilter.value === 'all' ? 1 : undefined,
      hidden_only: hiddenFilter.value === 'hidden' ? 1 : undefined,
      ordering: ordering.value,
    })
    if (Array.isArray(data)) {
      files.value = data
      total.value = data.length
    } else {
      files.value = data.results ?? []
      total.value = data.count ?? files.value.length
    }
    emit('total-change', total.value)
  } catch {
    files.value = []
    total.value = 0
    emit('total-change', 0)
  } finally {
    loading.value = false
    reconcileSelection()
  }
}

async function loadProductCodes() {
  try {
    const { data } = await datafilesApi.getProductCodes()
    productCodes.value = data.product_codes ?? []
  } catch {
    productCodes.value = []
  }
}

async function loadFormatTypes() {
  try {
    const { data } = await datafilesApi.getFormatTypes()
    formatTypes.value = data.format_types ?? []
  } catch {
    formatTypes.value = []
  }
}

async function loadAllTags() {
  try {
    const { data } = await datafilesApi.listTags()
    allTags.value = Array.isArray(data?.tags) ? data.tags : []
  } catch {
    allTags.value = []
  }
}

/**
 * 占用统计单独一趟，不并进 `loadFiles`：它要扫整棵目录树。本机 dev 树 112 个文件，
 * `get_user_usage(user, fresh=True)` 现量 5 次 = 3.21–6.20 ms（均值 3.92，2026-11-14；
 * dev 档三个用户 admin/user/viewer 里只有 admin 有数据，两棵空树 0.19–0.25 ms）；
 * Task 1 探针在同类树上量到 11.4 ms，两者都远低于设计稿停下来回口径的那道 300ms。
 * **不 await** —— chip 缺席不能连累文件列表（Task 8 的 e2e 用 500 拦这条，钉的是
 * 「列表照常、chip 不出现」；首屏就失败时 `usage` 从来没被写过、仍是 null，那条判据照旧成立）。
 *
 * `usageSeq` 是序号守卫，形状照 `composables/useAsyncData.ts` 的 seq（那边有 T2 钉着
 * 「过期响应不写 data」）：loadUsage 发后即忘、**不取消**，两次在途就可能反序落地，
 * 后到的旧载荷会把 chip 退回上一个数。后端的 KeyedLRU 单飞只合并「到达时间重叠同一次
 * 计算」的两次请求，两次 `fresh=1` 隔几秒就是两份不同载荷，前端这一层必须自己判过期。
 */
let usageSeq = 0

async function loadUsage(fresh = false) {
  const my = ++usageSeq
  try {
    const { data } = await datafilesApi.getFileUsage(fresh)
    if (my !== usageSeq) return // 过期响应：丢弃，不覆盖更新的数
    usage.value = data
  } catch {
    // 过期那一趟的失败同样什么都不做（拦截器的 toast 已经响了，这里没法撤回，也不该撤回）。
    if (my !== usageSeq) return
    // 失败时刻意**不**把 usage 置空。这与本文件另外四个 loader（loadFiles /
    // loadProductCodes / loadFormatTypes / loadAllTags）的「裸 catch + 重置状态」相反，
    // 是**有意的偏差**，不是漏改 —— 为了「和邻居一致」把它改回来就会重新引入这个 bug。
    // 三条各自独立的理由：
    // ① 拦截器（`api/index.ts` 的 NO_TOAST_ENDPOINTS 不含 /files/usage/）已经为这次失败
    //    弹过 toast 并 console.error 了，再让 chip 消失等于同一个故障发两条互相矛盾的
    //    信号：一句「服务器错误」＋一次工具栏重排把数拿走。
    // ② 瞬时故障会把它变成长期故障：报错的那一刻用户正看着这块面板，而本页没有任何
    //    「重试」路径 —— 只有下一次写操作（上面那条 watch）或离开再回来（下面那段
    //    onActivated）才会重新拉到一个数。置空 = 让他眼前的数消失到那时为止。
    // ③ `apps/datafiles/storage_usage.py` 对 `''` / `.` / `..` 直接 raise ValueError，而
    //    Django 的 UnicodeUsernameValidator **接受** `..` 当用户名 ⇒ 这种账号每一次请求
    //    都是 500，置空等于这个 chip 永久消失。
    // chip 缺席只应来自「成功但确实没数据」或「首屏那一次就失败」，不该来自一次瞬时故障。
    // 陈旧量由载荷里的 `scanned_at` 自己披露，这里不加重试、不加第二套 UI 状态、不加错误横幅。
  }
}

/**
 * 写操作后的失效刷新走合并器。为什么会有突发（不是假想）：`FileUploadArea.vue` 的
 * input 带 `multiple`，每个成功文件 emit 一次 `upload-success`，而 Element Plus 的
 * upload-content 逐条 dispatch、彼此不 await ⇒ K 个文件的响应落在 K 个 tick 上
 * ⇒ K 次 filesVersion watch 重入 ⇒ K 次全盘扫描。
 * leading+trailing ⇒ 单个写操作仍然立即刷新（零额外延迟），K 连发塌成 2 次，
 * 且尾巴那一次看到的是最终状态。
 *
 * 窗口 800ms 是对着三个量选的（其中两个本机现量），不是抄 analysis 那四处 150ms：
 * ① 下界必须盖住突发里两次 emit 的间隔 = 一次上传往返。本机现量：一个走完整 Django
 *    中间件的 GET 往返 1.7–20.8 ms（`curl -w %{time_total}` ×5，未鉴权 ⇒ 是下界，真实
 *    上传还要再叠一次落盘 + 解析），800ms ≈ 最慢那次的 38 倍，够一整条 burst 排在后面。
 *    analysis 那四处用 150ms 是因为触发器是**人手连点**（间隔就是点击间隔），这里触发器
 *    是服务端响应，不能照抄。
 * ② 上界由「用户还把这一下当成刚才那次操作的回应」定：burst 期间用户本来就在看上传进度条，
 *    而且 leading 已经把**单个**写操作（最常见路径）的感知延迟压到 0，付这 800ms 的只有
 *    真正连发的那种场景。
 * ③ 与后端 TTL 的关系：30s（`storage_usage.py` 的 `USAGE_CACHE_TTL_SECONDS`）的 2.7%，
 *    且 trailing 带 `fresh=1` 本来就绕过缓存 ⇒ 窗口不会把结果推到换桶边缘。
 */
const USAGE_TRAIL_MS = 800
const reloadUsage = useCoalescedCall((fresh: boolean) => loadUsage(fresh), USAGE_TRAIL_MS)

// ── Toolbar event handlers ──────────────────────────────────────────
function onSearch(text: string) {
  currentSearch.value = text
  currentPage.value = 1
  tableRef.value?.clearSelection() // 用户驱动的列表变化：不保留看不见行的勾选（见 onSortChange 上方）
  loadFiles()
}

function onUploadSuccess() {
  loadFiles()
  filesStore.notifyFilesChanged()
}

function onConsistencyDone() {
  loadFiles()
  filesStore.notifyFilesChanged()
}

// ── 组合为批次（新建 / 追加到已有批次） ─────────────────────────────
const showCombineDialog = ref(false)
const combineBatchNames = ref<string[]>([])

async function onCombine() {
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请先勾选要组合的文件')
    return
  }
  // 追加模式的候选批次（已注册批次名）
  try {
    const { data } = await datafilesApi.listBatchDirs()
    const dirs = Array.isArray(data) ? data : []
    combineBatchNames.value = dirs.filter((d) => d.registered).map((d) => d.name)
  } catch {
    combineBatchNames.value = []
  }
  showCombineDialog.value = true
}

async function onCombineSubmit(payload: {
  batchName: string
  combinationId?: number | null
  batchNo?: string
}) {
  try {
    const { data } = await datafilesApi.combineFiles([...selectedIds.value], payload.batchName, {
      combinationId: payload.combinationId,
      batchNo: payload.batchNo,
    })
    ElMessage.success(`已组合 ${data.combined} 个文件为批次 "${data.batch_name}"`)
    tableRef.value?.clearSelection()
    selectedIds.value = []
    showCombineDialog.value = false
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    // 失败时保留弹窗（错误 toast 由拦截器弹出），用户可改批次名重试
  }
}

// ── Pagination ──────────────────────────────────────────────────────
function onPageChange(page: number) {
  currentPage.value = page
  tableRef.value?.clearSelection() // 翻页同属用户驱动的列表变化（见 onSortChange 上方）
  loadFiles()
}

function onSelectionChange(ids: number[]) {
  selectedIds.value = ids
}

// ── Hide / unhide（软隐藏：只影响选文件候选） ────────────────────────
async function onToggleHidden(row: any) {
  const next = !row.is_hidden
  try {
    await datafilesApi.setHidden(row.id, next)
    ElMessage.success(next ? '文件已隐藏' : '已取消隐藏')
    await loadFiles()
  } catch {
    // 出声交给 axios 拦截器（页面不自造错误 toast 的既有约定）；失败不做乐观更新。
  }
}

// ── Delete operations ───────────────────────────────────────────────
async function deleteFile(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${row.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.remove(row.id)
    ElMessage.success('文件已删除')
    // 单条删除后不得留下指向已删行的勾选（reserve-selection 会按 row-key 试图还原它）
    tableRef.value?.clearSelection()
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function onBulkDelete() {
  if (selectedIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedIds.value.length} 个文件吗？磁盘上的源文件也会被一并移除，此操作不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    const ids = [...selectedIds.value]
    const { data } = await datafilesApi.bulkDelete(ids)
    ElMessage.success(`已删除 ${data?.deleted ?? ids.length} 个文件`)
    tableRef.value?.clearSelection()
    selectedIds.value = []
    if (files.value.length === ids.length && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

// ── Row interactions ────────────────────────────────────────────────
function viewFile(id: number, filename: string) {
  emit('view-file', id, filename)
}

function onRowClick(id: number, filename: string) {
  emit('row-click', id, filename)
}

// ── External refresh watcher ────────────────────────────────────────
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
  // 每一条本地写路径（上传/删除/批量删除/组合/修复）都会 bump filesVersion，
  // 所以这一行覆盖全部「做完就要看到新数」的场景，不需要在各处分别挂失效。
  // 多文件上传会连发 K 次，所以这里经过合并器（见上面 USAGE_TRAIL_MS 那段）。
  reloadUsage(true)
})

// 表头筛选值变化 → 刷新（FileListTable 内 ColumnHeaderFilter 写入 filters）
watch(filters, () => {
  currentPage.value = 1
  tableRef.value?.clearSelection() // 筛选属用户驱动的列表变化（见 onSortChange 上方）
  loadFiles()
}, { deep: true })

// 占用 chip 的「进入即拉」挂 onActivated，**不挂** onMounted —— 与本仓既有的承重约定同形：
// `MainLayout.vue:12` 用 `<keep-alive :max="10">` 包路由页且没有 include/exclude，本组件是
// `DataManagement` 的子孙，跟着一起被缓存 ⇒ 首次进入 mounted 与 activated **都**触发，
// 两处各拉一次就是每次进 /data 多发一条 `/files/usage/`（同一族的缺陷形态与实测见
// `DataManagement.vue` 里 `onActivated(loadFiles)` 上方那段注释，判据是
// `e2e/data/data.spec.ts`「进数据管理页只发一次全量文件列表」；子组件用 activated 的先例是
// `dashboard/components/BatchYieldTab.vue` 的 `onActivated`）。别把它挪回 onMounted。
//
// 为什么这一趟必须是激活级而不是只在挂载时跑一次：用户从资源管理器把文件直接拷进数据目录
// 是这块读数的旗舰场景，而 keep-alive 下 mounted 一个会话只跑一次 ⇒ 那些文件整个会话都不会
// 出现在数里，除非他碰巧上传或删除了什么。`storage_usage.py` 头部那句「≤30s 陈旧」是**后端
// 内部**的界，端到端不成立，所以载荷里放了 `scanned_at` 来披露这个窗口。写操作那条 watch
// 只覆盖「他自己在应用里做的写」，所以导航回来这一趟是把端到端窗口钉回 ≤30s 的唯一入口。
//
// fresh=false ⇒ 命中后端 30s 分桶 TTL：导航来回最坏也只是多次缓存命中，不会变成「每次导航
// 扫一遍盘」。另外四个 loader 的挂载口径见下面 FIX-4 那段：同为 activation 级、首进恰好一次，
// 判据 `e2e/data/file-list-activation.spec.ts`（六类请求各一次）。
//
// FIX-4（2026-11-17）：四个 sibling loader 与占用 chip 同一口径，全部挂 onActivated，
// **不要**再补一个 onMounted。机理是 Vue 把子孙组件的 `activated` 注册到最近的那个
// keep-alive 根上（`runtime-core` 的 `registerKeepAliveHook`：先 `injectHook` 进组件自己，
// 再沿 parent 链 `injectToKeepAliveRoot`）—— 于是一次挂载期内**首进就触发一次**
// （KeepAlive 首次 patch 时 `instance.a` 随 mounted 一起排队），之后每次重新激活各一次。
// 再加 onMounted 就是每个会话白白多发一整轮。
// 判据：`e2e/data/file-list-activation.spec.ts` 的「首屏六类请求各一次」（计数器先装、
// 再进页面，钉的就是这条）与「激活回 /data 六类各一次」；全量列表那一条对照
// `data.spec.ts` 的「只拉一次」。
// 已知代价（接受）：`onActivated` **只在 keep-alive 内生效**。若将来有入口不经
// `MainLayout.vue` 的 `<keep-alive>` 直接渲染本组件，这里五个 loader 会**一次都不跑** ——
// 表现为空表、且没有任何报错（不是 500、不是超时，是压根没发请求）。
onActivated(() => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
  loadCombinations()
  loadUsage()
})

defineExpose({ reload: loadFiles })
</script>

<style scoped>
.list-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.active-filters {
  display: flex;
  align-items: center;
  margin-top: 8px;
}

.filter-hint {
  font-size: var(--p-fs-dense);
  color: var(--text-3);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .filter-hint {
  color: rgba(255, 255, 255, 0.5);
}
</style>

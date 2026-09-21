<template>
  <div class="sftp-search-page">
    <div class="page-header">
      <div class="header-icon">
        <el-icon :size="30" aria-hidden="true"><Search /></el-icon>
      </div>
      <div class="header-title">
        <h2>SFTP 搜索</h2>
        <p class="header-subtitle">范围 → 过滤 → 命中；结果与运行状态在本应用内跨页面驻留</p>
      </div>
      <el-button :icon="Back" @click="router.push({ name: 'SftpBrowser' })">返回浏览器</el-button>
    </div>

    <!-- 未连接（计划 Step 2）：不探测、不为它新开端点 —— 400 里的 not_connected 才是权威信号 -->
    <el-alert v-if="connBlocked" class="ssp-alert" type="error" show-icon :closable="false"
              title="尚未建立 SFTP 连接，搜索无法开始">
      <div class="ssp-alert-body">
        <span>搜索要用已建立的 SFTP 会话。请先在 SFTP 浏览器连接，再回来点「搜索」。</span>
        <el-button size="small" type="primary" data-testid="sftp-search-goto-connect" @click="goConnect">去连接</el-button>
      </div>
    </el-alert>
    <el-alert v-else-if="connHint" class="ssp-alert" type="info" show-icon :closable="false"
              title="当前没有可自动重连的 SFTP 配置">
      <div class="ssp-alert-body">
        <span>若还没在 SFTP 浏览器里连接，搜索会直接失败——先连一次更省事。</span>
        <el-button size="small" :icon="Link" @click="goConnect">去连接</el-button>
      </div>
    </el-alert>

    <SearchCriteria
      v-model="spec"
      :current-path="currentPath"
      :presets="presetList"
      :can-run="store.canStart"
      @run="onRun"
      @save-preset="onSavePreset"
      @delete-preset="onDeletePreset"
    />

    <template v-if="run">
      <SearchProgress
        :stage="run.progress?.stage ?? 'listing'"
        :status="run.status"
        :done="run.progress?.done ?? 0"
        :total="run.progress?.total ?? null"
        :elapsed-s="elapsedSeconds"
        :matched="run.matchCount"
        :candidates="run.candidateCount"
        :engine="run.engine"
        :engine-reason="run.engineReason"
        :workers-actual="run.workersActual"
        :truncated="run.status === 'partial' || !!run.done?.truncated"
        :limits-hit="run.done?.limits_hit ?? []"
        @cancel="store.cancel(run.id)"
      />

      <div v-if="runErrors.length" class="ssp-errors">
        <p v-for="(e, i) in runErrors.slice(0, 5)" :key="i" class="ssp-error-line">
          [{{ e.scope }}] {{ e.path || '—' }}：{{ e.message }}
        </p>
        <p v-if="runErrors.length > 5" class="ssp-error-more">另有 {{ runErrors.length - 5 }} 条同类错误</p>
      </div>

      <SearchResultsTable
        :candidates="run.candidates"
        :matches="run.matches"
        :mode="run.spec.mode"
        :engine="run.engine"
        :term="run.spec.term ?? ''"
        :grouped="grouped"
        :case-sensitive="!!run.spec.case_sensitive"
        :actions-disabled="transferActive"
        :actions-disabled-reason="transferReason"
        @download="paths => transfer(paths, false)"
        @download-parse="paths => transfer(paths, true)"
        @export="onExport"
        @toggle-group="toggleGroup"
      />
    </template>
    <el-empty v-else description="还没有搜索记录：先加搜索目录，再点「搜索」" />

    <!-- 底部动作条：运行历史与再搜一次（下载/导出在结果表的动作带上，同一套互斥判据） -->
    <div class="ssp-bar">
      <span class="ssp-bar-label">本会话运行</span>
      <el-select v-model="pickedRunId" class="ssp-run-select" size="small" placeholder="选择一次运行"
                 data-testid="sftp-search-run-history">
        <el-option v-for="o in runOptions" :key="o.id" :label="o.label" :value="o.id" />
      </el-select>
      <el-tooltip :content="store.canStart ? '用这套条件再搜一次' : '上一次搜索还在收尾，稍候即可'" placement="top">
        <span class="ssp-tip-anchor">
          <el-button size="small" :icon="Refresh" :disabled="!run || !store.canStart" data-testid="sftp-search-rerun" @click="onRerun">
            再搜一次
          </el-button>
        </span>
      </el-tooltip>
      <el-button size="small" :disabled="!finishedCount" @click="store.clearFinished()">清除已结束</el-button>
      <span class="ssp-bar-note">切到别的页面搜索照跑（右上角常驻条可取消）；搜索期间下载按钮禁用。</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * SFTP 搜索页（计划 Task 17 Step 1–2 / spec §3.13）。
 *
 * **页面不持流**：run 的全部状态从 `useSftpSearchStore` 读（`activeRun`，或用户在底部
 * 条里从历史选中的那条）。SSE 的读循环住在 store 里，所以切路由/组件卸载都不会打断它 ——
 * 本页**故意不写** `onBeforeUnmount`/`onDeactivated` 里的 abort（spec §3.9 第 5 条）。
 *
 * 组件分工：`SearchCriteria` 只管表单值与校验（判据 `canRun` = store 的 `canStart`），
 * `SearchProgress` 只管渲染三态进度，`SearchResultsTable` 只管行集渲染与勾选。
 * 页面负责三件事：把 run 摊平成 props、跑预设的增删查、执行导出与下载。
 *
 * 下载互斥（Step 5.3）：`transferActive` = 本页一次下载在跑 ∨ 搜索在跑 ∨ 取消冷却中，
 * 与 `SftpBrowser.vue` 里那份同源同判据（都读 store 的 `isRunning`/`inCancelCooldown`），
 * 冷却只记一次时钟（Step 6）。
 */
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back, Link, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { isNotConnectedMessage, sftpSearchApi } from '../../api/sftpSearch'
import type { SearchPresetItem, SearchSpec } from '../../api/sftpSearch'
import { sftpApi } from '../../api/sftp'
import { useFilesStore } from '../../stores/files'
import { AUTO_GROUP_THRESHOLD, resultRows, useSftpSearchStore } from '../../stores/sftpSearch'
import { getSftpTimeoutSec } from '../../utils/sftpTimeout'
import { exportSearchResults } from '../../utils/sftpSearchExport'
import SearchCriteria from './components/SearchCriteria.vue'
import SearchProgress from './components/SearchProgress.vue'
import SearchResultsTable from './components/SearchResultsTable.vue'

const route = useRoute()
const router = useRouter()
const store = useSftpSearchStore()
const filesStore = useFilesStore()

const spec = ref<SearchSpec>({ roots: [], mode: 'name' })
const currentPath = ref('')
const presetList = ref<SearchPresetItem[]>([])
const downloadTimeoutSec = ref(600)

// ---------------------------------------------------------------- 入口与连接提示

function goConnect(): void { router.push({ name: 'SftpBrowser' }) }

/**
 * `query.root` 是「高级搜索」按钮与目录行右键菜单带进来的目录（Step 5.1/5.2）：
 * 填进 roots，同时留作 `currentPath`，「使用当前目录」按钮才有东西可用。
 * keep-alive 会缓存本页，所以 `onMounted` 之外还要 `onActivated` —— 第二次从浏览器
 * 进来时组件不重新挂载，只靠 onMounted 的话新目录根本不会填进来。
 */
function applyQueryRoot(): void {
  const raw = typeof route.query.root === 'string' ? route.query.root.trim() : ''
  if (!raw.startsWith('/')) return
  currentPath.value = raw
  const have = spec.value.roots ?? []
  if (!have.includes(raw)) spec.value = { ...spec.value, roots: [...have, raw] }
}

/** 挂载时的软提示：只读现成的 `last_visit`，不探测连接（项目没有那个端点，也不新建） */
const autoConnectHint = ref(false)
async function checkVisit(): Promise<void> {
  try {
    const { data } = await sftpApi.getLastVisit()
    autoConnectHint.value = data?.can_auto_connect !== true
  } catch { /* 取不到就当没有提示：权威信号是 400 里的 not_connected */ }
}

/** 收到过 `hello` 就说明连接是活的，软提示该退场 */
const everConnected = computed(() => store.runs.some(r => r.engine !== null))
const connBlocked = computed(() =>
  (run.value?.errors ?? []).some(e => e.scope === 'fatal' && isNotConnectedMessage(e.message)))
const connHint = computed(() => autoConnectHint.value && !connBlocked.value && !everConnected.value)

// ---------------------------------------------------------------- run 与结果行

const run = computed(() => store.activeRun)
const rows = computed(() =>
  (run.value ? resultRows(run.value.candidates, run.value.matches, run.value.spec.mode) : []))
const elapsedSeconds = computed(() =>
  run.value?.done?.elapsed_s ?? run.value?.progress?.elapsed_s ?? 0)
const runErrors = computed(() =>
  (run.value?.errors ?? []).filter(e => !isNotConnectedMessage(e.message)))
const finishedCount = computed(() => store.runs.filter(r => r.status !== 'running').length)

/** 超过阈值默认分组（spec §3.13），但用户手动切过之后就不再自动改他的视图 */
const grouped = ref(false)
const groupTouched = ref(false)
watch(() => rows.value.length, n => {
  if (!groupTouched.value) grouped.value = n > AUTO_GROUP_THRESHOLD
})
watch(() => run.value?.id, () => {
  groupTouched.value = false
  grouped.value = rows.value.length > AUTO_GROUP_THRESHOLD
})
function toggleGroup(): void {
  groupTouched.value = true
  grouped.value = !grouped.value
}

// ---------------------------------------------------------------- 互斥与动作

type TransferKind = 'download' | 'parse' | null
const pageTransfer = ref<TransferKind>(null)
const transferActive = computed(() =>
  pageTransfer.value !== null || store.isRunning || store.inCancelCooldown)
const transferReason = computed(() => {
  if (store.isRunning) return '搜索进行中不能同时下载：两者抢同一条按用户复用的 SFTP 连接'
  if (pageTransfer.value) return '本页已有一次下载在进行'
  return '上一次传输还在收尾（1.2s 冷却），稍候即可'
})

/** 计划 Step 1 的两个动作：单文件走 `download`，多文件/要解析走批量端点 */
async function transfer(paths: string[], parse: boolean): Promise<void> {
  if (!paths.length || transferActive.value) return
  pageTransfer.value = parse ? 'parse' : 'download'
  const cfg = { timeout: downloadTimeoutSec.value * 1000 }
  try {
    if (parse) {
      const { data } = await sftpApi.downloadAndParseBatch(paths, cfg)
      ElMessage.success(`已导入并解析 ${data.files?.length ?? 0}/${paths.length} 个文件（批次: ${data.batch_name}）`)
    } else if (paths.length === 1) {
      await sftpApi.download(paths[0])
      ElMessage.success(`已下载 ${paths[0].split('/').pop()}`)
    } else {
      const { data } = await sftpApi.downloadBatch(paths, cfg)
      ElMessage.success(`已导入 ${data.count} 个文件`)
    }
    filesStore.notifyFilesChanged()
  } catch { /* 错误 toast 由 axios 拦截器统一弹出 */ }
  finally { pageTransfer.value = null }
}

function onExport(): void {
  if (!run.value || !rows.value.length) return
  exportSearchResults(rows.value, run.value.spec.mode)
  ElMessage.success(`已导出 ${rows.value.length} 行 CSV`)
}

function onRun(): void { void store.start({ ...spec.value }) }
function onRerun(): void { if (run.value) void store.start({ ...run.value.spec }) }

// ---------------------------------------------------------------- 运行历史

const pickedRunId = computed<number | null>({
  get: () => store.activeRunId,
  set: id => { if (id !== null && id !== undefined) store.activeRunId = id },
})
const runOptions = computed(() => store.runs.map(r => ({
  id: r.id,
  label: `#${r.id} ${r.spec.mode} · ${r.status} · 命中 ${Math.max(r.matchCount, r.matches.length)}`,
})))

// ---------------------------------------------------------------- 预设与装载

async function loadPresets(): Promise<void> {
  try {
    const data = await sftpSearchApi.presets()
    presetList.value = data.presets ?? []
  } catch { /* 预设读不到不影响搜索：axios 拦截器已提示 */ }
}
async function onSavePreset(name: string): Promise<void> {
  try {
    await sftpSearchApi.savePreset(name, spec.value)
    ElMessage.success(`已保存预设「${name}」`)
    await loadPresets()
  } catch { /* 400 的 error 文案由拦截器弹出 */ }
}
async function onDeletePreset(id: number): Promise<void> {
  try {
    await sftpSearchApi.deletePreset(id)
    ElMessage.success('已删除预设')
    await loadPresets()
  } catch { /* 同上 */ }
}

onMounted(() => {
  applyQueryRoot()
  void checkVisit()
  void loadPresets()
  void (async () => {
    try { downloadTimeoutSec.value = await getSftpTimeoutSec() } catch { /* 回退 600s，与 SftpBrowser 同 */ }
  })()
})
onActivated(applyQueryRoot)
</script>

<style scoped>
.sftp-search-page { padding: 8px; }
.page-header {
  display: flex; align-items: center; gap: var(--p-space-4);
  margin-bottom: var(--p-space-5); padding: var(--p-space-4) var(--p-space-5);
  background: var(--bg-2); border: 1px solid var(--border-2);
  border-radius: var(--p-radius-md); box-shadow: var(--shadow-sm);
}
.header-icon {
  display: flex; align-items: center; justify-content: center;
  width: 52px; height: 52px; background: var(--bg);
  border-radius: var(--p-radius-md); box-shadow: var(--shadow-sm); color: var(--brand);
}
.header-title { flex: 1; }
.header-title h2 { margin: 0; font-size: var(--p-fs-headline); font-weight: var(--p-fw-semibold); color: var(--text); }
.header-subtitle { margin: 4px 0 0; font-size: var(--p-fs-small); color: var(--text-2); }
.ssp-alert { margin-bottom: var(--p-space-3); }
.ssp-alert-body { display: flex; align-items: center; gap: var(--p-space-3); flex-wrap: wrap; }

.ssp-errors {
  margin: var(--p-space-2) 0 var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-3);
  border: 1px solid var(--border-2); border-left: 3px solid var(--error);
  border-radius: var(--p-radius-sm); background: var(--bg-2);
}
.ssp-error-line, .ssp-error-more {
  margin: 0; font-size: var(--p-fs-micro); color: var(--text-2);
  font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ssp-error-more { color: var(--text-3); }

.ssp-bar {
  display: flex; align-items: center; gap: var(--p-space-2); flex-wrap: wrap;
  margin-top: var(--p-space-4); padding: var(--p-space-2) var(--p-space-3);
  background: var(--bg-2); border: 1px solid var(--border-2); border-radius: var(--p-radius-md);
}
.ssp-bar-label { font-size: var(--p-fs-dense); color: var(--text-2); }
.ssp-bar-note { margin-left: auto; font-size: var(--p-fs-micro); color: var(--text-3); }
.ssp-run-select { width: 220px; }
.ssp-tip-anchor { display: inline-flex; }
</style>

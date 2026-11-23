<template>
  <div class="admin-files">
    <el-form :model="filters" inline class="admin-files-filter" @submit.prevent="applySearch">
      <AdminPageToolbar>
        <template #left>
          <!-- data-testid 挂在 el-form-item 上（与 AuditLogPage 同约定）：ElInput/ElSelect 的
               attrs 落点由 EP 决定，挂控件上时「[data-testid] input」会数到 0 个。 -->
          <el-form-item label="用户" data-testid="admin-files-user">
            <el-select
              v-model="ownerId"
              filterable
              :loading="usersLoading"
              placeholder="选择要查看的用户"
              class="admin-filter-select admin-files-user-select"
            >
              <el-option
                v-for="u in users"
                :key="u.id"
                :label="userOptionLabel(u)"
                :value="u.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="搜索" data-testid="admin-files-search">
            <el-input
              v-model="filters.search"
              clearable
              placeholder="文件名 / 测试程序 / 批次 / 标签"
              class="admin-filter-input"
            />
          </el-form-item>
          <el-button native-type="submit">查询</el-button>
        </template>
        <template #right>
          <el-button :loading="busy" @click="refresh">刷新</el-button>
        </template>
      </AdminPageToolbar>
    </el-form>

    <p v-if="usersErrored" class="admin-files__hint">
      用户清单加载失败，可选账号暂不可用（点「刷新」重试）
    </p>

    <!-- 三颗 KPI 只认 usageBytesText 的形状（GB 封顶，null ⇒ '--'），口径唯一来源在
         KPI 那三个数各对应一个子树：数据树 / 作业产物树 / 两者之和，见 apps/datafiles/storage_usage.py。 -->
    <div class="admin-files-kpis">
      <div v-for="chip in kpis" :key="chip.key" class="kpi-chip">
        <span class="kpi-chip__label">{{ chip.label }}</span>
        <span class="kpi-chip__value" :data-testid="chip.testid">{{ chip.value }}</span>
      </div>
    </div>

    <el-card class="table-card">
      <el-table
        v-loading="loading"
        :data="rows"
        class="admin-files-table"
        row-key="id"
        stripe
      >
        <template #empty>
          <el-empty v-if="!loading" :description="emptyText" />
        </template>
        <el-table-column prop="filename" label="文件名" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.filename }}
            <el-tag v-if="row.is_hidden" size="small" type="info" effect="plain">已隐藏</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="产品" min-width="140">
          <template #default="{ row }">{{ row.product_code || PLACEHOLDER }}</template>
        </el-table-column>
        <el-table-column prop="format_type" label="格式" width="140" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ formatSize(row.file_size ?? 0) }}</template>
        </el-table-column>
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <!-- 刻意没有操作列：本页只读。查看/下载/删除/编辑都不属于它 —— 要操作请去数据管理页
             （那里按 owner=当前用户过滤，管理员也不能代劳）。 -->
      </el-table>

      <div class="admin-files-pagination">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :current-page="filters.page"
          :page-size="filters.pageSize"
          :page-sizes="pageSizes"
          :total="total"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { adminFilesApi, type AdminUserUsage } from '../../api/adminFiles'
import { datafilesApi } from '../../api/datafiles'
import type { DataFile } from '../../types'
import { usageBytesText } from '../../utils/diskUsage'
import { formatSize, formatTime } from '../../utils/format'

import AdminPageToolbar from './components/AdminPageToolbar.vue'

/** 列表信封（DRF PageNumberPagination）：count 是筛选后的总条数，不是当页条数。 */
interface FilePage {
  count: number
  results: DataFile[]
}

const PLACEHOLDER = '--'
const DEFAULT_PAGE_SIZE = 20
const pageSizes = [DEFAULT_PAGE_SIZE, 50, 100]

const users = ref<AdminUserUsage[]>([])
const usersLoading = ref(false)
const usersErrored = ref(false)
const ownerId = ref<number | null>(null)

const rows = ref<DataFile[]>([])
const total = ref(0)
const loading = ref(false)
const errored = ref(false)
const filters = reactive({ search: '', page: 1, pageSize: DEFAULT_PAGE_SIZE })

const busy = computed(() => loading.value || usersLoading.value)

const selectedUser = computed(
  () => users.value.find((u) => u.id === ownerId.value) ?? null,
)
const usage = computed(() => selectedUser.value?.usage ?? null)

const kpis = computed(() => [
  { key: 'data', label: '数据体积', value: usageBytesText(usage.value?.bytes), testid: 'admin-files-data-bytes' },
  { key: 'jobs', label: '作业产物体积', value: usageBytesText(usage.value?.jobs_bytes), testid: 'admin-files-jobs-bytes' },
  { key: 'total', label: '总占用', value: usageBytesText(usage.value?.total_bytes), testid: 'admin-files-total-bytes' },
])

/**
 * 三种空态必须长得不一样（同 AuditLogPage 的「别把失败说成没有」）：
 * 未选用户是「还没查」，加载失败是「查没成」，其余才是「这个用户没有文件」。
 */
const emptyText = computed(() => {
  if (ownerId.value === null) return '请先选择一个用户'
  if (errored.value) return '文件清单加载失败，请稍后重试'
  return '该用户没有文件'
})

/** 下拉候选：用户名是唯一标识，显示名只做辅助（空显示名就不画空括号）。 */
function userOptionLabel(u: AdminUserUsage): string {
  return u.display_name ? `${u.username}（${u.display_name}）` : u.username
}

async function loadUsers() {
  usersLoading.value = true
  usersErrored.value = false
  try {
    const { data } = await adminFilesApi.listUsers()
    users.value = data.results
    // 选中的人被停用/删掉时（清单只列启用账号）回到「未选」，而不是留一个查不到 id。
    if (ownerId.value !== null && !users.value.some((u) => u.id === ownerId.value)) {
      ownerId.value = null
    }
  } catch {
    // 提示由 axios 拦截器统一弹出；这里只把候选清空并把失败说出来（见模板的 hint）。
    usersErrored.value = true
    users.value = []
    ownerId.value = null
  } finally {
    usersLoading.value = false
  }
}

async function loadFiles() {
  if (ownerId.value === null) {
    rows.value = []
    total.value = 0
    errored.value = false
    return
  }
  loading.value = true
  errored.value = false
  try {
    const resp = await datafilesApi.listFiles({
      owner_id: ownerId.value,
      page: filters.page,
      page_size: filters.pageSize,
      search: filters.search.trim(),
      ordering: '-created_at',
      include_hidden: 1,
    })
    // 坏形状必须响在 catch 里：`?? []` 会把「后端给了个不该给的东西」粉饰成一次安静的空表。
    const page = resp.data as FilePage
    rows.value = page.results
    total.value = page.count
  } catch {
    errored.value = true
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

watch(ownerId, () => {
  filters.page = 1
  loadFiles()
})

function applySearch() {
  filters.page = 1
  loadFiles()
}

function onPageChange(page: number) {
  filters.page = page
  loadFiles()
}

function onSizeChange(size: number) {
  filters.pageSize = size
  filters.page = 1
  loadFiles()
}

async function refresh() {
  await loadUsers()
  if (ownerId.value !== null) await loadFiles()
}

onMounted(loadUsers)
</script>

<style scoped>
.admin-files-filter :deep(.el-form-item) {
  margin: 0;
}

/* 用户名 + 中文显示名比 160px 的下拉基准宽；三类的选择器才压得住工具栏壳的规则。 */
.admin-files :deep(.admin-files-user-select.admin-filter-select) {
  width: 240px;
}

.admin-files__hint {
  margin: 0 0 var(--p-space-2);
  color: var(--warn);
  font-size: var(--p-fs-small);
}

.admin-files-kpis {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-2);
  margin-bottom: var(--p-space-3);
}

.kpi-chip {
  display: inline-flex;
  align-items: baseline;
  gap: var(--p-space-1);
  padding: var(--p-space-1) var(--p-space-3);
  border: 1px solid var(--border-2);
  border-radius: 999px;
  background: var(--bg-2);
  color: var(--text);
  font-size: var(--p-fs-small);
}

.kpi-chip__label {
  color: var(--text-2);
}

.kpi-chip__value {
  font-weight: var(--p-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.table-card {
  border-radius: 8px;
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

.admin-files-pagination {
  display: flex;
  justify-content: flex-end;
  padding: var(--p-space-2) var(--p-space-3);
}

:deep(.el-card) {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-2);
  --el-table-tr-bg-color: var(--bg-2);
  --el-table-header-bg-color: var(--bg-3);
  --el-table-border-color: var(--border-2);
  --el-table-text-color: var(--text);
  --el-table-row-hover-bg-color: var(--bg-3);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-2) inset;
}

/* 本仓装的 element-plus 2.14.0：select 触发区是 .el-select__wrapper（理由同 AuditLogPage）。 */
:deep(.el-select__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-2) inset;
}
</style>

<template>
  <div class="audit-log">
    <el-card class="filter-card">
      <el-form :model="filters" inline @submit.prevent="applyFilters">
        <!-- data-testid 一律挂在 el-form-item 上（同 UserManagement.vue 的编辑弹窗），定位器形状是
             「[data-testid=…] input」与「[data-testid=audit-event] .el-select」：
             ElInput 是 inheritAttrs: false 且把 attrs 并到原生 input 自己身上，挂在 el-input 上时
             这两条都会落空；非 filterable 的 el-select 里那个 input 被排出文档流，点它永远等不到。 -->
        <el-form-item label="事件" data-testid="audit-event">
          <el-select v-model="filters.event" clearable placeholder="全部事件">
            <el-option
              v-for="(label, code) in AUDIT_EVENT_LABELS"
              :key="code"
              :label="label"
              :value="code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="账号" data-testid="audit-username">
          <el-input
            v-model="filters.username"
            placeholder="操作者或目标账号"
            clearable
            :maxlength="USERNAME_QUERY_MAX"
          />
        </el-form-item>
        <el-form-item label="起" data-testid="audit-date-from">
          <el-date-picker
            v-model="filters.dateFrom"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="开始日期"
          />
        </el-form-item>
        <el-form-item label="止" data-testid="audit-date-to">
          <el-date-picker
            v-model="filters.dateTo"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="结束日期"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="table-card">
      <el-table v-loading="loading" :data="rows" class="audit-table" row-key="id" stripe>
        <!-- 空态分两句话写：一次失败的请求留下的「暂无符合条件的审计记录」是在告诉管理员
             「系统查过了，这条件底下没有案子」，而事实是查询根本没成功。取证页上这句谎
             比空表格坏得多，所以 errored 必须由 load() 自己置位/复位（判据：e2e/admin/audit.spec.ts
             的倒置日期区间那一腿 —— 后端对 date_from >= date_to 抛 400）。 -->
        <template #empty>
          <el-empty
            v-if="!loading"
            :description="errored ? '审计记录加载失败，请调整条件后重试' : '暂无符合条件的审计记录'"
          />
        </template>
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre class="detail-json">{{ auditDetailJson(row.detail) }}</pre>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatAuditTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="事件" width="150">
          <template #default="{ row }">{{ auditEventLabel(row.event) }}</template>
        </el-table-column>
        <el-table-column label="操作者" min-width="140">
          <template #default="{ row }">{{ row.actor_username || AUDIT_PLACEHOLDER }}</template>
        </el-table-column>
        <el-table-column label="目标账号" min-width="140">
          <template #default="{ row }">{{ row.target_username || AUDIT_PLACEHOLDER }}</template>
        </el-table-column>
        <el-table-column label="IP" width="140">
          <template #default="{ row }">{{ row.ip_address || AUDIT_PLACEHOLDER }}</template>
        </el-table-column>
        <el-table-column label="详情摘要" min-width="240">
          <template #default="{ row }">
            <span class="detail-summary">{{ summarizeDetail(row.detail) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="audit-pagination">
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
import { onMounted, reactive, ref } from 'vue'

import { auditApi, type AuditEventRow } from '../../api/audit'
import {
  AUDIT_PAGE_SIZE_DEFAULT,
  AUDIT_PAGE_SIZE_MAX,
  AUDIT_EVENT_LABELS,
  AUDIT_PLACEHOLDER,
  USERNAME_QUERY_MAX,
  auditDetailJson,
  auditEventLabel,
  buildAuditQuery,
  defaultAuditFilters,
  formatAuditTime,
  summarizeDetail,
  type AuditFilters,
} from '../../utils/audit'

/**
 * 每页条数候选：20 是 DRF 的全局 PAGE_SIZE（config/settings/base.py:214-215，本端点的分页类
 * 没覆写 page_size 之外的字段），刻意**不**进 utils/audit 那对被后端源码钉住的常量；
 * 50 与 100 一律由 AUDIT_PAGE_SIZE_DEFAULT / AUDIT_PAGE_SIZE_MAX 推出 —— 在这里抄字面量
 * 就是把 Task 9 刚消灭的第二副本搬回组件（那两个数在 test/unit/audit.spec.ts 里对的是
 * apps/accounts/views.py 刮来的值）。判据在同目录之外的 test/unit/auditFormat.spec.ts
 * （剥注释扫本文件：三个常量名必须在、`[20, 50, 100]` 与 maxlength 的字面量必须不在）。
 * 这里是个普通常量而不是 computed：三个依赖全是模块级常量，包一层只多一个 ref 与一次求值。
 */
const pageSizes = [20, AUDIT_PAGE_SIZE_DEFAULT, AUDIT_PAGE_SIZE_MAX]

const rows = ref<AuditEventRow[]>([])
const total = ref(0)
const loading = ref(false)
const errored = ref(false)
/** 表单态与纯层契约同一份类型：日期两格可为 null，清空时 EP 交回的就是 null。 */
const filters = reactive<AuditFilters>({ ...defaultAuditFilters() })

async function load() {
  loading.value = true
  errored.value = false
  try {
    const { data } = await auditApi.listEvents(buildAuditQuery(filters))
    // 信封的四个键（count/next/previous/results）由 T1 钉着（test/backend/test_audit_api.py:68
    // 的 PAGE_KEYS，与那条整页走查），这里的类型也是两个非可选项。兜 `?? []` 不会更稳，只会把
    // 「后端给了个不该给的东西」变成一次安静的空表；`?? rows.length` 更坏 —— 一个畸形响应会被
    // 粉饰成「共 N 条、正好一页」，翻页器看着自洽却永远只有一页。坏形状要响在 catch 里（errored
    // 会把它说成「加载失败」），不能静悄悄变成「这一条件下没有记录」。
    rows.value = data.results
    total.value = data.count
  } catch {
    // 失败提示由 axios 拦截器统一弹出（api/index.ts 的 toastError），这里只把行集清空；
    // 筛选条件一律保留，管理员改一下就能原地重试，而不是被一次网络抖动打回默认条件。
    errored.value = true
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  filters.page = 1
  load()
}

function resetFilters() {
  Object.assign(filters, defaultAuditFilters())
  load()
}

function onPageChange(page: number) {
  filters.page = page
  load()
}

function onSizeChange(size: number) {
  filters.pageSize = size
  filters.page = 1
  load()
}

onMounted(load)
</script>

<style scoped>
.audit-log {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-card :deep(.el-form--inline .el-form-item) {
  margin-bottom: 0;
}

.audit-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

/* 摘要那一格不折行、不撑破列宽：预算 120 个字符那道截断在 utils/audit 的 summarizeDetail 里 */
.detail-summary {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.detail-json {
  margin: 0;
  padding: 12px 16px;
  background: var(--bg-3);
  color: var(--text);
  border-radius: 8px;
  font-size: var(--p-fs-dense);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-all;
}

:deep(.el-card) {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-2) inset;
}

/* 本仓装的 element-plus 2.14.0 里，select 的触发区用的是它自己的 .el-select__wrapper：
   theme-chalk/el-select.css 里有这个类，而 `.el-select .el-input__wrapper` 一条规则都没有 ⇒
   旧写法恒不命中，事件下拉就成了筛选行里唯一没拿到 --bg 的控件（date-picker 今天还被上面
   那条罩住，是因为它内部仍是 el-input 形状）。同一条死规则还留在 UserManagement.vue:555 与
   src/styles/element-plus-theme.css:598，那两处属于全局主题收敛、不在本批动，已记进 Task 14。 */
:deep(.el-select__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-2) inset;
}
</style>

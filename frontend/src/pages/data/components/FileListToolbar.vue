<template>
  <div class="list-toolbar">
    <div class="toolbar-left">
      <span class="section-title">📋 文件列表</span>
      <span class="section-count">{{ total }} 个文件</span>
      <!-- 磁盘占用：复用 .section-count 的外观（同一族 chip，不新增字号声明，
           过 e2e/global/fonts.spec.ts 那条禁硬编码 px 的闸），浮层用 el-descriptions
           而不是自定义样式 —— popper 被 teleport 到 body，scoped CSS 够不着它。 -->
      <el-popover
        v-if="usage"
        placement="bottom-start"
        :width="300"
        trigger="hover"
        popper-class="disk-usage-popover"
      >
        <template #reference>
          <span class="section-count" data-testid="disk-usage-chip">
            {{ usageChip }}
          </span>
        </template>
        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item
            v-for="(row, index) in usageRows"
            :key="`${row.label}:${index}`"
            :label="row.label"
          >
            {{ row.sizeText }} · {{ row.countText }}
          </el-descriptions-item>
          <el-descriptions-item v-if="!usageRows.length" label="数据目录">
            没有文件
          </el-descriptions-item>
          <!-- 总量里分桶行覆盖不到的那部分（作业产物树）。这一项**不传 label**：
               句子自带「作业产物」开头，再挂 `label="作业产物"` 会读成
               「作业产物：作业产物 3.0 KB…」（见 diskUsage.ts 的 usageJobsLine 注释）。 -->
          <el-descriptions-item v-if="usageJobs">
            {{ usageJobs }}
          </el-descriptions-item>
          <el-descriptions-item v-if="usageOutside" label="目录外记录">
            {{ usageOutside }}
          </el-descriptions-item>
          <el-descriptions-item v-if="usageScanned" label="统计时间">
            {{ usageScanned }}
          </el-descriptions-item>
        </el-descriptions>
      </el-popover>
    </div>
    <div class="toolbar-right">
      <!-- popper-class 是实例级下拉身份：面板 teleport 到 body，全局
           `.el-select-dropdown:visible` 在「上一个面板还在 leave 过渡」时会挑错家
           （机理见 e2e/helpers/elplus.ts 的 popperOf）。e2e 侧身份串是
           `dp-hidden-filter-popper`，产品侧改类名时两边一起改。
           aria-label 与 intro 书里这一档的文案对齐（「隐藏状态」）。 -->
      <el-select
        class="hidden-filter"
        data-testid="hidden-filter"
        popper-class="dp-hidden-filter-popper"
        aria-label="隐藏状态"
        :model-value="hiddenFilter"
        @change="onHiddenFilterChange"
      >
        <el-option label="全部（含隐藏）" value="all" />
        <el-option label="未隐藏" value="visible" />
        <el-option label="已隐藏" value="hidden" />
      </el-select>
      <el-input
        v-model="searchText"
        placeholder="按文件名/程序名/标签搜索"
        clearable
        class="search-input"
        @input="onSearchInput"
        @clear="onSearchInput"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button
        type="primary"
        plain
        :disabled="selectedCount < 1"
        :title="selectedCount < 1 ? '请先勾选文件' : '组合/追加为批次'"
        @click="emit('combine-click')"
      >
        <el-icon><Collection /></el-icon>
        组合为批次
      </el-button>
      <el-button
        type="primary"
        @click="emit('upload-click')"
      >
        <el-icon><Upload /></el-icon>
        上传文件
      </el-button>
      <el-button
        type="danger"
        plain
        :disabled="selectedCount === 0"
        @click="emit('bulk-delete')"
      >
        <el-icon><Delete /></el-icon>
        批量删除{{ selectedCount ? ` (${selectedCount})` : '' }}
      </el-button>
      <el-button
        type="warning"
        plain
        @click="emit('fix-click')"
      >
        <el-icon><Tools /></el-icon>
        数据修复
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search, Delete, Upload, Tools, Collection } from '@element-plus/icons-vue'
import type { FileUsage } from '../../../api/datafiles'
import {
  usageBreakdownRows,
  usageChipText,
  usageJobsLine,
  usageOutsideLine,
  usageScannedText,
} from '../../../utils/diskUsage'

export type HiddenFilter = 'all' | 'visible' | 'hidden'

const props = defineProps<{
  total: number
  selectedCount: number
  usage: FileUsage | null
  hiddenFilter: HiddenFilter
}>()

const emit = defineEmits<{
  search: [text: string]
  'upload-click': []
  'fix-click': []
  'bulk-delete': []
  'combine-click': []
  'hidden-filter-change': [value: HiddenFilter]
}>()

function onHiddenFilterChange(value: HiddenFilter) {
  emit('hidden-filter-change', value)
}

const usageChip = computed(() => usageChipText(props.usage))
const usageRows = computed(() => usageBreakdownRows(props.usage))
const usageJobs = computed(() => usageJobsLine(props.usage))
const usageOutside = computed(() => usageOutsideLine(props.usage))
const usageScanned = computed(() => usageScannedText(props.usage))
// 五个派生串一律走 computed，不在模板里直接调纯函数（Task 7 派发词原话「不在模板里重复调用
// 纯函数」，落地时是三个，2026-11-22 补齐成五个）：内联调用会在每次工具栏重渲染时重跑，而搜索框
// 是本地 state ⇒ 每敲一个字都重渲染这一片。代价本来是微秒级，改它的理由是**一致**。
//
// `:key` 用 `label:index` 而不是裸 `label`：`row.label` 的取值空间是
// `{单文件, 批次, 根目录散文件} ∪ {每个未知一级目录名原样}`，而未知键来自**文件系统**
// （`storage_usage.py` 按路径第一段建桶），所以数据根目录里真的可以有一个叫「单文件」的
// 一级目录和 `single` 并排 ⇒ 撞键。撞了不是「难看」那么简单：keyed diff 对重复 key 只保留
// 最后一个 index，之后 `usage` 再更新就可能把上一轮**另一个桶**的字节数 patch 到这个名字
// 下面，而这是一块读数面板（dev 模式只会 warn 一声）。行本身无状态、整批替换，所以让 index
// 参与 key 没有副作用；留着 label 是为了在 devtools 里读得出来这行是谁。
// 下面三行（数据目录 / 目录外记录 / 统计时间）是静态 `el-descriptions-item`、不在 v-for 里，
// 没有撞键问题：「数据目录」那行的 `v-if="!usageRows.length"` 与 v-for 互斥，永不同帧共存。

const searchText = ref('')

let searchTimer: ReturnType<typeof setTimeout> | undefined

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    emit('search', searchText.value)
  }, 300)
}
</script>

<style scoped>
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.section-title {
  font-size: var(--p-fs-base);
  font-weight: 600;
  color: var(--text);
}

.section-count {
  font-size: var(--p-fs-dense);
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--bg-2);
  border-radius: 10px;
}

.search-input {
  width: 220px;
}

.hidden-filter {
  width: 130px;
}

:root[data-theme="night"] .section-count {
  background: rgba(255, 255, 255, 0.08);
}
</style>

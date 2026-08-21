<template>
  <div>
    <!-- 筛选控制栏（5 控件 × span4 = 20） -->
    <el-row :gutter="12" style="margin-bottom: 12px">
      <el-col :span="4">
        <span class="ctl-label">显示测试列</span>
        <TestColumnSelector
          :cols="testCols"
          :model-value="selectedTestCols"
          @update:model-value="emit('update:selectedTestCols', $event)"
        />
      </el-col>
      <el-col :span="4">
        <span class="ctl-label">Pass/Fail</span>
        <el-select
          :model-value="passfail"
          placeholder="Pass/Fail筛选"
          aria-label="Pass/Fail筛选"
          @update:model-value="emit('update:passfail', $event)"
        >
          <el-option label="全部" value="" />
          <el-option label="Pass" value="Pass" />
          <el-option label="Fail" value="Fail" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <span class="ctl-label">Site</span>
        <el-select
          :model-value="siteFilter"
          placeholder="全部 Site"
          aria-label="站点筛选"
          :disabled="siteColDisabled"
          @update:model-value="emit('update:siteFilter', $event)"
        >
          <el-option label="全部 Site" value="" />
          <el-option v-for="s in siteOptions" :key="s" :label="'Site ' + s" :value="String(s)" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <span class="ctl-label">列宽</span>
        <el-select
          :model-value="autosizeMode"
          placeholder="手动调整"
          aria-label="列宽模式"
          @update:model-value="emit('update:autosizeMode', $event)"
        >
          <el-option label="适应内容宽度" value="fitCellContents" />
          <el-option label="适应网格宽度" value="fitGridWidth" />
          <el-option label="手动调整" value="none" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <span class="ctl-label">固定列</span>
        <el-select
          :model-value="pinnedCol"
          placeholder="搜索选择"
          clearable
          filterable
          aria-label="固定列"
          :disabled="!testCols.length"
          @update:model-value="emit('update:pinnedCol', $event)"
        >
          <el-option v-for="c in allCols" :key="c" :label="c" :value="c" />
        </el-select>
      </el-col>
    </el-row>

    <!-- 操作按钮 -->
    <el-row style="margin-bottom: 12px">
      <el-col style="text-align: right">
        <el-button type="primary" :loading="loading" @click="emit('load')">
          <el-icon><Refresh /></el-icon> 加载数据
        </el-button>
        <el-button :loading="exportingExcel" @click="emit('export-excel')">
          <el-icon><Download /></el-icon> 导出 Excel
        </el-button>
        <el-button :loading="exportingCsv" @click="emit('export-csv')">
          <el-icon><Document /></el-icon> 导出 CSV
        </el-button>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { Refresh, Download, Document } from '@element-plus/icons-vue'
import TestColumnSelector from './TestColumnSelector.vue'

interface Props {
  testCols: string[]
  selectedTestCols: string[]
  passfail: string
  siteFilter: string
  siteOptions: string[]
  siteColDisabled: boolean
  autosizeMode: string
  pinnedCol: string
  allCols: string[]
  loading: boolean
  exportingExcel: boolean
  exportingCsv: boolean
}

interface Emits {
  (e: 'update:selectedTestCols', v: string[]): void
  (e: 'update:passfail', v: string): void
  (e: 'update:siteFilter', v: string): void
  (e: 'update:autosizeMode', v: string): void
  (e: 'update:pinnedCol', v: string): void
  (e: 'load'): void
  (e: 'export-excel'): void
  (e: 'export-csv'): void
}

defineProps<Props>()
const emit = defineEmits<Emits>()
</script>

<style scoped>
/* 控件上方小字 label（双主题：CSS 变量自动适配） */
.ctl-label {
  display: block;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

/* Element Plus 控件双主题适配 */
:deep(.el-input) {
  --el-input-bg-color: var(--bg-primary);
  --el-input-border-color: var(--border-default);
  --el-input-hover-border-color: var(--brand-primary);
  --el-input-focus-border-color: var(--brand-primary);
  --el-input-text-color: var(--text-primary);
  --el-input-placeholder-color: var(--text-secondary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
}

:deep(.el-select) {
  --el-select-input-focus-border-color: var(--brand-primary);
}
</style>

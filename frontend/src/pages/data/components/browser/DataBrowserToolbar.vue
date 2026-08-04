<template>
  <div>
    <!-- 筛选控制栏（6 控件 × span4 = 24，修复原 spans 26>24 换行 bug） -->
    <el-row :gutter="12" style="margin-bottom: 12px">
      <el-col :span="4">
        <el-input
          :model-value="searchCol"
          placeholder="搜索列名…"
          clearable
          aria-label="搜索"
          @update:model-value="emit('update:searchCol', $event)"
        />
      </el-col>
      <el-col :span="4">
        <el-select
          :model-value="searchTestCol"
          placeholder="搜索测试项"
          clearable
          aria-label="搜索列"
          @update:model-value="emit('update:searchTestCol', $event)"
        >
          <el-option label="全部显示" value="" />
          <el-option v-for="c in allCols" :key="c" :label="c" :value="c" />
        </el-select>
      </el-col>
      <el-col :span="4">
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
        <el-select
          :model-value="siteFilter"
          placeholder="Site筛选"
          aria-label="站点筛选"
          :disabled="siteColDisabled"
          @update:model-value="emit('update:siteFilter', $event)"
        >
          <el-option label="全部 Site" value="" />
          <el-option v-for="s in siteOptions" :key="s" :label="'Site ' + s" :value="String(s)" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select
          :model-value="autosizeMode"
          placeholder="列宽自适应"
          aria-label="列宽模式"
          @update:model-value="emit('update:autosizeMode', $event)"
        >
          <el-option label="适应内容宽度" value="fitCellContents" />
          <el-option label="适应网格宽度" value="fitGridWidth" />
          <el-option label="手动调整" value="none" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select
          :model-value="pinnedCol"
          placeholder="固定列（搜索选择）"
          clearable
          filterable
          aria-label="固定列"
          :disabled="!allCols.length"
          @update:model-value="emit('update:pinnedCol', $event)"
        >
          <el-option v-for="c in allCols" :key="c" :label="c" :value="c" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select
          :model-value="hiddenCols"
          placeholder="隐藏列（默认全部显示）"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          clearable
          aria-label="隐藏列"
          :disabled="!allCols.length"
          @update:model-value="emit('update:hiddenCols', $event)"
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

interface Props {
  searchCol: string
  searchTestCol: string
  passfail: string
  siteFilter: string
  siteOptions: string[]
  siteColDisabled: boolean
  autosizeMode: string
  pinnedCol: string
  hiddenCols: string[]
  allCols: string[]
  loading: boolean
  exportingExcel: boolean
  exportingCsv: boolean
}

interface Emits {
  (e: 'update:searchCol', v: string): void
  (e: 'update:searchTestCol', v: string): void
  (e: 'update:passfail', v: string): void
  (e: 'update:siteFilter', v: string): void
  (e: 'update:autosizeMode', v: string): void
  (e: 'update:pinnedCol', v: string): void
  (e: 'update:hiddenCols', v: string[]): void
  (e: 'load'): void
  (e: 'export-excel'): void
  (e: 'export-csv'): void
}

defineProps<Props>()
const emit = defineEmits<Emits>()
</script>

<style scoped>
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

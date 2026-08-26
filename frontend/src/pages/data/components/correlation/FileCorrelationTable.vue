<template>
  <div class="fc-table fc-table-wrap">
    <!-- 模板风格信息栏：标题 + 文件对 + 口径 -->
    <div class="fc-table-info">
      <span class="info-title">Data A VS Data B</span>
      <span class="info-files">{{ result.file1_name }} <b>VS</b> {{ result.file2_name }}</span>
      <el-checkbox v-model="showLimits" size="small" class="fc-show-limits">
        显示 Limit/单位（Data A）
      </el-checkbox>
      <span class="info-meta">
        {{ viewLabel }} · 序列 {{ result.serials.length }} 个 · 阈值 {{ threshold }}% ·
        {{ diffRule === 'zero' ? '规则A：Diff 必须为 0' : '规则B：B 的 Limit 不更紧' }}
      </span>
    </div>

    <!-- 测试值对比表（ag-grid 行列双虚拟化：DOM 大小与序列数无关，
         解决 el-table 无列虚拟化导致的宽表卡顿/切 tab 慢） -->
    <ag-grid-vue
      :class="['ag-theme-quartz', isDark ? 'ag-theme-quartz-dark' : '', 'fc-grid']"
      :theme="'legacy'"
      style="height: 520px; width: 100%"
      :column-defs="columnDefs"
      :row-data="result.rows"
      :default-col-def="defaultColDef"
      :row-height="30"
      :header-height="42"
      :group-header-height="42"
      :suppress-header-focus="true"
      :suppress-movable-columns="true"
      :animate-rows="false"
      :row-buffer="10"
      :overlay-no-rows-template="'没有可对比的测试项'"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
import { useThemeStore } from '../../../../stores/theme'
import type { DiffRule, FileCorrelationResult } from '../../../../types'

// 注册 ag-grid 模块（幂等；与 DataBrowserAgGrid 同源初始化）
ModuleRegistry.registerModules([AllCommunityModule])

const props = defineProps<{
  result: FileCorrelationResult
  threshold: number
  diffRule: DiffRule
  /** 视图标签（信息栏展示，区分 Limit 对比） */
  viewLabel?: string
}>()

const isDark = computed(() => useThemeStore().currentTheme === 'night')
const viewLabel = props.viewLabel ?? '测试值对比'
/** 显示 Data A 的 Limit/单位（默认勾选） */
const showLimits = ref(true)

const defaultColDef = {
  sortable: false,
  filter: false,
  resizable: true,
  suppressHeaderFilterButton: true,
}

/** 数值格式化（null/undefined → '—'） */
function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return '—'
  return Number(v).toFixed(digits)
}

/** %Diff 显示（保留 2 位 + %） */
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${Number(v).toFixed(2)}%`
}

/** 测试值判定：仅按超差 fail_count（Limit 差异在 Limit 对比视图判定列） */
function verdictOf(row: any): 'PASS' | 'FAIL' {
  return row.fail_count > 0 ? 'FAIL' : 'PASS'
}

/** 判定列徽章样式（cellStyle 内联变量，主题自适应） */
function verdictStyle(p: any) {
  const pass = p.value === 'PASS'
  return {
    backgroundColor: pass ? 'var(--color-success)' : 'var(--color-error)',
    color: '#fff',
    fontWeight: '700',
    borderRadius: '10px',
    padding: '2px 10px',
    letterSpacing: '0.03em',
  }
}

const columnDefs = computed(() => {
  const defs: any[] = [
    {
      headerName: 'Parameters',
      field: 'param',
      pinned: 'left',
      width: 180,
      suppressSizeToFit: true,
      cellClass: 'fc-param-cell',
    },
  ]
  // Data A 的 Limit/单位（默认显示；可取消勾选腾出数据区宽度）
  if (showLimits.value) {
    defs.push(
      {
        headerName: 'LSL A',
        headerTooltip: 'Data A 下限（LSL）',
        pinned: 'left',
        width: 76,
        suppressSizeToFit: true,
        valueGetter: (p: any) => p.data.lsl_a ?? null,
        valueFormatter: (p: any) => fmtNum(p.value),
      },
      {
        headerName: 'USL A',
        headerTooltip: 'Data A 上限（USL）',
        pinned: 'left',
        width: 76,
        suppressSizeToFit: true,
        valueGetter: (p: any) => p.data.usl_a ?? null,
        valueFormatter: (p: any) => fmtNum(p.value),
      },
      {
        headerName: 'Unit',
        pinned: 'left',
        width: 70,
        suppressSizeToFit: true,
        valueGetter: (p: any) => p.data.unit || '—',
        valueFormatter: (p: any) => p.value,
      },
    )
  }
  defs.push({
    headerName: '判定',
    pinned: 'left',
    width: 92,
    suppressSizeToFit: true,
    valueGetter: (p: any) => verdictOf(p.data),
    valueFormatter: (p: any) => p.value,
    cellClass: 'fc-verdict-cell',
    cellStyle: verdictStyle,
  })
  for (const [si, serial] of props.result.serials.entries()) {
    defs.push({
      headerName: String(serial),
      headerTooltip: `序列 ${serial}`,
      children: [
        {
          headerName: 'ATE',
          width: 88,
          valueGetter: (p: any) => p.data.cells?.[si]?.ate ?? null,
          valueFormatter: (p: any) => fmtNum(p.value),
        },
        {
          headerName: 'Bench',
          width: 88,
          valueGetter: (p: any) => p.data.cells?.[si]?.bench ?? null,
          valueFormatter: (p: any) => fmtNum(p.value),
        },
        {
          headerName: 'Delta',
          width: 88,
          valueGetter: (p: any) => p.data.cells?.[si]?.delta ?? null,
          valueFormatter: (p: any) => fmtNum(p.value),
          cellClassRules: { 'fc-fail-cell': (p: any) => !!p.data.cells?.[si]?.fail },
        },
        {
          headerName: '% Diff',
          width: 92,
          valueGetter: (p: any) => p.data.cells?.[si]?.diff_pct ?? null,
          valueFormatter: (p: any) => fmtPct(p.value),
          cellClassRules: { 'fc-fail-cell': (p: any) => !!p.data.cells?.[si]?.fail },
        },
      ],
    })
  }
  return defs
})
</script>

<style scoped>
.fc-table-wrap {
  min-width: 0;
}

.fc-table-info {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  flex-wrap: wrap;
}

.info-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.info-files {
  font-size: 12px;
  color: var(--text-secondary);
}

.info-files b {
  color: var(--brand-primary);
}

.info-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: auto;
}

/* ag-grid 主题微调（legacy quartz + 项目 CSS 变量） */
.fc-grid {
  --ag-foreground-color: var(--text-primary);
  --ag-background-color: var(--bg-primary);
  --ag-header-background-color: var(--bg-secondary);
  --ag-border-color: var(--border-muted);
  --ag-row-hover-color: var(--bg-secondary);
  --ag-font-size: 12px;
  --ag-header-foreground-color: var(--text-primary);
  border-radius: 0 0 8px 8px;
  overflow: hidden;
  border: 1px solid var(--border-muted);
}

.fc-grid :deep(.ag-header-cell-text),
.fc-grid :deep(.ag-header-group-text),
.fc-grid :deep(.ag-cell) {
  font-size: 12px;
}

.fc-grid :deep(.ag-header-cell) {
  text-align: center;
}

.fc-grid :deep(.fc-param-cell) {
  font-size: 12px;
}

.fc-grid :deep(.fc-verdict-cell) {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
}

.fc-grid :deep(.fc-fail-cell) {
  background: var(--color-fail-bg) !important;
  color: var(--color-fail-text) !important;
  font-weight: 600;
}

/* Night */
:root[data-theme="night"] .fc-grid {
  --ag-foreground-color: #fff;
  --ag-background-color: rgba(255, 255, 255, 0.03);
  --ag-header-background-color: rgba(255, 255, 255, 0.05);
  --ag-border-color: rgba(255, 255, 255, 0.08);
  --ag-row-hover-color: rgba(255, 255, 255, 0.05);
}
</style>

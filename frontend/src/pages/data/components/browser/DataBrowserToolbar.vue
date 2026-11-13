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
        <!-- 本控件 2026-11-13（批1 Task 9C）由 v1 el-select 迁到 el-select-v2（设计稿 §2.9）：
             原先这里是 v-for="c in allCols" 的 el-option，且**从来没封顶过**（批1 前四个迁的是
             带 DROPDOWN_RENDER_CAP 的那四个），allCols = 表格全部列（ETS88_FT 千列级）⇒ 一打开
             就把每一列挂成完整组件实例，正是那个已删除常量防的主线程冻结。
             filterable **不传 filter-method**：v2 只有在传了之后才退化成纯回调
             （select-v2/src/useSelect.mjs:114-132 让 isValidOption 恒 true），不传时走 EP 内置的
             按 label 正则匹配 ⇒ 本控件没有自定义过滤，也不需要另四个下拉那套 kw/matches。
             popper-class 是实例级下拉身份（本页有 6 个下拉共用 .el-select-dropdown 类名），
             e2e 侧的同名串在 helpers/elplus.ts 的 PIN_COL_POPPER，改这里必须同步改它。 -->
        <el-select-v2
          :model-value="pinnedCols"
          :options="selectOptions"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="搜索选择"
          clearable
          filterable
          aria-label="固定列"
          popper-class="dp-pin-col-popper"
          :disabled="!testCols.length"
          @update:model-value="emit('update:pinnedCols', $event)"
        />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import TestColumnSelector from './TestColumnSelector.vue'
import { toOptions } from '../../../../utils/selectOptions'

interface Props {
  testCols: string[]
  selectedTestCols: string[]
  passfail: string
  siteFilter: string
  siteOptions: string[]
  siteColDisabled: boolean
  autosizeMode: string
  pinnedCols: string[]
  allCols: string[]
}

interface Emits {
  (e: 'update:selectedTestCols', v: string[]): void
  (e: 'update:passfail', v: string): void
  (e: 'update:siteFilter', v: string): void
  (e: 'update:autosizeMode', v: string): void
  (e: 'update:pinnedCols', v: string[]): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

/**
 * 固定列下拉的选项 = 表格全部列，**不截断**（虚拟化让千列可浏览）。
 *
 * 必须过 `toOptions`：`el-select-v2` 用 `lodash.get(item, 'label' | 'value')` 取值
 * （`select-v2/src/useProps.mjs:25-28`），把 `allCols` 这个 `string[]` 原样喂进 `:options`
 * 不报错，只得到**静默空白行** —— 行数照样是虚拟窗口那几行，所以 §2.9 那条验收除了
 * 「窗口行数远小于全集」还钉了「每行都是真实列名」，判据在 `e2e/data/view-data.spec.ts`。
 *
 * 命名照批1 四个下拉的约定叫 `selectOptions`：它不许顶掉任何 prop 名（Task 6 的头号陷阱是
 * `:disabled="options.length===0"` 被同名 computed 从「有没有数据」改成「有没有匹配」）。
 * 本文件 props 是 `allCols`/`testCols`，不撞名；props 里的 `siteOptions` 是 Site 那颗的候选。
 */
const selectOptions = computed(() => toOptions(props.allCols))
</script>

<style scoped>
/* 控件上方小字 label（双主题：CSS 变量自动适配） */
.ctl-label {
  display: block;
  font-size: var(--p-fs-micro);
  font-weight: 500;
  color: var(--text-2);
  margin-bottom: 4px;
}

/* Element Plus 控件双主题适配 */
:deep(.el-input) {
  --el-input-bg-color: var(--bg);
  --el-input-border-color: var(--border-2);
  --el-input-hover-border-color: var(--brand);
  --el-input-focus-border-color: var(--brand);
  --el-input-text-color: var(--text);
  --el-input-placeholder-color: var(--text-2);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
}

:deep(.el-select) {
  --el-select-input-focus-border-color: var(--brand);
}
</style>

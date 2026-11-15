<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">2</span>
      <span class="step-title">测试项归类</span>
      <span class="step-hint">可选：按名字前缀/后缀/包含分组；每类按页上限装箱</span>
    </div>
    <div class="step-body">
      <div class="grouping-globals">
        <el-select :model-value="modelValue.strategy" size="small" aria-label="归类冲突策略"
                   class="strategy-select" @update:model-value="patch({ strategy: $event })">
          <el-option value="first" label="首个命中（推荐）" />
          <el-option value="specific" label="最具体优先" />
          <el-option value="multi" label="允许一个参数多属" />
        </el-select>
        <span class="bw-label">每页最多</span>
        <el-select :model-value="modelValue.maxItemsPerSheet" size="small" aria-label="每页最多测试项数"
                   class="max-select" @update:model-value="patch({ maxItemsPerSheet: $event })">
          <el-option v-for="n in MAX_ITEMS_OPTIONS" :key="n" :value="n" :label="`${n} 项`" />
        </el-select>
      </div>

      <div v-for="(group, gi) in modelValue.groups" :key="group.id" class="group-row">
        <div class="group-head">
          <!-- data-testid 挂在包裹层而不是 el-input 上：EP 的 el-input 是
               `inheritAttrs: false` + `mergeProps(attrs)` 到内层 <input>，写在组件上的
               testid 会落到 input 自己身上，e2e 的 `getByTestId(..).locator('input')` 便无处可找。 -->
          <span class="group-name" data-testid="export-group-name">
            <el-input :model-value="group.name" size="small" placeholder="分类名，如 LKG"
                      aria-label="分类名" @update:model-value="updateGroup(gi, { name: $event })" />
          </span>
          <el-button size="small" link :disabled="gi === 0" @click="moveGroup(gi, -1)">上移</el-button>
          <el-button size="small" link :disabled="gi === modelValue.groups.length - 1"
                     @click="moveGroup(gi, 1)">下移</el-button>
          <el-button size="small" link @click="removeGroup(gi)">删除分类</el-button>
        </div>
        <div v-for="(pattern, pi) in group.patterns" :key="pi" class="pattern-row">
          <el-select :model-value="pattern.type" size="small" aria-label="条件类型" class="pattern-type"
                     @update:model-value="updatePattern(gi, pi, { type: $event })">
            <el-option value="prefix" label="前缀" />
            <el-option value="suffix" label="后缀" />
            <el-option value="contains" label="包含" />
          </el-select>
          <span class="pattern-text" data-testid="export-group-pattern-text">
            <el-input :model-value="pattern.text" size="small" placeholder="匹配文本"
                      aria-label="匹配文本" @update:model-value="updatePattern(gi, pi, { text: $event })" />
          </span>
          <el-button size="small" link @click="removePattern(gi, pi)">删除条件</el-button>
        </div>
        <el-button size="small" link data-testid="export-group-add-pattern" @click="addPattern(gi)">+ 条件</el-button>
      </div>

      <el-button size="small" data-testid="export-group-add" @click="addGroup">+ 添加分类</el-button>

      <!-- 预览：每个已命名分类都出一行（0 命中也不例外），「其他」恒在最后。
           条件有效但 0 命中 → 正常计数行（用户据此发现规则没匹配上）；
           名字填了但条件还没填 → `configured: false` 的占位行，明说它不参与导出
           （不能删掉这行：删掉就等于「打了个分类名，预览里凭空消失」）。 -->
      <div class="preview" data-testid="export-grouping-preview">
        <div v-for="(row, ri) in preview.rows" :key="ri" class="preview-line"
             :class="{ 'is-unconfigured': !row.configured }">
          <template v-if="row.configured">
            {{ row.name }}：{{ row.params.length }} 项<template v-if="row.params.length">
              （{{ row.params.slice(0, 3).join(', ') }}<template v-if="row.params.length > 3">…</template>）</template>
          </template>
          <template v-else>{{ row.name }}：未配置条件（不参与导出）</template>
        </div>
        <div class="preview-meta">
          预计 {{ preview.sheets }} 张 sheet · 约 {{ preview.seconds }}s · {{ preview.size }}
          <template v-if="isMulti"> · 共 {{ instanceCount }} 项次</template>
          <template v-if="preview.conflicts"> · 冲突 {{ preview.conflicts }} 项（命中多个分类）</template>
        </div>
        <div v-if="isMulti" class="preview-note" data-testid="export-grouping-multi-note">
          多属按出现次数计：同一测试项会出现在多个分类里，sheet 数与分页都按出现次数累加（不是按去重后的参数数）。
        </div>
      </div>

      <div class="grouping-help">
        匹配不区分大小写；同一分类内多个条件是「或」；未命中的测试项进「其他」；冲突策略决定一个测试项命中多个分类时归哪边。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import {
  DEFAULT_MAX_ITEMS, MAX_ITEMS_OPTIONS, newGroupId, previewGroups,
  type GroupingConfig, type GroupPattern,
} from '../../composables/exportGrouping'

const props = defineProps<{ modelValue: GroupingConfig; params: string[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: GroupingConfig): void }>()

function patch(part: Partial<GroupingConfig>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}
function replaceGroups(groups: GroupingConfig['groups']) {
  patch({ groups })
}
function addGroup() {
  replaceGroups([...props.modelValue.groups, { id: newGroupId(), name: '', patterns: [{ type: 'prefix', text: '' }] }])
}
function removeGroup(index: number) {
  replaceGroups(props.modelValue.groups.filter((_g, i) => i !== index))
}
function moveGroup(index: number, delta: number) {
  const groups = [...props.modelValue.groups]
  const target = index + delta
  if (target < 0 || target >= groups.length) return
  ;[groups[index], groups[target]] = [groups[target], groups[index]]
  replaceGroups(groups)
}
function updateGroup(index: number, part: Partial<GroupingConfig['groups'][number]>) {
  replaceGroups(props.modelValue.groups.map((g, i) => (i === index ? { ...g, ...part } : g)))
}
function addPattern(groupIndex: number) {
  const group = props.modelValue.groups[groupIndex]
  updateGroup(groupIndex, { patterns: [...group.patterns, { type: 'prefix', text: '' }] })
}
function removePattern(groupIndex: number, patternIndex: number) {
  const group = props.modelValue.groups[groupIndex]
  updateGroup(groupIndex, { patterns: group.patterns.filter((_p, i) => i !== patternIndex) })
}
function updatePattern(groupIndex: number, patternIndex: number, part: Partial<GroupPattern>) {
  const group = props.modelValue.groups[groupIndex]
  updateGroup(groupIndex, {
    patterns: group.patterns.map((p, i) => (i === patternIndex ? { ...p, ...part } : p)),
  })
}

const isMulti = computed(() => props.modelValue.strategy === 'multi')

const preview = computed(() => {
  const cap = props.modelValue.maxItemsPerSheet || DEFAULT_MAX_ITEMS
  const count = props.params.length
  const result = previewGroups(props.params, props.modelValue.groups, props.modelValue.strategy, cap)
  return {
    rows: result.rows,
    sheets: result.sheets,
    conflicts: result.conflicts,
    // 体积/耗时是粗略口径（与既有批量导出卡片同源：232ms/项、45KB/项）
    seconds: Math.max(1, Math.round((count * 232) / 1000)),
    size: `${(count * 45 / 1024).toFixed(1)} MB`,
  }
})

/** 参与项次：多属时同一参数在几行里就算几次，是「出现次数」口径的直观读数 */
const instanceCount = computed(() => preview.value.rows.reduce((sum, row) => sum + row.params.length, 0))
</script>

<style scoped>
.step-card { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; }
.step-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.step-number { width: 22px; height: 22px; border-radius: 50%; background: var(--brand); color: var(--text-inverse); display: inline-flex; align-items: center; justify-content: center; font-size: var(--p-fs-dense); font-weight: 700; flex-shrink: 0; }
.step-title { font-size: var(--p-fs-small); font-weight: 600; color: var(--text); }
.step-hint { margin-left: auto; font-size: var(--p-fs-micro); color: var(--text-3); }
.step-body { padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.grouping-globals { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.strategy-select { width: 180px; }
.max-select { width: 100px; }
.bw-label { font-size: var(--p-fs-dense); color: var(--text-2); }
.group-row { border: 1px dashed var(--border); border-radius: 8px; padding: 8px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.group-head, .pattern-row { display: flex; align-items: center; gap: 6px; }
.group-name { display: block; width: 180px; }
.pattern-type { width: 90px; }
.pattern-text { display: block; width: 220px; }
.preview { font-size: var(--p-fs-dense); color: var(--text-2); display: flex; flex-direction: column; gap: 2px; }
.is-unconfigured { color: var(--text-3); }
.preview-meta { color: var(--text-3); }
.preview-note { color: var(--text-3); }
.grouping-help { font-size: var(--p-fs-micro); color: var(--text-3); line-height: 1.5; }
</style>

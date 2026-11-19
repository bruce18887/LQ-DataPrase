<template>
  <div class="serial-selector">
    <el-select-v2
      ref="selectRef"
      :model-value="modelValue"
      :options="selectOptions"
      multiple
      filterable
      automatic-dropdown
      placeholder="搜索序列号"
      collapse-tags
      collapse-tags-tooltip
      class="seri-select"
      aria-label="对比序列"
      popper-class="dp-serial-popper"
      :loading="loading"
      :disabled="options.length === 0"
      :multiple-limit="MAX_SELECTED"
      :filter-method="filterMethod"
      @update:model-value="$emit('update:modelValue', clamp($event))"
      @keydown.capture="onSelectKeydown"
      @visible-change="onVisibleChange"
    >
      <template #empty>
        <div class="empty-hint">无匹配序列</div>
      </template>
      <template #footer>
        <div v-if="kw && matches.length > 0" class="match-hint">匹配 {{ matches.length }} 项，按 Enter 全选</div>
      </template>
    </el-select-v2>
    <div class="seri-actions">
      <el-button size="small" link type="primary" :disabled="options.length === 0" @click="selectAll">
        全选
      </el-button>
      <el-button size="small" link type="primary" :disabled="modelValue.length === 0" @click="clearAll">
        清空
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useSelectFilter } from '../../composables/useSelectFilter'

/**
 * 对比序列选择器：交互与查看数据「搜索测试项」输入框（TestColumnSelector）
 * 一致——输入关键词 → 按 Enter 全选匹配（合并语义增量累计）。
 * 选项 = 两文件公共序列（升序），默认由父级勾选前 10 颗。
 *
 * 模板上的 `popper-class="dp-serial-popper"` 是**实例级**下拉身份：面板 teleport 到 body，
 * 与本页两个文件选择器的 `.el-select-dropdown` 同名，而收起的 ~150ms leave 过渡里
 * `aria-hidden` 与 `display` 同拍才翻转，全局查询会挑中正在退出的那一份。
 * e2e 侧的名字在 `e2e/helpers/elplus.ts` 的 `SERIAL_POPPER`，改这里必须同步改它。
 */
interface Props {
  /** 已选序列 */
  modelValue: number[]
  /** 全部公共序列（升序） */
  options: number[]
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), { loading: false })
const emit = defineEmits<{
  (e: 'update:modelValue', value: number[]): void
}>()

/** 已选序列上限（el-table 无列虚拟化：200 序列 × 4 列 ≈ 800 列已到现实极限） */
const MAX_SELECTED = 200

/**
 * 本组件从 `useSelectFilter` destructure 的九个符号（selectRef / kw / matches /
 * selectOptions / filterMethod / onSelectKeydown / onVisibleChange / selectAll /
 * clearAll）与 TestColumn / Export 两族同源；`selectMatches` / `clearFilterInput`
 * 只在该 composable 内部用（Enter 全选、关面板清理），本文件不取。空关键词的 `[]`、
 * v2 filter-method 不过滤（`select-v2/src/useSelect.mjs:114-132`）、EP 内部
 * `states.inputValue` 只能靠冒泡的原生 input 事件同步、automatic-dropdown 打开时
 * input 还 `display:none` 故 isFocusable 跳过聚焦 —— 这些承重理由都写在那个文件里。
 *
 * 模板上两处不能顺手改：`ref="selectRef"`（clearFilterInput 靠它取 filter input）与
 * `@keydown.capture`（v2 的 Enter 绑在过滤 input 自己身上，`select-v2/src/select.mjs:227`
 * 的 `withKeys(withModifiers(onKeyboardSelect, ["stop","prevent"]), ["enter"])` ⇒ 只有
 * 祖先的捕获阶段才抢在「选中键盘高亮那一项」之前）。
 *
 * ⚠ `selectOptions` 不能改名成 `options`：props 里已有一个 `options: number[]`（模板里的
 * `options` 就是它）。同名会让 `:disabled="options.length === 0"` 从「有没有公共序列」变成
 * 「过滤后有没有匹配项」——空关键词时两者恰好等价，只有搜一个不存在的序列号时才把整个控件禁掉。
 */
const { selectRef, kw, matches, selectOptions, filterMethod,
        onSelectKeydown, onVisibleChange, selectAll, clearAll } =
  useSelectFilter<number>({
    source: () => props.options,
    selected: () => props.modelValue,
    onChange: (v) => emit('update:modelValue', v),
    limit: MAX_SELECTED,
    focusOnOpen: true,
  })

void selectRef // 绑模板 ref="selectRef"（noUnusedLocals 需要显式消费一次，同 Site3DChart）

/** 超限裁剪：保留前 N（配合 multiple-limit 双保险） */
function clamp(sel: number[]): number[] {
  return sel.length > MAX_SELECTED ? sel.slice(0, MAX_SELECTED) : sel
}
</script>

<style scoped>
.serial-selector {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 260px;
}

.seri-select {
  width: 100%;
}

.seri-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}

.seri-actions :deep(.el-button + .el-button) {
  margin-left: 2px;
}

.match-hint {
  padding: 6px 12px;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  border-top: 1px solid var(--border);
}

.empty-hint {
  padding: 8px 12px;
  font-size: var(--p-fs-dense);
  color: var(--text-3);
}
</style>

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
import { ref, computed, nextTick } from 'vue'
import { filterByKeyword, toOptions } from '../../../../utils/selectOptions'

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

const filterText = ref('')
const selectRef = ref<{ $el: HTMLElement }>()

const kw = computed(() => filterText.value.trim().toLowerCase())

/**
 * 匹配项：复用共享谓词 `filterByKeyword`（与参数下拉同一口径，含数字转字符串的子串匹配）。
 *
 * 空关键词这一支必须自己给 `[]`，不能把 `filterText` 透传进去让 `filterByKeyword` 处理：
 * 它空串时返回**入参本身**（全量，`filterByKeyword` 的 `toBe` 判据钉着这条引用契约），
 * 而这里「没有关键词」= 「没有可全选的匹配集」——footer 提示与 `onSelectKeydown` 的 Enter
 * 拦截都以 matches 非空为前提，透传会把「没输入」变成「全匹配」，Enter 于是从 EP 的
 * 「选中键盘高亮那一项」变成「全选上千颗序列」（`onSelectKeydown` 的注释就是要防这个）。
 */
const matches = computed(() => (kw.value ? filterByKeyword(props.options, filterText.value) : []))

/**
 * 下拉选项 = 匹配集（有关键词）或全量（无关键词），**不截断**。
 * `el-select-v2` 的 filter-method 不过滤（`select-v2/src/useSelect.mjs:114-132`：
 * 判到 filterMethod 合法后 `isValidOption` 恒 true ⇒ `filteredOptions` = 传进去的
 * `props.options` 原样），所以这里必须给已经过滤好的数组；虚拟化让上万条序列可浏览，
 * 旧「靠 300 封顶防冻结」的前提（el-select 无虚拟化）已随本次迁移作废。
 *
 * ⚠ 名字必须是 `selectOptions`，不能叫 `options`：props 里已有一个 `options: number[]`
 * （模板里的 `options` 就是它）。两边同名会让 `:disabled="options.length === 0"` 从「有没有
 * 公共序列」变成「过滤后有没有匹配项」——空关键词时两者恰好等价，正常路径看不出差别，
 * 只有搜一个不存在的序列号时才把整个控件禁掉。
 */
const selectOptions = computed(() => toOptions(kw.value ? matches.value : props.options))

/** 超限裁剪：保留前 N（配合 multiple-limit 双保险） */
function clamp(sel: number[]): number[] {
  return sel.length > MAX_SELECTED ? sel.slice(0, MAX_SELECTED) : sel
}

/** 只是记下关键词：v2 的 filter-method 不过滤（见上面 selectOptions 的注释），过滤由 kw/matches 承担 */
function filterMethod(query: string) {
  filterText.value = query
}

/**
 * 捕获阶段拦截 Enter：输入框有关键字且有匹配时 = 全选。
 * v2 里 Enter 绑在过滤 input 自己身上（`select-v2/src/select.mjs:227`：
 * `withKeys(withModifiers(onKeyboardSelect, ["stop", "prevent"]), ["enter"])`），
 * 目标上的监听器晚于祖先的捕获阶段 ⇒ 挂在根 div 的 capture 监听必先执行，
 * 这里 preventDefault + stopPropagation 才能抢在它（「选中键盘高亮那一项」）之前。
 * 输入框为空（kw 空）时不拦截，保留 EP 原行为（选中高亮项）。
 */
function onSelectKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && matches.value.length > 0) {
    e.preventDefault()
    e.stopPropagation()
    selectMatches()
  }
}

/**
 * 清空过滤（含 EP 内部 query）：states.inputValue 是 EP 内部状态，外部只能
 * 通过原生 input 事件（onInput → handleQueryChange）同步，故置空后派发 input 事件。
 */
function clearFilterInput() {
  filterText.value = ''
  const inputEl = selectRef.value?.$el?.querySelector('input')
  if (inputEl) {
    inputEl.value = ''
    inputEl.dispatchEvent(new Event('input', { bubbles: true }))
  }
}

/** 下拉打开时聚焦过滤框；关闭时清空过滤，避免残留过滤误导下一次打开 */
function onVisibleChange(visible: boolean) {
  if (visible) {
    // EP 2.14 automatic-dropdown：菜单在 wrapper 获焦（mousedown）时就打开，此时
    // filter input 仍 display:none，EP 的 click 焦点逻辑被 isFocusable 守卫跳过，
    // 焦点困在 tabindex=-1 的 wrapper 上——打开后须显式聚焦 input 才能打字过滤。
    nextTick(() => selectRef.value?.$el?.querySelector('input')?.focus())
  } else {
    clearFilterInput()
  }
}

function selectAll() {
  emit('update:modelValue', clamp([...props.options]))
}

function clearAll() {
  emit('update:modelValue', [])
}

/** 合并语义：已选 ∪ 匹配项（增量累计，误选靠清空/单项取消）；超 200 裁剪 */
function selectMatches() {
  if (matches.value.length === 0) return
  emit('update:modelValue', clamp([...new Set([...props.modelValue, ...matches.value])]))
  clearFilterInput()
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

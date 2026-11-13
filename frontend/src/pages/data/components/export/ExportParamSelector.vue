<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">1</span>
      <span class="step-title">选择参数</span>
      <span class="step-count">已选 {{ modelValue.length }} / 共 {{ params.length }} 个</span>
    </div>
    <div class="step-body">
      <!--
        `popper-class="dp-export-param-popper"` 是**实例级**下拉身份：面板 teleport 到 body，与导出页
        文件横幅的 FileSelect、`ExportActions.vue:11` 的 Sigma 下拉共用 `.el-select-dropdown` 类名，
        而收起那 ~150ms 的 leave 过渡里 `aria-hidden` 与 `display` 同拍才翻转，全局查询会挑中正在退出
        的那一份（机理见 `e2e/helpers/params.ts:28-49` 的采样表）。e2e 侧的名字在
        `e2e/helpers/elplus.ts` 的 `EXPORT_PARAM_POPPER`，改这里必须同步改它。
      -->
      <el-select-v2
        ref="selectRef"
        :model-value="modelValue"
        :options="selectOptions"
        multiple
        filterable
        placeholder="点击选择要导出的参数"
        collapse-tags
        collapse-tags-tooltip
        class="param-select"
        aria-label="选择导出参数"
        popper-class="dp-export-param-popper"
        :filter-method="filterMethod"
        @update:model-value="$emit('update:modelValue', $event)"
        @keydown.capture="onSelectKeydown"
        @visible-change="onVisibleChange"
      >
        <template #footer>
          <div v-if="kw && matches.length > 0" class="match-hint">匹配 {{ matches.length }} 项，按 Enter 全选</div>
        </template>
      </el-select-v2>
      <el-button size="small" :disabled="params.length === 0" @click="selectAll">全选</el-button>
      <el-button size="small" :disabled="modelValue.length === 0" @click="clearAll">清空</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { filterByKeyword, toOptions } from '../../../../utils/selectOptions'

interface Props {
  params: string[]
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const filterText = ref('')
const selectRef = ref<{ $el: HTMLElement }>()

const kw = computed(() => filterText.value.trim().toLowerCase())

/**
 * 匹配项：大小写不敏感子串匹配，复用共享谓词 `filterByKeyword`（与参数/序列/测试列下拉同一口径）。
 *
 * 空关键词这一支必须自己给 `[]`：`filterByKeyword` 空串时返回**入参本身**（全量，那是它自己的
 * 引用契约），透传会把「没输入」变成「全匹配」⇒ footer 冒出「按 Enter 全选」，而 `onSelectKeydown`
 * 于是从 EP 的「选中键盘高亮那一项」变成「全选上千个参数」（下面那段注释就是要防这个）。
 */
const matches = computed(() => (kw.value ? filterByKeyword(props.params, filterText.value) : []))

/**
 * 下拉选项 = 匹配集（有关键词）或全量（无关键词），**不截断**。
 * `el-select-v2` 的 filter-method 不过滤（`select-v2/src/useSelect.mjs:114-132`：判到
 * filterMethod 合法后 `isValidOption` 恒 true ⇒ `filteredOptions` = 传进去的 `props.options`
 * 原样），所以这里必须给已经过滤好的数组；虚拟化让上千参数可浏览，旧「渲染层一律截断到前 N」
 * 的前提（el-select 无虚拟化）已随本次迁移作废——全选走 props.params、Enter 走 matches，
 * 两者本来就是完整集合（旧注释那半句仍然成立，作废的是「截断」那半句）。
 *
 * 名字统一叫 `selectOptions`（Task 6/7/8 三个下拉的约定）：本组件的 props 是 `params`/`modelValue`，
 * 与之不撞名，footer 与按钮上的 `params.length` 引用的仍是全集。
 */
const selectOptions = computed(() => toOptions(kw.value ? matches.value : props.params))

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

/** 下拉关闭时清空过滤，避免残留过滤误导下一次打开 */
function onVisibleChange(visible: boolean) {
  if (!visible) clearFilterInput()
}

function selectAll() {
  emit('update:modelValue', [...props.params])
}

function clearAll() {
  emit('update:modelValue', [])
}

/** 合并语义：已选 ∪ 匹配项（增量累计，误选靠清空/单项取消） */
function selectMatches() {
  if (matches.value.length === 0) return
  emit('update:modelValue', [...new Set([...props.modelValue, ...matches.value])])
  clearFilterInput()
}
</script>

<style scoped>
.step-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand);
  color: var(--text-inverse);
  font-size: var(--p-fs-dense);
  font-weight: 700;
  flex-shrink: 0;
}

.step-title {
  font-size: var(--p-fs-small);
  font-weight: 600;
  color: var(--text);
}

.step-count {
  margin-left: auto;
  font-size: var(--p-fs-micro);
  font-weight: 500;
  color: var(--text-3);
}

.step-body {
  display: flex;
  align-items: center;
  gap: 10px;
}

.param-select {
  flex: 1;
}

.match-hint {
  padding: 6px 12px;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  border-top: 1px solid var(--border);
}
</style>

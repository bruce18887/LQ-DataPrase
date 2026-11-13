<template>
  <div class="test-col-selector">
    <el-select-v2
      ref="selectRef"
      :model-value="modelValue"
      :options="selectOptions"
      multiple
      filterable
      placeholder="搜索测试列"
      collapse-tags
      collapse-tags-tooltip
      class="col-select"
      aria-label="显示测试列"
      popper-class="dp-col-popper"
      :filter-method="filterMethod"
      @update:model-value="$emit('update:modelValue', $event)"
      @keydown.capture="onSelectKeydown"
      @visible-change="onVisibleChange"
    >
      <template #empty>
        <div class="empty-hint">无匹配测试列</div>
      </template>
      <template #footer>
        <!-- 全选/清空收进下拉底部：挂在控件下面会多撑出一行（实测筛选行 75px → 54px），
             而这两个动作只在看列表时才用得到 -->
        <div class="col-footer">
          <div class="col-actions">
            <el-button size="small" link type="primary" :disabled="cols.length === 0" @click="selectAll">
              全选
            </el-button>
            <el-button size="small" link type="primary" :disabled="modelValue.length === 0" @click="clearAll">
              清空
            </el-button>
          </div>
          <div v-if="kw && matches.length > 0" class="match-hint">匹配 {{ matches.length }} 项，按 Enter 全选</div>
        </div>
      </template>
    </el-select-v2>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { filterByKeyword, toOptions } from '../../../../utils/selectOptions'

/**
 * 显示测试列选择器：复用导出工具「选择参数」的交互模式——
 * 输入关键词 → 按 Enter 全选匹配测试列（合并语义增量累计）。
 * 选中列 = 查看数据表格仅显示这些测试列；空选中集 = 显示全部（默认）。
 * 模式来源：ExportParamSelector.vue（2026-08-12 方案 A）。
 *
 * 模板上的 `popper-class="dp-col-popper"` 是**实例级**下拉身份：面板 teleport 到 body，
 * 与本页工具栏另外四个 el-select、文件横幅的 FileSelect 的 `.el-select-dropdown` 同名，
 * 而收起的 ~150ms leave 过渡里 `aria-hidden` 与 `display` 同拍才翻转，全局查询会挑中
 * 正在退出的那一份（2026-11-13 Task 4/5 实测）。e2e 侧的名字在 `e2e/helpers/elplus.ts`
 * 的 `COL_POPPER`，改这里必须同步改它。
 */
interface Props {
  /** 全部测试列（系统列已由父级排除） */
  cols: string[]
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
 * 匹配项：大小写不敏感子串匹配，复用共享谓词 `filterByKeyword`（与参数/序列下拉同一口径）。
 *
 * 空关键词这一支必须自己给 `[]`：`filterByKeyword` 空串时返回**入参本身**（全量，那是它
 * 自己的引用契约），透传会把「没输入」变成「全匹配」⇒ footer 冒出「按 Enter 全选」，
 * 而 `onSelectKeydown` 于是从 EP 的「选中键盘高亮那一项」变成「全选上千列」。
 */
const matches = computed(() => (kw.value ? filterByKeyword(props.cols, filterText.value) : []))

/**
 * 下拉选项 = 匹配集（有关键词）或全量（无关键词），**不截断**。
 * `el-select-v2` 的 filter-method 不过滤（`select-v2/src/useSelect.mjs:114-132`：判到
 * filterMethod 合法后 `isValidOption` 恒 true ⇒ `filteredOptions` = 传进去的 `props.options`
 * 原样），所以这里必须给已经过滤好的数组；虚拟化让上千测试列可浏览，旧「靠 300 封顶
 * 防冻结」的前提（el-select 无虚拟化）已随本次迁移作废。
 *
 * ⚠ 名字必须是 `selectOptions`（Task 6/7/8 三个下拉的统一约定）：本组件的 props 是
 * `cols`/`modelValue`，与它不撞名，所以 footer 上 `:disabled="cols.length === 0"` 引用的仍是
 * **全集**。哪天有人把 computed 改成顶掉 `cols` 的名字，「搜一个不存在的关键词」就会把全选
 * 按钮禁掉——空关键词时两者恰好等价，正常路径看不出差别（Task 6 的同款陷阱）。
 */
const selectOptions = computed(() => toOptions(kw.value ? matches.value : props.cols))

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
  emit('update:modelValue', [...props.cols])
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
.col-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 12px;
}

.col-actions {
  display: flex;
  gap: 2px;
}

.col-actions :deep(.el-button + .el-button) {
  margin-left: 2px;
}

.match-hint {
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  margin-left: auto;
}

.empty-hint {
  padding: 8px 12px;
  font-size: var(--p-fs-dense);
  color: var(--text-3);
}
</style>

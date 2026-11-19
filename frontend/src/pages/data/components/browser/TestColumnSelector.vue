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
import { useSelectFilter } from '../../composables/useSelectFilter'

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

/**
 * 九个符号（selectRef / kw / matches / selectOptions / filterMethod / onSelectKeydown /
 * onVisibleChange / selectAll / clearAll）与 Serial / Export 两族同源，承重理由的 owner 是
 * `composables/useSelectFilter.ts`：空关键词必须自己给 `[]`（`filterByKeyword` 空串返回入参
 * 本身）、v2 的 filter-method 不过滤（`useSelect.mjs:114-132`）故选项要预过滤、EP 内部
 * `states.inputValue` 只能靠冒泡的原生 input 事件同步、Enter 必须走祖先捕获阶段才抢在
 * 「选中键盘高亮那一项」之前。选项 = 匹配集或全集，**不截断**（可浏览性交给虚拟化）。
 * `selectMatches` / `clearFilterInput` 只在该 composable 内部用，本文件不取。
 *
 * 模板上两处不能顺手改：`ref="selectRef"`（清过滤靠它取 filter input）与 `@keydown.capture`。
 *
 * ⚠ `selectOptions` 不能改名成 `cols`：footer 的 `:disabled="cols.length === 0"` 引用的是
 * **全集 props**。同名会让「搜一个不存在的关键词」把全选按钮禁掉——空关键词时两者恰好
 * 等价，正常路径看不出差别。
 */
const { selectRef, kw, matches, selectOptions, filterMethod,
        onSelectKeydown, onVisibleChange, selectAll, clearAll } =
  useSelectFilter<string>({
    source: () => props.cols,
    selected: () => props.modelValue,
    onChange: (v) => emit('update:modelValue', v),
  })

void selectRef // 绑模板 ref="selectRef"（noUnusedLocals 要显式消费一次，同 SerialSelector）
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

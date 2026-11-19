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
import { useSelectFilter } from '../../composables/useSelectFilter'

interface Props {
  params: string[]
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

/**
 * 九个符号（selectRef / kw / matches / selectOptions / filterMethod / onSelectKeydown /
 * onVisibleChange / selectAll / clearAll）与 Serial / 测试列两族同源，承重理由的 owner 是
 * `composables/useSelectFilter.ts`：空关键词必须自己给 `[]`（`filterByKeyword` 空串返回入参
 * 本身）、v2 的 filter-method 不过滤（`useSelect.mjs:114-132`）故选项要预过滤、EP 内部
 * `states.inputValue` 只能靠冒泡的原生 input 事件同步、Enter 必须走祖先捕获阶段才抢在
 * 「选中键盘高亮那一项」之前。选项 = 匹配集或全集，**不截断**（可浏览性交给虚拟化）。
 * `selectMatches` / `clearFilterInput` 只在该 composable 内部用，本文件不取。
 *
 * 模板上两处不能顺手改：`ref="selectRef"`（清过滤靠它取 filter input）与 `@keydown.capture`。
 *
 * ⚠ `selectOptions` 不能改名成 `params`：按钮与 footer 引用的 `params.length` 是**全集 props**。
 * 同名会让「搜一个不存在的关键词」把全选按钮禁掉——空关键词时两者恰好等价，正常路径看不出差别。
 */
const { selectRef, kw, matches, selectOptions, filterMethod,
        onSelectKeydown, onVisibleChange, selectAll, clearAll } =
  useSelectFilter<string>({
    source: () => props.params,
    selected: () => props.modelValue,
    onChange: (v) => emit('update:modelValue', v),
  })

void selectRef // 绑模板 ref="selectRef"（noUnusedLocals 要显式消费一次，同 SerialSelector）
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

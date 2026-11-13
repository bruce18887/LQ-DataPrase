<template>
  <div class="param-selector" :class="{ 'param-selector--inline': inline }">
    <div class="selector-label">选择参数 (↑↓ 切换)</div>
    <el-select-v2
      :model-value="selectedParam"
      :options="options"
      placeholder="输入搜索或选择参数..."
      filterable
      clearable
      size="small"
      :style="inline ? 'width: 260px' : 'width: 100%'"
      :filter-method="filterMethod"
      :popper-class="popperClass"
      @change="onParamChange"
      @visible-change="onVisibleChange"
    >
      <!-- 高亮片段**在这里**算，不是在 computed 里：`el-select-v2` 的 #default 是逐条
           渲染器，虚拟窗口每帧只渲染十来行（2026-11-13 实测 1723 项的文件上 DOM 里 11 行，
           输入 '1' 命中 585 项时 highlightSegments 只被调用 33 次）。旧写法在 listView 里
           给每个匹配项预建 segments 数组，那是性能批 d1146dd 治掉的东西（原注释：1,702 项
           的文件上每次击键建 1,702 份），全量渲染后放回来就是原样回退。 -->
      <template #default="{ item }">
        <div class="param-option">
          <span class="param-name">
            <!-- 分段算的是 **label**：EP 自己的兜底渲染的也是 `getLabel(item)`
                 （`select-v2/src/select-dropdown.mjs:110`）。今天 label===String(value)，
                 换成 item.value 看不出差别，但后面三个下拉一旦 label≠value（序列号要有
                 「SN-3」这类展示名），照抄的这段就会高亮一个屏幕上根本不存在的文本。 -->
            <span
              v-for="(seg, i) in segmentsFor(String(item.label))"
              :key="i"
              :class="{ 'param-name__hit': seg.mark }"
            >{{ seg.text }}</span>
          </span>
        </div>
      </template>
      <template #footer>
        <!-- 封顶取消了，但「一共多少项」仍然要说：用户需要知道自己在看的不是残缺列表 -->
        <div class="param-count-hint">共 {{ total }} 项</div>
      </template>
    </el-select-v2>
    <div class="nav-buttons">
      <el-button :disabled="params.length === 0" size="small" @click="onPrev">
        ◀ 上一个
      </el-button>
      <el-button :disabled="params.length === 0" size="small" @click="onNext">
        下一个 ▶
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { buildParamOptions, highlightSegments } from '../../../utils/selectOptions'

const props = withDefaults(defineProps<{
  params: string[]
  selectedParam: string
  /** teleport 到 body 的下拉面板**实例级** class：ParamSelector 在单文件 tab
   * （非 lazy 常驻）与多文件 tab 各挂一个，同名 popper 会让隐藏 pane 的面板
   * 参与全局可见性查询——reference 零尺寸导致 popper 逐帧重定位、
   * `.first()` 误点另一个 tab 的选项（lessons 2026-09-05）。
   * ⚠ 迁 v2 后它只挂在外层 `.el-popper` 上（v1 还会把同一个 class 复制一份到内层
   * `.el-select-dropdown`，`select-v2/src/select-dropdown.mjs:155` 没有那一项），
   * 所以定位必须落在 `.el-popper.<这里>` —— 那也正是 `helpers/params.ts` 的写法。 */
  popperClass?: string
  /** inline：横向单行（label + select + 上下一个），用于单文件 tab 顶部冻结行；
      默认纵向堆叠（多文件 tab 的 top-bar 布局不变） */
  inline?: boolean
}>(), { popperClass: 'dp-param-popper-single', inline: false })

const emit = defineEmits<{
  'update:selectedParam': [value: string]
}>()

const filterText = ref('')

/** 视图 = 过滤 → 前缀优先排序 → {value,label} 映射；无截断（见 utils 的注释） */
const view = computed(() => buildParamOptions(props.params, filterText.value))
const options = computed(() => view.value.options)
const total = computed(() => view.value.total)

/** 由 #default 逐条渲染器调用 ⇒ 只对虚拟窗口内的项计算 */
function segmentsFor(name: string) {
  return highlightSegments(name, filterText.value)
}

/**
 * `el-select-v2` 的 filter-method 在 2.14.0 里**不过滤**，只是回调
 * （`select-v2/src/useSelect.mjs:114-132`）。这里只记关键词，过滤由上面的 `view` 承担。
 */
function filterMethod(query: string) {
  filterText.value = query
}

/** 下拉框关闭时清空过滤 */
function onVisibleChange(visible: boolean) {
  if (!visible) filterText.value = ''
}

function onParamChange(val: string) {
  emit('update:selectedParam', val)
}

/** ◀上一个/下一个▶：推进逻辑只有这一份（父组件曾经还有一份同逻辑副本，
 *  与这里的 emit 叠成「点一次跳两项」，2026-10-17 删掉）。 */
function onPrev() {
  const idx = props.params.indexOf(props.selectedParam)
  if (idx > 0) {
    emit('update:selectedParam', props.params[idx - 1])
  } else if (props.params.length > 0) {
    emit('update:selectedParam', props.params[props.params.length - 1])
  }
}

function onNext() {
  const idx = props.params.indexOf(props.selectedParam)
  if (idx < props.params.length - 1) {
    emit('update:selectedParam', props.params[idx + 1])
  } else if (props.params.length > 0) {
    emit('update:selectedParam', props.params[0])
  }
}
</script>

<style scoped>
.param-selector {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selector-label {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-weight: 500;
}

.nav-buttons {
  display: flex;
  gap: 8px;
}

.nav-buttons :deep(.el-button) {
  flex: 1;
  padding: 6px 8px;
  font-size: var(--p-fs-dense);
}

/* inline：单行不换行、按钮自适应宽度（不撑满） */
.param-selector--inline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.param-selector--inline .selector-label {
  white-space: nowrap;
}
.param-selector--inline .nav-buttons {
  flex: none;
}
.param-selector--inline .nav-buttons :deep(.el-button) {
  flex: none;
  padding: 5px 8px;
}

.param-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.param-name {
  font-size: var(--p-fs-small);
  color: var(--text);
}

.param-name__hit {
  color: var(--brand);
  font-weight: 600;
  background-color: color-mix(in srgb, var(--brand) 15%, transparent);
  padding: 0 2px;
  border-radius: 2px;
}

/* 全量计数提示（footer 槽）：两主题都走 token，不写死颜色 */
.param-count-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  text-align: center;
}
</style>

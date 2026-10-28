<template>
  <div class="param-selector" :class="{ 'param-selector--inline': inline }">
    <div class="selector-label">选择参数 (↑↓ 切换)</div>
    <el-select
      :model-value="selectedParam"
      placeholder="输入搜索或选择参数..."
      filterable
      clearable
      size="small"
      :style="inline ? 'width: 260px' : 'width: 100%'"
      :filter-method="filterMethod"
      @change="onParamChange"
      @visible-change="onVisibleChange"
      :popper-class="popperClass"
    >
      <el-option
        v-for="item in filteredItems"
        :key="item.value"
        :label="item.value"
        :value="item.value"
      >
        <div class="param-option">
          <span class="param-name">
            <template v-if="item.segments">
              <span
                v-for="(seg, i) in item.segments"
                :key="i"
                :class="{ 'param-name__hit': seg.mark }"
              >{{ seg.text }}</span>
            </template>
            <template v-else>{{ item.value }}</template>
          </span>
          <!-- 分类提示：暂时关闭，后续开发启用 -->
          <!-- <span v-if="item.hint" class="param-hint">{{ item.hint }}</span> -->
        </div>
      </el-option>
      <template #footer>
        <!-- 渲染封顶必须说出来：用户看到的不是全量，靠输入缩小范围 -->
        <div v-if="capped" class="param-cap-hint">
          共 {{ listView.total }} 项，仅显示前 {{ DROPDOWN_RENDER_CAP }}，继续输入可缩小范围
        </div>
      </template>
    </el-select>
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
import { ref, computed } from 'vue'
import { DROPDOWN_RENDER_CAP } from '../../../constants/dropdown'

interface ParamSegment { text: string; mark: boolean }

interface ParamItem {
  value: string
  segments?: ParamSegment[]
  hint?: string
}

const props = withDefaults(defineProps<{
  params: string[]
  selectedParam: string
  /** teleport 到 body 的下拉面板**实例级** class：ParamSelector 在单文件 tab
   * （非 lazy 常驻）与多文件 tab 各挂一个，同名 popper 会让隐藏 pane 的面板
   * 参与全局 `:visible` 选项查询——reference 零尺寸导致 popper 逐帧重定位、
   * `.first()` 误点另一个 tab 的选项（lessons 2026-09-05） */
  popperClass?: string
  /** inline：横向单行（label + select + 上下一个），用于单文件 tab 顶部冻结行；
      默认纵向堆叠（多文件 tab 的 top-bar 布局不变） */
  inline?: boolean
}>(), { popperClass: 'dp-param-popper-single', inline: false })

const emit = defineEmits<{
  'update:selectedParam': [value: string]
}>()

const filterText = ref('')

/** 构建参数列表（带分类提示） */
const allItems = computed<ParamItem[]>(() =>
  props.params.map((p) => ({
    value: p,
    hint: getParamHint(p),
  }))
)

/**
 * 列表视图：items = 实际渲染的选项（截断到 DROPDOWN_RENDER_CAP），total = 截断前条数。
 *
 * 顺序改成「过滤 → 排序 → 截断 → 高亮」。原写法是「过滤 → 高亮 → 排序」，即给每个
 * 匹配项都建一份 segments 数组（1,702 项的文件上每次击键建 1,702 份），而真正渲染的
 * 只有前 N 项。排序必须留在截断之前，否则截到的是错的 N 项。
 */
const listView = computed<{ items: ParamItem[]; total: number }>(() => {
  const raw = filterText.value
  if (!raw) {
    const all = allItems.value
    return { items: all.slice(0, DROPDOWN_RENDER_CAP), total: all.length }
  }
  const query = raw.toLowerCase()
  const matched = allItems.value
    .filter((item) => item.value.toLowerCase().includes(query))
    .sort((a, b) => {
      // 前缀匹配优先
      const aStarts = a.value.toLowerCase().startsWith(query)
      const bStarts = b.value.toLowerCase().startsWith(query)
      if (aStarts && !bStarts) return -1
      if (!aStarts && bStarts) return 1
      return a.value.localeCompare(b.value)
    })
  return {
    items: matched
      .slice(0, DROPDOWN_RENDER_CAP)
      .map((item) => ({ ...item, segments: highlightSegments(item.value, raw) })),
    total: matched.length,
  }
})

/** 渲染中的选项（已封顶） */
const filteredItems = computed(() => listView.value.items)
/** 是否发生截断：决定 footer 提示是否出现 */
const capped = computed(() => listView.value.total > DROPDOWN_RENDER_CAP)

/** 根据参数名推断分类提示 */
function getParamHint(param: string): string {
  const upper = param.toUpperCase()
  if (upper.includes('VOLTAGE') || upper.includes('V_') || upper.startsWith('V')) return '电压'
  if (upper.includes('CURRENT') || upper.includes('I_') || upper.startsWith('I')) return '电流'
  if (upper.includes('RESISTANCE') || upper.includes('R_') || upper.startsWith('R')) return '电阻'
  if (upper.includes('FREQUENCY') || upper.includes('F_') || upper.startsWith('F')) return '频率'
  if (upper.includes('TIME') || upper.includes('T_')) return '时间'
  if (upper.includes('POWER') || upper.includes('P_')) return '功率'
  if (upper.includes('GAIN') || upper.includes('G_')) return '增益'
  if (upper.includes('TEMP') || upper.includes('T_')) return '温度'
  return ''
}

/** 高亮分段：返回 {text, mark} 片段列表，模板用 {{ }} 插值渲染。
 * 不走 v-html：参数名来自上传文件的列头（用户可控输入），旧实现对 text
 * 未转义，列名含 `<img src=x onerror=...>` 即成存储型 XSS，普通 `<`/`&`
 * 也会被当标签/实体吞掉导致下拉显示错乱。大小写不敏感子串匹配与旧
 * `gi` 正则高亮等价，且无正则元字符转义问题。 */
function highlightSegments(text: string, query: string): ParamSegment[] {
  if (!query) return [{ text, mark: false }]
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  const segments: ParamSegment[] = []
  let i = 0
  while (i < text.length) {
    const idx = lower.indexOf(q, i)
    if (idx === -1) {
      segments.push({ text: text.slice(i), mark: false })
      break
    }
    if (idx > i) segments.push({ text: text.slice(i, idx), mark: false })
    segments.push({ text: text.slice(idx, idx + q.length), mark: true })
    i = idx + q.length
  }
  return segments
}

/** 自定义过滤方法 */
function filterMethod(query: string) {
  filterText.value = query
}

/** 下拉框关闭时清空过滤 */
function onVisibleChange(visible: boolean) {
  if (!visible) {
    filterText.value = ''
  }
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

.param-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  margin-left: 12px;
  flex-shrink: 0;
}

/* 截断提示（footer 槽）：两主题都走 token，不写死颜色 */
.param-cap-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  text-align: center;
}
</style>

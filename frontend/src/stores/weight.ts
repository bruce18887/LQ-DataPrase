import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import { slotCount, type WeightDocDto } from '../pages/weight/weightChartOption'

/** 只活在本会话：刷新即丢（spec §11，不落 localStorage）。 */
export const useWeightStore = defineStore('weight', () => {
  /**
   * 解析产物：最坏 2000 条系列 × 1024 点（`apps/weight/parser.py` 的
   * DECLARATION_LIMIT / LENGTH_LIMIT）。它整体替换、从不就地改字段，所以用 shallowRef
   * 只让「换文件」这件事进依赖表 —— 深度代理会给每个点对象建一层 Proxy，读一遍就是
   * 上百万次代理跳转，而这份数据每次重绘都要被完整遍历。
   */
  const doc = shallowRef<WeightDocDto | null>(null)
  const rawText = ref('')            // 导出要把原文再交回同一个解析器（spec §2 第 4 条）
  const filename = ref('')
  const visible = ref<number[]>([])
  /** 组内曲线（图例项 1/2/3/4…）的可见槽位：只影响图表，明细表与 xlsx 都不跟。 */
  const visibleSlots = ref<number[]>([])
  const showMean = ref(true)          // 默认打开均值（2026-10-20 用户点定）
  const showLegend = ref(true)        // 图例总开关：只管底部那行标签画不画，不影响任何曲线
  const errorText = ref('')
  const busy = ref(false)

  function setDoc(next: WeightDocDto, text: string) {
    doc.value = next
    rawText.value = text
    filename.value = next.filename
    visible.value = next.groups.map((g) => g.index)   // 换文件全量复位
    // 槽位数取该文件的最长组：同名出现 6 次就有第 6 槽，别按「一组四条」写死
    visibleSlots.value = Array.from({ length: slotCount(next) }, (_, i) => i)
    showMean.value = true
    showLegend.value = true
    errorText.value = ''
  }
  // 组/槽位的可见性改动走组件自己的 `update:visible` emit（WeightFilterChips:22-32），
  // 这里不再放第三份 toggle 实现。
  return {
    doc, rawText, filename, visible, visibleSlots, showMean, showLegend, errorText, busy,
    setDoc,
  }
})

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { WeightDocDto } from '../pages/weight/weightChartOption'

/** 只活在本会话：刷新即丢（spec §11，不落 localStorage）。 */
export const useWeightStore = defineStore('weight', () => {
  const doc = ref<WeightDocDto | null>(null)
  const rawText = ref('')            // 导出要把原文再交回同一个解析器（spec §2 第 4 条）
  const filename = ref('')
  const visible = ref<number[]>([])
  const showMean = ref(true)          // 默认打开均值（2026-10-20 用户点定）
  const errorText = ref('')
  const busy = ref(false)

  const allVisible = computed(() => doc.value !== null && visible.value.length === doc.value.group_count)

  function reset() {
    doc.value = null; rawText.value = ''; filename.value = ''
    visible.value = []; showMean.value = true
    errorText.value = ''; busy.value = false
  }
  function setDoc(next: WeightDocDto, text: string) {
    doc.value = next
    rawText.value = text
    filename.value = next.filename
    visible.value = next.groups.map((g) => g.index)   // 换文件全量复位
    showMean.value = true
    errorText.value = ''
  }
  function toggleGroup(index: number, on: boolean) {
    const set = new Set(visible.value)
    on ? set.add(index) : set.delete(index)
    visible.value = [...set].sort((a, b) => a - b)
  }
  return { doc, rawText, filename, visible, showMean, errorText, busy, allVisible, reset, setDoc, toggleGroup }
})

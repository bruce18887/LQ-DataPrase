import { computed, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { copyText } from './clipboard'

/**
 * 查看数据表头右键菜单：复制原始列名 / 打开分布图。
 *
 * 菜单状态、分布图对话框状态都住在这里，DataBrowserAgGrid 只负责
 * 把右键事件转进来。非数值列的「展示分布图」置灰（页面提示原因）。
 */
export function useHeaderMenu(opts: {
  numericColumns: Ref<string[]>
  isSystemCol: (col: string) => boolean
  closeOtherMenu: () => void
}) {
  const visible = ref(false)
  const x = ref(0)
  const y = ref(0)
  const col = ref('')

  const isSystem = computed(() => (col.value ? opts.isSystemCol(col.value) : false))
  const isNumeric = computed(() =>
    col.value ? opts.numericColumns.value.includes(col.value) : false,
  )

  const histDialogVisible = ref(false)
  const analyzeParam = ref('')

  function close() {
    visible.value = false
  }

  function open(name: string, e: MouseEvent) {
    opts.closeOtherMenu()
    col.value = name
    x.value = e.clientX
    y.value = e.clientY
    visible.value = true
  }

  async function copyName() {
    const name = col.value
    close()
    if (!name) return
    if (await copyText(name)) {
      ElMessage.success(`已复制：${name}`)
    } else {
      ElMessage.error('复制失败，请检查剪贴板权限')
    }
  }

  function showHistogram() {
    const name = col.value
    close()
    if (!name || !opts.numericColumns.value.includes(name)) return
    analyzeParam.value = name
    histDialogVisible.value = true
  }

  return {
    visible,
    x,
    y,
    col,
    isSystem,
    isNumeric,
    histDialogVisible,
    analyzeParam,
    open,
    close,
    copyName,
    showHistogram,
  }
}

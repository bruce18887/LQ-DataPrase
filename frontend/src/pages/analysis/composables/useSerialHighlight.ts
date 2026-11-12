/**
 * 会话级 serial 芯片高亮（2026-11-12 子集跟进计划 Task 4）。
 * 模块单例仿 useSubsetPanels：detached effectScope(true) 常驻，不绑首个调用组件的作用域。
 * 切文件清空（R5，watch store.fileId）；换账号由 auth 复位调 resetSerialHighlight()。
 * **切参数不清**（显式例外）：同一批芯片跨参数保持，在新参数的图上重画。
 * 高亮渲染以 SerialChart 的 props.enableSelection 为闸，其它页面不显示单参数 tab 的高亮。
 *
 * 高亮来源有二，取并集（2026-11-12 跟进：子图展示即高亮其芯片，关掉子图才取消）：
 *  ① 散点框选（brush）——set/clear 操作这一份，右键「清除高亮」只清它；
 *  ② 打开的子集面板（selection 固化为 serials 后）——只要面板在就持续贡献，
 *     关闭面板/切文件清空后自然消失，无需手动清。serial 图后开启也能立即看到高亮。
 */
import { ref, computed, watch, effectScope } from 'vue'
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { useSubsetPanels } from './useSubsetPanels'
import type { ChartSelection } from './selectionGeometry'

function create() {
  const brushSerials = ref<(number | string)[]>([])
  const serialCol = ref<string | undefined>(undefined)
  const store = useSingleTabStore()
  const subsetPanels = useSubsetPanels()

  /** 子集面板贡献的芯片：selection 固化为 serials 的面板取并集。 */
  const subsetSerials = computed(() => {
    const out: (number | string)[] = []
    for (const p of subsetPanels.panels.value) {
      if (p.selection.kind === 'serials') out.push(...p.selection.serials)
    }
    return out
  })

  /** 对外高亮集合 = brush ∪ 子集，去重保序（brush 在前）。 */
  const serials = computed(() => {
    const seen = new Set<number | string>()
    const out: (number | string)[] = []
    for (const s of [...brushSerials.value, ...subsetSerials.value]) {
      if (!seen.has(s)) { seen.add(s); out.push(s) }
    }
    return out
  })

  /** 只收 serials 选区（rect 框选立即消费时传来）；value_range 不建高亮。 */
  function set(sel: ChartSelection) {
    if (sel.kind !== 'serials') return
    brushSerials.value = [...sel.serials]
    serialCol.value = sel.serial_col
  }
  /** 只清 brush 那份；子集贡献随面板关闭自然消失。 */
  function clear() {
    brushSerials.value = []
    serialCol.value = undefined
  }

  // detached scope：单例 watch 不能绑在首个调用组件的作用域上——登出/401 卸载
  // MainLayout 会停掉它，而单例不重建、resetSerialHighlight 只清不重臂 ⇒ 重新登录后
  // 切文件不再清高亮（R5 泄漏）。effectScope(true) 脱离组件作用域常驻。
  const scope = effectScope(true)
  scope.run(() => {
    // 切文件清空（R5）；换账号由 resetSerialHighlight 显式清；切参数不清（显式例外）
    watch(() => store.fileId, clear)
  })

  return { serials, serialCol, set, clear }
}

let singleton: ReturnType<typeof create> | null = null

export function useSerialHighlight() {
  if (!singleton) singleton = create()
  return singleton
}

/** 登出/登入（stores/auth.ts）调用：不赌 fileId 一定变，显式清空。 */
export function resetSerialHighlight() { singleton?.clear() }

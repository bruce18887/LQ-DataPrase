/**
 * 子集面板 ↔ dock guest 同步桥（2026-11-12：子集并入 dock，可与直方图同排拖拽）。
 *
 * useSubsetPanels 是会话级面板数据源；useChartDock 的 rows 里以 `subset:<id>` guest
 * 表达其布局位次。本桥单向把面板集合投影成 guest：新增面板→addGuest（追加一行），
 * 面板被关/切文件清空→removeGuest。dock 内拖拽只改 rows 不改面板集合，故不会回环。
 * guest 绝不进持久化（useChartDock.persist 剥离），保持 D4/R5 的账号记忆契约。
 */
import { watch } from 'vue'
import { useChartDock, guestKeyOf, isGuestKey, guestIdOf, type ChartKey } from './useChartDock'
import { useSubsetPanels } from './useSubsetPanels'

export function useSubsetDockBridge(getActive: () => ChartKey[]) {
  const dock = useChartDock(getActive)
  const { panels } = useSubsetPanels()

  watch(
    () => panels.value.map((p) => p.id).join(','),
    () => {
      const ids = new Set(panels.value.map((p) => p.id))
      for (const p of panels.value) dock.addGuest(guestKeyOf(p.id))
      for (const g of dock.rows.value.flat().filter(isGuestKey)) {
        if (!ids.has(guestIdOf(g))) dock.removeGuest(g)
      }
    },
    { immediate: true },
  )

  return dock
}
/**
 * useAboutDialog — 「关于」对话框的全局单例状态。
 *
 * 两个入口共享同一对话框：
 * - Electron 菜单 Help → About LQ-DataPrase（AppAboutDialog 内部监听）
 * - Topbar 版本徽章点击
 */
import { ref } from 'vue'

const visible = ref(false)

export function useAboutDialog() {
  function open(): void {
    visible.value = true
  }

  function close(): void {
    visible.value = false
  }

  return { visible, open, close }
}

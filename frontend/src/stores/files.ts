import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 全局文件列表状态管理
 *
 * 解决 SFTP 导入后文件列表不同步的问题：
 * - 生产者（SftpBrowser / FileManager）导入成功后调用 notifyFilesChanged()
 * - 消费者（DashboardPage / DataManagement）通过 onActivated 或 watch filesVersion 重新加载
 */
export const useFilesStore = defineStore('files', () => {
  /** 每次文件变更时递增，消费者 watch 此值触发刷新 */
  const filesVersion = ref(0)

  /** 通知所有消费者文件列表已变更 */
  function notifyFilesChanged() {
    filesVersion.value++
  }

  return { filesVersion, notifyFilesChanged }
})

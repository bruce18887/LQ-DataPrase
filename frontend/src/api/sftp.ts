import type { AxiosRequestConfig } from 'axios'

import api from './index'

export interface SseProgressData {
  event: 'progress'
  current: number
  total: number
  filename: string
  rel_path: string
  percent: number
  speed: number
  eta: number
}

export interface SseDoneData {
  event: 'done'
  dir_name: string
  file_count: number
  total: number
  saved_dir: string
}

export interface SseErrorData {
  event: 'error'
  filename: string
  message: string
}

export interface SftpConfigItem {
  id: number
  name: string
  host: string
  port: number
  username: string
  has_password: boolean
  created_at?: string
  updated_at?: string
}

export interface SftpLastVisit {
  can_auto_connect: boolean
  config_name: string
  host: string
  port: number
  username: string
  last_path: string
}

export interface SftpConnectPayload {
  host?: string
  port?: number
  username?: string
  password?: string
  config_id?: number
  config_name?: string
}

export const sftpApi = {
  /**
   * Connect to an SFTP server. Either supply explicit
   * `{ host, port, username, password }` (legacy manual connect) OR a
   * `{ config_name }` / `{ config_id }` referencing a saved config — in which
   * case the backend decrypts the stored password server-side, so the password
   * never travels to the browser.
   */
  connect(payload: SftpConnectPayload) {
    return api.post('/sftp/connect/', payload)
  },
  disconnect(config?: AxiosRequestConfig) {
    return api.post('/sftp/disconnect/', undefined, config)
  },
  /** 断线续连信息：上次访问路径 + 上次连接凭据（can_auto_connect 表示可服务端自动重连） */
  getLastVisit() {
    return api.get('/sftp/last_visit/')
  },
  /** 用上次保存的配置自动重连（密码服务端解密，不进浏览器）；可选 config_name 覆盖记录 */
  autoConnect(configName?: string) {
    return api.post('/sftp/auto_connect/', configName ? { config_name: configName } : {})
  },
  listFiles(path: string, sortBy = 'name', sortOrder = 'asc') {
    return api.get('/sftp/list_files/', { params: { path, sort_by: sortBy, sort_order: sortOrder } })
  },
  download(path: string) {
    return api.post('/sftp/download/', { path })
  },
  downloadDir(path: string, onlyData = false) {
    return api.post('/sftp/download_dir/', { path, only_data: onlyData })
  },
  downloadBatch(paths: string[]) {
    return api.post('/sftp/download_batch/', { paths })
  },
  downloadAndParse(path: string) {
    return api.post('/sftp/download_and_parse/', { path })
  },
  downloadAndParseBatch(paths: string[]) {
    return api.post('/sftp/download_and_parse/', { paths })
  },
  getConfigs() {
    return api.get('/sftp/configs/')
  },
  saveConfig(payload: { name: string; host: string; port: number; username: string; password?: string }, config?: AxiosRequestConfig) {
    return api.post('/sftp/save_config/', payload, config)
  },
  deleteConfig(payload: { name?: string; id?: number }) {
    return api.post('/sftp/delete_config/', payload)
  },

  /**
   * SSE-based directory download with real-time progress.
   * Uses fetch() instead of axios because EventSource cannot set Authorization headers.
   */
  async downloadDirStream(
    path: string,
    onlyData: boolean,
    onProgress: (data: SseProgressData) => void,
    onDone: (data: SseDoneData) => void,
    onError: (msg: string) => void,
  ) {
    const token = localStorage.getItem('access_token')
    // Re-use the axios base URL so this works in Electron (file://) as well as
    // the browser dev/prod builds, where absolute paths resolve incorrectly.
    const baseUrl = (api.defaults.baseURL || '/api/v1').replace(/\/$/, '')
    try {
      const response = await fetch(`${baseUrl}/sftp/download_dir/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ path, only_data: onlyData }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: '请求失败' }))
        onError(err.error || `HTTP ${response.status}`)
        return
      }
      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop()!
        for (const evt of events) {
          if (!evt.startsWith('data: ')) continue
          try {
            const data = JSON.parse(evt.slice(6))
            if (data.event === 'progress') onProgress(data as SseProgressData)
            else if (data.event === 'done') onDone(data as SseDoneData)
            else if (data.event === 'error') onError(data.message || '下载失败')
          } catch { /* skip malformed events */ }
        }
      }
    } catch (e: any) {
      onError(e.message || '网络错误')
    }
  },
}

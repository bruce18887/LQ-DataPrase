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

export const sftpApi = {
  connect(host: string, port: number, username: string, password: string) {
    return api.post('/sftp/connect/', { host, port, username, password })
  },
  disconnect() {
    return api.post('/sftp/disconnect/')
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
  saveConfig(name: string, config: { host: string; port: number; username: string; password: string }) {
    return api.post('/sftp/save_config/', { name, ...config })
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
    try {
      const response = await fetch('/api/v1/sftp/download_dir/', {
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

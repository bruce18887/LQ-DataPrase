import type { AxiosRequestConfig } from 'axios'

import api from './index'
import { getSftpTimeoutSec } from '../utils/sftpTimeout'
import { safeGetItem } from '../utils/safeStorage'

export interface SseProgressData {
  event: 'progress'
  current: number
  total: number
  filename: string
  rel_path: string
  percent: number
  speed: number
  eta: number
  /** 目录下载：实际累计下载字节 / 远端总字节（按总大小计算进度） */
  bytes_done?: number
  total_bytes?: number
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

export interface SseFileProgressData {
  event: 'progress'
  percent: number
  speed: number
  eta: number
  filename: string
  bytes_done: number
  total_bytes: number
}

export interface SseFileDoneData {
  event: 'done'
  filename: string
  size: number
  datafile_id: number
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
  downloadBatch(paths: string[], config?: AxiosRequestConfig) {
    return api.post('/sftp/download_batch/', { paths }, config)
  },
  downloadAndParse(path: string) {
    return api.post('/sftp/download_and_parse/', { path })
  },
  downloadAndParseBatch(paths: string[], config?: AxiosRequestConfig) {
    return api.post('/sftp/download_and_parse/', { paths }, config)
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

  // ------------------------------------------------------------------
  // SSE download streams
  // ------------------------------------------------------------------

  /**
   * 单文件下载（SSE，带百分比/速率/ETA 进度）。
   *
   * 与 downloadDirStream 同构：fetch + ReadableStream（EventSource 不能带
   * Authorization 头）。timeout 为该次下载允许的最长秒数（后端以此设
   * channel socket 超时 + 整体 deadline；用户可在工具栏自由设定）。
   * 事件：progress(percent/speed/eta) → done(filename/size/datafile_id)
   * 或 error(message)。连接层错误由 onError 回调提示。
   */
  async downloadFileStream(
    path: string,
    timeoutSec: number,
    onProgress: (data: SseFileProgressData) => void,
    onDone: (data: SseFileDoneData) => void,
    onError: (msg: string) => void,
    signal?: AbortSignal,
  ) {
    try {
      await postSse(
        '/sftp/download_file_stream/',
        { path, timeout: timeoutSec },
        (data) => {
          if (data.event === 'progress') onProgress(data as SseFileProgressData)
          else if (data.event === 'done') onDone(data as SseFileDoneData)
          else if (data.event === 'error') onError(data.message || '下载失败')
        },
        signal,
      )
    } catch (e: any) {
      // AbortError 表示用户主动取消（组件卸载），不弹错误提示
      if (e?.name === 'AbortError') return
      onError(e?.message || '网络错误')
    }
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
    signal?: AbortSignal,
  ) {
    const timeoutSec = await getSftpTimeoutSec()
    try {
      await postSse(
        '/sftp/download_dir/',
        { path, only_data: onlyData, timeout: timeoutSec },
        (data) => {
          if (data.event === 'progress') onProgress(data as SseProgressData)
          else if (data.event === 'done') onDone(data as SseDoneData)
          else if (data.event === 'error') onError(data.message || '下载失败')
        },
        signal,
      )
    } catch (e: any) {
      // AbortError 表示用户主动取消（组件卸载），不弹错误提示
      if (e?.name === 'AbortError') return
      onError(e?.message || '网络错误')
    }
  },
}

/**
 * POST 一个 SSE 端点并逐事件回调。非 2xx：解析错误体后抛出（调用方负责
 * 提示）；流式解析与事件分发与旧 downloadDirStream 实现一致。
 *
 * signal: 可选 AbortSignal，透传给 fetch —— 修复此前无法取消进行中 SSE 流
 * 的缺陷（组件卸载后 reader 仍持有并回调更新已失效 ref → 内存泄漏 + 幽灵回调）。
 * localStorage 读取改走 safeGetItem（Electron 磁盘满/权限异常时不白屏）。
 */
async function postSse(
  url: string,
  body: Record<string, unknown>,
  onData: (data: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = safeGetItem('access_token')
  // Re-use the axios base URL so this works in Electron (file://) as well as
  // the browser dev/prod builds, where absolute paths resolve incorrectly.
  const baseUrl = (api.defaults.baseURL || '/api/v1').replace(/\/$/, '')
  const response = await fetch(`${baseUrl}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: '请求失败' }))
    throw new Error(err.error || `HTTP ${response.status}`)
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
        onData(JSON.parse(evt.slice(6)))
      } catch { /* skip malformed events */ }
    }
  }
}

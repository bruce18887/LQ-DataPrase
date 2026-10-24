import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

import { authApi } from './auth'
import { useAuthStore } from '../stores/auth'
import { formatError } from '../utils/error'
import { safeGetItem } from '../utils/safeStorage'

// 请求级逃生口：设为 true 时该请求的错误不弹全局提示（调用方自行处理，
// 如表单行内校验、静默轮询）。
declare module 'axios' {
  interface AxiosRequestConfig {
    silent?: boolean
  }
}

// 同一错误消息 2 秒内只弹一次，避免图表联动等并发场景的 toast 轰炸。
// ⚠ 这道闸只护得住**走拦截器**的提示：调用方自己 `ElMessage.error(...)` 绕开它，
// 而请求级 `silent` 也只是让**这一条**请求不响（同页其它请求照样各响一次）。
// ⇒ 「页面再补一句」在这个仓库里没有好形状：2026-10-23 收口池实测，两条同族
// `.el-message--error` 会把按文案取 toast 的 e2e/global/error-handling.spec.ts
// 顶成 strict mode 歧义。失败要出声就交回这里（单声源），别另开一条通路。
let lastToastMessage = ''
let lastToastAt = 0

function toastError(message: string) {
  const now = Date.now()
  if (message === lastToastMessage && now - lastToastAt < 2000) return
  lastToastMessage = message
  lastToastAt = now
  ElMessage.error(message)
}

// ---------------------------------------------------------------------------
// Electron backend URL detection
// ---------------------------------------------------------------------------
// When running inside Electron the main process passes the backend base URL
// (e.g. "http://localhost:52341") via window.__backendUrl__. Build the full
// API base from that. Falls back to "/api/v1" in web mode where Vite proxies
// /api → localhost:8000.

function getBaseUrl(): string {
  if (typeof window !== 'undefined' && window.__backendUrl__) {
    console.log(`[api] Using Electron backend URL: ${window.__backendUrl__}`)
    return `${window.__backendUrl__}/api/v1`
  }
  // Running in a normal browser: Vite dev server proxies /api to localhost:8000.
  console.log('[api] Using browser fallback base URL: /api/v1')
  return '/api/v1'
}

const api = axios.create({
  baseURL: getBaseUrl(),
  timeout: 30000,
  paramsSerializer: {
    indexes: null,
  },
})

// Sanity check: in Electron production mode we must have a backend URL.
// 例外是首次运行的连接页（#/connect）：此刻用户还没选完「连哪个后端」，主进程刻意
// 不 spawn 本机后端，所以 __backendUrl__ 为空是**预期状态**，不是故障。
// 因此降级为 warn 并写明这一点 —— 否则日志里一条 error 会把「首启还没选」误诊成「API 全挂」。
if (typeof window !== 'undefined' && window.electronAPI && !window.__backendUrl__) {
  console.warn(
    '[api] Electron 内尚未拿到后端地址。若正停留在 #/connect（首次运行的选择页），' +
      '这是预期状态；选择并重启后即恢复。其它情况下 API 请求会失败。'
  )
}

/**
 * Dynamically change the Axios base URL at runtime.
 *
 * Called by the Electron preload bridge when the backend restarts on a
 * different port (e.g. after the user manually kills the python process and
 * the main process auto-restarts it).
 */
export function setApiBaseURL(backendUrl: string): void {
  api.defaults.baseURL = `${backendUrl}/api/v1`
}

// Listen for dynamic backend URL changes from the Electron main process.
// When the backend restarts on a different port the main process notifies
// the renderer so Axios stays pointed at the correct address.
if (typeof window !== 'undefined' && window.electronAPI?.onBackendUrlChange) {
  window.electronAPI.onBackendUrlChange((url: string) => {
    setApiBaseURL(url)
  })
}

api.interceptors.request.use((config) => {
  const token = safeGetItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (config.url) {
    console.log(`[api] Request: ${config.method?.toUpperCase() ?? 'GET'} ${config.url}`)
  }
  return config
})

// ---------------------------------------------------------------------------
// 401 -> refresh -> retry pipeline
// ---------------------------------------------------------------------------
// `refreshPromise` is the single in-flight call to /auth/refresh/ for the
// current burst of 401s. Every concurrent 401 awaits the same promise,
// gets the new access token, and retries. Without this, three parallel
// 401s would fire three refreshes and burn through the rotated refresh
// tokens (ROTATE_REFRESH_TOKENS=True blacklists the previous one).
let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise

  const refresh = safeGetItem('refresh_token')
  if (!refresh) return null

  refreshPromise = (async () => {
    try {
      const resp = await authApi.refresh(refresh)
      const data = resp.data
      if (!data?.access) return null
      const newRefresh = data.refresh ?? refresh
      // Keep Pinia store in sync (interceptor may run before any store
      // action is dispatched, so touching refs here is the only way).
      const auth = useAuthStore()
      auth.setTokens(data.access, newRefresh)
      return data.access
    } catch {
      return null
    } finally {
      // Always release the slot so the next 401 burst (after the next
      // 30-min expiry) can refresh again.
      refreshPromise = null
    }
  })()
  return refreshPromise
}

/** 401 时**不做刷新重试、直接 forceLogout** 的端点（仅限登录/注销/刷新本身）：
 *  login 的 401 是凭据错误（页面内联处理）；logout/refresh 的 401 意味着
 * 会话已死。注意：/auth/profile/ 等受保护端点必须走刷新管线——否则过期后
 * 整页刷新时 Topbar 的 profile 401 会先于任何业务请求到达而强制登出，
 * 刷新续签功能形同虚设（2026-08-29 e2e 复现修正）。 */
const NON_RETRY_AUTH_ENDPOINTS = ['/auth/login/', '/auth/logout/', '/auth/refresh/']

// 这几个端点的错误由页面/管线自行处理，拦截器不弹全局 toast：
// 登录页有内联错误 UI，refresh 在 401 刷新管线中静默处理。
const NO_TOAST_ENDPOINTS = ['/auth/login/', '/auth/refresh/', '/auth/logout/']

function shouldToastError(url: string): boolean {
  return !NO_TOAST_ENDPOINTS.some((endpoint) => url.includes(endpoint))
}

function forceLogout() {
  // The store's logout() posts /auth/logout/, which would itself be
  // intercepted and (because we have no valid refresh token) bounce
  // through this same path. Drop tokens directly (memory + localStorage)
  // instead — 必须清 Pinia store，否则 isLoggedIn 仍为 true，路由守卫
  // 会把 /login 弹回 dashboard 造成无限跳转循环。
  useAuthStore().clearSession()
  // In Electron the router uses hash history (#/login) because file://
  // protocol does not support pushState.  In a browser, we use the
  // standard path-based redirect.
  const isElectron = typeof window !== 'undefined' && !!window.electronAPI
  if (isElectron) {
    if (!window.location.hash.startsWith('#/login')) {
      window.location.hash = '#/login'
    }
  } else {
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
  }
}

api.interceptors.response.use(
  (response) => {
    console.log(`[api] Response: ${response.status} ${response.config.url ?? ''}`)
    return response
  },
  async (error: AxiosError) => {
    const status = error.response?.status
    const originalRequest = error.config as
      | (AxiosRequestConfig & { _retry?: boolean })
      | undefined

    // 自己中止的请求**不是错误**：既不提示，也不写 console.error。
    // 少了这一早退，「连切测试项把上一个在途请求 abort 掉」这个正常动作会被
    // formatError 映射成「无法连接服务器，请检查网络」（utils/error.ts:72 那条，
    // 被 test/unit/error.spec.ts:30-31 钉着）——而无 console.error 是 P0 冒烟
    // 「/analysis 无控制台错误」判据的前提（见 frontend/e2e/README.md 已知问题#3 同族）。
    if (axios.isCancel(error)) return Promise.reject(error)

    console.error(
      `[api] Request failed: ${error.config?.method?.toUpperCase() ?? 'GET'} ` +
        `${error.config?.url ?? '(unknown url)'} - ` +
        `status=${status ?? 'no response'}, code=${error.code ?? 'none'}, message=${error.message}`
    )

    if (status !== 401) {
      // 统一错误提示：未标记 silent 的请求直接弹全局 toast。
      // login/refresh/logout 由页面内联 UI / 401 管线自行处理，不在此提示。
      if (shouldToastError(error.config?.url ?? '') && !error.config?.silent) {
        toastError(formatError(error))
      }
      return Promise.reject(error)
    }

    // The refresh endpoint is the *only* request that is allowed to
    // bubble a 401 out without retrying — otherwise we'd recurse
    // forever. Also bail if the original request was already retried
    // (avoid infinite loops on a permanently bad access token) or
    // there's no refresh token to begin with.
    if (
      !originalRequest
      || originalRequest._retry
      || NON_RETRY_AUTH_ENDPOINTS.some((endpoint) => (originalRequest.url ?? '').includes(endpoint))
      || !safeGetItem('refresh_token')
    ) {
      forceLogout()
      return Promise.reject(error)
    }

    const newAccess = await refreshAccessToken()
    if (!newAccess) {
      forceLogout()
      return Promise.reject(error)
    }

    // Stamp the retry flag and replay the request with the fresh token.
    originalRequest._retry = true
    originalRequest.headers = {
      ...(originalRequest.headers ?? {}),
      Authorization: `Bearer ${newAccess}`,
    }
    return api(originalRequest)
  }
)

export default api

import axios, { AxiosError, isAxiosError } from 'axios'
import api from './index'

/**
 * Refresh tokens are NOT routed through the shared `api` instance.
 *
 * The shared instance's response interceptor catches 401s and triggers a
 * refresh — if we went through it for the refresh call itself, a failed
 * refresh would recurse and never return. Using a bare axios.post with
 * the same baseURL keeps the refresh endpoint on the standard URL but
 * out of the interceptor's reach.
 *
 * The baseURL is read lazily (function, not top-level const) to avoid a
 * circular-import trap: `api/defaults` is populated by the body of
 * `api/index.ts`, which itself imports from this file.
 */
const getBaseURL = (): string => (api.defaults.baseURL ?? '/api/v1').replace(/\/$/, '')

export interface RefreshResponse {
  access: string
  /** Only present when SIMPLE_JWT.ROTATE_REFRESH_TOKENS=True. */
  refresh?: string
}

/** Stable error codes the LoginView returns. Keep in sync with
 * ``LOGIN_ERROR_CODES`` in ``apps/accounts/views.py``. */
export type LoginErrorCode =
  | 'missing_credentials'
  | 'user_not_found'
  | 'invalid_credentials'
  | 'account_disabled'
  | 'account_locked'

/** Error payload shape for the LoginView. */
export interface LoginErrorPayload {
  code: LoginErrorCode
  detail: string
  /** Wrong-password path: how many more attempts before lockout. */
  remaining_attempts?: number
  /** Locked path: minutes until the user can try again. */
  retry_after_minutes?: number
  /** Locked path: ISO 8601 timestamp. */
  locked_until?: string
  /** Missing-credentials path: which fields were absent. */
  missing_fields?: string[]
}

/** Categories that the LoginPage maps to distinct Chinese messages.
 * These are frontend-side only — they are NOT returned by the API. */
export type LoginFailureCategory =
  | LoginErrorCode
  | 'network_error'
  | 'timeout'
  | 'server_error'
  | 'unknown'

/** Parsed error info, ready for the LoginPage to display. */
export interface LoginErrorInfo {
  category: LoginFailureCategory
  /** User-facing message (already translated to Chinese). */
  message: string
  /** The raw API code, if any. */
  code?: LoginErrorCode
  /** Optional structured fields. */
  remaining_attempts?: number
  retry_after_minutes?: number
}

/** Pull a structured error description out of an arbitrary thrown value.
 * Used by the LoginPage to render a meaningful Chinese message even
 * when the server is down or the network times out. */
export function parseLoginError(err: unknown): LoginErrorInfo {
  if (isAxiosError(err)) {
    const ax = err as AxiosError<LoginErrorPayload>
    // No response = the request never reached the server, or never
    // got back. Distinguish "no response at all" (network down) from
    // "response took longer than the timeout".
    if (!ax.response) {
      if (ax.code === 'ECONNABORTED') {
        return {
          category: 'timeout',
          message: '服务器响应超时，请检查网络后重试',
        }
      }
      return {
        category: 'network_error',
        message: '无法连接服务器，请确认网络正常',
      }
    }
    const payload = ax.response.data
    if (payload && typeof payload === 'object' && 'code' in payload) {
      // Server returned a structured login error. Map to Chinese
      // user-facing message; fall back to server-supplied detail.
      const code = payload.code as LoginErrorCode
      return {
        category: code,
        code,
        message: translateLoginCode(code, payload.detail),
        remaining_attempts: payload.remaining_attempts,
        retry_after_minutes: payload.retry_after_minutes,
      }
    }
    // Response came back but isn't a structured login error — likely
    // a 5xx or proxy/CDN page.
    const status = ax.response.status
    if (status >= 500) {
      return {
        category: 'server_error',
        message: '服务器异常，请稍后重试',
      }
    }
    return {
      category: 'unknown',
      message: ax.message || '登录失败，请检查用户名和密码',
    }
  }
  return {
    category: 'unknown',
    message: '登录失败，请稍后重试',
  }
}

function translateLoginCode(code: LoginErrorCode, fallback: string): string {
  switch (code) {
    case 'missing_credentials':
      return fallback || '请填写用户名和密码'
    case 'user_not_found':
      return fallback || '用户名不存在，请确认后重试'
    case 'invalid_credentials':
      return fallback || '密码错误，请重试'
    case 'account_disabled':
      return fallback || '账号已被禁用，请联系管理员'
    case 'account_locked':
      return fallback || '登录失败次数过多，账号已被锁定'
  }
}

export const authApi = {
  login(username: string, password: string) {
    return api.post('/auth/login/', { username, password })
  },
  logout(refresh: string) {
    return api.post('/auth/logout/', { refresh })
  },
  /**
   * Exchange a refresh token for a new access token.
   * With ROTATE_REFRESH_TOKENS=True the response also contains a new
   * refresh token; the old one is blacklisted by the server.
   */
  refresh(refresh: string) {
    return axios.post<RefreshResponse>(
      `${getBaseURL()}/auth/refresh/`,
      { refresh },
      { headers: { 'Content-Type': 'application/json' } }
    )
  },
  getProfile() {
    return api.get('/auth/profile/')
  },
  updateProfile(data: Record<string, unknown>) {
    return api.put('/auth/profile/', data)
  },
  getSettings() {
    return api.get('/auth/settings/')
  },
  updateSettings(data: Record<string, unknown>) {
    return api.put('/auth/settings/', data)
  },
}

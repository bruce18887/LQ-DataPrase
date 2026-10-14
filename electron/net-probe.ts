/**
 * 后端可达性探测（只用 node 内置 http/https，**不 import electron**）。
 *
 * 为什么不放在 `backend.ts` 里：那个模块 import 了 `electron` 的 `app`，一旦被前端的
 * 测试/类型项目引用，就会把 electron 的类型声明拖进前端 tsconfig 的编译范围并报
 * `Cannot find module 'electron'`（2026-10-14 实测：加了探针用例后 `vue-tsc -b` 当场红）。
 * 探测本身与 Electron 无关，所以单独成模块，两侧都干净。
 */
import * as http from 'http'
import * as https from 'https'

/**
 * 探测一个后端地址是否活着。任意 HTTP 响应都算活着 —— 未认证时后端回 401，
 * 那恰好证明服务在跑（与 `backend.ts` 里 waitForBackend 的判据一致）。
 *
 * 返回值决定首启之后的兜底方向：判成可达会把窗口丢给其实连不上的服务器；
 * 判成不可达会把用户留在连接页。两种误判都比崩溃难查，所以有特征化用例
 * （`frontend/test/unit/backendProbe.spec.ts`）。
 */
export function probeBackendUrl(baseUrl: string, timeoutMs = 5000): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (ok: boolean): void => {
      if (settled) return
      settled = true
      resolve(ok)
    }

    let target: URL
    try {
      target = new URL(`${baseUrl.replace(/\/+$/, '')}/api/v1/`)
    } catch {
      finish(false)
      return
    }

    const lib = target.protocol === 'https:' ? https : http
    const req = lib.get(target, (res) => {
      res.resume()
      finish(true)
    })
    req.on('error', () => finish(false))
    req.setTimeout(timeoutMs, () => {
      req.destroy()
      finish(false)
    })
  })
}

/**
 * 退出路径：别让托管后端活过主进程。
 *
 * 两条通道各管一种死法：
 * - `stopBackendBeforeQuit`：正常退出（关窗口 / `app.quit()`）。拦住退出事件，等
 *   stopBackend 的第一级 HTTP 优雅关闭跑完 —— 那是 Windows 上唯一真能到达 Python 的一级
 *   （Node 的 `child.kill('SIGTERM')` 走 TerminateProcess，Python 侧一个 handler 都不跑），
 *   也只有它能让 SQLite 把 WAL 落盘。
 * - `killBackendOnExit`：兜住崩溃这类根本不走 before-quit 的死法；'exit' 阶段只能同步做事。
 *
 * 为什么拦住退出是必需的（而不是可选的加固）：Electron **不 await** 异步监听器。旧写法
 * `app.on('before-quit', async () => { await stopBackend(info) })` 在窗口关完那一刻就已经
 * 退出了，HTTP 请求与 5s 强杀定时器都还没落地，留下一个仍握着 db.sqlite3 的托管 python ——
 * 下次启动就是两个后端挤同一个库（本仓实测过 14 分钟双后端互挤）。
 */

import { spawnSync } from 'child_process'
import type { BackendInfo } from './backend-info'

/** 只用到 app 的两个成员：方便测试传桩，也避免本模块运行期依赖 electron。 */
export interface ShutdownApp {
  on(event: 'before-quit', listener: (event: { preventDefault(): void }) => void): void
  quit(): void
}

export interface BeforeQuitDeps {
  app: ShutdownApp
  getInfo: () => BackendInfo | null
  setInfo: (info: BackendInfo | null) => void
  stop: (info: BackendInfo) => Promise<void>
  log: (level: 'info' | 'error', message: string) => void
}

/**
 * 挂 before-quit：第一次拦住退出并停后端，停完清空引用再真正退出。
 *
 * 重复触发（就是我们自己那句 `app.quit()` 引发的第二次）直接放行 —— 此时后端已经停了，
 * 再拦一次就是把退出流程吊死。
 */
export function stopBackendBeforeQuit(deps: BeforeQuitDeps): void {
  const { app, getInfo, setInfo, stop, log } = deps
  let stopStarted = false

  app.on('before-quit', (event) => {
    const info = getInfo()
    if (!info || stopStarted) return
    event.preventDefault()
    stopStarted = true
    log('info', '[electron] before-quit, stopping backend before exit')
    stop(info)
      .catch((err: unknown) => {
        log('error', `[electron] stopBackend failed: ${err instanceof Error ? err.message : String(err)}`)
      })
      .finally(() => {
        setInfo(null)
        app.quit()
      })
  })
}

/**
 * 'exit' 兜底：还活着的托管进程按 PID 同步杀掉。
 *
 * 刻意**不**按镜像名全量杀（`taskkill /IM python.exe`）—— build.bat 的既有教训：那会误伤
 * 别人起的 python。dev 档复用外部后端时 managed=false，整段跳过。
 */
export function killBackendOnExit(
  info: BackendInfo | null,
  opts: { platform?: NodeJS.Platform; killSync?: (cmd: string, args: string[]) => void } = {}
): void {
  const platform = opts.platform ?? process.platform
  if (!info?.managed || info.pid == null) return
  if (info.process && info.process.exitCode !== null) return

  const isWin = platform === 'win32'
  const cmd = isWin ? 'taskkill' : 'kill'
  const args = isWin ? ['/F', '/PID', String(info.pid)] : [String(info.pid)]
  const killSync =
    opts.killSync ??
    ((c: string, a: string[]) => {
      try {
        spawnSync(c, a, { timeout: 3000, windowsHide: true })
      } catch {
        // 退出路径上无法处理任何失败
      }
    })
  killSync(cmd, args)
}

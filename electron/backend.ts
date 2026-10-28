/**
 * Python backend process manager for the Electron app.
 *
 * Responsibilities:
 * - Locate the PyInstaller-built exe (production) or python interpreter (dev)
 * - Spawn the Django backend as a child process with --port 0 (auto-assign)
 * - Detect backend readiness via HTTP polling after parsing stdout for the port
 * - Provide graceful shutdown: POST the backend's shutdown endpoint first, then
 *   fall back to SIGTERM → force-kill after a timeout
 */

import { spawn } from 'child_process'
import * as crypto from 'crypto'
import * as path from 'path'
import * as fs from 'fs'
import * as http from 'http'
import { app } from 'electron'
import { buildBackendEnv } from './backend-env'
import type { BackendInfo } from './backend-info'

// ---------------------------------------------------------------------------
// Logging (mirrors the logger in main.ts so backend.ts can also be tested
// independently without pulling in main.ts).
// ---------------------------------------------------------------------------
// Delay log directory initialization until the first write so that importing
// this module before Electron has finished booting does not crash the app.

let backendLogFile = ''

function formatBackendLog(level: string, args: unknown[]): string {
  const message = args
    .map((a) => {
      if (a instanceof Error) {
        return `${a.message}\n${a.stack ?? ''}`
      }
      if (typeof a === 'object' && a !== null) {
        try {
          return JSON.stringify(a)
        } catch {
          return String(a)
        }
      }
      return String(a)
    })
    .join(' ')
  return `[${new Date().toISOString()}] [${level}] ${message}\n`
}

function initBackendLog(): void {
  if (backendLogFile) return
  const dir = path.join(app.getPath('userData'), 'logs')
  fs.mkdirSync(dir, { recursive: true })
  backendLogFile = path.join(dir, 'backend.log')
}

function writeBackendLog(level: string, args: unknown[]): void {
  try {
    if (!backendLogFile) initBackendLog()
    fs.appendFileSync(backendLogFile, formatBackendLog(level, args))
  } catch {
    // Logging must never crash the app.
  }
}

/**
 * 本模块的日志出口 —— **不改全局 console**。
 *
 * 旧写法在这里把 console.log/error/warn 换成了「写 backend.log + 转原生」，而 main.ts
 * 之后又包了一层（main.ts 的 originalLog 因此捕获到的是本模块的壳）。两层的后果是
 * 主进程每打一行日志都 `appendFileSync` 两次、且 main.log 与 backend.log 互相抄全，
 * 而后端 stdout/stderr 与渲染层 console-message 都在这条热路径上（每 chunk 一次）。
 *
 * 取原生引用发生在模块求值时（main.ts:14 先 import 本模块，main.ts 的补丁在其之后），
 * 所以 native* 就是未被包装的那一份：后端生命周期的行只写 backend.log 一次 + 落终端。
 */
const nativeLog = console.log.bind(console)
const nativeError = console.error.bind(console)
const nativeWarn = console.warn.bind(console)

const blog = {
  log: (...args: unknown[]) => {
    writeBackendLog('INFO', args)
    nativeLog(...args)
  },
  error: (...args: unknown[]) => {
    writeBackendLog('ERROR', args)
    nativeError(...args)
  },
  warn: (...args: unknown[]) => {
    writeBackendLog('WARN', args)
    nativeWarn(...args)
  },
}

// ---------------------------------------------------------------------------
// Locate the backend executable / command
// ---------------------------------------------------------------------------

function getBackendPath(isDev: boolean): { exe: string; args: string[]; cwd: string } {
  if (isDev) {
    const venvDirName = process.platform === 'win32'
      ? '.venv\\Scripts\\python.exe'
      : '.venv/bin/python'

    // Walk up from __dirname (frontend/electron-dist/) to find standalone.py.
    // In a git worktree standalone.py is checked out into the worktree root —
    // that is the file we want to run.
    let searchDir = path.resolve(__dirname)
    for (let i = 0; i < 6; i++) {
      searchDir = path.dirname(searchDir)
      if (fs.existsSync(path.join(searchDir, 'standalone.py'))) break
    }
    const projectRoot = searchDir

    // The .venv directory may live in the main repository (one level above the
    // worktree root) rather than inside the worktree. Walk up independently
    // from projectRoot until we find a .venv or exhaust the search depth.
    let venvRoot = projectRoot
    let venvPython = path.join(venvRoot, venvDirName)
    for (let i = 0; i < 6; i++) {
      if (fs.existsSync(venvPython)) break
      venvRoot = path.dirname(venvRoot)
      venvPython = path.join(venvRoot, venvDirName)
    }

    if (!fs.existsSync(venvPython)) {
      throw new Error(
        `Python venv not found. Searched up to ${venvRoot}. ` +
        'Set up the virtual environment first: python -m venv .venv'
      )
    }
    return {
      exe: venvPython,
      // --host is passed explicitly (not left to standalone.py's default) so the
      // loopback-only contract is visible here: main.ts points the renderer at
      // http://localhost:<port>, and binding 0.0.0.0 would expose the API and
      // every uploaded test file to the whole subnet.
      args: [path.join(projectRoot, 'standalone.py'), '--port', '0', '--host', '127.0.0.1'],
      // Python needs the project root as cwd so that the `config` package
      // (and other project packages) are importable.
      cwd: projectRoot,
    }
  }
  // Production: the backend exe lives in extraResources (process.resourcesPath).
  const resourcesPath = process.resourcesPath
  const exePath = path.join(resourcesPath, 'LQ-DataPrase.exe')
  blog.log(`[electron] Resolved backend exe: ${exePath}`)
  blog.log(`[electron] Backend exe exists: ${fs.existsSync(exePath)}`)
  return {
    exe: exePath,
    args: ['--port', '0', '--host', '127.0.0.1'],
    cwd: resourcesPath,
  }
}

// ---------------------------------------------------------------------------
// HTTP polling – wait until the Django server responds
// ---------------------------------------------------------------------------

function waitForBackend(port: number, timeoutMs: number = 60000): Promise<void> {
  return new Promise((resolve, reject) => {
    const startTime = Date.now()
    const probeUrl = `http://127.0.0.1:${port}/api/v1/health/`
    blog.log(`[electron] Polling backend at ${probeUrl} (timeout ${timeoutMs}ms)`)

    function poll(): void {
      if (Date.now() - startTime > timeoutMs) {
        reject(new Error(`Backend did not respond on port ${port} within ${timeoutMs}ms`))
        return
      }

      const req = http.get(probeUrl, (res) => {
        res.resume()
        if (res.statusCode === 200) {
          blog.log('[electron] Backend health probe returned 200')
          resolve()
          return
        }
        // A non-200 means something is listening that is NOT our app (or our
        // app is broken). Requiring 200 rather than "any response" is the point
        // of having a dedicated probe: `/api/v1/` used to accept a 404, which
        // would also have accepted any unrelated HTTP server on that port.
        blog.log(`[electron] Backend health probe returned ${res.statusCode}, retrying`)
        setTimeout(poll, 250)
      })

      req.on('error', (err) => {
        // Exponential-ish backoff capped at 1 second.
        const elapsed = Date.now() - startTime
        const delay = Math.min(100 * Math.pow(2, Math.floor(elapsed / 1000)), 1000)
        if (elapsed % 5000 < 1000) {
          blog.log(`[electron] Backend poll error after ${elapsed}ms: ${err.message}`)
        }
        setTimeout(poll, delay)
      })

      req.setTimeout(3000, () => {
        req.destroy()
        setTimeout(poll, 500)
      })
    }

    poll()
  })
}

// ---------------------------------------------------------------------------
// Dev backend detection
// ---------------------------------------------------------------------------

// 后端口与 `frontend/vite.config.ts:50` 的 `/api` 代理目标读同一个 `E2E_PORT`，兜底 8000。
// 四家读者同源这件事由 `frontend/test/unit/portWiring.spec.ts` 钉住；不用它时行为与写死 8000 逐字一致。
const DEV_BACKEND_PORT = Number(process.env.E2E_PORT || 8000)
const DEV_BACKEND_URL = `http://127.0.0.1:${DEV_BACKEND_PORT}`

/**
 * Probe the browser development backend on the port `E2E_PORT` names (default 8000).
 *
 * In dev mode we want Electron to share the same Django process as the
 * browser so both use the same SQLite database (project root db.sqlite3).
 */
function detectDevBackend(timeoutMs: number = 3000): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`${DEV_BACKEND_URL}/api/v1/`, (res) => {
      // Any response (even 401) means the dev server is alive.
      res.resume()
      resolve(true)
    })

    req.on('error', () => resolve(false))

    req.setTimeout(timeoutMs, () => {
      req.destroy()
      resolve(false)
    })
  })
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Prepare the Python backend for Electron.
 *
 * In production this spawns the PyInstaller-built exe and waits until it is
 * ready. The backend's ``--port 0`` flag binds an OS-assigned free port; we
 * parse the startup banner to discover the port and then HTTP-poll it.
 *
 * In dev mode we do **not** spawn a backend. Instead we detect the browser
 * dev server on localhost:8000 and reuse it so Electron and the browser share
 * the same SQLite database.
 *
 * The ``LQDP_BASE_DIR`` env var is set in the child's environment so the
 * backend writes ``db.sqlite3``, ``media/``, and ``secret.key`` into the
 * Electron userData directory instead of next to the (potentially read-only)
 * installed executable.
 */
export async function spawnBackend(isDev: boolean): Promise<BackendInfo> {
  // In dev mode Electron should share the browser's Django backend so both
  // use the same SQLite database. Detect localhost:8000 instead of spawning
  // a second backend process.
  if (isDev) {
    const hasDevBackend = await detectDevBackend()
    if (hasDevBackend) {
      blog.log(`[electron] Reusing dev backend at ${DEV_BACKEND_URL}`)
    } else {
      blog.warn(
        `[electron] No dev backend found at ${DEV_BACKEND_URL}. ` +
          `Start it with: python manage.py runserver ${DEV_BACKEND_PORT}`
      )
    }
    return { port: DEV_BACKEND_PORT, pid: null, process: null, managed: false, shutdownToken: null }
  }

  return new Promise((resolve, reject) => {
    const { exe, args, cwd } = getBackendPath(isDev)
    const userDataPath = app.getPath('userData')

    blog.log(`[electron] Spawning backend: ${exe} ${args.join(' ')} (cwd: ${cwd})`)
    blog.log(`[electron] Backend userData (LQDP_BASE_DIR): ${userDataPath}`)

    // Ensure the userData directory exists before the backend tries to write into it.
    fs.mkdirSync(userDataPath, { recursive: true })

    // Set LQDP_BACKEND_CONSOLE=1 (or true) to keep the backend console window
    // visible on Windows. Useful for debugging backend startup / crashes.
    // Also supports the --backend-console command-line switch for packaged apps.
    const showBackendConsole =
      process.env.LQDP_BACKEND_CONSOLE === '1' ||
      process.env.LQDP_BACKEND_CONSOLE === 'true' ||
      app.commandLine.hasSwitch('backend-console')
    blog.log(`[electron] showBackendConsole=${showBackendConsole} (env=${process.env.LQDP_BACKEND_CONSOLE ?? 'unset'})`)

    // Per-launch shutdown token. The backend only mounts
    // POST /api/v1/system/shutdown/ when this is set, and requires the token
    // plus a loopback source. It is generated fresh every start and never
    // persisted, so it cannot be replayed across launches — the point is that
    // some *other* local process reaching the loopback API cannot kill us.
    const shutdownToken = crypto.randomBytes(32).toString('hex')

    const child = spawn(exe, args, {
      cwd,
      env: buildBackendEnv(process.env, { userDataPath, shutdownToken }),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: !showBackendConsole,
    })

    let port: number | null = null
    let startupOutput = ''

    child.stdout?.on('data', (data: Buffer) => {
      const text = data.toString()
      blog.log(`[backend-stdout] ${text}`)
      // 端口一旦解析出来，这份缓冲就没有别的用途了（两处消费都是 `slice(-1000)` 的
      // 崩溃摘要）。旧写法每来一个 chunk 都无上限 append，再对**整段历史**重跑一次
      // 正则 ⇒ 启动期 O(n²) 的主线程 CPU + 全程只增不减的字符串。
      if (port !== null) return
      // 跨 chunk 拼接只需要相邻几个包：留尾部 8KB，崩溃摘要也够诊断。
      startupOutput = (startupOutput + text).slice(-8192)

      // Parse "[server] Starting LQ-DataPrase on http://0.0.0.0:{port}"
      // from the accumulated output (not individual chunks) because Node
      // may split the startup banner line across multiple data events.
      const match = startupOutput.match(/Starting LQ-DataPrase on http:\/\/[\d.]+:(\d+)/)
      if (match) {
        port = parseInt(match[1], 10)
        blog.log(`[electron] Parsed backend port: ${port}`)

        waitForBackend(port)
          .then(() => {
            blog.log(`[electron] Backend confirmed ready on port ${port}`)
            resolve({
              port: port!,
              pid: child.pid ?? null,
              process: child,
              managed: true,
              shutdownToken,
            })
          })
          .catch((err) => {
            blog.error(`[electron] waitForBackend failed:`, err)
            child.kill()
            reject(err)
          })
      }
    })

    child.stderr?.on('data', (data: Buffer) => {
      const text = data.toString()
      blog.error(`[backend-stderr] ${text}`)
    })

    child.on('error', (err) => {
      blog.error(`[electron] Failed to spawn backend process (${exe}):`, err)
      reject(new Error(`Failed to spawn backend process (${exe}): ${err.message}`))
    })

    child.on('exit', (code, signal) => {
      if (port === null) {
        const err = new Error(
          `Backend exited before becoming ready (code=${code}, signal=${signal}). ` +
            `Last output: ${startupOutput.slice(-1000)}`
        )
        blog.error('[electron]', err)
        reject(err)
        return
      }
      // Backend crashed after successful startup. Log and let the UI
      // show connection errors. The main process does not auto-restart.
      blog.error(
        `[electron] Backend process exited unexpectedly (code=${code}, signal=${signal}). ` +
          `It was listening on port ${port}.`
      )
    })

    // Safety net – the backend should output its port within 600 seconds.
    // First-time runs need to migrate the database, which on slow disks or
    // under antivirus scanning can take several minutes. We keep the window
    // hidden during this time; the UI appears as soon as the backend responds.
    setTimeout(() => {
      if (port === null) {
        const err = new Error(
          `Backend did not output port within 600 s. ` +
            `Output so far: ${startupOutput.slice(-1000)}`
        )
        blog.error('[electron]', err)
        reject(err)
        child.kill()
      }
    }, 600000)
  })
}

/**
 * Ask the backend to shut itself down via its HTTP endpoint.
 *
 * Returns true when the backend acknowledged (HTTP 200), meaning it has already
 * scheduled its own cleanup + exit.
 */
function requestBackendShutdown(info: BackendInfo, timeoutMs = 3000): Promise<boolean> {
  return new Promise((resolve) => {
    if (!info.shutdownToken) {
      resolve(false)
      return
    }

    const payload = '{}'
    const req = http.request(
      {
        host: '127.0.0.1',
        port: info.port,
        path: '/api/v1/system/shutdown/',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
          'X-LQDP-Shutdown-Token': info.shutdownToken,
        },
        timeout: timeoutMs,
      },
      (res) => {
        res.resume()
        blog.log(`[electron] Backend shutdown endpoint returned ${res.statusCode}`)
        resolve(res.statusCode === 200)
      }
    )

    req.on('error', (err) => {
      blog.warn(`[electron] Backend shutdown request failed: ${err.message}`)
      resolve(false)
    })
    req.on('timeout', () => {
      req.destroy()
      resolve(false)
    })

    req.write(payload)
    req.end()
  })
}

/**
 * Gracefully shut down the backend child process.
 *
 * Three stages, in order:
 *
 * 1. **HTTP shutdown endpoint** — the backend runs its cleanup (close DB
 *    connections so SQLite checkpoints its WAL) and exits 0. This is the only
 *    stage that actually reaches Python on Windows: Node implements
 *    `child.kill('SIGTERM')` with `TerminateProcess`, which runs no
 *    Python-level handler at all. See apps/common/shutdown.py.
 * 2. **SIGTERM** — if the endpoint is unavailable (older build, already
 *    unresponsive, or no token). Effective on POSIX.
 * 3. **Force-kill** after 5 s (`taskkill /F` on Windows), with a 12 s absolute
 *    safety net so `app.quit()` can never hang forever.
 */
export function stopBackend(info: BackendInfo): Promise<void> {
  return new Promise((resolve) => {
    // Unmanaged backends (e.g. the dev server on localhost:8000) are owned by
    // the developer, so Electron must not kill them on quit.
    if (!info.managed || !info.process) {
      resolve()
      return
    }

    const child = info.process
    const pid = info.pid

    if (!pid || child.killed || child.exitCode !== null) {
      resolve()
      return
    }

    const forceKillTimeout = setTimeout(() => {
      if (!child.killed) {
        if (process.platform === 'win32') {
          spawn('taskkill', ['/F', '/PID', String(pid)], { windowsHide: true })
        } else {
          child.kill('SIGKILL')
        }
      }
      // 强杀已经发出就不再等 12s 保险：留着它会在几秒后对已停的后端补一条
      // 「did not stop within timeout, giving up」的假警告（且 resolve 早跑过一次）。
      clearTimeout(safetyTimeout)
    }, 5000)

    // Absolute safety net: resolve after 12 seconds even if the process
    // is somehow unkillable. Prevents app.quit() from hanging forever.
    const safetyTimeout = setTimeout(() => {
      blog.warn(`[electron] Backend process ${pid} did not stop within timeout, giving up.`)
      clearTimeout(forceKillTimeout)
      resolve()
    }, 12000)

    child.on('exit', () => {
      clearTimeout(forceKillTimeout)
      clearTimeout(safetyTimeout)
      resolve()
    })

    // Stage 1 → stage 2. The HTTP request is the only path that reaches Python
    // on Windows; SIGTERM is the POSIX fallback when it is unavailable.
    requestBackendShutdown(info).then((acknowledged) => {
      if (acknowledged) {
        // The backend has scheduled its own exit (~150 ms). Let the 5 s
        // force-kill timer stand as the backstop in case it does not.
        return
      }
      if (!child.killed && child.exitCode === null) {
        child.kill('SIGTERM')
      }
    })
  })
}

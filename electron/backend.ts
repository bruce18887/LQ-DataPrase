/**
 * Python backend process manager for the Electron app.
 *
 * Responsibilities:
 * - Locate the PyInstaller-built exe (production) or python interpreter (dev)
 * - Spawn the Django backend as a child process with --port 0 (auto-assign)
 * - Detect backend readiness via HTTP polling after parsing stdout for the port
 * - Provide graceful shutdown (SIGTERM → force-kill after timeout)
 */

import { spawn, ChildProcess } from 'child_process'
import * as path from 'path'
import * as fs from 'fs'
import * as http from 'http'
import { app } from 'electron'

export interface BackendInfo {
  port: number
  pid: number | null
  process: ChildProcess | null
  /** Whether this process was spawned by Electron and should be stopped on quit. */
  managed: boolean
}

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

const mainLog = console.log
const mainError = console.error
const mainWarn = console.warn

console.log = (...args: unknown[]) => {
  writeBackendLog('INFO', args)
  mainLog(...args)
}
console.error = (...args: unknown[]) => {
  writeBackendLog('ERROR', args)
  mainError(...args)
}
console.warn = (...args: unknown[]) => {
  writeBackendLog('WARN', args)
  mainWarn(...args)
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
      args: [path.join(projectRoot, 'standalone.py'), '--port', '0'],
      // Python needs the project root as cwd so that the `config` package
      // (and other project packages) are importable.
      cwd: projectRoot,
    }
  }
  // Production: the backend exe lives in extraResources (process.resourcesPath).
  const resourcesPath = process.resourcesPath
  const exePath = path.join(resourcesPath, 'LQ-DataPrase.exe')
  console.log(`[electron] Resolved backend exe: ${exePath}`)
  console.log(`[electron] Backend exe exists: ${fs.existsSync(exePath)}`)
  return {
    exe: exePath,
    args: ['--port', '0'],
    cwd: resourcesPath,
  }
}

// ---------------------------------------------------------------------------
// HTTP polling – wait until the Django server responds
// ---------------------------------------------------------------------------

function waitForBackend(port: number, timeoutMs: number = 60000): Promise<void> {
  return new Promise((resolve, reject) => {
    const startTime = Date.now()
    console.log(`[electron] Polling backend on http://127.0.0.1:${port}/api/v1/ (timeout ${timeoutMs}ms)`)

    function poll(): void {
      if (Date.now() - startTime > timeoutMs) {
        reject(new Error(`Backend did not respond on port ${port} within ${timeoutMs}ms`))
        return
      }

      const req = http.get(`http://127.0.0.1:${port}/api/v1/`, (res) => {
        // Any response – even a 401 from the missing JWT – proves the server
        // is up and running.
        console.log(`[electron] Backend responded with status ${res.statusCode}`)
        res.resume()
        resolve()
      })

      req.on('error', (err) => {
        // Exponential-ish backoff capped at 1 second.
        const elapsed = Date.now() - startTime
        const delay = Math.min(100 * Math.pow(2, Math.floor(elapsed / 1000)), 1000)
        if (elapsed % 5000 < 1000) {
          console.log(`[electron] Backend poll error after ${elapsed}ms: ${err.message}`)
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

const DEV_BACKEND_PORT = 8000
const DEV_BACKEND_URL = `http://127.0.0.1:${DEV_BACKEND_PORT}`

/**
 * Probe the browser development backend on localhost:8000.
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
      console.log(`[electron] Reusing dev backend at ${DEV_BACKEND_URL}`)
    } else {
      console.warn(
        `[electron] No dev backend found at ${DEV_BACKEND_URL}. ` +
          `Start it with: python manage.py runserver ${DEV_BACKEND_PORT}`
      )
    }
    return { port: DEV_BACKEND_PORT, pid: null, process: null, managed: false }
  }

  return new Promise((resolve, reject) => {
    const { exe, args, cwd } = getBackendPath(isDev)
    const userDataPath = app.getPath('userData')

    console.log(`[electron] Spawning backend: ${exe} ${args.join(' ')} (cwd: ${cwd})`)
    console.log(`[electron] Backend userData (LQDP_BASE_DIR): ${userDataPath}`)

    // Ensure the userData directory exists before the backend tries to write into it.
    fs.mkdirSync(userDataPath, { recursive: true })

    // Set LQDP_BACKEND_CONSOLE=1 (or true) to keep the backend console window
    // visible on Windows. Useful for debugging backend startup / crashes.
    // Also supports the --backend-console command-line switch for packaged apps.
    const showBackendConsole =
      process.env.LQDP_BACKEND_CONSOLE === '1' ||
      process.env.LQDP_BACKEND_CONSOLE === 'true' ||
      app.commandLine.hasSwitch('backend-console')
    console.log(`[electron] showBackendConsole=${showBackendConsole} (env=${process.env.LQDP_BACKEND_CONSOLE ?? 'unset'})`)

    const child = spawn(exe, args, {
      cwd,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',    // flush stdout line-by-line (not block-buffered)
        LQDP_BASE_DIR: userDataPath,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: !showBackendConsole,
    })

    let port: number | null = null
    let startupOutput = ''

    child.stdout?.on('data', (data: Buffer) => {
      const text = data.toString()
      startupOutput += text
      console.log(`[backend-stdout] ${text}`)

      // Parse "[server] Starting LQ-DataPrase on http://0.0.0.0:{port}"
      // from the accumulated output (not individual chunks) because Node
      // may split the startup banner line across multiple data events.
      const match = startupOutput.match(/Starting LQ-DataPrase on http:\/\/[\d.]+:(\d+)/)
      if (match && port === null) {
        port = parseInt(match[1], 10)
        console.log(`[electron] Parsed backend port: ${port}`)

        waitForBackend(port)
          .then(() => {
            console.log(`[electron] Backend confirmed ready on port ${port}`)
            resolve({ port: port!, pid: child.pid ?? null, process: child, managed: true })
          })
          .catch((err) => {
            console.error(`[electron] waitForBackend failed:`, err)
            child.kill()
            reject(err)
          })
      }
    })

    child.stderr?.on('data', (data: Buffer) => {
      const text = data.toString()
      console.error(`[backend-stderr] ${text}`)
    })

    child.on('error', (err) => {
      console.error(`[electron] Failed to spawn backend process (${exe}):`, err)
      reject(new Error(`Failed to spawn backend process (${exe}): ${err.message}`))
    })

    child.on('exit', (code, signal) => {
      if (port === null) {
        const err = new Error(
          `Backend exited before becoming ready (code=${code}, signal=${signal}). ` +
            `Last output: ${startupOutput.slice(-1000)}`
        )
        console.error('[electron]', err)
        reject(err)
        return
      }
      // Backend crashed after successful startup. Log and let the UI
      // show connection errors. The main process does not auto-restart.
      console.error(
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
        console.error('[electron]', err)
        reject(err)
        child.kill()
      }
    }, 600000)
  })
}

/**
 * Gracefully shut down the backend child process.
 *
 * Sends SIGTERM first, then force-kills after a 5-second timeout. On Windows
 * this uses `taskkill /F` because SIGTERM is not reliably delivered to
 * console-free processes.
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
    }, 5000)

    // Absolute safety net: resolve after 12 seconds even if the process
    // is somehow unkillable. Prevents app.quit() from hanging forever.
    const safetyTimeout = setTimeout(() => {
      console.warn(`[electron] Backend process ${pid} did not stop within timeout, giving up.`)
      resolve()
    }, 12000)

    child.on('exit', () => {
      clearTimeout(forceKillTimeout)
      clearTimeout(safetyTimeout)
      resolve()
    })

    child.kill('SIGTERM')
  })
}

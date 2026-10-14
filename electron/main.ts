/**
 * Electron main process entry point.
 *
 * Orchestrates the application lifecycle:
 * 1. Single-instance lock – prevents duplicate launches
 * 2. Backend lifecycle – spawns/stops the Python Django server
 * 3. Window creation – BrowserWindow with secure defaults
 * 4. Application menu – File/Edit/View/Help with IPC bridge to renderer
 */

import { app, BrowserWindow, Menu, dialog } from 'electron'
import * as path from 'path'
import * as fs from 'fs'
import { spawnBackend, stopBackend } from './backend'
import type { BackendInfo } from './backend'
import { registerIpcHandlers } from './ipc-handlers'
import { probeBackendUrl } from './backend'
import {
  DEFAULT_CLIENT_CONFIG,
  hasClientConfig,
  normalizeServerUrl,
  planStartup,
  readClientConfig,
  writeClientConfig,
} from './client-config'
import type { ClientConfig } from './client-config'

// ---------------------------------------------------------------------------
// 「连哪个后端」的运行时状态
// ---------------------------------------------------------------------------
// 判据与校验都在 client-config.ts（纯模块，有单测）；这里只负责流程分支：
//   首启（无配置文件） → 不 spawn 本机后端，窗口先进 #/connect 让用户选
//   mode=local         → 照旧 spawn 一个 127.0.0.1 后端
//   mode=remote        → 不 spawn，直接加载服务器地址（同源，Electron 只是壳）
// 远端连不上时**留在连接页**，不把窗口丢给 Chromium 的错误页 —— 用户得有机会改回本机。
let clientConfig: ClientConfig = { ...DEFAULT_CLIENT_CONFIG }
let clientConfigDir = ''
let isFirstRun = false
let remoteReachable: boolean | null = null
/** 远端模式下要加载的地址；null 表示走本机（file://）。 */
let remoteUrlToLoad: string | null = null
/** 非空时窗口先落到这个前端路由，例如 '#/connect'。 */
let startupRoute: string | null = null

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
// Production Electron apps have no visible stdout, so persist logs to the
// userData directory. This is essential for diagnosing "cannot connect to
// backend" reports from end users.
//
// We intentionally do NOT initialize the log file until app.whenReady()
// because some Electron versions crash if file I/O happens before the
// app module has finished its internal initialization.

let LOG_FILE = ''

function formatLogMessage(level: string, args: unknown[]): string {
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

function initLogger(): void {
  if (LOG_FILE) return
  const logDir = path.join(app.getPath('userData'), 'logs')
  fs.mkdirSync(logDir, { recursive: true })
  LOG_FILE = path.join(logDir, 'main.log')
}

function logToFile(level: string, args: unknown[]): void {
  try {
    if (!LOG_FILE) initLogger()
    fs.appendFileSync(LOG_FILE, formatLogMessage(level, args))
  } catch {
    // Logging must never crash the app.
  }
}

const originalLog = console.log
const originalError = console.error
const originalWarn = console.warn

console.log = (...args: unknown[]) => {
  logToFile('INFO', args)
  originalLog(...args)
}
console.error = (...args: unknown[]) => {
  logToFile('ERROR', args)
  originalError(...args)
}
console.warn = (...args: unknown[]) => {
  logToFile('WARN', args)
  originalWarn(...args)
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let mainWindow: BrowserWindow | null = null
let backendUrl = ''
let backendInfo: BackendInfo | null = null

const isDev = process.env.ELECTRON_DEV === 'true'

// ---------------------------------------------------------------------------
// Single-instance lock
// ---------------------------------------------------------------------------
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  console.warn('[electron] Another instance is already running. Quitting.')
  // 立即退出：app.quit() 是异步的，后面的模块级初始化（whenReady →
  // createWindow → spawnBackend）会继续执行，导致第二个实例再起一个
  // 后端进程并短暂弹出窗口。
  app.exit(0)
}

// ---------------------------------------------------------------------------
// Application menu
// ---------------------------------------------------------------------------
function createMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Open File...',
          accelerator: 'CmdOrCtrl+O',
          click: (): void => {
            mainWindow?.webContents.send('menu-open-file')
          },
        },
        {
          label: 'Open Directory...',
          accelerator: 'CmdOrCtrl+Shift+O',
          click: (): void => {
            mainWindow?.webContents.send('menu-open-directory')
          },
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'About LQ-DataPrase',
          click: (): void => {
            mainWindow?.webContents.send('menu-about')
          },
        },
      ],
    },
  ]

  // macOS has a standard application menu
  if (process.platform === 'darwin') {
    template.unshift({
      label: app.getName(),
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    })
  }

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------
async function createWindow(): Promise<BrowserWindow> {
  console.log('[electron] Creating BrowserWindow...')

  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    title: 'LQ-DataPrase',
    // Neutral dark background avoids a white flash before the SPA paints.
    // The SPA's theme system later sets `document.documentElement.dataset.theme`
    // to 'light' or 'night' via localStorage, overriding the visual appearance.
    backgroundColor: '#1a1a2e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // Pass the backend URL synchronously to the preload script. Setting
      // process.env at runtime in the main process is not always visible in
      // the renderer, so additionalArguments is the reliable channel.
      additionalArguments: backendUrl ? [`--backend-url=${backendUrl}`] : [],
    },
  })

  // Diagnostic lifecycle logging – helps distinguish "window never shows"
  // from "renderer crashed / page failed to load".
  win.once('ready-to-show', () => {
    console.log('[electron] Window ready-to-show, showing now')
    win.show()
  })

  win.webContents.on('did-start-loading', () => {
    console.log('[electron] Renderer did-start-loading')
  })

  win.webContents.on('did-finish-load', () => {
    console.log('[electron] Renderer did-finish-load')
    // Safety net: if ready-to-show never fires (some Electron/Vite combos),
    // still reveal the window so the user can see DevTools errors.
    if (!win.isVisible()) {
      console.log('[electron] Fallback: showing window after did-finish-load')
      win.show()
    }
  })

  win.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error(
      `[electron] Renderer did-fail-load: ${errorCode} ${errorDescription} ` +
        `(URL: ${validatedURL})`
    )
  })

  win.webContents.on('render-process-gone', (_event, details) => {
    console.error(
      `[electron] Renderer process gone: ${details.reason} (exitCode=${details.exitCode})`
    )
  })

  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    const levels = ['debug', 'log', 'warn', 'error']
    console.log(`[renderer:${levels[level] ?? level}] ${message} (${sourceId}:${line})`)
  })

  win.on('closed', () => {
    console.log('[electron] Window closed')
    mainWindow = null
  })

  if (isDev) {
    // In dev the Vite server is running on :3000
    const devUrl = 'http://localhost:3000' + (startupRoute ?? '')
    console.log(`[electron] Loading dev URL ${devUrl}`)
    await win.loadURL(devUrl)
    // Only open DevTools on demand. Auto-opening it floods the terminal with
    // benign Chromium-internal noise (Unknown VE context: language-mismatch,
    // Autofill.enable / Autofill.setAddresses not found, etc.).
    if (process.env.ELECTRON_OPEN_DEVTOOLS === 'true') {
      win.webContents.openDevTools()
    }
  } else if (remoteUrlToLoad) {
    // 远端模式：页面由服务器自己发（同源），Electron 退化成壳。
    // SPA 是按 `base: './'` 构建的相对路径产物，所以 file:// 与 http:// 两种加载方式都成立。
    const url = remoteUrlToLoad + (startupRoute ?? '')
    console.log(`[electron] Loading remote URL ${url}`)
    try {
      await win.loadURL(url)
    } catch (err) {
      console.error(`[electron] Failed to load remote URL ${url}:`, err)
      startupRoute = '#/connect'
      remoteUrlToLoad = null
      await win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), { hash: '/connect' })
    }
  } else {
    // In production the frontend/dist/ directory sits in the ASAR next to
    // electron-dist/. Using a relative path + file:// protocol means we must
    // have built the SPA with `base: './'` so asset references are relative.
    const indexPath = path.join(__dirname, '..', 'dist', 'index.html')
    console.log(`[electron] Loading production file: ${indexPath} route=${startupRoute ?? '-'}`)
    console.log(`[electron] __dirname: ${__dirname}`)
    try {
      if (startupRoute) {
        await win.loadFile(indexPath, { hash: startupRoute.replace(/^#/, '') })
      } else {
        await win.loadFile(indexPath)
      }
    } catch (err) {
      console.error('[electron] Failed to load production index.html:', err)
      throw err
    }
  }

  return win
}

// ---------------------------------------------------------------------------
// Backend startup failure UI
// ---------------------------------------------------------------------------
function showBackendErrorDialog(err: unknown): void {
  const detail = err instanceof Error ? err.message : String(err)
  dialog.showErrorBox(
    'LQ-DataPrase 启动失败',
    `无法启动本地服务进程，请查看日志文件排查问题。\n\n日志路径：${LOG_FILE}\n\n错误详情：${detail}`
  )
}

// ---------------------------------------------------------------------------
// 连接方式的选择（本机 / 远端服务器）
// ---------------------------------------------------------------------------
/**
 * 校验并落盘用户的选择。**不自动重启**：本机↔远端切换要换的是整个后端进程，
 * 热切换做不到；界面保存后引导用户重启（复用现成的 restart-app 通道）。
 *
 * 落盘失败（磁盘满、目录不可写）不能抛出去 —— 那会在主进程里变成一次无声崩溃。
 */
function saveClientConfigChoice(input: {
  mode: 'local' | 'remote'
  serverUrl: string
}): { ok: boolean; error?: string } {
  let next: ClientConfig
  if (input.mode === 'local') {
    next = { mode: 'local', serverUrl: '' }
  } else {
    const checked = normalizeServerUrl(input.serverUrl)
    if (!checked.ok) {
      return { ok: false, error: checked.error }
    }
    next = { mode: 'remote', serverUrl: checked.url }
  }

  try {
    writeClientConfig(clientConfigDir, next)
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    console.error('[electron] Failed to persist client config:', err)
    return { ok: false, error: `配置写入失败（${clientConfigDir}）：${detail}` }
  }

  clientConfig = next
  isFirstRun = false
  console.log(`[electron] Client config saved: mode=${next.mode} url=${next.serverUrl || '-'}`)
  return { ok: true }
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  console.log('[electron] App ready')
  createMenu()

  clientConfigDir = app.getPath('userData')
  isFirstRun = !hasClientConfig(clientConfigDir)
  clientConfig = readClientConfig(clientConfigDir)
  console.log(`[electron] Backend target: mode=${clientConfig.mode} firstRun=${isFirstRun}`)

  // 可达性只在「已经选了远端」时才需要探一次；首启不探（还没有地址可探）。
  if (!isFirstRun && clientConfig.mode === 'remote') {
    remoteReachable = await probeBackendUrl(clientConfig.serverUrl)
    console.log(`[electron] Remote probe ${clientConfig.serverUrl} → ${remoteReachable}`)
  }

  // 四条分支的判据在 client-config.ts 的 planStartup（有 T2 单测）；这里只执行计划。
  const plan = planStartup(clientConfig, {
    firstRun: isFirstRun,
    remoteReachable: remoteReachable === true,
  })
  startupRoute = plan.route
  if (plan.loadUrl) {
    backendUrl = plan.loadUrl
    remoteUrlToLoad = plan.loadUrl
  }
  console.log(
    `[electron] Startup plan: spawn=${plan.spawnLocalBackend} load=${plan.loadUrl ?? '-'}` +
      ` route=${plan.route ?? '-'} remoteReachable=${remoteReachable}`,
  )

  if (plan.spawnLocalBackend) {
    // Start the Python backend
    try {
      console.log('[electron] Starting backend...')
      backendInfo = await spawnBackend(isDev)
      backendUrl = `http://localhost:${backendInfo.port}`
      const managedLabel = backendInfo.managed ? '(managed)' : '(external)'
      console.log(`[electron] Backend ready on ${backendUrl} ${managedLabel}`)
    } catch (err) {
      console.error('[electron] Failed to start backend:', err)
      showBackendErrorDialog(err)
      // Continue without backend – the UI will show connection errors.
    }
  }

  // Register IPC handlers (pass a getter so they always return the current URL)
  registerIpcHandlers(() => backendUrl, {
    read: () => ({
      mode: clientConfig.mode,
      serverUrl: clientConfig.serverUrl,
      reachable: remoteReachable,
      firstRun: isFirstRun,
    }),
    save: (input) => saveClientConfigChoice(input),
  })

  // Pass the backend URL to the preload script via an env var so it can
  // synchronously expose window.__backendUrl__ before the SPA's module-init
  // code runs. IPC events arrive too late — the Axios instance is created at
  // module level and checks __backendUrl__ immediately.
  if (backendUrl) {
    process.env.ELECTRON_BACKEND_URL = backendUrl
  }

  mainWindow = await createWindow()

  // Also send via IPC for dynamic port changes (e.g. backend restart).
  if (mainWindow && backendUrl) {
    console.log('[electron] Sending backend-url-change to renderer:', backendUrl)
    mainWindow.webContents.send('backend-url-change', backendUrl)
  }

  // macOS: re-create window when dock icon is clicked
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow().then((w) => {
        mainWindow = w
        if (backendUrl) {
          w.webContents.send('backend-url-change', backendUrl)
        }
      })
    }
  })
})

// On a second launch attempt, focus the existing window instead of starting
// a second instance.
app.on('second-instance', () => {
  console.log('[electron] Second instance detected, focusing existing window')
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
})

app.on('window-all-closed', () => {
  console.log('[electron] All windows closed')
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async () => {
  console.log('[electron] before-quit, stopping backend')
  if (backendInfo) {
    await stopBackend(backendInfo)
  }
})

/**
 * Electron main process entry point.
 *
 * Orchestrates the application lifecycle:
 * 1. Single-instance lock – prevents duplicate launches
 * 2. Backend lifecycle – spawns/stops the Python Django server
 * 3. Window creation – BrowserWindow with secure defaults
 * 4. Application menu – File/Edit/View/Help with IPC bridge to renderer
 */

import { app, BrowserWindow, Menu } from 'electron'
import * as path from 'path'
import { spawnBackend, stopBackend } from './backend'
import type { BackendInfo } from './backend'
import { registerIpcHandlers } from './ipc-handlers'

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
  app.quit()
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

  win.on('closed', () => {
    console.log('[electron] Window closed')
    mainWindow = null
  })

  if (isDev) {
    // In dev the Vite server is running on :3000
    console.log('[electron] Loading dev URL http://localhost:3000')
    await win.loadURL('http://localhost:3000')
    win.webContents.openDevTools()
  } else {
    // In production the frontend/dist/ directory sits in the ASAR next to
    // electron-dist/. Using a relative path + file:// protocol means we must
    // have built the SPA with `base: './'` so asset references are relative.
    await win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  return win
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  createMenu()

  // Start the Python backend
  try {
    backendInfo = await spawnBackend(isDev)
    backendUrl = `http://localhost:${backendInfo.port}`
    console.log(`[electron] Backend ready on ${backendUrl}`)
  } catch (err) {
    console.error('[electron] Failed to start backend:', err)
    // Continue without backend – the UI will show connection errors.
  }

  // Register IPC handlers (pass a getter so they always return the current URL)
  registerIpcHandlers(() => backendUrl)

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
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async () => {
  if (backendInfo) {
    await stopBackend(backendInfo)
  }
})

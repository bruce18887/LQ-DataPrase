/**
 * IPC handler registration for the Electron main process.
 *
 * Each handler bridges a preload `ipcRenderer.invoke(...)` call to the
 * corresponding Electron main-process API (dialog, app, etc.).
 */

import { ipcMain, dialog, app, BrowserWindow } from 'electron'

/** 主进程注入的「连哪个后端」桥：读当前状态 / 保存新选择。 */
export interface ClientConfigBridge {
  read(): { mode: 'local' | 'remote'; serverUrl: string; reachable: boolean | null; firstRun: boolean }
  save(input: { mode: 'local' | 'remote'; serverUrl: string }): { ok: boolean; error?: string }
}

export function registerIpcHandlers(
  getBackendUrl: () => string,
  clientConfig: ClientConfigBridge
): void {
  // ---- Backend URL ---------------------------------------------------------
  ipcMain.handle('get-backend-url', () => {
    return getBackendUrl()
  })

  // ---- 连哪个后端 ----------------------------------------------------------
  ipcMain.handle('get-client-config', () => clientConfig.read())

  ipcMain.handle('set-client-config', (_event, input) => clientConfig.save(input))

  // ---- Zoom ----------------------------------------------------------------
  ipcMain.handle('get-zoom-factor', () => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    return win?.webContents.getZoomFactor() ?? 1
  })

  ipcMain.handle('set-zoom-factor', (_event, factor: number) => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    if (!win) return
    const clamped = Math.min(Math.max(factor, 0.5), 2)
    win.webContents.setZoomFactor(clamped)
  })

  // ---- App metadata --------------------------------------------------------
  ipcMain.handle('get-app-version', () => {
    return app.getVersion()
  })

  // ---- App restart ----------------------------------------------------------
  // Used by the settings page to apply storage-path changes. app.quit() (NOT
  // app.exit(0)) fires main.ts's before-quit handler, which gracefully stops
  // the Django child before the process relaunches.
  ipcMain.handle('restart-app', () => {
    app.relaunch()
    app.quit()
    return true
  })

  // ---- File open dialog ----------------------------------------------------
  ipcMain.handle(
    'open-file-dialog',
    async (_event, filters?: Electron.FileFilter[]) => {
      const win = BrowserWindow.getFocusedWindow()
      if (!win) return null

      const result = await dialog.showOpenDialog(win, {
        properties: ['openFile', 'multiSelections'],
        filters: filters ?? [
          { name: 'Data Files', extensions: ['csv', 'txt', 'std', 'std.gz', 'xlsx', 'xls', '7z', 'rar'] },
          { name: 'All Files', extensions: ['*'] },
        ],
      })

      return result.canceled ? null : result.filePaths
    }
  )

  // ---- Directory open dialog -----------------------------------------------
  ipcMain.handle('open-directory-dialog', async () => {
    const win = BrowserWindow.getFocusedWindow()
    if (!win) return null

    const result = await dialog.showOpenDialog(win, {
      properties: ['openDirectory'],
    })

    return result.canceled ? null : (result.filePaths[0] ?? null)
  })

  // ---- File save dialog ----------------------------------------------------
  ipcMain.handle('save-file-dialog', async (_event, defaultName?: string) => {
    const win = BrowserWindow.getFocusedWindow()
    if (!win) return null

    const result = await dialog.showSaveDialog(win, {
      defaultPath: defaultName,
      filters: [
        { name: 'CSV Files', extensions: ['csv'] },
        { name: 'Excel Files', extensions: ['xlsx'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    })

    return result.canceled ? null : (result.filePath ?? null)
  })
}

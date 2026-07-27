/**
 * IPC handler registration for the Electron main process.
 *
 * Each handler bridges a preload `ipcRenderer.invoke(...)` call to the
 * corresponding Electron main-process API (dialog, app, etc.).
 */

import { ipcMain, dialog, app, BrowserWindow } from 'electron'

export function registerIpcHandlers(getBackendUrl: () => string): void {
  // ---- Backend URL ---------------------------------------------------------
  ipcMain.handle('get-backend-url', () => {
    return getBackendUrl()
  })

  // ---- App metadata --------------------------------------------------------
  ipcMain.handle('get-app-version', () => {
    return app.getVersion()
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

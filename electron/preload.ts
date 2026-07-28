/**
 * Electron preload script.
 *
 * Exposes the ElectronAPI contract (defined in `frontend/src/electron.d.ts`)
 * to the renderer process via `contextBridge.exposeInMainWorld`. Every method
 * in the interface has a corresponding implementation here.
 */

import { contextBridge, ipcRenderer } from 'electron'

// Expose the initial backend URL synchronously so the SPA's axios instance
// (created at module-init time) sees the correct base URL immediately.
// The main process passes the URL via webPreferences.additionalArguments
// because process.env set at runtime is not reliably inherited by the
// renderer process.
function getBackendUrlFromArgs(): string {
  const prefix = '--backend-url='
  const arg = process.argv.find((a) => a.startsWith(prefix))
  return arg ? arg.slice(prefix.length) : ''
}

const initialBackendUrl = getBackendUrlFromArgs() || process.env.ELECTRON_BACKEND_URL || ''

// Always expose __backendUrl__ so the renderer can distinguish "running in
// Electron without a backend" from "running in a normal browser". An empty
// string is a valid value; the renderer uses `window.electronAPI` to detect
// Electron mode.
contextBridge.exposeInMainWorld('__backendUrl__', initialBackendUrl)

contextBridge.exposeInMainWorld('electronAPI', {
  // ---- Backend URL ---------------------------------------------------------
  getBackendUrl: (): Promise<string> => ipcRenderer.invoke('get-backend-url'),

  onBackendUrlChange: (callback: (url: string) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, url: string): void => {
      callback(url)
    }
    ipcRenderer.on('backend-url-change', handler)
    return () => {
      ipcRenderer.removeListener('backend-url-change', handler)
    }
  },

  // ---- File dialogs --------------------------------------------------------
  openFileDialog: (filters?: Electron.FileFilter[]): Promise<string[] | null> =>
    ipcRenderer.invoke('open-file-dialog', filters),

  openDirectoryDialog: (): Promise<string | null> =>
    ipcRenderer.invoke('open-directory-dialog'),

  saveFileDialog: (defaultName?: string): Promise<string | null> =>
    ipcRenderer.invoke('save-file-dialog', defaultName),

  // ---- App metadata --------------------------------------------------------
  getAppVersion: (): Promise<string> => ipcRenderer.invoke('get-app-version'),

  getPlatform: (): string => process.platform,

  // ---- Menu callbacks ------------------------------------------------------
  onMenuOpenFile: (callback: () => void): (() => void) => {
    const handler = (): void => callback()
    ipcRenderer.on('menu-open-file', handler)
    return () => {
      ipcRenderer.removeListener('menu-open-file', handler)
    }
  },

  onMenuOpenDirectory: (callback: () => void): (() => void) => {
    const handler = (): void => callback()
    ipcRenderer.on('menu-open-directory', handler)
    return () => {
      ipcRenderer.removeListener('menu-open-directory', handler)
    }
  },

  onMenuAbout: (callback: () => void): (() => void) => {
    const handler = (): void => callback()
    ipcRenderer.on('menu-about', handler)
    return () => {
      ipcRenderer.removeListener('menu-about', handler)
    }
  },
})

/**
 * TypeScript declarations for the Electron preload bridge.
 *
 * The Electron main process exposes these APIs to the renderer process via
 * `contextBridge.exposeInMainWorld('electronAPI', ...)` in the preload script.
 * When running in a browser (non-Electron), `window.electronAPI` is undefined.
 */

export interface FileFilter {
  name: string
  extensions: string[]
}

export interface ElectronAPI {
  /** Returns the current backend URL (e.g. "http://localhost:8000"). */
  getBackendUrl(): Promise<string>

  /**
   * Register a callback that fires when the backend URL changes (e.g. the
   * Python process was restarted on a different port). Returns a cleanup
   * function that removes the listener.
   */
  onBackendUrlChange(callback: (url: string) => void): () => void

  /** Open a native file selection dialog. Returns selected file paths or null. */
  openFileDialog(filters?: FileFilter[]): Promise<string[] | null>

  /** Open a native directory selection dialog. Returns the path or null. */
  openDirectoryDialog(): Promise<string | null>

  /** Open a native save-file dialog. Returns the chosen path or null. */
  saveFileDialog(defaultName?: string): Promise<string | null>

  /** Returns the Electron app version from package.json. */
  getAppVersion(): Promise<string>

  /** Returns the current OS platform ('win32', 'darwin', 'linux', etc.). */
  getPlatform(): string

  /** Register a callback for the File > Open File menu item. */
  onMenuOpenFile(callback: () => void): () => void

  /** Register a callback for the File > Open Directory menu item. */
  onMenuOpenDirectory(callback: () => void): () => void

  /** Register a callback for the Help > About menu item. */
  onMenuAbout(callback: () => void): () => void
}

declare global {
  interface Window {
    /** Preload bridge – only defined when running inside Electron. */
    electronAPI?: ElectronAPI
    /**
     * Set by the Electron main process before loading the page. Contains the
     * backend base URL (e.g. "http://localhost:8000") so the Axios instance can
     * target the correct port without hardcoding.
     */
    __backendUrl__?: string
  }
}

export {}

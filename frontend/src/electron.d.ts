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

/** 「连哪个后端」的当前状态（判据与校验都在 Electron 侧，见 electron/client-config.ts）。 */
export interface ClientConfigView {
  mode: 'local' | 'remote'
  serverUrl: string
  /** 远端模式本次启动能否连通；本机/首启为 null（不适用）。 */
  reachable: boolean | null
  /** true = 还没有配置文件，界面应把连接页当作首启入口。 */
  firstRun: boolean
}

export interface ClientConfigResult {
  ok: boolean
  error?: string
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

  /** Relaunches the app (gracefully stops the backend child first). */
  restartApp(): Promise<boolean>

  /** 当前「连哪个后端」的配置。只在 Electron 内可用（浏览器形态下本界面不需要它）。 */
  getClientConfig(): Promise<ClientConfigView>

  /**
   * 保存连接方式。Electron 侧校验后落盘；**不会自动重启**，由界面提示用户重启生效
   * （本机↔远端切换要换的是整个后端进程，热切换做不到）。
   */
  setClientConfig(input: { mode: 'local' | 'remote'; serverUrl: string }): Promise<ClientConfigResult>

  /** Returns the current web contents zoom factor (1 = 100%). */
  getZoomFactor(): Promise<number>

  /** Sets the web contents zoom factor (clamped between 0.5 and 2.0). */
  setZoomFactor(factor: number): Promise<void>

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

  // 构建时由 vite.config.ts 注入的应用元数据
  /** 应用版本（单一事实源：frontend/package.json，与 electron-builder 打包版本一致） */
  const __APP_VERSION__: string
  /** 构建时 git short-hash，排障用 */
  const __BUILD_COMMIT__: string
  /** 构建日期（YYYY-MM-DD） */
  const __BUILD_DATE__: string
}

export {}

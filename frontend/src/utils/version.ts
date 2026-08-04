/**
 * 应用版本与构建信息。
 *
 * 版本单一事实源：frontend/package.json（electron-builder 打包版本，app.getVersion()
 * 与之一致），由 vite.config.ts 在构建时注入为 __APP_VERSION__ / __BUILD_COMMIT__
 * / __BUILD_DATE__ 三个全局常量。此处为同步常量，UI 可直接使用。
 */

export const APP_VERSION: string = __APP_VERSION__
export const BUILD_COMMIT: string = __BUILD_COMMIT__
export const BUILD_DATE: string = __BUILD_DATE__

/**
 * 通过 Electron 主进程 app.getVersion() 获取版本（与注入值同源，可用于
 * 运行时校验）。浏览器环境回退到构建注入值。
 */
export async function getAppVersion(): Promise<string> {
  if (typeof window !== 'undefined' && window.electronAPI?.getAppVersion) {
    try {
      return await window.electronAPI.getAppVersion()
    } catch {
      // 主进程异常时回退注入值
    }
  }
  return APP_VERSION
}

/** 运行环境与操作系统标签（Electron 优先，浏览器按 UA 判断） */
export function getPlatformLabel(): string {
  if (typeof window !== 'undefined' && window.electronAPI) {
    const p = window.electronAPI.getPlatform()
    if (p === 'win32') return 'Windows'
    if (p === 'darwin') return 'macOS'
    if (p === 'linux') return 'Linux'
    return p
  }
  const ua = navigator.userAgent
  if (/Windows/i.test(ua)) return 'Windows'
  if (/Mac/i.test(ua)) return 'macOS'
  if (/Linux/i.test(ua)) return 'Linux'
  return '浏览器'
}

/** 运行外壳：Electron 或浏览器 */
export function isElectronEnv(): boolean {
  return typeof window !== 'undefined' && !!window.electronAPI
}

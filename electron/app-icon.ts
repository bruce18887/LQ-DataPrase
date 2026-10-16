/**
 * 图标路径推导（纯模块：只碰 path/fs，不 import electron，所以能进 T2）。
 * nativeImage 的调用留在 main.ts —— 它需要 electron 运行时。
 */
import * as fs from 'fs'
import * as path from 'path'

/** 与 electron-builder.yml 的 appId 同源；由 T2 断言钉住。 */
export const APP_ID = 'com.lq-dataprase.app'

export interface IconPathOpts {
  packaged: boolean
  resourcesPath: string
  electronDistDir: string
}

/**
 * 打包态：electron-builder 的 extraResources 把 icon.ico 落在 resources/ 下，
 * 运行时只能靠 process.resourcesPath 定位。resourcesPath 缺失时返回空串，
 * **不**从 electronDistDir 往上猜 —— 打包后 __dirname 在 app.asar 内，
 * "跳几级才出 asar"取决于打包布局（旧的两级回落其实落在 app.asar/resources/，
 * extraResources 从不写那里），猜出来的路径是 wrong-but-dead 的地雷。
 * 空串经 iconFileExists 判 false，windowIcon() 走既有的「默认图标 + 警告」降级路径。
 * 开发态：main.js 编译到 frontend/electron-dist/，仓库根是它的上两级。
 */
export function resolveIconPath(opts: IconPathOpts): string {
  if (opts.packaged) {
    if (!opts.resourcesPath) return ''
    return path.join(opts.resourcesPath, 'icon.ico')
  }
  return path.join(opts.electronDistDir, '..', '..', 'build', 'icon.ico')
}

/** 空串与不存在都回 false —— dev 首启没跑过 gen-icon 是正常态，不能抛。 */
export function iconFileExists(p: string): boolean {
  if (!p) return false
  try {
    return fs.existsSync(p) && fs.statSync(p).isFile()
  } catch {
    return false
  }
}

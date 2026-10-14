/**
 * 客户端「连哪个后端」的配置：纯逻辑部分（不 import electron / fs）。
 *
 * 之所以切成纯模块：这块判据跑在 Electron **主进程**，崩了就是启动白屏，没有任何界面
 * 能显示错误；同时它是「用户输入 → 后端地址」的唯一闸口。判据与用例见
 * `frontend/test/unit/clientConfig.spec.ts`。
 *
 * 存储位置是 Electron 的 userData（由调用方给路径），不是数据库也不是 localStorage：
 * 存库是循环依赖（连哪个后端决定用哪个库），而 localStorage 在 `file://`（本机模式）与
 * `http://`（远端模式）下是两个互相看不见的隔离空间 —— 切形态即丢，所以都不能用。
 */

import * as fs from 'fs'
import * as path from 'path'

export type ClientMode = 'local' | 'remote'

export interface ClientConfig {
  mode: ClientMode
  /** 远端模式的基地址，不含尾部斜杠；本机模式恒为空串。 */
  serverUrl: string
}

export const DEFAULT_CLIENT_CONFIG: ClientConfig = { mode: 'local', serverUrl: '' }

export type UrlCheck = { ok: true; url: string } | { ok: false; error: string }

/**
 * 校验并归一化后端地址。
 *
 * 不做的事：不替用户补协议（`localhost:8000` 会被 `URL` 解成 `protocol:'localhost:'`，
 * 补上去就等于悄悄把一个非法地址变成合法请求目标），不放开非 http(s) 协议，
 * 不接受 `user:pass@host`（那会把口令写进配置文件）。
 */
export function normalizeServerUrl(raw: unknown): UrlCheck {
  const value = typeof raw === 'string' ? raw.trim() : ''
  if (!value) {
    return { ok: false, error: '请填写服务器地址，例如 http://10.0.0.9:8000' }
  }

  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return { ok: false, error: `地址格式无法解析：${value}（需要带 http:// 或 https:// 前缀）` }
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, error: `只支持 http/https 地址，收到的是 ${parsed.protocol}` }
  }
  if (!parsed.hostname) {
    return { ok: false, error: `地址里缺少主机名：${value}` }
  }
  if (parsed.username || parsed.password) {
    return { ok: false, error: '地址中不能包含用户名或密码' }
  }

  // 尾部斜杠必须去掉：前端拼的是 `${base}/api/v1`，留着会变成 `//api/v1`。
  const path = parsed.pathname.replace(/\/+$/, '')
  const port = parsed.port ? `:${parsed.port}` : ''
  return { ok: true, url: `${parsed.protocol}//${parsed.hostname}${port}${path}` }
}

/** 解析配置文件内容：任何坏输入都回落本机模式，**绝不抛异常**。 */
export function parseClientConfig(text: string): ClientConfig {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return { ...DEFAULT_CLIENT_CONFIG }
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return { ...DEFAULT_CLIENT_CONFIG }
  }

  const record = data as Record<string, unknown>
  if (record.mode !== 'remote') {
    // 含 mode:'local' 与一切不认识的取值：本机模式是唯一安全回落。
    return { ...DEFAULT_CLIENT_CONFIG }
  }

  const checked = normalizeServerUrl(record.serverUrl)
  if (!checked.ok) {
    return { ...DEFAULT_CLIENT_CONFIG }
  }
  return { mode: 'remote', serverUrl: checked.url }
}

/** 写盘用的序列化。字段名是对外契约（文件要能被人手工排查），不要改。 */
export function serializeClientConfig(cfg: ClientConfig): string {
  return JSON.stringify({ mode: cfg.mode, serverUrl: cfg.serverUrl }, null, 2)
}

/** 启动计划：主进程拿它决定「spawn 本机 / 加载远端 / 先走连接页」。 */
export interface StartupPlan {
  spawnLocalBackend: boolean
  /** 非空表示直接加载这个地址（同源，Electron 退化成壳）。 */
  loadUrl: string | null
  /** 非空表示窗口先落到这个前端路由，例如 '#/connect'。 */
  route: string | null
}

export const CONNECT_ROUTE = '#/connect'

/**
 * 启动决策 —— 刻意从 main.ts 抽到这里，因为主进程逻辑在本仓库里没有驱动通路
 * （Playwright 跑的是浏览器 project，不驱动 Electron 壳；而单实例锁会让第二次启动
 * 直接走到 second-instance 分支去聚焦别人的窗口）。抽成纯函数才能把这四条分支钉进 T2。
 *
 * 四条分支的共同前提：**首启不 spawn 本机后端**。否则用户还没选，本机就已经建好一份库了，
 * 等于替他做了一个他没做的决定。
 */
export function planStartup(
  cfg: ClientConfig,
  opts: { firstRun: boolean; remoteReachable: boolean }
): StartupPlan {
  if (opts.firstRun) {
    return { spawnLocalBackend: false, loadUrl: null, route: CONNECT_ROUTE }
  }
  if (cfg.mode === 'remote') {
    // 连不上就留在连接页：把窗口丢给 Chromium 的「无法访问此网站」等于困死用户，
    // 他连「改回本机」的入口都见不到。
    return opts.remoteReachable
      ? { spawnLocalBackend: false, loadUrl: cfg.serverUrl, route: null }
      : { spawnLocalBackend: false, loadUrl: null, route: CONNECT_ROUTE }
  }
  return { spawnLocalBackend: true, loadUrl: null, route: null }
}

// ---------------------------------------------------------------------------
// 文件读写（只用 fs/path，仍不 import electron —— 目录由调用方传 app.getPath('userData')）
// ---------------------------------------------------------------------------

export const CONFIG_FILENAME = 'client-config.json'

export function configFilePath(dir: string): string {
  return path.join(dir, CONFIG_FILENAME)
}

/** 配置文件是否存在 —— 不存在即「首次运行」，主进程据此决定要不要走连接页。 */
export function hasClientConfig(dir: string): boolean {
  return fs.existsSync(configFilePath(dir))
}

/** 读配置：文件缺失/不可读/内容坏，一律回落本机模式，**绝不抛**。 */
export function readClientConfig(dir: string): ClientConfig {
  let text = ''
  try {
    text = fs.readFileSync(configFilePath(dir), 'utf-8')
  } catch {
    return { ...DEFAULT_CLIENT_CONFIG }
  }
  return parseClientConfig(text)
}

/**
 * 原子写：先写 `*.tmp` 再 rename。
 *
 * 配置文件决定「连不连本机后端」，一次写入中断（磁盘满、被强杀）留下的半截 JSON
 * 会让下次启动读不回任何配置；rename 在同一目录内是原子的，读者只会看到旧值或新值。
 */
export function writeClientConfig(dir: string, cfg: ClientConfig): void {
  const file = configFilePath(dir)
  const tmp = file + '.tmp'
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(tmp, serializeClientConfig(cfg), 'utf-8')
  try {
    fs.renameSync(tmp, file)
  } catch (err) {
    try {
      fs.unlinkSync(tmp)
    } catch {
      /* 临时文件清不掉也不该掩盖原始错误 */
    }
    throw err
  }
}


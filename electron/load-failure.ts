/**
 * 「页面根本没加载出来」时的判据与兜底页 —— 纯模块，**不 import electron**。
 *
 * 两个不写在 `main.ts` 里的理由：
 * 1. 主进程逻辑在本仓库没有驱动通路（同 `client-config.ts` 的取舍），而「什么时候该出兜底页」
 *    正是 2026-10-17 那次 dev 黑屏的判据本身 —— 不抽出来就只能靠手跑 Electron 观察，等于没测。
 * 2. 一旦 import `electron`，前端 tsconfig 会被拖进 electron 类型并报
 *    `Cannot find module 'electron'`（`net-probe.ts:4-7` 记过一次实测）。
 *
 * 兜底页刻意用 `data:` URL 而不是新增一个 html 资产：`electron-builder` 的文件清单不用动
 * （与批 4 选 `#/connect` 而不选 `mode-picker.html` 同一个理由）。
 */

/** Chromium `ERR_ABORTED`：正常导航与 reload 也会抛它，绝不能当失败处理。 */
export const ERR_ABORTED = -3

export interface LoadFailureProbe {
  errorCode: number
  validatedURL: string
  isMainFrame: boolean
}

/**
 * 该不该为这次失败出兜底页。三条放行各有实据，少一条就会造出新的坏行为：
 * - 非主框架：子资源失败不等于整页失败，出页面等于把还能用的界面盖掉；
 * - `ERR_ABORTED`：一次正常跳转就会命中，接住它等于每次导航都闪一张错误页；
 * - `data:`：那是自家兜底页，不拦会自我递归。
 */
export function shouldShowLoadFailure(p: LoadFailureProbe): boolean {
  if (!p.isMainFrame) return false
  if (p.errorCode === ERR_ABORTED) return false
  if (p.validatedURL.startsWith('data:')) return false
  return true
}

/**
 * 判 `index.html` 是不是「绝对 base」构建。那种产物在 `file://` 下**静默空白且零报错**
 * （lessons.md:1405-1408：chunk 请求打到了文件系统根，文档本身加载成功，所以
 * `did-fail-load` 抓不到），只能在上加载之前先看一眼。
 *
 * 故意只认 `/assets/` 这一个前缀：`/favicon.svg` 这类公开资源两种构建都可能是绝对路径，
 * 放宽到 `="/` 会把正常产物误判成坏的、直接拦停 —— 这条判据错杀的代价是应用起不来，
 * 所以宁可漏判（退回原来的黑屏）不可错杀。
 */
export function isAbsoluteBaseIndexHtml(html: string): boolean {
  return /(?:src|href)="\/assets\//.test(html)
}

/** 按当前形态给排查方向；顺序即优先级，第一条就是最可能的原因。 */
export function loadFailureHints(opts: {
  isDev: boolean
  attemptedUrl: string
}): string[] {
  const hints: string[] = []
  if (opts.isDev) {
    hints.push(
      `开发模式：前端开发服务器（Vite）在 ${opts.attemptedUrl} 上没有响应。` +
        '关掉这个窗口，重新运行 npm run electron:dev 即可恢复。',
    )
  }
  if (opts.attemptedUrl.startsWith('file:')) {
    hints.push(
      'file:// 加载：确认 frontend/dist 是用 VITE_ELECTRON=true npm run build 构建的，' +
        '绝对 base 的产物在 file:// 下会一片空白且不报任何错。',
    )
  }
  if (/^https?:\/\//i.test(opts.attemptedUrl) && !opts.isDev) {
    hints.push(
      '远端地址无响应：确认服务器进程活着、端口没被防火墙拦。' +
        '连不上时应用会留在连接页，可以改回本机模式继续工作。',
    )
  }
  hints.push('按 View → Reload 可以重试；关闭应用后重新打开总能恢复到默认形态。')
  return hints
}

/** 转义所有会改变文档结构的字符。URL 来自用户填的服务器地址，未经转义不得进 HTML。 */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export interface LoadFailureInfo {
  attemptedUrl: string
  /** 一行人话原因；失败码与描述由调用方拼进来。 */
  reason: string
  hints: string[]
  logPath: string
}

/**
 * 兜底页本体。两条硬约束：
 * - `default-src 'none'` 把脚本彻底禁掉，转义万一退化也执行不了（`style-src 'unsafe-inline'`
 *   是因为页面自带内联样式，这是这张页唯一需要的例外）；
 * - 双主题：默认深色对齐窗口底色 `#1a1a2e`（避免白闪），light 走 `prefers-color-scheme`。
 */
export function buildLoadFailurePage(info: LoadFailureInfo): string {
  const hints = info.hints
    .map((h) => `<li>${escapeHtml(h)}</li>`)
    .join('')
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>页面加载失败 - LQ-DataPrase</title>
<style>
  :root {
    --bg: #1a1a2e;
    --card: #23233c;
    --border: #353552;
    --text: #e8e8f0;
    --text-2: #a8a8bf;
    --error: #ff7a7a;
    --code: #12121f;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #fafbfc;
      --card: #ffffff;
      --border: #e2e5ea;
      --text: #1a1d23;
      --text-2: #5c6472;
      --error: #b3261e;
      --code: #f2f4f7;
    }
  }
  body {
    margin: 0;
    padding: 32px 24px;
    background: var(--bg);
    color: var(--text);
    font: 14px/1.6 "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  }
  .wrap { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--text-2); margin: 0 0 20px; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 22px;
  }
  code {
    display: block;
    background: var(--code);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 13px;
    color: var(--error);
    word-break: break-all;
    white-space: pre-wrap;
  }
  .label { color: var(--text-2); font-size: 12px; margin: 18px 0 6px; }
  ul { margin: 0; padding-left: 20px; color: var(--text-2); }
  li { margin-bottom: 8px; }
  li:first-child { color: var(--text); }
  .log { color: var(--text-2); word-break: break-all; }
</style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>页面没能加载出来</h1>
      <p class="sub">窗口是空的，不是应用崩了 —— 主进程还在，下面这次导航失败了。</p>
      <p class="label">尝试加载</p>
      <code>${escapeHtml(info.attemptedUrl)}</code>
      <p class="label">原因</p>
      <code>${escapeHtml(info.reason)}</code>
      <p class="label">怎么办</p>
      <ul>${hints}</ul>
      <p class="label">主进程日志</p>
      <p class="log">${escapeHtml(info.logPath)}</p>
    </div>
  </div>
</body>
</html>`
}

export function buildLoadFailureUrl(info: LoadFailureInfo): string {
  return `data:text/html;charset=utf-8,${encodeURIComponent(buildLoadFailurePage(info))}`
}

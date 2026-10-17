/**
 * T2：主进程「页面没加载出来」的判据与兜底页（`electron/load-failure.ts`）。
 *
 * 为什么这些判据必须在 T2 而不是靠手跑 Electron：主进程没有驱动通路（同
 * `clientConfig.spec.ts` 头部记的理由），而 2026-10-17 那次 dev 黑屏恰恰是主进程的
 * `did-fail-load` 只写日志不出页面造成的 —— 没有这层测试，改动的判据等于没人承重。
 *
 * 每条判据都带**反向对照**：只翻转一个变量就应当改变结论。少了对照组，
 * 「判据其实没生效」和「判据生效但这次用例选对了」长得一模一样。
 *
 * 跑：npm run test:unit
 */
import { describe, expect, it } from 'vitest'

import {
  buildLoadFailurePage,
  buildLoadFailureUrl,
  ERR_ABORTED,
  escapeHtml,
  isAbsoluteBaseIndexHtml,
  loadFailureHints,
  shouldShowLoadFailure,
} from '../../../electron/load-failure'

describe('shouldShowLoadFailure：三条拦截', () => {
  // 2026-10-17 事故的真实取值：dev 下 relaunch 的实例连不上已被杀掉的 vite。
  const REFUSED = { errorCode: -102, validatedURL: 'http://localhost:3000/', isMainFrame: true }

  it('子框架失败不出页面（否则会把还能用的界面盖掉）', () => {
    expect(shouldShowLoadFailure({ ...REFUSED, isMainFrame: false })).toBe(false)
  })

  it('同一条错误码只翻转 isMainFrame 就改变结论 —— 判据确实承重', () => {
    const asFrame = shouldShowLoadFailure({ ...REFUSED, isMainFrame: false })
    const asMain = shouldShowLoadFailure(REFUSED)
    expect(asFrame).not.toBe(asMain)
    expect(asMain).toBe(true)
  })

  it('ERR_ABORTED 一律放过：正常导航与被后续 loadFile 打断都会抛它', () => {
    expect(shouldShowLoadFailure({ ...REFUSED, errorCode: ERR_ABORTED })).toBe(false)
    // 远端兜底会紧接着 loadFile，此时自家 data: 页被打断报的就是 -3。
    expect(shouldShowLoadFailure({ errorCode: ERR_ABORTED, validatedURL: 'http://10.0.0.9:8000/', isMainFrame: true })).toBe(false)
  })

  it('兜底页自己（data:）不再触发，避免自我递归', () => {
    expect(
      shouldShowLoadFailure({
        errorCode: -102,
        validatedURL: 'data:text/html;charset=utf-8,%3Chtml%3E',
        isMainFrame: true,
      }),
    ).toBe(false)
  })
})

describe('shouldShowLoadFailure：三种真实失败形态都要接住', () => {
  const cases = [
    { name: 'dev 下 vite 被杀', errorCode: -102, validatedURL: 'http://localhost:3000/' },
    { name: '打包产物缺 index.html', errorCode: -6, validatedURL: 'file:///app/dist/index.html' },
    { name: '远端主机名解析不了', errorCode: -105, validatedURL: 'http://gone.invalid:8000/' },
  ]
  for (const c of cases) {
    it(c.name, () => {
      expect(shouldShowLoadFailure({ ...c, isMainFrame: true })).toBe(true)
    })
  }
})

describe('isAbsoluteBaseIndexHtml：只认 /assets/，宁可漏判不可错杀', () => {
  // 两份 fixture 逐字取自本机真实产物的形状（dist/ 是构建产物、CI 检出里没有，故不读盘）。
  const ABSOLUTE_BASE = `<!doctype html><html><head>
<link rel="icon" href="/favicon.svg" />
<script type="module" crossorigin src="/assets/index-DK53bRFI.js"></script>
<link rel="stylesheet" crossorigin href="/assets/index-CTke68KK.css">
</head><body><div id="app"></div></body></html>`

  const RELATIVE_BASE = ABSOLUTE_BASE.split('="/assets/').join('="./assets/')

  it('绝对 base（file:// 下会静默空白零报错）判成坏构建', () => {
    expect(isAbsoluteBaseIndexHtml(ABSOLUTE_BASE)).toBe(true)
  })

  it('相对 base 是 Electron 正常产物，绝不能拦停', () => {
    expect(isAbsoluteBaseIndexHtml(RELATIVE_BASE)).toBe(false)
  })

  it('只有绝对 /favicon.svg 不算坏构建 —— 判据没放宽到任何="/"', () => {
    expect(
      isAbsoluteBaseIndexHtml('<link rel="icon" href="/favicon.svg"><script src="./assets/a.js"></script>'),
    ).toBe(false)
  })

  it('空串与无资源引用的壳都不判坏（读不到文件时不该拦在原路径上）', () => {
    expect(isAbsoluteBaseIndexHtml('')).toBe(false)
    expect(isAbsoluteBaseIndexHtml('<div id="app"></div>')).toBe(false)
  })
})

describe('loadFailureHints：按形态给第一条处置', () => {
  it('dev + :3000 被拒 → 第一条就让人重跑 electron:dev', () => {
    const hints = loadFailureHints({ isDev: true, attemptedUrl: 'http://localhost:3000/' })
    expect(hints[0]).toContain('npm run electron:dev')
    // 判别式：dev 形态下不该同时给出「服务器进程活着」那条远端处置。
    expect(hints.join('')).not.toContain('防火墙')
  })

  it('打包 file:// → 指向 VITE_ELECTRON 构建', () => {
    const hints = loadFailureHints({ isDev: false, attemptedUrl: 'file:///app/dist/index.html' })
    expect(hints.join('')).toContain('VITE_ELECTRON=true')
  })

  it('远端 http → 给服务器与回本机模式的处置', () => {
    const hints = loadFailureHints({ isDev: false, attemptedUrl: 'http://10.0.0.9:8000/' })
    expect(hints.join('')).toContain('防火墙')
    expect(hints.join('')).toContain('本机模式')
  })

  it('任何形态最后一条都是重试/重启的出口', () => {
    for (const opts of [
      { isDev: true, attemptedUrl: 'http://localhost:3000/' },
      { isDev: false, attemptedUrl: 'file:///x' },
      { isDev: false, attemptedUrl: 'http://h:1/' },
    ]) {
      expect(loadFailureHints(opts).at(-1)).toContain('Reload')
    }
  })
})

describe('兜底页：转义与 CSP 承重', () => {
  // 最坏输入：serverUrl 是用户在连接页里手打的，必须当成攻击面。
  const EVIL = 'http://x/"><script>alert(1)</script>&\'<img src=x onerror=boom>'
  const page = buildLoadFailurePage({
    attemptedUrl: EVIL,
    reason: '-102 ERR_CONNECTION_REFUSED',
    hints: ['<b>hint</b>'],
    logPath: 'C:\\Users\\me\\AppData\\Roaming\\lq-dataprase\\logs\\main.log',
  })

  it('URL 里的脚本标签被转义，原文一个字都不剩', () => {
    expect(page).not.toContain('<script>')
    expect(page).toContain('&lt;script&gt;')
    expect(page).toContain('&quot;')
    // 属性注入也只能沦为可见文本：标签尖括号已经不成形，所以 onerror 不再挂任何事件。
    expect(page).toContain('&lt;img src=x onerror=boom&gt;')
  })

  it('判别式：escapeHtml 确实是唯一防线，去掉它同一条输入就会漏', () => {
    expect(escapeHtml(EVIL)).not.toContain('<')
    expect(EVIL).toContain('<')
  })

  it('提示与日志路径同样转义，日志里的反斜杠原样保留', () => {
    expect(page).not.toContain('<b>hint</b>')
    expect(page).toContain('&lt;b&gt;hint&lt;/b&gt;')
    expect(page).toContain('lq-dataprase')
  })

  it('CSP 彻底禁脚本（转义万一退化也执行不了）', () => {
    expect(page).toContain("default-src 'none'")
    expect(page).not.toContain('unsafe-eval')
    expect(page).toContain("style-src 'unsafe-inline'")
  })

  it('双主题：默认深色对齐窗口底色，light 走 prefers-color-scheme', () => {
    expect(page).toContain('#1a1a2e')
    expect(page).toContain('prefers-color-scheme: light')
  })
})

describe('buildLoadFailureUrl：data: URL 必须能真的导航', () => {
  const url = buildLoadFailureUrl({
    attemptedUrl: 'http://localhost:3000/#/connect?a=1',
    reason: '-102 ERR_CONNECTION_REFUSED',
    hints: ['重跑 npm run electron:dev'],
    logPath: 'C:\\logs\\main.log',
  })

  it('带 charset，否则中文提示会变乱码', () => {
    expect(url.startsWith('data:text/html;charset=utf-8,')).toBe(true)
  })

  it('裸 # 与换行都会被截断 data: URL，必须全部编码掉', () => {
    const body = url.slice('data:text/html;charset=utf-8,'.length)
    expect(body).not.toContain('#')
    expect(body).not.toContain('\n')
    expect(body).not.toContain(' ')
  })

  it('解码回来仍是原页面内容（编码没有丢信息）', () => {
    const decoded = decodeURIComponent(url.slice('data:text/html;charset=utf-8,'.length))
    expect(decoded).toContain('页面没能加载出来')
    expect(decoded).toContain('npm run electron:dev')
  })
})

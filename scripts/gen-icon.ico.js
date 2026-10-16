#!/usr/bin/env node
/**
 * Generate build/icon.ico (+ build/icon.png) from frontend/public/favicon.svg.
 *
 * Background: build/ is gitignored (resource binaries don't travel in git),
 * so the Electron/NSIS icon must be reproducible. The app's own brand mark is
 * frontend/public/favicon.svg (single-path bolt, light #2563eb / night #f9a825);
 * this script rasterizes the D4 **plate form factor** — full-bleed rounded
 * gradient plate + white symbol, gradient stops parsed from
 * frontend/src/styles/design-tokens.css (single source, no hardcoded brand
 * hex) — with the project's installed Playwright Chromium at the sizes an
 * .ico needs (256/128/64/48/32/16, PNG-compressed entries) and writes
 * build/icon.ico + a reference build/icon.png.
 *
 * 判据、阈值出处与内缩档位都在 scripts/icon-lib.cjs / icon-metrics.cjs /
 * icon-audit.cjs（纯函数，由 frontend/test/unit/iconLib.spec.ts 守着，
 * 不必起浏览器就能回归）。
 *
 * Wired into package.json dist:win / dist:win:dir (before electron-builder).
 * 每次都真重生成，**没有幂等短路**（Task 11 删掉了旧的 mtime `isUpToDate()`，闭 I3）：按 mtime
 * 判断让本文件头里那句「手工重跑」在 mtime 未变时是空操作，而 `cp -p` 还原 mtime 可以让一个
 * 陈旧图标**永久不被审计**——本分支自己就用过两次 `cp -p`，这不是假想敌。实测整条重生成
 * **0.67–0.76 秒**（整窗口径：task-11 用 `date +%s%N` 包 `node scripts/gen-icon.ico.js` 进程起至
 * 退出，3 次 0.701/0.736/0.763；task-13 在产出逐字节相同 .ico 的 scratch 树上 11 次 0.674–0.753。
 * 更早的实现者自测 0.62–0.64 **未记录量法**，不用作下界。分段参考：`main()`→写盘（含 Chromium
 * 启动）0.52–0.55 秒、六帧渲染 + 逐帧自检 + 写盘 0.29–0.31 秒；原始数字见 task-13 报告），
 * 而 dist:win 本身是分钟级的 PyInstaller + electron-builder：这里省下的不是几秒，是
 * 「陈旧产物静默进分发包」那一整个故障类，代价 <1 秒。不加哈希 sidecar、不加 `--force`——那是同一个洞换个形状。
 *
 * 三种失败的区别是刻意的：
 * - 自检未过（G1 符号糊边 / G2 端点缺席 / G3 底板几何 / G4 16px 可辨性，见 icon-audit.cjs）
 *   或品牌色解析失败 → 打印问题、process.exit(1)，且在写盘之前——坏图标一旦进分发包就
 *   再也摘不下来，宁可不出。
 * - playwright/Chromium 加载不到，**但既有 build/icon.ico 在** → warn 并退出 0（降级放行，
 *   spec §3.1 明文要的行为）：打包永远不该被图标挡住，留下的还是上一份 .ico，日志点名它可能已陈旧。
 * - playwright/Chromium 加载不到，**且没有 build/icon.ico** → 非零退出（I2）：降级的前提是
 *   「有东西可降」，没有产物时退出 0 只是把爆炸推到更远的地方——electron-builder.yml 的
 *   `win.icon` / `extraResources` / `nsis.installerIcon` / `nsis.uninstallerIcon` 与
 *   lq_dataprase.spec 的 `icon='build/icon.ico'` 全都会硬失败，且报错点比这里难读得多。
 *
 * 手工重跑：node scripts/gen-icon.ico.js（现在每次都真重生成，这句不再是空操作）
 */
const fs = require('fs')
const path = require('path')
const {
  SIZES,
  parseBrandGradient,
  frameHtml,
  frameStats,
  auditVerdict,
  assembleIco,
} = require('./icon-lib.cjs')

const ROOT = path.join(__dirname, '..')
const SVG = path.join(ROOT, 'frontend', 'public', 'favicon.svg')
const TOKENS = path.join(ROOT, 'frontend', 'src', 'styles', 'design-tokens.css')
const OUT_ICO = path.join(ROOT, 'build', 'icon.ico')
const OUT_PNG = path.join(ROOT, 'build', 'icon.png')

async function main() {
  // 品牌色单源化（I4）：底板渐变与审计端点判据吃同一份解析结果。解析失败在这里抛，
  // main().catch 非零退出——**不许**静默回落到硬编常量（图腾判据的起点）。
  const brand = parseBrandGradient(fs.readFileSync(TOKENS, 'utf8'))
  console.log(
    `[gen-icon] brand plate gradient from design-tokens: ${brand.stops.map((s) => `#${s.hex}@${s.pct}%`).join(' ')}`,
  )

  let chromium
  try {
    ;({ chromium } = require(path.join(ROOT, 'frontend', 'node_modules', 'playwright')))
  } catch {
    // 降级放行成立的**前提**是有东西可降（I2 裁定，spec §3.1 同批更正）：
    // build/icon.ico 已在盘上 → 保持退出 0，打包继续用上一份产物，日志里看得见原因与陈旧风险；
    // 不在盘上 → 必须非零退出。此时退出 0 只是把爆炸推到更远的地方——electron-builder.yml 的
    // win.icon(:59) / extraResources(:51-52) / nsis.installerIcon 与 uninstallerIcon(:75-76)，
    // 外加 lq_dataprase.spec 的 icon='build/icon.ico'（PyInstaller FileNotFoundError），
    // 五个下游消费者全都硬失败，而且报错点比这里难读得多。
    const next = 'node scripts/gen-icon.ico.js（在装有 frontend/node_modules 的机器上）'
    if (fs.existsSync(OUT_ICO)) {
      console.warn(
        `[gen-icon] 载入不到 frontend/node_modules/playwright；build/icon.ico 已存在 → 降级放行，` +
          `打包用的还是盘上那份（若 favicon.svg/design-tokens.css 已改动，它就是陈旧的）。重生成：${next}`,
      )
      return
    }
    console.error(
      `[gen-icon] 载入不到 frontend/node_modules/playwright，且没有可降级的既有产物 ${path.relative(ROOT, OUT_ICO).replace(/\\/g, '/')}` +
        ` —— 非零退出：缺这份产物时 win.icon / extraResources / nsis.installerIcon|uninstallerIcon / ` +
        `lq_dataprase.spec 的 icon= 都会硬失败，与其在那边撞墙不如在这里就把话说清。下一步：${next}`,
    )
    process.exit(1)
  }

  const svg = fs.readFileSync(SVG, 'utf8')
  const browser = await chromium.launch()
  try {
    const rendered = []
    const problems = []
    const page = await browser.newPage()
    // 母版带 @media (prefers-color-scheme: dark) 分支，只服务浏览器标签。
    // Task 9 起底板配色由 parseBrandGradient 从 light :root 块取、符号被 !important 钉死
    // 反白，这行 emulateMedia 不再是金色进 .ico 的唯一闸门；但它仍决定母版**未被覆盖**的
    // 绘制属性（stroke/opacity 类），保留为纵深防御。金色底板帧会被 icon-audit.cjs 的
    // G2 端点门判红（frontend/test/unit/iconLib.spec.ts 用合成 #c17900→#ffd54f 帧守着）。
    await page.emulateMedia({ colorScheme: 'light' })
    for (const size of SIZES) {
      await page.setViewportSize({ width: size, height: size })
      await page.setContent(frameHtml(svg, size, brand), { waitUntil: 'load' })
      const png = await page.screenshot({ omitBackground: true })
      const stats = frameStats(png, brand)
      problems.push(...auditVerdict(stats, brand))
      console.log(
        `[gen-icon] ${size}px: 底板 ${(stats.plateRatio * 100).toFixed(1)}% / 端点 ${stats.startPixels}+${stats.endPixels} px / ` +
          `符号 ink ${stats.inkCount} px(${stats.inkTones} 色阶) / 剪影 ${stats.bboxW}×${stats.bboxH} / ` +
          `角透明 ${(stats.cornerTransp * 100).toFixed(0)}% / 尾行 ${stats.tailRowW} px`,
      )
      rendered.push({ size, png })
    }
    if (problems.length) {
      console.error('[gen-icon] 自检未通过，未写盘：\n  ' + problems.join('\n  '))
      process.exit(1)
    }
    fs.mkdirSync(path.dirname(OUT_ICO), { recursive: true })
    fs.writeFileSync(OUT_PNG, rendered.find((r) => r.size === 256).png)
    fs.writeFileSync(OUT_ICO, assembleIco(rendered))
    console.log(`[gen-icon] wrote build/icon.ico (${SIZES.join('/')}) + build/icon.png`)
  } finally {
    await browser.close()
  }
}

main().catch((err) => {
  console.error('[gen-icon] failed:', err.message)
  process.exit(1)
})

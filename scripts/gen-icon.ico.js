#!/usr/bin/env node
/**
 * Generate build/icon.ico (+ build/icon.png) from frontend/public/favicon.svg.
 *
 * Background: build/ is gitignored (resource binaries don't travel in git),
 * so the Electron/NSIS icon must be reproducible. The app's own brand mark is
 * frontend/public/favicon.svg (purple #863bff bolt, inlined SVG); this script
 * rasterizes it with the project's installed Playwright Chromium at the sizes
 * an .ico needs (256/128/64/48/32/16, PNG-compressed entries) and writes
 * build/icon.ico + a reference build/icon.png.
 *
 * Wired into package.json dist:win / dist:win:dir (before electron-builder).
 * Idempotent: regenerates only when favicon.svg is newer than build/icon.ico;
 * if Playwright/Chromium is unavailable and the icon is missing or stale it
 * warns and exits 0 so packaging is never blocked by an icon (a stale icon
 * is still better than none, and the failure mode is visible in the log).
 *
 * Re-run manually: node scripts/gen-icon.ico.js
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const SVG = path.join(ROOT, 'frontend', 'public', 'favicon.svg')
const OUT_ICO = path.join(ROOT, 'build', 'icon.ico')
const OUT_PNG = path.join(ROOT, 'build', 'icon.png')
const SIZES = [256, 128, 64, 48, 32, 16]

function isUpToDate() {
  if (!fs.existsSync(OUT_ICO) || !fs.existsSync(SVG)) {
    return false
  }
  return fs.statSync(OUT_ICO).mtimeMs >= fs.statSync(SVG).mtimeMs
}

/** Assemble a multi-size ICO container (Vista+ PNG-compressed entries). */
function assembleIco(rendered) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: icon
  header.writeUInt16LE(rendered.length, 4)

  const entries = []
  const blobs = []
  let offset = 6 + 16 * rendered.length
  for (const { size, png } of rendered) {
    const entry = Buffer.alloc(16)
    entry[0] = size >= 256 ? 0 : size // 0 means 256
    entry[1] = entry[0]
    entry[2] = 0 // color count
    entry[3] = 0 // reserved
    entry.writeUInt16LE(1, 4) // planes
    entry.writeUInt16LE(32, 6) // bits per pixel
    entry.writeUInt32LE(png.length, 8)
    entry.writeUInt32LE(offset, 12)
    entries.push(entry)
    blobs.push(png)
    offset += png.length
  }
  return Buffer.concat([header, ...entries, ...blobs])
}

async function main() {
  if (isUpToDate()) {
    console.log('[gen-icon] build/icon.ico is up to date, skipping')
    return
  }

  let chromium
  try {
    ;({ chromium } = require(path.join(ROOT, 'frontend', 'node_modules', 'playwright')))
  } catch {
    const reason = fs.existsSync(OUT_ICO)
      ? 'stale (favicon.svg changed) but build/icon.ico exists'
      : 'build/icon.ico is missing'
    console.warn(
      `[gen-icon] cannot load playwright from frontend/node_modules; ${reason}. ` +
        'Run the generator on a machine with frontend deps installed.'
    )
    return
  }

  const svg = fs.readFileSync(SVG, 'utf8')
  const html = (size) =>
    `<!doctype html><html><head><style>` +
    `html,body{margin:0;padding:0;background:transparent}` +
    `svg{width:100%;height:100%;display:block}` +
    `</style></head><body>${svg}</body></html>`

  const browser = await chromium.launch()
  try {
    const rendered = []
    const page = await browser.newPage()
    for (const size of SIZES) {
      await page.setViewportSize({ width: size, height: size })
      await page.setContent(html(size), { waitUntil: 'load' })
      await page.waitForTimeout(150) // let SVG blur filters rasterize
      rendered.push({ size, png: await page.screenshot({ omitBackground: true }) })
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

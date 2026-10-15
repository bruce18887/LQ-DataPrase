# 图标家族与运行时接入 实施计划（计划 1 / 共 2 份）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把品牌母标志从"16 层高斯模糊合成件"改成单色硬边母版，派生出 `.ico`/`png`/文档站图标，并补上 Electron / PyInstaller / NSIS 三处缺失的图标接入，最后让应用内 4 个品牌位用上同一枚形状。

**Architecture:** 单一形状事实源 = `frontend/public/favicon.svg`（母版，零留白 viewBox）。位图家族由 `scripts/gen-icon.ico.js` 按帧尺寸注入留白后栅格化，并在写盘前对**实际字节**做色阶/剪影自检；界面侧由新增的 `AppLogo.vue` 消费同一条 path，并用一条 T2 断言锁住两者不漂移。运行时接入分三处：Electron 窗口/任务栏、PyInstaller 后端 exe、NSIS 安装器。

**Tech Stack:** Vue 3.5 + Vite + Element Plus、Electron（electron-builder + rcedit via `scripts/afterPack.js`）、PyInstaller、Playwright（既是生成器也是 e2e）、vitest、Django/DRF。

**Spec:** `docs/superpowers/specs/2026-10-15-icon-system-design.md` —— 本计划只覆盖该 spec 的 **§9 批 1–3**。批 4–6（图标注册表与尺寸 token、emoji 治理、死资产清理）另出计划 2。

## Global Constraints

- 不新增任何 npm / pip 依赖（PNG 解码用 Node 内置 `zlib` 手写，见 Task 2）。
- 单个 `.vue` / `.py` 文件不超过 600 行（`.claude/CLAUDE.md`）。
- 任何界面改动必须 light 与 night 两套主题同时成立（`.claude/CLAUDE.md`）。
- 本计划**不改** `--on-brand` 的取值，只给它加文档注记（Task 8）。
- 本计划**不动** `frontend/public/icons.svg`、`scripts/generate_icon.py`、`frontend/src/constants/icons.ts`（属批 4–6）。
- 新测试按层落位：纯函数进 `frontend/test/unit/`（`npm run test:unit`）；只有"真实渲染 / 双主题计算色 / 选择器契约"进 `frontend/e2e/`，且必须带 `@p0|@p1|@p2` 标签。
- 每批 commit 前跑 `npm run test:e2e:affected`；看到 `NO AFFECTED TESTS` 视为本轮无测试承重，不许当绿灯。
- 逐文件显式 `git add`，禁止 `git add -A`；**本计划不含任何 `git push`**。
- 母版 path 的唯一改动是尾针左界 `V33.937` → `L19.4 33.937`，其余顶点/圆角/倾斜方向一字不改（spec §2.1）。
- `.ico` 帧集固定 `[256,128,64,48,32,16]`，不增不减。

---

## 文件结构

| 动作 | 路径 | 职责 |
|---|---|---|
| Modify | `frontend/public/favicon.svg` | 母版形状唯一事实源（位图家族 + 界面共用） |
| Create | `scripts/icon-lib.cjs` | 纯函数：留白档位、母版解析包装、PNG 解码与帧自检 |
| Create | `frontend/test/unit/iconLib.spec.ts` | 上述纯函数的 T2 用例 |
| Modify | `scripts/gen-icon.ico.js` | 栅格化 + 写盘前自检；消费 icon-lib |
| Create | `frontend/test/unit/brandMark.spec.ts` | 母版守门（无模糊/无 mask/尾针坐标/双主题色） |
| Create | `electron/app-icon.ts` | 纯函数：图标路径推导 + 存在性判定 |
| Create | `frontend/test/unit/appIcon.spec.ts` | 上者的 T2 用例 + `APP_ID` 与 `appId` 一致性 |
| Modify | `electron/main.ts` | `setAppUserModelId` + `BrowserWindow.icon` |
| Modify | `electron-builder.yml` | `extraResources` 带 icon.ico；NSIS installer/uninstaller 图标 |
| Modify | `lq_dataprase.spec:457` | 后端 exe 图标 |
| Create | `frontend/src/components/common/AppLogo.vue` | 界面品牌符号组件 |
| Modify | `frontend/src/components/common/index.ts` | 导出 AppLogo |
| Modify | `Sidebar.vue` / `LoginPage.vue` / `ConnectPage.vue` / `AppAboutDialog.vue` | 四处品牌位落位 |
| Create | `frontend/e2e/global/brand-mark.spec.ts` | 渲染 + 双主题计算色 + 形状不漂移的接线证明 |
| Modify | `docs/user-guide/build.js` / `docs/user-guide/template.html` | 文档站 favicon 与品牌位 |
| Modify | `docs/reference/ui-design-guide.md` | §3.3 `--on-brand` 注记 |

---

## Task 1: 母版 favicon.svg 重写 + 母版守门

**Files:**
- Modify: `frontend/public/favicon.svg`（整文件替换）
- Test: `frontend/test/unit/brandMark.spec.ts`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `frontend/public/favicon.svg` —— viewBox `0 0 48 46`、零留白、单 `<path class="b">`、内含 `<style>` 双主题分支。Task 2 的生成器与 Task 5 的 `AppLogo.vue` 都从这里取同一条 `d`。母版 path 的 `d` 属性值即 spec §2.1 那一串。

- [ ] **Step 1: 写失败的守门测试**

新建 `frontend/test/unit/brandMark.spec.ts`：

```ts
/**
 * T2：品牌母版守门（frontend/public/favicon.svg）。
 *
 * 现用母版是 16 个高斯模糊椭圆经 mask 裁进闪电轮廓的合成件，实测其 16px 帧
 * 带 100 个实心色阶（同尺寸单色版为 1 个）—— 这就是任务栏图标糊成一团的根因。
 * 本文件锁死"不得把模糊/遮罩/多色阶加回来"，以及尾针必须加宽到能站住小尺寸。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const svg = readFileSync(new URL('../../public/favicon.svg', import.meta.url), 'utf8')

describe('品牌母版 favicon.svg', () => {
  it('不含任何滤镜与遮罩（模糊是 16px 糊边的根因）', () => {
    expect(svg).not.toMatch(/<filter|feGaussianBlur|<mask|mask=/)
  })

  it('只有一条 path，且为单色 class 驱动', () => {
    expect(svg.match(/<path/g) ?? []).toHaveLength(1)
    expect(svg).toMatch(/<path\s+class="b"/)
  })

  it('viewBox 零留白：紧贴 48×46 剪影（留白由生成器按帧尺寸注入）', () => {
    expect(svg).toMatch(/viewBox="0 0 48 46"/)
  })

  it('尾针左界已加宽到 x=19.4（原 23.925 只有 4.2% 画布宽，16px 下必然化开）', () => {
    expect(svg).toContain('L19.4 33.937')
    expect(svg).not.toContain('V33.937')
  })

  it('双主题色走 token 值：light #2563eb / night #f9a825', () => {
    expect(svg).toMatch(/\.b\{fill:#2563eb\}/)
    expect(svg).toMatch(/prefers-color-scheme:\s*dark[\s\S]*?fill:#f9a825/)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:unit -- brandMark`
Expected: FAIL —— 前 4 条全红（现母版有 `<filter>`/`<mask>`、16 条 path、viewBox 是 `0 0 48 46` 但含 `V33.937`、无 `.b{fill:`）。

- [ ] **Step 3: 替换母版**

把 `frontend/public/favicon.svg` 整文件改成：

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="48" height="46" viewBox="0 0 48 46" role="img" aria-label="LQ-DataPrase">
  <style>.b{fill:#2563eb}@media (prefers-color-scheme:dark){.b{fill:#f9a825}}</style>
  <path class="b" d="M25.946 44.938c-.664.845-2.021.375-2.021-.698L19.4 33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.946 44.94z"/>
</svg>
```

相对现文件的改动只有三处：删 `<mask>`/16 组 `<g filter>`/`<defs>`、`V33.937` → `L19.4 33.937`、颜色由内联 hex 改为 `<style>` 的 `.b` 类。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test:unit -- brandMark`
Expected: PASS（5 passed）

- [ ] **Step 5: 浏览器里肉眼确认一次**

Run: `cd frontend && npx vite --port 5199`（后台），打开 `http://localhost:5199/favicon.svg`，切系统深浅各看一次。
Expected: light 下蓝色闪电、night 下金黄色闪电；**不是**带光晕的紫青渐变。看完关掉端口。

- [ ] **Step 6: 提交**

```bash
git add frontend/public/favicon.svg frontend/test/unit/brandMark.spec.ts
git commit -m "feat(brand): 母版闪电去模糊改单色，尾针加宽到 9.4% 画布宽"
```

---

## Task 2: 图标生成器改造 —— 留白注入 / 锁 light / 字节级自检

**Files:**
- Create: `scripts/icon-lib.cjs`
- Modify: `scripts/gen-icon.ico.js`
- Test: `frontend/test/unit/iconLib.spec.ts`

**Interfaces:**
- Consumes: Task 1 产出的 `frontend/public/favicon.svg`（viewBox `0 0 48 46`、单 path）
- Produces（`scripts/icon-lib.cjs`，CommonJS 导出）：
  - `padPct(size: number): number`
  - `frameHtml(svgText: string, size: number): string`
  - `decodePngRgba(buf: Buffer): { width: number; height: number; data: Buffer }`
  - `frameStats(buf: Buffer): { size: number; tones: number; bboxW: number; bboxH: number }`
  - `auditVerdict(stats: { size: number; tones: number; bboxW: number; bboxH: number }): string[]`
  - `SIZES: number[]`
  - `assembleIco(rendered: Array<{ size: number; png: Buffer }>): Buffer`

- [ ] **Step 1: 写失败的纯函数测试**

新建 `frontend/test/unit/iconLib.spec.ts`：

```ts
/**
 * T2：.ico 生成器的纯函数层。
 *
 * 为什么把这几段从 gen-icon.ico.js 里抽出来：留白档位和自检判据是"会决定
 * 最终图标长什么样"的判断，而生成器本体要起浏览器（≈秒级、依赖 Chromium）。
 * 抽成纯函数后，回归这两条判据不必打包。
 */
import { deflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'

import {
  padPct,
  frameHtml,
  decodePngRgba,
  frameStats,
  auditVerdict,
  SIZES,
} from '../../../scripts/icon-lib.cjs'

/** 造一张 8bit RGBA 非隔行 PNG，用于验证解码/统计确实读的是字节。 */
function encodePngRgba(width: number, height: number, px: (x: number, y: number) => number[]) {
  const raw = Buffer.alloc(height * (1 + width * 4))
  let p = 0
  for (let y = 0; y < height; y++) {
    raw[p++] = 0 // filter: None
    for (let x = 0; x < width; x++) {
      const [r, g, b, a] = px(x, y)
      raw[p++] = r; raw[p++] = g; raw[p++] = b; raw[p++] = a
    }
  }
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length, 0)
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body) >>> 0, 0)
    return Buffer.concat([len, body, crc])
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

let CRC_TABLE: number[] | null = null
function crc32(buf: Buffer) {
  if (!CRC_TABLE) {
    CRC_TABLE = []
    for (let n = 0; n < 256; n++) {
      let c = n
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
      CRC_TABLE[n] = c >>> 0
    }
  }
  let c = 0xffffffff
  for (const byte of buf) c = CRC_TABLE![(c ^ byte) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

describe('padPct —— 留白按帧尺寸分档（spec D7）', () => {
  it('16px 只留 2%，更大才敢留到 8%', () => {
    expect(padPct(16)).toBeCloseTo(0.02)
    expect(padPct(24)).toBeCloseTo(0.06)
    expect(padPct(32)).toBeCloseTo(0.06)
    expect(padPct(48)).toBeCloseTo(0.08)
    expect(padPct(256)).toBeCloseTo(0.08)
  })

  it('8% 留白在 16px 上是净损失，所以小帧不给', () => {
    // 实测：16px 帧加 8% 留白后剪影 16×16→14×14、总墨迹 −27%
    expect(16 - 2 * Math.round(16 * padPct(16))).toBeGreaterThanOrEqual(15)
  })
})

describe('frameHtml —— 母版按尺寸包进方框并注入留白', () => {
  const master = '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="46" viewBox="0 0 48 46">' +
    '<style>.b{fill:#2563eb}</style><path class="b" d="M0 0H48V46H0Z"/></svg>'

  it('外层是 size×size 方框，内层保留母版 viewBox', () => {
    const html = frameHtml(master, 32)
    expect(html).toMatch(/<svg width="32" height="32" viewBox="0 0 32 32"/)
    expect(html).toContain('viewBox="0 0 48 46"')
  })

  it('48×46 的非正方母版在方框里垂直居中，不拉伸', () => {
    const html = frameHtml(master, 32)
    const m = /<svg x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"/.exec(html)!
    const [, x, y, w, h] = m.map(Number)
    expect(w).toBe(32 - 2 * x)
    expect(h).toBe(Math.round(w * 46 / 48))
    expect(y).toBe(Math.round((32 - h) / 2))
  })

  it('母版缺 viewBox 时直接抛错，不静默出坏图标', () => {
    expect(() => frameHtml('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', 16))
      .toThrow(/viewBox/)
  })
})

describe('decodePngRgba + frameStats —— 审的是要写进 .ico 的字节', () => {
  it('能解自己编的 8bit RGBA 图，色阶与剪影框对得上', () => {
    // 4×4：左上 2×2 实心红、右下 2×2 实心蓝、其余全透明
    const png = encodePngRgba(4, 4, (x, y) => {
      if (x < 2 && y < 2) return [255, 0, 0, 255]
      if (x >= 2 && y >= 2) return [0, 0, 255, 255]
      return [0, 0, 0, 0]
    })
    expect(decodePngRgba(png).width).toBe(4)
    const s = frameStats(png)
    expect(s).toEqual({ size: 4, tones: 2, bboxW: 4, bboxH: 4 })
  })

  it('半透明像素不计入色阶与剪影（只算 alpha>=240 的实心）', () => {
    const png = encodePngRgba(2, 2, () => [10, 20, 30, 120])
    const s = frameStats(png)
    expect(s.tones).toBe(0)
    expect(s.bboxW).toBe(0)
  })
})

describe('auditVerdict —— 写盘前的红线', () => {
  it('单色实心大帧：无问题', () => {
    expect(auditVerdict({ size: 256, tones: 1, bboxW: 210, bboxH: 200 })).toEqual([])
  })

  it('色阶 >2 判红，并点名是模糊/渐变被加回来了', () => {
    const problems = auditVerdict({ size: 16, tones: 100, bboxW: 16, bboxH: 16 })
    expect(problems.join()).toMatch(/100 个实心色阶/)
    expect(problems.join()).toMatch(/模糊|渐变/)
  })

  it('16px 帧剪影小于 15×15 判红（留白吃掉了小尺寸面积）', () => {
    expect(auditVerdict({ size: 16, tones: 1, bboxW: 14, bboxH: 14 }).join()).toMatch(/剪影/)
    expect(auditVerdict({ size: 16, tones: 1, bboxW: 15, bboxH: 15 })).toEqual([])
  })

  it('大帧不卡剪影下限（只有 16px 帧有此约束）', () => {
    expect(auditVerdict({ size: 48, tones: 1, bboxW: 40, bboxH: 38 })).toEqual([])
  })

  it('SIZES 固定六档，不增不减', () => {
    expect(SIZES).toEqual([256, 128, 64, 48, 32, 16])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:unit -- iconLib`
Expected: FAIL —— `Failed to resolve import "../../../scripts/icon-lib.cjs"`（文件还不存在）。

- [ ] **Step 3: 写 `scripts/icon-lib.cjs`**

```js
/**
 * .ico 生成器的纯函数层（被 scripts/gen-icon.ico.js 消费，被 T2 用例守门）。
 *
 * 抽出来的理由：留白档位与自检判据会直接决定任务栏里的图标长什么样，
 * 而生成器本体要起 Chromium。判据必须能在不打包的前提下回归。
 */
const zlib = require('zlib')

const SIZES = [256, 128, 64, 48, 32, 16]

/**
 * 留白比例按帧尺寸分档（spec D7）。
 * 实测 16px 帧给 8% 留白会让剪影从 16×16 缩到 14×14、总墨迹掉 27%，
 * 所以小帧几乎不留，大帧才敢留。
 */
function padPct(size) {
  if (size <= 16) return 0.02
  if (size <= 32) return 0.06
  return 0.08
}

/** 取母版的 viewBox 与 <svg> 内部标记。 */
function parseMaster(svgText) {
  const vb = /viewBox="\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*"/.exec(svgText)
  if (!vb) throw new Error('favicon.svg 缺 viewBox，无法按帧尺寸注入留白')
  const inner = svgText.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '')
  return { vb: vb.slice(1, 5).map(Number), inner }
}

/** 把母版包进 size×size 的方框：外层方、内层保留母版坐标系与非正方比例。 */
function frameHtml(svgText, size) {
  const { vb, inner } = parseMaster(svgText)
  const pad = Math.round(size * padPct(size))
  const w = size - 2 * pad
  const h = Math.round((w * vb[3]) / vb[2])
  const y = Math.round((size - h) / 2)
  return (
    `<!doctype html><html><head><style>html,body{margin:0;padding:0;background:transparent}</style></head><body>` +
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<svg x="${pad}" y="${y}" width="${w}" height="${h}" viewBox="${vb.join(' ')}">${inner}</svg>` +
    `</svg></body></html>`
  )
}

/** 解 8bit RGBA 非隔行 PNG（Chromium 截图就是这个格式）。 */
function decodePngRgba(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error('不是 PNG 数据')
  let pos = 8
  let width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0
  const idat = []
  while (pos + 8 <= buf.length) {
    const len = buf.readUInt32BE(pos)
    const type = buf.toString('ascii', pos + 4, pos + 8)
    const data = buf.subarray(pos + 8, pos + 8 + len)
    if (type === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      bitDepth = data[8]; colorType = data[9]; interlace = data[12]
    } else if (type === 'IDAT') {
      idat.push(data)
    } else if (type === 'IEND') {
      break
    }
    pos += 12 + len
  }
  if (bitDepth !== 8 || colorType !== 6 || interlace !== 0) {
    throw new Error(`只支持 8bit RGBA 非隔行，实际 depth=${bitDepth} colorType=${colorType} interlace=${interlace}`)
  }
  const raw = zlib.inflateSync(Buffer.concat(idat))
  const stride = width * 4
  const out = Buffer.alloc(height * stride)
  let rp = 0
  for (let y = 0; y < height; y++) {
    const filter = raw[rp++]
    for (let x = 0; x < stride; x++) {
      const cur = raw[rp + x]
      const a = x >= 4 ? out[y * stride + x - 4] : 0
      const b = y > 0 ? out[(y - 1) * stride + x] : 0
      const c = x >= 4 && y > 0 ? out[(y - 1) * stride + x - 4] : 0
      let v
      if (filter === 0) v = cur
      else if (filter === 1) v = cur + a
      else if (filter === 2) v = cur + b
      else if (filter === 3) v = cur + ((a + b) >> 1)
      else if (filter === 4) {
        const p = a + b - c
        const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c)
        v = cur + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)
      } else throw new Error(`未知 PNG filter: ${filter}`)
      out[y * stride + x] = v & 0xff
    }
    rp += stride
  }
  return { width, height, data: out }
}

/** 只统计实心像素（alpha>=240）：色阶数与剪影框。 */
function frameStats(buf) {
  const { width, height, data } = decodePngRgba(buf)
  const tones = new Set()
  let minX = width, maxX = -1, minY = height, maxY = -1
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      if (data[i + 3] < 240) continue
      tones.add(`${data[i]},${data[i + 1]},${data[i + 2]}`)
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  }
  return {
    size: width,
    tones: tones.size,
    bboxW: maxX < 0 ? 0 : maxX - minX + 1,
    bboxH: maxY < 0 ? 0 : maxY - minY + 1,
  }
}

/**
 * 写盘前的红线。
 * 色阶数是唯一能区分"单色硬边"与"模糊合成"的指标 —— 实测 partial alpha 占比
 * 不区分（任何硬边图形在 16px 都约 16%，那只是抗锯齿边缘）。
 */
function auditVerdict({ size, tones, bboxW, bboxH }) {
  const problems = []
  if (tones > 2) {
    problems.push(`${size}px 帧有 ${tones} 个实心色阶（阈值 ≤2）——模糊或渐变被加回来了`)
  }
  if (size === 16 && (bboxW < 15 || bboxH < 15)) {
    problems.push(`16px 帧剪影 ${bboxW}×${bboxH}，小于 15×15——留白吃掉了小尺寸面积`)
  }
  return problems
}

/** Vista+ 多尺寸 ICO 容器（PNG 压缩条目）。 */
function assembleIco(rendered) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0)
  header.writeUInt16LE(1, 2)
  header.writeUInt16LE(rendered.length, 4)
  const entries = []
  const blobs = []
  let offset = 6 + 16 * rendered.length
  for (const { size, png } of rendered) {
    const entry = Buffer.alloc(16)
    entry[0] = size >= 256 ? 0 : size
    entry[1] = entry[0]
    entry[2] = 0
    entry[3] = 0
    entry.writeUInt16LE(1, 4)
    entry.writeUInt16LE(32, 6)
    entry.writeUInt32LE(png.length, 8)
    entry.writeUInt32LE(offset, 12)
    entries.push(entry)
    blobs.push(png)
    offset += png.length
  }
  return Buffer.concat([header, ...entries, ...blobs])
}

module.exports = { SIZES, padPct, frameHtml, decodePngRgba, frameStats, auditVerdict, assembleIco }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test:unit -- iconLib`
Expected: PASS（11 passed）。若 `frameHtml` 的非正方居中那条红了，说明 `h` 用了 `vb[2]`/`vb[3]` 反了 —— 母版是 48 宽 46 高。

- [ ] **Step 5: 改写生成器消费 icon-lib，并加锁 light + 自检**

`scripts/gen-icon.ico.js` 里**删掉**文件内的 `SIZES` 常量（`:27`）与整个 `assembleIco()`（`:36–61`），改为从 lib 引入；`isUpToDate()` 保持不动：

```js
const { SIZES, frameHtml, frameStats, auditVerdict, assembleIco } = require('./icon-lib.cjs')
```

`main()` 内的渲染循环替换为：

```js
  const svg = fs.readFileSync(SVG, 'utf8')
  const browser = await chromium.launch()
  try {
    const rendered = []
    const problems = []
    const page = await browser.newPage()
    // 母版带 @media (prefers-color-scheme: dark) 分支，只服务浏览器标签。
    // 不锁 light 的话，深色系统的构建机会截出金黄色 .ico —— 同一份源码两种图标。
    await page.emulateMedia({ colorScheme: 'light' })
    for (const size of SIZES) {
      await page.setViewportSize({ width: size, height: size })
      await page.setContent(frameHtml(svg, size), { waitUntil: 'load' })
      const png = await page.screenshot({ omitBackground: true })
      const stats = frameStats(png)
      problems.push(...auditVerdict(stats))
      console.log(`[gen-icon] ${size}px: ${stats.tones} 色阶 / 剪影 ${stats.bboxW}×${stats.bboxH}`)
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
```

同时删掉 `await page.waitForTimeout(150) // let SVG blur filters rasterize` —— 母版已无滤镜，这行是给模糊擦的。文件头注释里 `purple #863bff bolt, inlined SVG` 改成 `single-path bolt (light #2563eb / night #f9a825)`，并把"自检失败必红、但 playwright 缺失仍降级放行"这条区别写进注释（降级路径 :72–81 保持不动）。

- [ ] **Step 6: 强制重生成并核对指标**

```bash
rm -f build/icon.ico && node scripts/gen-icon.ico.js
```
Expected: 六行统计，其中 `16px: 1 色阶 / 剪影 15×15`（或 16×16），末行 `wrote build/icon.ico`，退出码 0。
若 16px 那行剪影 <15，自检会以非零退出并点名留白 —— 回去调 `padPct`，不要调低阈值。

- [ ] **Step 7: 证明自检这条线真的会拦（不动真母版）**

**不要**用"把 `frontend/public/favicon.svg` 临时改坏再跑生成器"来证明 —— 那是原地改真实资产，还原失败就留下一个坏母版，而且这类破坏性反证在本项目会被安全策略拦下。改用两条无副作用的证法：

1. Step 1 的单测已经断言 `auditVerdict({ size: 16, tones: 100, ... })` 返回问题项 —— 判据本身有测试承重。
2. 再走读确认调用点存在且非零退出：

```bash
grep -n "problems.length" -A 3 scripts/gen-icon.ico.js
grep -n "process.exit(1)" scripts/gen-icon.ico.js
```
Expected: 能看到 `if (problems.length) { ... process.exit(1) }`，且它在 `fs.writeFileSync(OUT_ICO, ...)` **之前** —— 顺序错了就等于"自检报了问题但仍然写盘"，那是本次改造的核心目的，必须看到"先 exit 后写盘"。

把这两条的输出贴进报告文件。若第 2 条显示写盘在自检之前，那是实现 bug，按原样修掉再重跑 Step 6。

- [ ] **Step 8: 提交**

```bash
git add scripts/icon-lib.cjs scripts/gen-icon.ico.js frontend/test/unit/iconLib.spec.ts
git commit -m "feat(build): 图标生成器按帧尺寸注入留白，并对 .ico 字节做色阶自检"
```

---

## Task 3: Electron 窗口图标与 AppUserModelID

**Files:**
- Create: `electron/app-icon.ts`
- Modify: `electron/main.ts`（import 段 `:12`、`APP_ID` 常量、`createWindow()` 的 `new BrowserWindow` `:223–243`）
- Modify: `electron-builder.yml:42-47`（extraResources）
- Test: `frontend/test/unit/appIcon.spec.ts`

**Interfaces:**
- Consumes: `build/icon.ico`（Task 2 产物）；`electron-builder.yml:19` 的 `appId`
- Produces（`electron/app-icon.ts`，纯模块，不 import electron）：
  - `APP_ID: string`（值 `'com.lq-dataprase.app'`）
  - `resolveIconPath(opts: { packaged: boolean; resourcesPath: string; electronDistDir: string }): string`
  - `iconFileExists(p: string): boolean`

- [ ] **Step 1: 写失败的测试**

新建 `frontend/test/unit/appIcon.spec.ts`：

```ts
/**
 * T2：图标路径推导 + AppUserModelID 一致性。
 *
 * APP_ID 与 electron-builder.yml 的 appId 是同一份信息写两处（Windows 靠它把
 * 任务栏分组与快捷方式归到同一应用）。仓库里已经因为"页面级元数据写两份"漂过
 * 一次（lessons.md:1587），所以这里用一条读文件的断言钉住，而不是再建一个共享常量
 * —— yml 不是 TS，抽公共常量要引 yaml 解析器，得不偿失。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { APP_ID, resolveIconPath, iconFileExists } from '../../../electron/app-icon'

describe('APP_ID 与 electron-builder.yml 的 appId 同源', () => {
  it('两处字面量一致', () => {
    const yml = readFileSync(new URL('../../../electron-builder.yml', import.meta.url), 'utf8')
    const m = /^appId:\s*(\S+)\s*$/m.exec(yml)
    expect(m).not.toBeNull()
    expect(APP_ID).toBe(m![1])
  })
})

describe('resolveIconPath', () => {
  const norm = (p: string) => p.replace(/\\/g, '/')

  it('打包态走 resources 下的 icon.ico（extraResources 的落点）', () => {
    expect(norm(resolveIconPath({ packaged: true, resourcesPath: 'C:/app/resources', electronDistDir: 'D:/x' })))
      .toBe('C:/app/resources/icon.ico')
  })

  it('dev 态走仓库 build/icon.ico：electron-dist 的上两级是仓库根', () => {
    expect(norm(resolveIconPath({ packaged: false, resourcesPath: '', electronDistDir: '/repo/frontend/electron-dist' })))
      .toMatch(/\/repo\/build\/icon\.ico$/)
  })

  it('resourcesPath 为空时不返回一个裸相对路径', () => {
    const p = resolveIconPath({ packaged: true, resourcesPath: '', electronDistDir: '/repo/frontend/electron-dist' })
    expect(p).not.toBe('icon.ico')
    expect(p.length).toBeGreaterThan(0)
  })
})

describe('iconFileExists', () => {
  it('空串与不存在路径一律 false，不抛', () => {
    expect(iconFileExists('')).toBe(false)
    expect(iconFileExists('/nope/definitely/not/here.ico')).toBe(false)
  })

  it('存在的文件为 true', () => {
    expect(iconFileExists(fileURLToPath(new URL('../../public/favicon.svg', import.meta.url)))).toBe(true)
  })
})
```

`import` 段需要 `import { fileURLToPath } from 'node:url'`。三条路径断言全部经 `norm()` 或正则比对 —— 本项目跑在 Windows 上，`path.join` 产出反斜杠，直接 `toBe('/a/b')` 会假红。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:unit -- appIcon`
Expected: FAIL —— `Failed to resolve import "../../../electron/app-icon"`。

- [ ] **Step 3: 写 `electron/app-icon.ts`**

```ts
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
 * 打包态：electron-builder 的 extraResources 把 icon.ico 落在 resources/ 下。
 * 开发态：main.js 编译到 frontend/electron-dist/，仓库根是它的上两级。
 */
export function resolveIconPath(opts: IconPathOpts): string {
  if (opts.packaged) {
    const base = opts.resourcesPath || path.join(opts.electronDistDir, '..', '..', 'resources')
    return path.join(base, 'icon.ico')
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test:unit -- appIcon`
Expected: PASS（5 passed）

- [ ] **Step 5: 在 main.ts 接线**

`electron/main.ts:12` 的 import 加上 `nativeImage`，并引入新模块：

```ts
import { app, BrowserWindow, Menu, dialog, nativeImage } from 'electron'
```

在 `:18` 的 `import { registerIpcHandlers } ...` 附近加：

```ts
import { APP_ID, resolveIconPath, iconFileExists } from './app-icon'
```

在 `// Window creation` 段上方（`createWindow` 之前）加：

```ts
/**
 * Windows 用 AppUserModelID 把任务栏按钮、通知与快捷方式归到同一个应用。
 * 不设它，打包版的通知与图标会挂到"electron.exe"名下。
 */
if (process.platform === 'win32') {
  app.setAppUserModelId(APP_ID)
}

/** dev 首启未跑过 gen-icon 时返回 undefined —— BrowserWindow 会回落默认图标，不抛错。 */
function windowIcon() {
  const p = resolveIconPath({
    packaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    electronDistDir: __dirname,
  })
  if (!iconFileExists(p)) {
    console.warn(`[electron] icon 不存在，窗口将显示默认图标: ${p}`)
    return undefined
  }
  const img = nativeImage.createFromPath(p)
  return img.isEmpty() ? undefined : img
}
```

`new BrowserWindow({ ... })` 的选项里，在 `title: 'LQ-DataPrase',` 之后加一行：

```ts
    icon: windowIcon(),
```

- [ ] **Step 6: 让打包态真能读到那个文件**

`electron-builder.yml:42-47` 的 `extraResources` 追加一项：

```yaml
extraResources:
  - from: "dist/LQ-DataPrase/"
    to: "."
    filter:
      - "LQ-DataPrase.exe"
      - "_internal/**"
  # 窗口/任务栏图标：BrowserWindow 的 icon 要一个运行时可读的文件路径，
  # asar 里的东西读不到，所以显式落到 resources/ 下。
  - from: "build/icon.ico"
    to: "icon.ico"
```

- [ ] **Step 7: 类型检查与 dev 冒烟**

```bash
cd frontend && npm run electron:build:ts && npm run test:unit -- appIcon
```
Expected: tsc 无错；单测 PASS。
再 `npm run electron:dev`（后台），确认日志里**没有** `icon 不存在` 警告（本机已有 `build/icon.ico`），窗口左上角与任务栏显示闪电。看完释放端口。

- [ ] **Step 8: 提交**

```bash
git add electron/app-icon.ts electron/main.ts electron-builder.yml frontend/test/unit/appIcon.spec.ts
git commit -m "feat(electron): 设 AppUserModelID 并把 icon.ico 接到窗口与任务栏"
```

---

## Task 4: PyInstaller 与 NSIS 的图标接线 + 真打包验收

**Files:**
- Modify: `lq_dataprase.spec:457`
- Modify: `electron-builder.yml:62-70`（nsis 段）

**Interfaces:**
- Consumes: `build/icon.ico`
- Produces: 无（终端消费者是 Windows 资源管理器 / 安装向导）

- [ ] **Step 1: 后端 exe 图标**

`lq_dataprase.spec:457` 把 `icon=None,` 改成：

```python
    icon='build/icon.ico',
```

理由写进上方注释块（该段现有注释在讲 UPX，另起一行）：

```python
# icon: 这个 exe 是后端进程，任务管理器与"打开文件位置"里都能看到它；
# 不设图标时它显示 PyInstaller 默认飞船。与前端 exe 同一份 build/icon.ico。
```

- [ ] **Step 2: 安装器图标**

`electron-builder.yml` 的 `nsis:` 段，在 `shortcutName: LQ-DataPrase` 之前加：

```yaml
  installerIcon: build/icon.ico
  uninstallerIcon: build/icon.ico
```

- [ ] **Step 3: 跑一次目录式打包（不出安装包，最快）**

**必须走 `dist:win:dir` 而不是裸调 electron-builder** —— 新工作树里 `frontend/dist/`（Vite 产物）与 `dist/LQ-DataPrase/`（PyInstaller 产物）都是 gitignore 的，根本不存在，裸调 electron-builder 会因缺文件失败。`dist:win:dir` 一条链把该建的都建了：

```bash
npm run dist:win:dir
```
Expected: 依次跑 `patch-nsis-template.js` → `gen-icon.ico.js` → 前端构建 → electron TS 构建 → PyInstaller → `electron-builder --win --dir`，产出 `out/win-unpacked/`，末行无 error。

耗时以分钟计，属正常。若 `afterPack.js` 打印 rcedit 重试日志（本机杀软锁 exe），等它退避完成，不要跳过、不要 `--no-verify`。

**不要用 `build.bat`** —— 它会 `taskkill` 别的会话的进程；`dist:win:dir` 这条链不经过 build.bat。

- [ ] **Step 4: 核 extraResources 真的落了文件**

```bash
ls -la out/win-unpacked/resources/icon.ico
ls -la dist/LQ-DataPrase/LQ-DataPrase.exe
```
Expected: 两个文件都在。`resources/icon.ico` 存在即证明 Task 3 的 `extraResources` 生效（打包态 `resolveIconPath` 指向的就是它）。

exe 内嵌图标**没有可靠的自动化读法**（要解 PE 的 `RT_GROUP_ICON` 资源，且 `afterPack.js` 的 rcedit 失败路径本来就只打日志不阻断），所以 Step 5 的人工目视是本任务唯一的承重验收，不许跳过。

- [ ] **Step 5: 人工目视（无自动化通路，必须做并记录）**

打开 `out/win-unpacked/`，在资源管理器里看 `LQ-DataPrase.exe` 与 `dist/LQ-DataPrase/LQ-DataPrase.exe` 的图标；双击启动 `out/win-unpacked/LQ-DataPrase.exe`，看**任务栏**与**窗口标题栏左上角**；再 `out/win-unpacked/resources/LQ-DataPrase.exe` 直接跑一次看任务栏分组名。
Expected: 三处都是闪电，不是 Electron 默认蓝灰方块。把结论（含"哪处不对"）写进 `docs/tasks/todo.md` 的本任务条目。

- [ ] **Step 6: 提交**

```bash
git add lq_dataprase.spec electron-builder.yml
git commit -m "feat(build): 后端 exe 与 NSIS 安装/卸载程序接上图标"
```

---

## Task 5: AppLogo.vue 与形状漂移守门

**Files:**
- Create: `frontend/src/components/common/AppLogo.vue`
- Modify: `frontend/src/components/common/index.ts`
- Test: `frontend/test/unit/brandMark.spec.ts`（追加一条）

**Interfaces:**
- Consumes: `frontend/public/favicon.svg` 的 path `d`
- Produces: `<AppLogo :size="number" />` —— 渲染一条 `<path>`，`fill="currentColor"`；导出名 `AppLogo`，从 `@/components/common` 可用。母版 `d` 与组件内 `d` 的一致性由 `brandMark.spec.ts` 的 `母版与 AppLogo 形状同源` 用例保证。

- [ ] **Step 1: 追加失败的守门用例**

在 `frontend/test/unit/brandMark.spec.ts` 末尾加：

```ts
describe('AppLogo 与母版同源', () => {
  it('组件里的 path d 与 favicon.svg 完全一致（防两处形状各改一半）', () => {
    const masterD = /<path[^>]*\sd="([^"]+)"/.exec(svg)![1]
    const comp = readFileSync(new URL('../../src/components/common/AppLogo.vue', import.meta.url), 'utf8')
    // 组件模板里是 :d="d"（变量），字面量在 <script setup> 的 const d = '…'
    const compD = /const d = '([^']+)'/.exec(comp)![1]
    expect(compD).toBe(masterD)
  })
})
```

同时在该文件顶部 `import` 段确认已有 `readFileSync`（Task 1 已引入）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:unit -- brandMark`
Expected: FAIL —— 读不到 `AppLogo.vue`（ENOENT）。

- [ ] **Step 3: 写组件**

新建 `frontend/src/components/common/AppLogo.vue`：

```vue
<script setup lang="ts">
/**
 * 品牌符号。形状的唯一界面出口 —— 位图家族用 frontend/public/favicon.svg，
 * 两者的 d 必须一致，由 test/unit/brandMark.spec.ts 钉住。
 *
 * 刻意不做描边版：这枚标志的识别度全在实心剪影（spec §2.2）。
 */
const props = withDefaults(defineProps<{ size?: number }>(), { size: 28 })

// 48×46 非正方：按宽定高，避免被拉扁
const height = Math.round((props.size * 46) / 48)

const d = 'M25.946 44.938c-.664.845-2.021.375-2.021-.698L19.4 33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.946 44.94z'
</script>

<template>
  <svg
    class="app-logo"
    :width="size"
    :height="height"
    viewBox="0 0 48 46"
    aria-hidden="true"
    focusable="false"
  >
    <path class="app-logo__mark" :d="d" />
  </svg>
</template>

<style scoped>
.app-logo {
  display: block;
  flex: 0 0 auto;
}

.app-logo__mark {
  fill: currentColor;
}
</style>
```

注意：装饰性图形统一挂 `aria-hidden="true"`，与 `Sidebar.vue:6`、`Empty.vue:3` 的既有约定一致。

- [ ] **Step 4: 导出**

`frontend/src/components/common/index.ts` 的 import 段与两处 export 各加一行（保持现有顺序，插在 `GridBackground` 之后）：

```ts
import AppLogo from './AppLogo.vue'
```
```ts
export {
  Card,
  Button,
  Badge,
  Loading,
  Empty,
  CircularProgress,
  GridBackground,
  AppLogo,
}
```
```ts
export default {
  Card,
  Button,
  Badge,
  Loading,
  Empty,
  CircularProgress,
  GridBackground,
  AppLogo,
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npm run test:unit -- brandMark`
Expected: PASS（6 passed）

若红了：`props.size` 在 `<script setup>` 顶层只算一次，`height` 不会响应 `size` 变化 —— 改成 `const height = computed(() => Math.round((props.size * 46) / 48))` 并在模板用 `:height="height"`。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/common/AppLogo.vue frontend/src/components/common/index.ts frontend/test/unit/brandMark.spec.ts
git commit -m "feat(ui): 新增 AppLogo 品牌符号组件，并锁住与母版的形状同源"
```

---

## Task 6: 四处界面品牌位落位 + e2e 接线证明

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.vue:5-7`
- Modify: `frontend/src/pages/auth/LoginPage.vue:6-10`、`:178-180`、`:361-363`
- Modify: `frontend/src/pages/auth/ConnectPage.vue:5-7`
- Modify: `frontend/src/components/common/AppAboutDialog.vue:12`、`:77-79`
- Test: `frontend/e2e/global/brand-mark.spec.ts`（新建）

**Interfaces:**
- Consumes: Task 5 的 `AppLogo`
- Produces: DOM 契约 `data-test="app-logo"`（四处都有），供 e2e 与后续用例定位

- [ ] **Step 1: 写失败的 e2e 用例**

新建 `frontend/e2e/global/brand-mark.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { loginAs } from '../helpers/auth'

/**
 * T3（浏览器不可替代的两件事）：
 *   1) 品牌位真的渲染出实心 SVG 剪影，而不是 EP 折线图图标或 emoji；
 *   2) 双主题下的**计算色** —— CSS 变量在运行时解析的结果，T2 拿不到。
 * 形状本身不漂移由 T2（brandMark.spec.ts）负责，这里不重复。
 *
 * 侧栏与登录页是两种形制，所以断言不同：
 *   侧栏 `.logo-icon` 是 40×40 的 var(--brand) 实色底板 + 反白符号（现状即如此）；
 *   登录页 `.logo-icon` 只有 color: var(--brand)，无底板。
 * 侧栏 night 下原本仍是"白符号压 #f9a825 金黄底"= 约 1.9:1，本任务按 spec D6 改深墨。
 */

const BRAND_LIGHT = 'rgb(37, 99, 235)'    // --brand light  = #2563eb
const BRAND_NIGHT = 'rgb(249, 168, 37)'   // --brand night  = #f9a825
const INK_LIGHT = 'rgb(255, 255, 255)'    // 侧栏底板上的反白
const INK_NIGHT = 'rgb(19, 19, 39)'       // 侧栏 night 底板上的深墨 = --p-slate-950

test.describe('@p1 品牌位', { tag: ['@p1', '@global'] }, () => {
  test('侧栏品牌位是 AppLogo，底板墨色随主题切换且不再是白压金黄', async ({ page }) => {
    await loginAs(page, 'user')
    await gotoApp(page, '/dashboard')
    const logo = page.locator('aside.sidebar [data-test="app-logo"]')
    await expect(logo).toBeVisible()
    await expect(logo.locator('path')).toHaveCount(1)
    await expect(logo).toHaveCSS('color', INK_LIGHT)
    await expect(page.locator('aside.sidebar .logo-icon')).toHaveCSS('background-color', BRAND_LIGHT)

    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await gotoApp(page, '/dashboard')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    await expect(page.locator('aside.sidebar .logo-icon')).toHaveCSS('background-color', BRAND_NIGHT)
    await expect(page.locator('aside.sidebar [data-test="app-logo"]')).toHaveCSS('color', INK_NIGHT)
  })

  test('登录页品牌位是 AppLogo，不再是 TrendCharts 或 emoji', async ({ page }) => {
    await page.goto('/login')
    const logo = page.locator('[data-test="app-logo"]')
    await expect(logo).toBeVisible()
    await expect(logo).toHaveCSS('color', BRAND_LIGHT)
    // 旧的 EP 图标会留下 .el-icon 包装，emoji 会留在文本里
    await expect(page.locator('.logo-section .el-icon')).toHaveCount(0)
    await expect(page.locator('.logo-section')).not.toContainText('📊')
  })
})
```

`loginAs(page, 'user')` 的 `'user'` 是 `helpers/auth` 的 `Role` 联合成员（`loginAs(page: Page, role: Role)`，`helpers/auth.ts:25`）。

- [ ] **Step 2: 跑 e2e 确认失败**

Run: `cd frontend && npx playwright test e2e/global/brand-mark.spec.ts --project=P1 --workers=1`
Expected: FAIL —— `aside.sidebar [data-test="app-logo"]` 等不到（现在还是 `el-icon`）。

- [ ] **Step 3: 侧栏落位（保留底板形制，修 night 墨色）**

`Sidebar.vue:5-7` 替换为：

```html
      <div class="logo-icon">
        <AppLogo :size="28" data-test="app-logo" />
      </div>
```

`<script setup>` 的 import 段加：

```ts
import { AppLogo } from '@/components/common'
```

**`TrendCharts` 的 import 保留** —— 已核实该文件里 `TrendCharts` 出现 3 次（import、`:6` 的 logo、`:90` 的 `menuItems` 数据分析项），删掉 logo 用处后菜单项仍在用，删 import 会让 `npm run build` 的 `vue-tsc -b` 直接红。

`Sidebar.vue:147-157` 的 `.logo-icon` 现为 `background: var(--brand); color: #fff`。night 下这就是"白符号压 `#f9a825`"，对比约 1.9:1 —— 正是 spec D6 判定的缺陷在应用内的现网实例。在该规则块之后补一条 night 覆盖（本项目双主题选择器统一 `:root[data-theme="night"]`）：

```css
/* night 的金黄底上白字只有约 1.9:1，改深墨（spec D6） */
:root[data-theme="night"] .logo-icon {
  color: var(--p-slate-950);
}
```

- [ ] **Step 4: 登录页落位，并清掉尺寸双机制**

`LoginPage.vue:6-10` 替换为：

```html
        <div class="logo-section">
          <AppLogo :size="64" class="logo-icon" data-test="app-logo" />
        </div>
```

`<script setup>` 加 `import { AppLogo } from '@/components/common'`，并**删掉 `TrendCharts` 的 import** —— 已核实该文件 `TrendCharts` 只出现 2 次（import + `:8` 的 logo），删 logo 后 import 即无使用者。

`:178-180` 的 `.logo-icon { color: var(--brand); }` **保留**：登录页是"无底板、符号取品牌色"的界面形制（spec §2.2），AppLogo 靠 `currentColor` 上色。

`:361-363` 窄屏媒体查询里的这一段**整块删掉**：

```css
  .logo-icon {
    font-size: 48px; /* @type-scale-one-off 登录页装饰图标 */
  }
```

理由：`:size="64"` prop 与宿主 `font-size: 48px` 是两套机制在争同一个尺寸（spec §5.1）。删掉 CSS 那侧，尺寸由组件的 `size` prop 单点决定。窄屏要变小属于批 4 的 token 档位工作，本任务不做。

- [ ] **Step 5: 连接页与关于对话框**

`ConnectPage.vue:5-7` 替换为：

```html
        <div class="logo-section">
          <AppLogo :size="64" class="logo-icon" data-test="app-logo" />
        </div>
```

`<script setup>` 加 `import { AppLogo } from '@/components/common'`，并**删掉 `Connection` 的 import** —— 已核实该文件 `Connection` 只出现 2 次（import + `:6`）。

`AppAboutDialog.vue:12` 替换为：

```html
        <AppLogo :size="28" class="about-logo" data-test="app-logo" />
```

`AppAboutDialog.vue:77-79` 的 `.about-logo { font-size: var(--p-fs-headline); }` 替换为：

```css
.about-logo {
  color: var(--brand);
}
```

并在其 `<script setup>` 加 `import { AppLogo } from '@/components/common'`。

- [ ] **Step 6: 跑构建与单测**

```bash
cd frontend && npm run build && npm run test:unit
```
Expected: `vue-tsc -b` 无错（未使用的 EP import 会在这里暴露）、vite 构建成功、单测全绿。

- [ ] **Step 7: 跑 e2e 确认转绿**

Run: `cd frontend && npx playwright test e2e/global/brand-mark.spec.ts --project=P1 --workers=1`
Expected: 2 passed。

- [ ] **Step 8: 跑受影响面门禁**

Run: `cd frontend && npm run lint:e2e && npm run test:e2e:affected`
Expected: 不出现 `NO AFFECTED TESTS`；auth/global/theme 相关用例全绿。若 `e2e/auth/auth.spec.ts` 或 `e2e/global/global.spec.ts` 里有按 `.el-icon`/emoji 定位登录页 logo 的断言，**先把定位迁到 `data-test="app-logo"`**（单独一次提交），再回来跑本步。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/components/layout/Sidebar.vue frontend/src/pages/auth/LoginPage.vue frontend/src/pages/auth/ConnectPage.vue frontend/src/components/common/AppAboutDialog.vue frontend/e2e/global/brand-mark.spec.ts
git commit -m "feat(ui): 侧栏/登录/连接/关于四处品牌位改用 AppLogo，删掉登录页尺寸双机制"
```

---

## Task 7: 文档站 favicon 与品牌位

**Files:**
- Modify: `docs/user-guide/template.html:6`（`<title>` 后）、`:233`
- Modify: `docs/user-guide/build.js:105-112` 附近

**Interfaces:**
- Consumes: `frontend/public/favicon.svg`（不复制第二份母版）
- Produces: `docs/user-guide/dist/favicon.svg`

- [ ] **Step 1: 构建时把母版复制进 dist**

`docs/user-guide/build.js` 的"Copy images"块之后追加：

```js
// Copy the brand mark from the SPA's master asset — one source of truth for the
// shape; docs never keep their own copy of the path data.
const MASTER_FAVICON = path.join(__dirname, '..', '..', 'frontend', 'public', 'favicon.svg');
if (fs.existsSync(MASTER_FAVICON)) {
  fs.copyFileSync(MASTER_FAVICON, path.join(DIST_DIR, 'favicon.svg'));
  console.log('Copied brand favicon');
} else {
  console.warn('frontend/public/favicon.svg missing; docs site will have no icon');
}
```

- [ ] **Step 2: 模板挂上图标**

`docs/user-guide/template.html` 第 6 行 `<title>…</title>` **之后**插入：

```html
  <link rel="icon" type="image/svg+xml" href="{{rootPrefix}}favicon.svg">
```

`{{rootPrefix}}` 是 build.js 已在做的替换（`:96`），子目录页会拿到正确的相对前缀。

- [ ] **Step 3: 侧栏品牌位换母版内联**

`template.html:231-235` 的 `.sidebar-title` 内，把 `<span>📊</span>` 替换成内联母版（文档站是纯静态、无组件系统，所以内联一份 path；`:233` 这一处是**唯一**允许出现第二份 `d` 的地方，因为它跨不到 frontend 的构建产物）：

```html
          <svg width="20" height="19" viewBox="0 0 48 46" aria-hidden="true" style="fill:currentColor;flex:0 0 auto">
            <path d="M25.946 44.938c-.664.845-2.021.375-2.021-.698L19.4 33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.946 44.94z"/>
          </svg>
```

- [ ] **Step 4: 构建并核验**

```bash
cd docs/user-guide && npm run build && grep -c "favicon.svg" dist/index.html && ls -la dist/favicon.svg && grep -c "📊" dist/index.html
```
Expected: `dist/index.html` 含 1 处 favicon 引用、`dist/favicon.svg` 存在、`📊` 计数为 **0**。

- [ ] **Step 5: 提交**

```bash
git add docs/user-guide/build.js docs/user-guide/template.html
git commit -m "feat(docs): 用户指南接上品牌图标，侧栏去 emoji"
```

---

## Task 8: ui-design-guide 的 `--on-brand` 口径修正

**Files:**
- Modify: `docs/reference/ui-design-guide.md:94`（§3.3 品牌表）

**Interfaces:**
- Consumes: Task 2 产出的 night 底板（深墨）事实
- Produces: 无

- [ ] **Step 1: 改表格行**

`docs/reference/ui-design-guide.md:94` 现为：

```markdown
| `--on-brand` | `#ffffff` | `#ffffff` | 品牌底上的前景色 |
```

替换为：

```markdown
| `--on-brand` | `#ffffff` | `#ffffff` | 品牌底上的前景色。**仅适用于 light 渐变底**；night 渐变底（amber 系）上白字对比只有约 1.9:1，前景改用 `--p-slate-950 #131327`（图标家族已按此实现） |
```

并在 §3.3 表格下方加一行说明：

```markdown
> 图标家族的底板规则：Light 底板反白符号，Night 底板深色墨符号，界面内符号一律 `currentColor` 取 `--brand`。见 `docs/superpowers/specs/2026-10-15-icon-system-design.md` §2.2。
```

- [ ] **Step 2: 确认没动 token 值本身**

Run: `git diff --stat docs/reference/ui-design-guide.md frontend/src/styles/design-tokens.css`
Expected: 只有 guide 一个文件有改动，`design-tokens.css` **不在**列表里（本计划不改 token 取值，只改文档口径）。

- [ ] **Step 3: 提交**

```bash
git add docs/reference/ui-design-guide.md
git commit -m "docs(reference): 修正 --on-brand 在 night 渐变底上不成立，记入深墨口径"
```

---

## 完成判据

全部满足才算这轮做完：

1. `cd frontend && npm run test:unit` 全绿，且新增 3 个 spec 文件都在跑（`brandMark` / `iconLib` / `appIcon`），既有用例无回归。
2. `cd frontend && npm run build` 通过（`vue-tsc -b` 会抓出 Task 6 删剩的未使用 EP import）。
3. 后端静态资源回归：`.venv/Scripts/python.exe manage.py test test.backend -p "test_static_assets.py"` 全绿 —— 母版 `favicon.svg` 换了内容，`/favicon.svg` 与 `/icons.svg` 两条 content-type 断言必须仍然过（本计划不删 `icons.svg`）。
4. `node scripts/gen-icon.ico.js` 输出的 16px 行是 `1 色阶 / 剪影 ≥15×15`，且把母版改成多色阶后自检会以非零退出（Task 2 Step 7）。
5. `out/win-unpacked/` 里 exe 图标、任务栏图标、窗口标题栏图标三处**人工目视**确认为闪电，结论记进 `docs/tasks/todo.md`。
6. `npm run test:e2e:affected` 与 `npx playwright test e2e/global/brand-mark.spec.ts --project=P1 --workers=1` 全绿；侧栏 night 下品牌位是深墨压金黄（不再是白压金黄）。
7. `docs/user-guide` 构建产物里 `📊` 计数为 0，`dist/favicon.svg` 存在。
8. 工作区里除 `build/`、`out/`、`dist/`、`tasks/` 这些 gitignore 路径外无新增未跟踪文件。

## 不在本计划范围

- 图标注册表与 7 档尺寸 token（批 4）
- emoji C/D 两类治理与 `ui-design-guide.md:309`/`:341`/`:403` 三处对账（批 5，前置是逐处站点清单）
- 删 `frontend/public/icons.svg` + `config/urls.py:89` + `test_static_assets.py:104-109`、删 `scripts/generate_icon.py`（批 6，需单独批准）
- 系统托盘（spec §10 已移出）

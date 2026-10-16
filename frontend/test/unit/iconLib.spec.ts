/**
 * T2：.ico 生成器的纯函数层 —— **底板形制版**（Task 9，C1 修复）。
 *
 * 形制：渐变圆角底板铺满整帧（D4/spec §2.2）+ 反白符号按帧分档内缩。
 * 判据随之重定基线（简报「重定审计基线」表）：
 *   G1 符号(反白)区域实心色阶 ≤ **逐帧**阈值表 —— 防模糊加回符号（D2）；
 *   G2 底板两支 stop 在帧内真实出现 —— 防 night/错色板进 .ico；
 *   G3 底板几何（不透明占比区间 + 剪影=整帧 + 四角透明）—— 防「裸符号无底板」（C1 本体）；
 *   G4 16px 符号可辨性（ink 像素数 + 底部 25% 最宽行）—— 替代旧「剪影 ≥15×15」。
 * 阈值出处与余量注释在 scripts/icon-lib.cjs / scripts/icon-audit.cjs 原位。
 *
 * 反向对照（每条新门各红一次，全部用合成字节，不起浏览器）：
 *   裸闪电帧 → G3 红；底板画了但内缩 1px → 只剩 G3b 红（I3）；模糊化反白符号入底板 → G1 红；
 *   金色(amber)底板 → G2 红；16px 符号像素不足 → G4 红。
 * Task 11 又补三条，都属于「文案与可达原因对齐」那一族（E.3/E.4/M3）：
 *   占比**越过上界**的方板内缩 → G3b 文案不许说「掉到下界以下」，也不许替别的帧说
 *   「这条门是该回归在 16px 的唯一承运人」；符号**没被反白** → 只有 G4 红，且文案必须点名
 *   这第三种原因；外加 assembleIco 的容器**往返**（条目偏移/长度/每帧可解，M2）。
 *   合成字节夹具（encodePngRgba / synthFrame）搬到了 test/unit/helpers/icoSynth.ts ——
 *   判据用例本身要留在本文件读，夹具再留一份就撞 CLAUDE.md 的「单文件 ≤600 行」。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
  SIZES,
  CORNER_RATE,
  plateRadius,
  insetPct,
  parseBrandGradient,
  frameHtml,
  decodePngRgba,
  frameStats,
  auditVerdict,
  assembleIco,
  AUDIT_LIMITS,
  inkTonesMax,
} from '../../../scripts/icon-lib.cjs'
import { encodePngRgba, synthFrame } from './helpers/icoSynth'

// 旧实现没有 parseBrandGradient：模块级直接调用会让整个 suite 挂掉、逐条负对照无法呈现。
// 兜成 null 后，每条用例各自红在「它要的新能力不存在」上（Task 9 的 RED 证据按用例看）。
const BRAND = (() => {
  try {
    return parseBrandGradient(readFileSync(new URL('../../src/styles/design-tokens.css', import.meta.url), 'utf8'))
  } catch {
    return null as never
  }
})()

describe('parseBrandGradient —— 品牌色单源化（I4：不许再硬编 #2563eb）', () => {
  it('从真实 design-tokens.css 解析出 light --grad-brand 两支端点，var() 经 primitive 表落到 hex', () => {
    expect(BRAND.stops.map(s => s.hex)).toEqual(['1d4ed8', '2563eb'])
    // 0/100 无显式位置的 stop 按等距补全（light 两支 = 端点即 0%、100%）
    expect(BRAND.stops.map(s => s.pct)).toEqual([0, 100])
    expect(BRAND.first).toEqual([29, 78, 216])
    expect(BRAND.last).toEqual([37, 99, 235])
  })

  it('令牌一改就红在这里：今天 design-tokens 的 light 渐变字面值是 #1d4ed8 → #2563eb', () => {
    // **全仓唯一**允许写下这两个 hex 的测试（本轮 Minor 5）：模板/判据/其余用例一律吃 BRAND。
    // 分档的原因是「同源」与「钉住今天改了什么」是两件事 —— 前者不许抄字面量，后者必须抄，
    // 抄的那一份集中在这一个具名用例里，改令牌的人只需要面对这一处噪音。
    expect(BRAND.stops.map((s) => `#${s.hex}@${s.pct}%`)).toEqual(['#1d4ed8@0%', '#2563eb@100%'])
  })

  it('stop 数量不写死：三档写法（照抄 night 的 55% 中档位置）也按数量处理', () => {
    const css =
      ':root { --p-amber-700: #c17900; --p-amber-500: #f9a825; --p-amber-300: #ffd54f; ' +
      "--grad-brand: linear-gradient(135deg, var(--p-amber-700), var(--p-amber-500) 55%, var(--p-amber-300)); }"
    const parsed = parseBrandGradient(css)
    expect(parsed.stops.map(s => [s.hex, s.pct])).toEqual([
      ['c17900', 0],
      ['f9a825', 55],
      ['ffd54f', 100],
    ])
  })

  it('锚定 light 块：night 排在前面也必须取裸 :root 那一个（--grad-brand 全文出现两次）', () => {
    const css =
      ":root[data-theme='night'] { --grad-brand: linear-gradient(135deg, var(--p-amber-700), var(--p-amber-300)); }\n" +
      ":root { --p-amber-700: #c17900; --p-amber-300: #ffd54f; }\n" +
      ":root { --grad-brand: linear-gradient(135deg, var(--p-blue-700), var(--p-blue-600)); }\n" +
      ":root { --p-blue-700: #1d4ed8; --p-blue-600: #2563eb; }"
    expect(parseBrandGradient(css).stops.map(s => s.hex)).toEqual(['1d4ed8', '2563eb'])
  })

  it('解析失败必须抛错：缺 --grad-brand / var 解析不到 hex / 非 linear-gradient 值', () => {
    expect(() => parseBrandGradient(':root { --bg: red; }')).toThrow(/grad-brand/)
    expect(() => parseBrandGradient(':root { --grad-brand: var(--x); }')).toThrow()
    expect(() =>
      parseBrandGradient(':root { --grad-brand: linear-gradient(135deg, var(--nope), var(--b)); --b: #000000; }'),
    ).toThrow(/nope/)
    expect(() => parseBrandGradient(':root { --grad-brand: #2563eb; }')).toThrow(/linear-gradient/)
  })
})

describe('insetPct / plateRadius —— 底板几何与符号内缩（D7 语义改为内缩）', () => {
  it('底板铺满整帧：圆角半径 = round(22% * size)，逐档核对', () => {
    expect(CORNER_RATE).toBeCloseTo(0.22)
    const bySize = Object.fromEntries(SIZES.map((s) => [s, plateRadius(s)]))
    expect(bySize).toEqual({ 16: 4, 32: 7, 48: 11, 64: 14, 128: 28, 256: 56 })
  })

  it('内缩分档：16px 最窄、≥48px 最宽（档位数值以实测选型为准，见 icon-lib.cjs 注释）', () => {
    expect(insetPct(16)).toBeCloseTo(0.06)
    expect(insetPct(24)).toBeCloseTo(0.1)
    expect(insetPct(32)).toBeCloseTo(0.1)
    expect(insetPct(48)).toBeCloseTo(0.19)
    expect(insetPct(256)).toBeCloseTo(0.19)
  })

  it('16px 内缩取整后必须 ≥1px：底板铺满帧时，0 内缩会吃掉符号-底板间隙', () => {
    for (const s of SIZES) expect(Math.round(s * insetPct(s))).toBeGreaterThanOrEqual(1)
  })
})

describe('frameHtml —— 底板 + 反白符号', () => {
  const master =
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="46" viewBox="0 0 48 46">' +
    '<style>.b{fill:#2563eb}@media (prefers-color-scheme:dark){.b{fill:#f9a825}}</style>' +
    '<path class="b" d="M0 0H48V46H0Z"/></svg>'

  it('底板矩形铺满整帧（outer pad=0），圆角按 22%，渐变用注入的 stop（不硬编品牌色）', () => {
    const html = frameHtml(master, 32, BRAND)
    expect(html).toMatch(/<rect x="0" y="0" width="32" height="32" rx="7"/)
    // 断言吃的是**解析出来的 BRAND**，不是字面量 —— 本任务的存在理由就是把硬编令牌消掉，
    // 测试再抄一遍 #1d4ed8/#2563eb 等于把常量请回第二个家。今天字面量的唯一钉子见
    // parseBrandGradient 那组的「令牌一改就红在这里」。
    expect(html).toContain(`stop-color="#${BRAND.stops[0].hex}"`)
    expect(html).toContain(`stop-color="#${BRAND.stops[BRAND.stops.length - 1].hex}"`)
    // CSS 135deg 对正方形 = 左上→右下：objectBoundingBox (0,0)→(1,1)
    expect(html).toContain('gradientUnits="objectBoundingBox"')
    expect(html).toContain('x1="0" y1="0" x2="1" y2="1"')
    // 帧尺寸=渲染尺寸的契约：内联 <svg> 默认进文本流，Chromium 实测把整幅内容下移 1px、
    // 吃掉最后一行（旧 .ico 16px 剪影 16×15 的真实根因，不是 Math.ceil/round 之争）。
    expect(html).toContain('svg{display:block}')
    // 外层帧的**唯一对外契约**（Task 2 记录在案，本模板没有任何其他对外接口）：
    // `<svg` 之后紧跟 width/height/viewBox，xmlns 必须在属性表末尾 —— Task 2 改判 1 的原样钉子。
    for (const size of SIZES) {
      expect(frameHtml(master, size, BRAND)).toContain(
        `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">`,
      )
    }
  })

  it('符号强制反白：!important 覆盖母版 class 与内联 style（旧模糊母版同模板也画成白）', () => {
    const html = frameHtml(master, 32, BRAND)
    expect(html).toMatch(/plate-symbol[^>]*\*\s*\{[^}]*fill:\s*#(fff|ffffff)\s*!important/)
  })

  it('符号按内缩分档放方框里，保留 48:46 比例、内框高**精确等于** Math.ceil(w*46/48)', () => {
    // 这条从 `>=` 收成精确等式是**刻意的**（本轮 I1）：底板形制下 ceil→round 不再改变剪影
    // （16px 两版都 16×16，因为 G3b 判的是铺满整帧的 <rect> 而不是符号框），实测只把
    // 16px 尾行 2→1、64px 尾行 3→2，而 TAIL_MIN_16=1 正好压在 1 上（见 icon-audit.cjs 的
    // G4b 注释）。也就是说**没有任何像素门守着这个 ceil** —— 这条等式是它唯一的绊线，
    // 改回 round 必须红在测试上，而不是红在一段注释里。
    for (const size of SIZES) {
      const html = frameHtml(master, size, BRAND)
      const m = /<svg class="plate-symbol" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" viewBox="0 0 48 46"/.exec(html)!
      const [, x, y, w, h] = m.map(Number)
      const inset = Math.round(size * insetPct(size))
      expect(x).toBe(inset)
      expect(w).toBe(size - 2 * inset)
      expect(h).toBe(Math.ceil((w * 46) / 48)) // 精确等式：round 会挤掉一整行 ink（Task 2 教训）
      expect(y).toBe(Math.round((size - h) / 2))
    }
  })

  it('opts.insetPx 可显式覆盖内缩 —— 档位选型探针（tasks/ 临时件）依赖这条契约', () => {
    const html = frameHtml(master, 16, BRAND, { insetPx: 3 })
    expect(html).toMatch(/x="3" y="\d+" width="10"/)
  })

  it('缺 viewBox 或缺 brand 都直接抛错，不静默出坏图标', () => {
    expect(() => frameHtml('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', 16, BRAND)).toThrow(/viewBox/)
    expect(() => (frameHtml as (s: string, n: number, b?: unknown) => string)(master, 16)).toThrow(/brand|渐变/i)
  })
})

describe('decodePngRgba + frameStats —— 审的是要写进 .ico 的字节', () => {
  it('能解自己编的 8bit RGBA 图，色阶与剪影框对得上', () => {
    const png = encodePngRgba(4, 4, (x, y) => {
      if (x < 2 && y < 2) return [255, 0, 0, 255]
      if (x >= 2 && y >= 2) return [0, 0, 255, 255]
      return [0, 0, 0, 0]
    })
    expect(decodePngRgba(png).width).toBe(4)
    const s = frameStats(png)
    expect(s).toMatchObject({ size: 4, tones: 2, dominant: '255,0,0', bboxW: 4, bboxH: 4 })
  })

  it('色阶只认 alpha===255，剪影框认 alpha>=8（两个口径不同）', () => {
    const haze = encodePngRgba(2, 2, () => [10, 20, 30, 120])
    expect(frameStats(haze)).toMatchObject({ tones: 0, bboxW: 2, bboxH: 2 })
    const core = encodePngRgba(2, 2, (x, y) => [37, 99, 235, x === 0 && y === 0 ? 255 : 250])
    expect(frameStats(core).tones).toBe(1)
  })

  it('ink 口径 = alpha===255 且各通道 ≥240：白符号进、渐变底板不进、半透明白边不进', () => {
    const s = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        blob: { x: 4, y: 4, w: 8, h: 4, color: [255, 255, 255] },
      }),
    )
    expect(s.inkTones).toBe(1)
    expect(s.inkCount).toBe(32)
  })

  it('底板两支 stop 的容差计数（切比雪夫 ≤ AUDIT_LIMITS.STOP_TOL 的实心像素）', () => {
    const s = frameStats(synthFrame(16, { startHex: BRAND.firstHex, endHex: BRAND.lastHex, blob: null as never }), BRAND)
    // 左上三角区离 #1d4ed8 近、右下三角区离 #2563eb 近，两块都必须数到
    expect(s.startPixels).toBeGreaterThan(AUDIT_LIMITS.STOP_PIXELS_MIN)
    expect(s.endPixels).toBeGreaterThan(AUDIT_LIMITS.STOP_PIXELS_MIN)
    // 金色板离蓝端点极远：计数须≈0（G2 红的基础，见 auditVerdict 负对照）
    const gold = frameStats(synthFrame(16, { startHex: 'c17900', endHex: 'ffd54f', blob: null as never }), BRAND)
    expect(gold.startPixels).toBe(0)
    expect(gold.endPixels).toBe(0)
  })

  it('底板几何：不透明占比 / 四角 r/2 圆盘透明率 / 底部 25% 最宽行', () => {
    const round = frameStats(synthFrame(16, { startHex: BRAND.firstHex, endHex: BRAND.lastHex, blob: null as never }))
    expect(round.plateRatio).toBeGreaterThan(AUDIT_LIMITS.PLATE_RATIO_MIN)
    expect(round.plateRatio).toBeLessThan(AUDIT_LIMITS.PLATE_RATIO_MAX)
    expect(round.cornerTransp).toBe(1)
    const square = frameStats(
      synthFrame(16, { startHex: BRAND.firstHex, endHex: BRAND.lastHex, squarePlate: true, blob: null as never }),
    )
    expect(square.cornerTransp).toBe(0)
    // 尾部两行有宽 5 的 ink，底部 25%（16px → 行 12..15）最宽行 = 5
    const tailed = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        blob: { x: 4, y: 12, w: 5, h: 2, color: [255, 255, 255] },
      }),
    )
    expect(tailed.tailRowW).toBe(5)
  })
})

describe('G1 逐帧阈值表（本轮 I4：一档全局常量套在随尺寸增长的统计量上会丢判别力）', () => {
  // 两列实测是这条门的出处，都在 tracked 通路上渲（本机 Playwright Chromium 截 frameHtml →
  // frameStats）：交付 = frameHtml(现母版)；真模糊 = frameHtml(旧模糊母版) 反白进同一底板。
  // 复测记录：tasks/_fixr_ctrl_verify.txt B 段（本轮独立复现，非抄评审/简报的数字）。
  const MEASURED: [number, number, number][] = [
    [16, 5, 8],
    [32, 8, 11],
    [48, 10, 15],
    [64, 11, 17],
    [128, 15, 24],
    [256, 14, 24],
  ]
  it('六个交付帧各有自己的一行：严格高于该帧交付值、且仍低于该帧真模糊值', () => {
    for (const [size, delivered, blurred] of MEASURED) {
      const { max, tabulated } = inkTonesMax(size)
      expect(tabulated, `${size}px 必须在逐帧表里（新增帧要先测后加行）`).toBe(true)
      expect(max, `${size}px 阈值必须严格高于交付实测（I7：不许零余量图腾）`).toBeGreaterThan(delivered)
      expect(max, `${size}px 阈值必须仍拦得住该帧的真模糊实测`).toBeLessThan(blurred)
      // 定档规则本体：默认给 +3 的 AA 漂移余量，但**余量不得吃掉牙齿**
      expect(max).toBe(Math.min(delivered + 3, blurred - 1))
    }
  })

  it('16px 这帧的两个目标互相挤压：保住牙齿（阈值=真模糊−1=7），余量只能给 +2', () => {
    // 交付 5 / 真模糊 8 → 余量给到 +3 就是阈值 8，**等于或高于**真模糊实测，该帧的牙齿没了。
    // 评审举的示意档 {16:9} 正是这种：9 > 8，宣称恢复了小帧判别力、同时把它悄悄丢掉。
    const { max } = inkTonesMax(16)
    expect(max).toBe(7)
    expect(max - 5).toBe(2) // 相对交付实测的余量
    expect(8 - max).toBe(1) // 相对真模糊实测的拦截差距
    expect(5 + 3).toBeGreaterThanOrEqual(8) // 「+3 余量」在这一帧必然吃掉牙齿：不是我没用，是无解
  })

  it('表外尺寸借「不小于它的第一档」，绝不给没测过的尺寸放行更宽口径', () => {
    expect(inkTonesMax(24)).toEqual({ max: 10, tabulated: false }) // 借 32 档
    expect(inkTonesMax(200)).toEqual({ max: 17, tabulated: false }) // 借 256 档
    expect(inkTonesMax(512)).toEqual({ max: 17, tabulated: false }) // 比最大档还大：借最大档，绝不返回 undefined
    expect(inkTonesMax(8)).toEqual({ max: 7, tabulated: false }) // 借 16 档（最严）
    // 未映射尺寸也不能让门失效（undefined 阈值 = 永远不红 = 静默放行）
    const stats = frameStats(
      synthFrame(512, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        blob: { x: 160, y: 160, w: 120, h: 200, toneCells: true },
      }),
      BRAND,
    )
    expect(auditVerdict(stats, BRAND).join('\n')).toMatch(/借上一档/)
  })

  it('把某帧真模糊的实测值造进合成字节，那一帧必须红（小帧牙齿是活的，不只是大帧兜）', () => {
    for (const [size, , blurred] of MEASURED) {
      const stats = frameStats(
        synthFrame(size, {
          startHex: BRAND.firstHex,
          endHex: BRAND.lastHex,
          blob: { x: Math.round(size * 0.31), y: Math.round(size * 0.25), w: Math.round(size * 0.375), h: Math.round(size * 0.75), tones: blurred },
        }),
        BRAND,
      )
      expect(stats.inkTones, `${size}px 合成样本的色阶数应等于该帧真模糊实测`).toBe(blurred)
      const problems = auditVerdict(stats, BRAND).filter((p) => /色阶/.test(p))
      expect(problems.length, `${size}px 帧的模糊回归必须由 G1 在该帧判红（阈值 ${inkTonesMax(size).max}）`).toBe(1)
    }
  })
})

describe('auditVerdict —— 底板形制的红线（含四条负对照）', () => {
  it('G3 负对照【裸闪电帧】：无底板 → 底板几何门红（C1 本体的直接守门）', () => {
    // 透明底上一块品牌蓝方斑：旧判据下它 tones=1、主色=#2563eb 全绿放行 —— 这正是 C1 泄漏的路径
    const bare = frameStats(synthFrame(16, { body: { x: 2, y: 2, w: 12, h: 12 } }), BRAND)
    const problems = auditVerdict(bare, BRAND)
    expect(problems.join('\n')).toMatch(/底板/)
    expect(problems.join('\n')).toMatch(/剪影/)
  })

  it('G3b 负对照【底板画了但整圈内缩 1px】：G3a/G3c 都放行，只剩 G3b 红，且文案不许指「裸符号」', () => {
    // 本轮 I3 的靶：16px 底板内缩 1px → 不透明占比仍在 [0.70,0.975]、四角样本仍全透明，
    // 于是**这条门是该回归在 16px 的唯一承运人**。旧文案把它一律报成「底板没铺满（这是裸符号的
    // 指纹）」，会把人往「底板没画」的方向支走 —— 与早先整枝评审 I7 同一缺陷类。
    const insetPlate = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        plateMargin: 1,
        blob: { x: 5, y: 4, w: 6, h: 12, color: [255, 255, 255] },
      }),
      BRAND,
    )
    expect(insetPlate.bboxW).toBe(14)
    expect(insetPlate.bboxH).toBe(14)
    // 这两个数字就是「G3b 是唯一承运人」的证据，钉在这里而不是只写在注释里
    expect(insetPlate.plateRatio).toBeCloseTo(0.75, 4) // 在 [0.70, 0.975] 区间内 → G3a 绿
    expect(insetPlate.cornerTransp).toBe(1) // → G3c 绿
    expect(insetPlate.inkTones).toBe(1) // → G1 绿
    const problems = auditVerdict(insetPlate, BRAND)
    const g3b = problems.filter((p) => /剪影/.test(p))
    expect(g3b.length).toBe(1)
    expect(g3b[0]).toMatch(/内缩|裁掉/)
    expect(g3b[0]).not.toMatch(/裸符号/) // 这一帧的 plateRatio 在区间内，裸符号不是可达原因
  })

  it('G3b 对照【占比也不达标的裸符号】：文案必须把两种可达原因都写出来', () => {
    const bare = frameStats(synthFrame(16, { body: { x: 2, y: 2, w: 12, h: 12 } }), BRAND)
    const g3b = auditVerdict(bare, BRAND).filter((p) => /剪影/.test(p))
    expect(g3b[0]).toMatch(/根本没画出来/)
    expect(g3b[0]).toMatch(/大幅内缩|裁掉整边/) // 占比同样不达标时，内缩/裁边也是可达原因
  })

  it('G3b 文案按**方向**措辞（E.3），且不许替别的帧说话（E.4）', () => {
    // 可达性不是设想出来的：tasks/_t11_g3b_matrix.mjs 逐帧实测——
    //   256px 方板整圈内缩 1px → plateRatio 0.9844（> PLATE_RATIO_MAX）且剪影 254×254≠256×256，
    //   于是 G3a 在**上界**红、G3b 同时红；旧文案对区间外的每一帧都写「占比也一起掉到下界以下」，
    //   对上界违例是假的（评审点名的 I3 轻量版，同一个病灶）。
    const overMax = frameStats(
      synthFrame(256, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        squarePlate: true,
        plateMargin: 1,
        blob: null as never,
      }),
      BRAND,
    )
    expect(overMax.plateRatio).toBeGreaterThan(AUDIT_LIMITS.PLATE_RATIO_MAX)
    const gOver = auditVerdict(overMax, BRAND).filter((p) => /必须等于整帧/.test(p))
    expect(gOver.length).toBe(1)
    expect(gOver[0], `上界违例的帧不许被说成「掉到下界以下」：${gOver[0]}`).not.toMatch(/下界以下/)
    expect(gOver[0]).toMatch(/上界|外扩|圆角没剪/)
    // 区间内那一支（内缩/裁边）在**每一帧**都会打「这条门是该回归在 16px 的唯一承运人」，
    // 而 256px 帧根本不是 16px：尺寸相关的事实不许硬编进每帧消息（E.4）。
    const insetBig = frameStats(
      synthFrame(256, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        plateMargin: 1,
        blob: { x: 79, y: 64, w: 96, h: 192, color: [255, 255, 255] },
      }),
      BRAND,
    )
    expect(insetBig.plateRatio).toBeLessThanOrEqual(AUDIT_LIMITS.PLATE_RATIO_MAX)
    const gIn = auditVerdict(insetBig, BRAND).filter((p) => /必须等于整帧/.test(p))
    expect(gIn.length).toBe(1)
    expect(gIn[0], `256px 帧的消息里不该出现 16px：${gIn[0]}`).not.toMatch(/16px/)
  })

  it('G1 负对照【模糊化符号进底板】：ink 区色阶门红（这条只证明**门能红**，不是真回归的证据）', () => {
    // 底板、几何、端点全正常，只有符号从「纯白硬边」变成「72 个不同近白色阶」。
    // **它不是真回归的样子**：旧模糊母版经 !important 反白进底板的实测是 8/11/15/17/24/24
    // （16→256px，见上一条 describe 的逐帧表与 tasks/_fixr_ctrl_verify.txt），本样本把它放大成
    // 72 阶只为证明门是通的。真回归的逐帧证据在「把某帧真模糊的实测值造进合成字节」那条用例里，
    // 每一帧各红一次。红必须只指向 G1。
    const blurred = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        blob: { x: 5, y: 4, w: 6, h: 12, toneCells: true },
      }),
      BRAND,
    )
    const problems = auditVerdict(blurred, BRAND)
    expect(problems.join('\n')).toMatch(/符号/)
    expect(problems.join('\n')).toMatch(/色阶/)
    expect(problems.join('\n')).toMatch(/模糊|柔化/)
    expect(problems.length).toBe(1) // 其余判据都该放行 —— 红必须指向 G1
  })

  it('G2 负对照【金色/amber 底板】：渐变端点门红（night 进 .ico 的字节指纹）', () => {
    const amber = frameStats(
      synthFrame(16, {
        startHex: 'c17900',
        endHex: 'ffd54f',
        blob: { x: 4, y: 4, w: 8, h: 12, color: [255, 255, 255] },
      }),
      BRAND,
    )
    const problems = auditVerdict(amber, BRAND)
    expect(problems.join('\n')).toMatch(/端点/)
    expect(problems.join('\n')).toMatch(/1d4ed8|2563eb/)
    expect(problems.length).toBe(2) // start/end 各点名一次，几何与符号门都放行
  })

  it('G4 负对照【16px 符号像素不足】：可辨性门红，且文案不甩锅给「留白吃掉面积」（16px 外边距恒 0，I7 教训）', () => {
    const thin = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        blob: { x: 7, y: 7, w: 2, h: 2, color: [255, 255, 255] },
      }),
      BRAND,
    )
    const problems = auditVerdict(thin, BRAND)
    expect(problems.join('\n')).toMatch(/可辨/)
    expect(problems.join('\n')).not.toMatch(/留白/)
    expect(problems.length).toBe(1)
  })

  it('G4 负对照【符号没被反白】：底板/几何/端点全正常，只有可辨性红，文案必须点名这第三种原因（M3）', () => {
    // 模板里 `svg.plate-symbol *{fill:#fff !important}` 被改掉时的字节形状：符号还是画出来，
    // 只是画成品牌蓝 ⇒ ink 口径（各通道>=240）数不到它。本轮实测：ink=0、尾行=0、占比 0.9531、
    // 剪影 16×16、G1/G2/G3 全绿、只有 G4 红 —— 而旧文案写「只剩内缩档位和母版形状」，
    // 会把人支到两个不可能的方向上去（注释强于代码的同族，Task 11 M3）。
    const notWhite = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        // 符号画成渐变的**终点色**（= 反白那条 !important 没生效时母版本来的颜色）。
        // BRAND.last 由 CJS 模块推出为 number[]，夹具要的是三元组，这里按形状收窄。
        blob: { x: 5, y: 4, w: 6, h: 12, color: BRAND.last as [number, number, number] },
      }),
      BRAND,
    )
    expect(notWhite.inkCount).toBe(0)
    expect(notWhite.bboxW).toBe(16)
    const problems = auditVerdict(notWhite, BRAND)
    expect(problems.length).toBe(1)
    expect(problems[0]).toMatch(/可辨/)
    expect(problems[0], '反白失效必须是被点名的一种可能原因').toMatch(/反白/)
  })

  it('正对照【合成底板帧 16px / 48px】：全绿', () => {
    for (const size of [16, 48]) {
      const good = frameStats(
        synthFrame(size, {
          startHex: BRAND.firstHex,
          endHex: BRAND.lastHex,
          // 形状刻意仿 16px 实帧符号占位：偏中的窄列 + 探入底部 25% 的尾，
          // 不铺满对角端点邻域（否则合成样本自己会把端点计数吃穿）。
          blob: {
            x: Math.round(size * 0.31),
            y: Math.round(size * 0.25),
            w: Math.round(size * 0.375),
            h: Math.round(size * 0.75),
            color: [255, 255, 255],
          },
        }),
        BRAND,
      )
      expect(auditVerdict(good, BRAND)).toEqual([])
    }
  })

  it('方板（圆角没画）→ 角透明门红', () => {
    const square = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        squarePlate: true,
        blob: { x: 4, y: 4, w: 8, h: 12, color: [255, 255, 255] },
      }),
      BRAND,
    )
    expect(auditVerdict(square, BRAND).join('\n')).toMatch(/圆角|四角/)
  })

  it('没传 brand 或统计字段不全 → 抛错，绝不静默放行（解析失败必须非零退出）', () => {
    expect(() => auditVerdict(frameStats(synthFrame(16, { startHex: '2563eb', endHex: '2563eb', blob: null as never })), undefined as never)).toThrow(/brand/)
    // 用例名字承诺的两条路径都要真的走一遍（本轮 Minor 4）：字段不全这一支以前没测过。
    const good = frameStats(
      synthFrame(16, {
        startHex: BRAND.firstHex,
        endHex: BRAND.lastHex,
        blob: { x: 5, y: 4, w: 6, h: 12, color: [255, 255, 255] },
      }),
      BRAND,
    )
    expect(auditVerdict(good, BRAND)).toEqual([]) // 先证明底子是干净的，红只能来自下面那个字段
    for (const missing of ['plateRatio', 'inkTones', 'tailRowW'] as const) {
      expect(
        () => auditVerdict({ ...good, [missing]: undefined } as never, BRAND),
        `${missing} 缺失必须抛错，不许当成 0 放行`,
      ).toThrow(new RegExp(missing))
    }
  })

  it('assembleIco 仍是 6 帧 Vista+ 容器（帧集不增不减）', () => {
    const png = encodePngRgba(4, 4, () => [0, 0, 0, 0])
    const ico = assembleIco(SIZES.map((size) => ({ size, png })))
    expect(ico.readUInt16LE(2)).toBe(1)
    expect(ico.readUInt16LE(4)).toBe(6)
    expect(SIZES).toEqual([256, 128, 64, 48, 32, 16])
  })

  it('assembleIco 往返：解回容器的每一条 entry，PNG 都能解码且尺寸/字节数与输入一致（M2）', () => {
    // 收口评审是靠解析产物容器手工验过的（header 计数、偏移、每条目可解）；这里把那次验收
    // 变成常驻往返测试——容器错位一字节，Windows 就取到半张图，而没人会去看十六进制。
    const frames = SIZES.map((size) => ({ size, png: encodePngRgba(size, size, () => [1, 2, 3, 255]) }))
    const ico = assembleIco(frames)
    const count = ico.readUInt16LE(4)
    expect(count).toBe(frames.length)
    let cursor = 6 + 16 * count
    for (const [i, f] of frames.entries()) {
      const entry = 6 + 16 * i
      expect(ico[entry]).toBe(f.size >= 256 ? 0 : f.size) // Ico 里 256 按 0 编码，宽高同字节
      expect(ico[entry + 1]).toBe(ico[entry])
      expect(ico.readUInt32LE(entry + 8)).toBe(f.png.length)
      expect(ico.readUInt32LE(entry + 12)).toBe(cursor)
      const view = ico.subarray(cursor, cursor + f.png.length)
      expect(view.length).toBe(f.png.length)
      expect(decodePngRgba(view).width).toBe(f.size)
      expect(decodePngRgba(view).height).toBe(f.size)
      cursor += f.png.length
    }
    expect(cursor).toBe(ico.length) // 条目铺到容器末尾，没有游离字节
  })
})

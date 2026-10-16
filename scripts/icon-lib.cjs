/**
 * .ico 生成器的纯函数层（被 scripts/gen-icon.ico.js 消费，被 T2 用例守门）。
 *
 * 抽出来的理由：底板形制的几何、品牌色解析与自检判据会直接决定任务栏里的图标长什么样，
 * 而生成器本体要起 Chromium。判据必须能在不打包的前提下回归。
 *
 * Task 9（C1 修复）起为三模块：本文件管**渲染**（母版+底板模板、品牌色单源解析、ICO 容器），
 * scripts/icon-metrics.cjs 管**度量**（解 PNG 字节、逐帧统计），scripts/icon-audit.cjs 管
 * **判据**（阈值与红线）。度量/判据在这里转发，消费者只用认 icon-lib 一个门牌。
 */
const { CORNER_RATE, plateRadius, decodePngRgba, frameStats } = require('./icon-metrics.cjs')
const { AUDIT_LIMITS, auditVerdict, inkTonesMax } = require('./icon-audit.cjs')

const SIZES = [256, 128, 64, 48, 32, 16]

/**
 * 符号内缩比例按帧尺寸分档（D7 留白语义在 Task 9 改为「符号内缩」：底板本身铺满整帧，
 * outer pad 恒 0，能缩的只剩符号）。
 *
 * 档位选型实测（tasks/_task9_inset_probe.mjs → tasks/_task9_probe_out.json；本机 Playwright
 * Chromium 截 frameHtml 字节；间隙 = 符号 ink 到圆角底板边界最小连续距离；ink = alpha===255
 * 且各通道>=240；尾行 = 底部 25% 区最宽 ink 行）：
 * - 16px：4%/6%/8% 取整同为 1 px，像素全同（ink 72、间隙 2.5、尾行 2、plate 89.1%）；
 *   12%（2 px）ink 49/尾行 1，16%（3 px）ink 29/尾行 0。简报选型规则（间隙>=1 且尾行>=3
 *   取最窄）在 16px **无可行档**——尾行 >=3 只在 inset=0 时成立、而那违反间隙>=1。
 *   按规则精神（小帧优先保可辨性=ink/尾行最大）取 1 px 档，字面值定 6%（4~8% 渲染同像素，
 *   取候选表中语义档）；尾行=2 作为双形制代价记入 spec §8，判据 TAIL_MIN_16=1 兜底。
 * - 32px：8%/10% 同为 3 px（ink 287、间隙 4.5、尾行 5）——两条前提全满足，取最窄档 10%；
 *   14%（4 px）ink 248/尾行 4、18%（6 px）ink 162/尾行 1，均更差。
 * - 48/64/128/256px：**12%**。原先定 19%，理由写的是"大帧尾针站得住"，但那个理由和 16px 的
 *   判据自相矛盾 —— 19% 下 48px 尾行 = **2**，与 16px 被视为问题的值完全相同，却没人把它当缺陷。
 *   复测（tasks/_inset12_rebaseline.cjs，2026-10-16；同尺量两代交付字节 + 裸闪电基线）证明
 *   **吃掉尾针的是这一档内缩，不是底板**：把 ≥48px 从 19% 降到 12%，尾行 48px 2→5、64px 3→8、
 *   128px 7→17、256px 14→35；而 8% 档的 48/64/128 尾行 8/11/23 与**改版前裸闪电同值**。
 *   12% 是"仍留有可见留白"与"尾针对齐裸符号"之间的取舍点（12% 时 ink 552/1027/4424，
 *   间隙足够，且不触碰圆角弧）。旧 19% 记录保留在此不删，因为它是一档被实测否证的设计决定。
 */
function insetPct(size) {
  if (size <= 16) return 0.06
  if (size <= 32) return 0.1
  return 0.12
}

/** 取母版的 viewBox 与 <svg> 内部标记。 */
function parseMaster(svgText) {
  const vb = /viewBox="\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*"/.exec(svgText)
  if (!vb) throw new Error('favicon.svg 缺 viewBox，无法按帧尺寸布置底板与符号')
  const inner = svgText.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '')
  return { vb: vb.slice(1, 5).map(Number), inner }
}

/**
 * 从 design-tokens.css 解析 light `--grad-brand` 的渐变 stops（品牌色单源化，闭 I4：
 * 生成器与判据都不许再硬编 #2563eb）。解析失败必须抛错 —— gen-icon.ico.js 让非零退出，
 * 不许静默回落到常量。
 *
 * 为什么锚「selector 列表里含裸 :root 的那个块」而不是「全文第一个 :root 块」：
 * 简报说取第一个 :root 块，但实测本文件第一个 `:root {` 是 ① Primitive 色阶表（:12），
 * 里面根本没有 --grad-brand；light 的 --grad-brand 在 ② Semantic·Light 块，其选择器是
 * `:root, :root[data-theme='light'], .force-light`（:55-57）。night 块的选择器是
 * `:root[data-theme='night'], .force-night`（:99-100），`:root` 后面紧跟 `[`，按
 * 「逗号分隔后恰为 :root」即被排除。所以判据是「选择器列表含独立的 :root 项且块内有
 * --grad-brand」，取文件序第一个 —— 对 light 块唯一命中，且 night 块就算排在前面试探
 * 也不会被选中（单测钉住这条）。
 */
function parseBrandGradient(cssText) {
  const blockRe = /([^{}]+)\{([^{}]*)\}/g
  let m
  let decl = null
  while ((m = blockRe.exec(cssText))) {
    const selector = m[1].replace(/\/\*[\s\S]*?\*\//g, '')
    const hasBareRoot = /(?:^|,)\s*:root\s*(?:,|$)/.test(selector)
    const g = /(?:^|;)\s*--grad-brand\s*:\s*([^;]+)/.exec(m[2])
    if (hasBareRoot && g) {
      decl = g[1].trim()
      break
    }
  }
  if (!decl) throw new Error("design-tokens.css 里找不到 light :root 块的 --grad-brand（锚定失败=必须抛错，不许回落常量）")
  if (!decl.includes('linear-gradient(')) {
    throw new Error(`--grad-brand 不是 linear-gradient 写法：${decl.slice(0, 60)}…`)
  }
  const argsSrc = decl.slice(decl.indexOf('(') + 1, decl.lastIndexOf(')'))
  const args = []
  let depth = 0
  let cur = ''
  for (const ch of argsSrc) {
    if (ch === '(') depth++
    if (ch === ')') depth--
    if (ch === ',' && depth === 0) {
      args.push(cur.trim())
      cur = ''
    } else cur += ch
  }
  if (cur.trim()) args.push(cur.trim())
  if (/^-?\d*\.?\d+(deg|grad|rad|turn)$|^to\s/i.test(args[0])) args.shift() // 方向段（135deg / to bottom right）不是 stop，丢弃
  if (args.length < 2) throw new Error(`--grad-brand 的 stop 少于两支：${decl}`)

  // var() 名 → hex 的解析表：primitive 定义（--p-* 等）都是 `--name: #rrggbb` 一行式，
  // 全文扫一遍收进来；解析不到 hex 的 var 直接抛错（静默回落=图腾判据的起点）。
  const hexMap = new Map()
  const varRe = /--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*(?:;|\})?/g
  let vm
  while ((vm = varRe.exec(cssText))) {
    if (!hexMap.has(vm[1])) hexMap.set(vm[1], vm[2].toLowerCase())
  }

  const stops = args.map((arg) => {
    let raw = arg
    let pct = null
    const pm = /\s(-?\d*\.?\d+)%\s*$/.exec(raw)
    if (pm) {
      pct = Number(pm[1])
      raw = raw.slice(0, pm.index).trim()
    }
    let hex = null
    const vrm = /^var\(\s*(--[\w-]+)\s*\)$/.exec(raw)
    if (vrm) {
      hex = hexMap.get(vrm[1].slice(2)) // varRe 的捕获键不含 `--` 前缀，这里剥掉再查
      if (!hex || !/^#[0-9a-fA-F]{6}$/.test(hex)) {
        throw new Error(`--grad-brand 的 stop ${vrm[1]} 在 primitive 表里解析不到 6 位 hex（拿到 ${hex ?? '无'}）`)
      }
    } else if (/^#[0-9a-fA-F]{6}$/.test(raw)) {
      hex = raw.toLowerCase()
    } else {
      throw new Error(`--grad-brand 的 stop 写法不认（需要 var(--x) 或 #rrggbb，可带位置）：${raw}`)
    }
    return { hex: hex.slice(1), pct }
  })
  // 位置补全：显式位置照抄（night 中档 55%）；缺省的首/尾钉 0/100，中间等距（CSS 规范缺省）。
  // 收口成 pct 恒为 number 的数组再返回——下游（模板/判据/单测推断类型）不该见到 null。
  const finalStops = stops.map((s, i) => ({
    hex: s.hex,
    pct: s.pct ?? Math.round((i / (stops.length - 1)) * 100),
  }))

  const toRgb = (hex) => [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
  return {
    stops: finalStops,
    first: toRgb(finalStops[0].hex),
    last: toRgb(finalStops[finalStops.length - 1].hex),
    firstHex: finalStops[0].hex,
    lastHex: finalStops[finalStops.length - 1].hex,
  }
}

/**
 * 底板形制的帧模板：渐变圆角底板**铺满整帧**（outer pad=0，D4/spec §2.2 + Task 9 裁定），
 * 符号按 insetPct 分档内缩、保留母版 48:46 比例与 viewBox。
 *
 * 三条曾经的踩坑保持原样：内层高度必须**上取整**（`Math.round` 在 16/48px 挤掉顶部一行 ink，
 * Task 2 改判 2；底板形制下实测：ceil→round 让 16px 尾行 2→1、64px 尾行 3→2、ink 686→702，
 * 但剪影仍 16×16 且 G3b 由铺满整帧的 `<rect>` 决定 —— 所以**没有任何像素门守着这个 ceil**，
 * 它唯一的绊线是 frontend/test/unit/iconLib.spec.ts 里 `h === Math.ceil(w*46/48)` 那条精确等式）；
 * 外层 `<svg` 后紧跟 width/height/viewBox、xmlns 挪末尾（帧尺寸是模板对
 * 单测的唯一契约，属性顺序曾让正则永远匹配不上，Task 2 改判 1）；渐变用
 * objectBoundingBox (0,0)→(1,1)，正方形帧上等价 CSS 135deg 左上→右下。
 * Task 9 新增第四条：模板里 `svg{display:block}` —— 内联 <svg> 默认进文本流，Chromium 实测
 * 把整幅内容下移 1px 吃掉最后一行（旧 .ico 16px 剪影 16×15、底板角样本全瞎的真实根因；
 * Task 2 曾把它归因给 ceil/round——归因错了，display:block 后 16px 剪影=16×16）。
 *
 * 符号反白用 `svg.plate-symbol *{fill:#ffffff !important}`：
 * - 比「后插入同特异性规则靠层叠序取胜」更稳（不依赖 <style> 相对顺序）；
 * - 比「只钉 .b 类」更通用 —— 旧模糊母版（负对照素材）的填充写在各元素 style="fill:#863bff"
 *   内联属性上，作者 !important 声明按 CSS 层叠优先级压过内联 style，所以同一模板能把
 *   任何母版画成白色符号，模糊回归才会以「反白区多色阶」的形态显出来（G1 判据的前提）。
 */
function frameHtml(svgText, size, brand, opts = {}) {
  if (!brand || !Array.isArray(brand.stops) || brand.stops.length < 2) {
    throw new Error('frameHtml 需要 parseBrandGradient 产出的 brand（品牌色单源，不许硬编渐变）')
  }
  const { vb, inner } = parseMaster(svgText)
  const inset = Number.isInteger(opts.insetPx) ? opts.insetPx : Math.round(size * insetPct(size))
  const r = plateRadius(size)
  const w = size - 2 * inset
  const h = Math.ceil((w * vb[3]) / vb[2])
  const y = Math.round((size - h) / 2)
  const gradStops = brand.stops
    .map((s) => `<stop offset="${s.pct}%" stop-color="#${s.hex}"/>`)
    .join('')
  return (
    `<!doctype html><html><head><style>html,body{margin:0;padding:0;background:transparent}svg{display:block}</style></head><body>` +
    `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">` +
    `<defs><linearGradient id="plate" gradientUnits="objectBoundingBox" x1="0" y1="0" x2="1" y2="1">${gradStops}</linearGradient></defs>` +
    `<rect x="0" y="0" width="${size}" height="${size}" rx="${r}" fill="url(#plate)"/>` +
    `<style>svg.plate-symbol *{fill:#ffffff !important}</style>` +
    `<svg class="plate-symbol" x="${inset}" y="${y}" width="${w}" height="${h}" viewBox="${vb.join(' ')}">${inner}</svg>` +
    `</svg></body></html>`
  )
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

module.exports = {
  SIZES,
  CORNER_RATE,
  plateRadius,
  insetPct,
  parseMaster,
  parseBrandGradient,
  frameHtml,
  assembleIco,
  // 度量与判据的转发（判据阈值表也在门牌这一层可见，单测/探针不引第二路径）
  decodePngRgba,
  frameStats,
  auditVerdict,
  AUDIT_LIMITS,
  inkTonesMax,
}

/**
 * .ico 帧的字节度量层（纯函数，不起浏览器）：解 Chromium 截图 PNG + 底板形制的统计。
 * 被 scripts/icon-lib.cjs 转发、scripts/gen-icon.ico.js 消费；单测守门见
 * frontend/test/unit/iconLib.spec.ts。
 */
const zlib = require('zlib')
const { AUDIT_LIMITS, INK_FLOOR } = require('./icon-audit.cjs')

/** 底板圆角率 22%（spec §2.2）：几何公式在渲染、度量、测试三处同源，只留这一份。 */
const CORNER_RATE = 0.22
function plateRadius(size) {
  return Math.round(CORNER_RATE * size)
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

/**
 * 底板形制的全量字节统计。口径（全部基于**要写进 .ico 的截图字节**，不是页面像素）：
 * - tones/dominant：alpha===255 的实心像素（旧口径原样保留，只做日志，不再做判据——
 *   渐变底板天然数百色阶，旧「<=2」会把 spec 规定的形制判死，见 Task 9 简报）。
 *   为什么色阶必须卡 ==255 而不是 >=240 alpha：旧实测（单色母版 frameHtml 通路）16px 帧
 *   ==255 → 1 个 vs alpha>=240 → 4 个，多出来的是抗锯齿预乘残差。
 * - ink（符号反白区）：alpha===255 且 R/G/B 全部 >= INK_FLOOR(240)。硬边白符号在蓝底上
 *   只有纯白进这个域；底板蓝渐变（通道 29..99）不进；白蓝混合的糊边按色阶数暴露模糊回归。
 * - startPixels/endPixels：实心像素里与 brand.first / brand.last 的切比雪夫距离
 *   <= AUDIT_LIMITS.STOP_TOL 的个数（G2 端点门的度量基础）。
 * - plateRatio：alpha===255 占全帧比例（G3a）。
 * - cornerTransp：四角各取以角点为圆心、半径 plateRadius/2 的圆盘样本（连续像素中心欧氏距离
 *   <= r/2），样本中 alpha<128（AA 半覆盖以下，理由见下面角样本处的注释）的比例，
 *   取四角最小值（G3c）。
 * - tailRowW：底部 25% 行区 [floor(0.75*size), size) 内，单行 ink 像素 max(x)-min(x)+1 的最大值
 *   （spec §1.2 尾针指标，G4b）。
 * - bboxW/bboxH：有墨口径 alpha>=8 的剪影框（G3b 要求它 === size）。
 */
function frameStats(buf, brand) {
  const { width, height, data } = decodePngRgba(buf)
  const size = width
  const tol = AUDIT_LIMITS.STOP_TOL
  const toneCount = new Map()
  const inkToneCount = new Map()
  let inkCount = 0
  let opaque = 0
  let startPixels = 0
  let endPixels = 0
  let minX = size, maxX = -1, minY = height, maxY = -1
  let inkMinX = size, inkMaxX = -1, inkMinY = height, inkMaxY = -1
  const tailRows = new Map() // y -> [minX, maxX]，底部 25% 行的 ink 分布
  const tailStart = Math.floor(height * 0.75)
  const r = plateRadius(size)
  const cornerR2 = (r / 2) * (r / 2)
  // 角样本按**连续像素中心**距离判：顶点在连续坐标 (0,0)/(size,0)/…，像素中心 (x+0.5, y+0.5)。
  // SVG 圆角就定义在连续坐标上；用整数坐标会把「弧恰好扫过的像素」在合成样本与真截图之间
  // 判反。透明口径 alpha<128（AA 半覆盖以下）：圆角弧离角点 0.414r，r/2 圆盘的外半区正好骑在
  // 弧的抗锯齿带上（alpha 连续爬升），alpha<8 会把 16px 交付帧本身判成 0% 透明（实测）——
  // 方板（该门的靶子）样本 alpha=255，两种口径都红，判别力不受口径放宽影响。
  const cornerV = [
    [0, 0],
    [size, 0],
    [0, height],
    [size, height],
  ]
  const cornerTotals = [0, 0, 0, 0]
  const cornerClear = [0, 0, 0, 0]
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4
      const a = data[i + 3]
      if (a === 255) {
        const key = `${data[i]},${data[i + 1]},${data[i + 2]}`
        toneCount.set(key, (toneCount.get(key) ?? 0) + 1)
        opaque++
        if (data[i] >= INK_FLOOR && data[i + 1] >= INK_FLOOR && data[i + 2] >= INK_FLOOR) {
          inkToneCount.set(key, (inkToneCount.get(key) ?? 0) + 1)
          inkCount++
          if (x < inkMinX) inkMinX = x
          if (x > inkMaxX) inkMaxX = x
          if (y < inkMinY) inkMinY = y
          if (y > inkMaxY) inkMaxY = y
          if (y >= tailStart) {
            const row = tailRows.get(y)
            if (row) {
              if (x < row[0]) row[0] = x
              if (x > row[1]) row[1] = x
            } else tailRows.set(y, [x, x])
          }
        }
        if (brand) {
          const d0 = Math.max(Math.abs(data[i] - brand.first[0]), Math.abs(data[i + 1] - brand.first[1]), Math.abs(data[i + 2] - brand.first[2]))
          const d1 = Math.max(Math.abs(data[i] - brand.last[0]), Math.abs(data[i + 1] - brand.last[1]), Math.abs(data[i + 2] - brand.last[2]))
          if (d0 <= tol) startPixels++
          if (d1 <= tol) endPixels++
        }
      }
      if (a < 8) continue
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  }
  for (let c = 0; c < 4; c++) {
    const [vx, vy] = cornerV[c]
    const rad = r / 2
    const xFrom = Math.max(0, Math.floor(vx - rad - 1))
    const xTo = Math.min(size - 1, Math.ceil(vx + rad))
    const yFrom = Math.max(0, Math.floor(vy - rad - 1))
    const yTo = Math.min(height - 1, Math.ceil(vy + rad))
    for (let y = yFrom; y <= yTo; y++) {
      for (let x = xFrom; x <= xTo; x++) {
        const dx = x + 0.5 - vx
        const dy = y + 0.5 - vy
        if (dx * dx + dy * dy > cornerR2) continue
        cornerTotals[c]++
        if (data[(y * size + x) * 4 + 3] < 128) cornerClear[c]++
      }
    }
  }
  let cornerTransp = 1
  for (let c = 0; c < 4; c++) {
    if (cornerTotals[c] > 0) cornerTransp = Math.min(cornerTransp, cornerClear[c] / cornerTotals[c])
  }
  let tailRowW = 0
  for (const [rowMinX, rowMaxX] of tailRows.values()) {
    tailRowW = Math.max(tailRowW, rowMaxX - rowMinX + 1)
  }
  // 平票取栅格序先出现的（`>` 严格比较 + Map 插入序）——判据与日志必须可复现。
  let dominant = ''
  let dominantCount = 0
  for (const [tone, count] of toneCount) {
    if (count > dominantCount) {
      dominant = tone
      dominantCount = count
    }
  }
  return {
    size,
    tones: toneCount.size,
    dominant,
    bboxW: maxX < 0 ? 0 : maxX - minX + 1,
    bboxH: maxY < 0 ? 0 : maxY - minY + 1,
    inkTones: inkToneCount.size,
    inkCount,
    inkBboxW: inkMaxX < 0 ? 0 : inkMaxX - inkMinX + 1,
    inkBboxH: inkMaxY < 0 ? 0 : inkMaxY - inkMinY + 1,
    plateRatio: opaque / (size * height),
    cornerTransp,
    tailRowW,
    startPixels: brand ? startPixels : null,
    endPixels: brand ? endPixels : null,
  }
}

module.exports = { CORNER_RATE, plateRadius, decodePngRgba, frameStats }

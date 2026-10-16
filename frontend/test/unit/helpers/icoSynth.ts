/**
 * 单测共用的**合成字节**助手：造 8bit RGBA 非隔行 PNG（含 CRC），并按底板形制的几何合成整帧，
 * 供 iconLib.spec.ts 的负对照/正对照与 assembleIco 往返测试喂给
 * `decodePngRgba` / `frameStats` / `auditVerdict`（判据吃的就是这些字节）。
 *
 * 为什么在 test/unit/helpers/ 而不是 scripts/：这是**测试夹具**，不是生产构建脚本的一部分
 * （生成器只会被 Playwright 截真图，从不自编 PNG）。放生产模块里等于给构建链加一条没人走的代码
 * 路径；放这里则同时受 tsconfig.unit.json 与 `vue-tsc -b` 的类型检查。
 *
 * 抽成共享文件的直接原因：CLAUDE.md 的「单文件 ≤600 行」——判据用例本身要留在 iconLib.spec.ts
 * 里读，夹具再留一份就超限；复制一份到第二个文件更糟（同一件事两个家，正是本分支在杀的病）。
 */
import { deflateSync } from 'node:zlib'
import { CORNER_RATE } from '../../../../scripts/icon-lib.cjs'

/** PNG 单行 filter 表用的 CRC32 表（惰性建一次）。 */
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

/** 造一张 8bit RGBA 非隔行 PNG，用于验证解码/统计确实读的是字节。 */
export function encodePngRgba(width: number, height: number, px: (x: number, y: number) => number[]) {
  const raw = Buffer.alloc(height * (1 + width * 4))
  let p = 0
  for (let y = 0; y < height; y++) {
    raw[p++] = 0 // filter: None
    for (let x = 0; x < width; x++) {
      const [r, g, b, a] = px(x, y)
      raw[p++] = r
      raw[p++] = g
      raw[p++] = b
      raw[p++] = a
    }
  }
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4)
    len.writeUInt32BE(data.length, 0)
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(crc32(body) >>> 0, 0)
    return Buffer.concat([len, body, crc])
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 6
  ihdr[10] = 0
  ihdr[11] = 0
  ihdr[12] = 0
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
}

/**
 * 合成一张「底板形制」帧的字节（负对照与正对照都从这里出，不起浏览器）。
 * 底板 = 圆角矩形（半径 = plateRadius 同款公式），像素色按 CSS 135deg 等价式
 * t=(x+y)/(2*size) 线性插值两支 stop；blob = 符号区，支持「多色阶柔化」模拟模糊回归。
 */
export interface SynthCfg {
  startHex?: string // 底板渐变起点；缺省 = 不画底板（裸符号帧）
  endHex?: string
  squarePlate?: boolean // 画成方板：四角不剪 → G3 角透明门该红
  plateMargin?: number // 底板整圈内缩 N px（画了、但没铺满整帧——G3b 的靶，见 I3/方向用例）
  blob?: { x: number; y: number; w: number; h: number; color?: [number, number, number]; toneCells?: boolean; tones?: number }
  blobColor?: [number, number, number] // 无 plate 时的主体色（裸闪电对照 = 品牌蓝）
  body?: { x: number; y: number; w: number; h: number } // 无底板时画的那块符号
}

export function synthFrame(size: number, cfg: SynthCfg) {
  const m = cfg.plateMargin ?? 0
  const e = size - 2 * m // 内缩后的底板边长（plateMargin 缺省时就是整帧）
  const rIn = Math.round(CORNER_RATE * e)
  const start = cfg.startHex ? hexToRgb(cfg.startHex) : null
  const end = cfg.endHex ? hexToRgb(cfg.endHex) : null
  return encodePngRgba(size, size, (x, y) => {
    if (start && end) {
      if (x < m || y < m || x >= size - m || y >= size - m) return [0, 0, 0, 0]
      const lx = x - m
      const ly = y - m
      const inCorner =
        (lx < rIn && ly < rIn) ||
        (lx >= e - rIn && ly < rIn) ||
        (lx < rIn && ly >= e - rIn) ||
        (lx >= e - rIn && ly >= e - rIn)
      const cx = lx < rIn ? rIn : e - rIn
      const cy = ly < rIn ? rIn : e - rIn
      // 连续像素中心判圆角（SVG 的 rx 就定义在连续坐标上；整数口径会把弧扫过的像素判反）
      if (!cfg.squarePlate && inCorner && Math.hypot(lx + 0.5 - cx, ly + 0.5 - cy) > rIn) return [0, 0, 0, 0]
      const t = Math.min(1, (lx + ly) / (2 * e))
      const c = start.map((v, i) => Math.round(v + (end[i] - v) * t))
      const b = cfg.blob!
      if (b && x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h) {
        if (b.tones) {
          // 生成**恰好 N 个互异的近白色阶**（N ≤ 64，且符号面积 ≥ N）：用来把该帧真模糊的实测值
          // 造进合成字节，而不是只造一个必然红的 72 阶大块（见 G1 逐帧阈值表用例）。
          // 边界是 Task 11 量出来的（原注释写 N<=16，而唯一调用方传的却是 8/11/15/17/24）：
          //   r=240+i%4 ≤ 243、g=240+⌊i/4⌋ ≤ 255 在 i<64 内成立 ⇒ N ≤ 64 时色阶数恰等于 N 且
          //   全部满足 ink 口径（各通道 ≥240）；N=65 起 g 算出 256、写进 Buffer 截断成 0，那一个
          //   色阶掉出 ink 口径，「N 个近白色阶」就与手里的字节分家了。
          const i = ((y - b.y) * b.w + (x - b.x)) % b.tones
          return [240 + (i % 4), 240 + Math.floor(i / 4), 255, 255]
        }
        if (b.toneCells) {
          // 每个像素一个不同的「近白」三元组（alpha=255、各通道 ≥240）——模糊符号的字节指纹；
          // 实测对照与阈值出处见 icon-audit.cjs G1 注释
          const i = (y - b.y) * b.w + (x - b.x)
          return [240 + (i % 16), 240 + (Math.floor(i / 16) % 16), 255, 255]
        }
        return [...(b.color ?? [255, 255, 255]), 255]
      }
      return [...c, 255]
    }
    const body = cfg.body
    if (body && x >= body.x && x < body.x + body.w && y >= body.y && y < body.y + body.h) {
      return [...(cfg.blobColor ?? hexToRgb('2563eb')), 255]
    }
    return [0, 0, 0, 0]
  })
}

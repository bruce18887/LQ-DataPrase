/**
 * 字号归档 codemod：把散落的 `font-size: NNpx` / `fontSize: NN` 归到 9 档 Type Scale。
 *
 * 折叠规则是**就近归档、平手取小**：11.5→11、12.5→12、13.5→13、15→14、17→16、20→18、
 * 24→22、28→26。超过顶档（>32）的大字**不自动改**，只列出来等人工定档 —— 仪表板 KPI
 * 那类一次性的 40/48/96px 折到 32 会把大数字压扁，那是改设计不是归档。
 *
 * 用法：
 *   node scripts/type_scale_migrate.mjs                      # 干跑，只报统计
 *   node scripts/type_scale_migrate.mjs --write              # 实际改写
 *   node scripts/type_scale_migrate.mjs --write --scope pages/data   # 分批
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'frontend', 'src')
const args = process.argv.slice(2)
const WRITE = args.includes('--write')
const scopeAt = args.indexOf('--scope')
const SCOPE = scopeAt >= 0 ? args[scopeAt + 1] : null

/** 9 档 Type Scale：px → 档位名。CSS 里是 --p-fs-<name>，TS 里是 chartFontSize.<name>。
 *  名字必须是合法标识符（不能用 2xl/3xl —— `obj.2xl` 是语法错误）。 */
export const SCALE = [
  [11, 'micro'],
  [12, 'dense'],
  [13, 'small'],
  [14, 'base'],
  [16, 'lead'],
  [18, 'title'],
  [22, 'headline'],
  [26, 'display'],
  [32, 'hero'],
]
const TOP = SCALE[SCALE.length - 1][0]
const ON_SCALE = new Set(SCALE.map(([px]) => px))

/** 就近归档、平手取小 */
export function fold(px) {
  let best = null
  for (const [size, name] of SCALE) {
    const d = Math.abs(size - px)
    if (best === null || d < best.d || (d === best.d && size < best.size)) best = { size, name, d }
  }
  return best
}

function walk(dir, acc = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(p, acc)
    else if (/\.(vue|css|ts)$/.test(entry.name)) acc.push(p)
  }
  return acc
}

const files = walk(SRC).filter((f) => (SCOPE ? path.relative(SRC, f).startsWith(SCOPE) : true))
const stats = { css: 0, camel: 0, quoted: 0, oversized: [], folds: {}, touched: 0 }

const note = (px, name) => {
  if (!ON_SCALE.has(px)) stats.folds[`${px}→${name}`] = (stats.folds[`${px}→${name}`] || 0) + 1
}

for (const file of files) {
  const original = fs.readFileSync(file, 'utf8')
  let text = original
  let usesChartFontSize = false

  // ① CSS 声明 / 模板内联 style：font-size: 12px
  text = text.replace(/font-size:\s*(\d+(?:\.\d+)?)px/g, (m, raw) => {
    const px = Number(raw)
    if (px > TOP) {
      stats.oversized.push({ file: path.relative(SRC, file), px, kind: 'css' })
      return m
    }
    const { name } = fold(px)
    stats.css += 1
    note(px, name)
    return `font-size: var(--p-fs-${name})`
  })

  // ② 带引号的 px 字符串（Vue 内联 style 对象）：fontSize: '10px'
  text = text.replace(/fontSize:\s*(["'])(\d+(?:\.\d+)?)px\1/g, (m, q, raw) => {
    const px = Number(raw)
    if (px > TOP) {
      stats.oversized.push({ file: path.relative(SRC, file), px, kind: 'quoted' })
      return m
    }
    const { name } = fold(px)
    stats.quoted += 1
    note(px, name)
    return `fontSize: ${q}var(--p-fs-${name})${q}`
  })

  // ③ ECharts 裸数值：fontSize: 12 —— 只吃数字，所以引 chartFontSize 常量
  text = text.replace(/fontSize:\s*(\d+(?:\.\d+)?)(?![\w.%])/g, (m, raw) => {
    const px = Number(raw)
    if (px > TOP) {
      stats.oversized.push({ file: path.relative(SRC, file), px, kind: 'camel' })
      return m
    }
    const { name } = fold(px)
    stats.camel += 1
    note(px, name)
    usesChartFontSize = true
    return `fontSize: chartFontSize.${name}`
  })

  // 用到 chartFontSize 的文件补 import（相对路径按目录深度算，已有则不重复加）
  if (usesChartFontSize && !/theme\/typography/.test(text)) {
    let rel = path.relative(path.dirname(file), path.join(SRC, 'theme', 'typography'))
      .split(path.sep).join('/')
    if (!rel.startsWith('.')) rel = './' + rel
    const firstImport = text.match(/^import[ \t]/m)
    const line = `import { chartFontSize } from '${rel}'\n`
    text = firstImport
      ? text.slice(0, firstImport.index) + line + text.slice(firstImport.index)
      : line + text
  }

  if (text !== original) {
    stats.touched += 1
    if (WRITE) fs.writeFileSync(file, text)
  }
}

console.log(`${WRITE ? '已改写' : '干跑'} ${stats.touched} 个文件`)
console.log(`  CSS font-size: ${stats.css} ｜ 引号 px: ${stats.quoted} ｜ ECharts 裸数值: ${stats.camel}`)
console.log('  折叠明细:', JSON.stringify(stats.folds))
console.log(`  >${TOP}px 待人工定档: ${stats.oversized.length}`)
for (const o of stats.oversized) console.log(`    ${o.file}  ${o.px}px (${o.kind})`)

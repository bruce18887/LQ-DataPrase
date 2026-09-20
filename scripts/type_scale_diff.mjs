/**
 * 字号归档差量核对：把 before/after 两份计算值快照比成一张「元素 → 旧值 → 新值」表，
 * 并按折叠规则判定每一行是**预期内**还是**回归**。
 *
 * 判据（这是这一步的"改对没改对"）：
 *   - 旧值已在 9 档上 → 新值必须**完全相同**（归档不该动已在档位上的元素）
 *   - 旧值 off-scale → 新值必须等于「就近归档、平手取小」的折叠结果
 *   - 新值出现档位表以外的尺寸 → 直接判失败
 *
 * 用法：node scripts/type_scale_diff.mjs [before.json] [after.json]
 *       默认比 test/type-snapshot/before.json 与 after.json；退出码非 0 = 有回归。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const SNAP = path.join(ROOT, 'test', 'type-snapshot')
const BEFORE = process.argv[2] || path.join(SNAP, 'before.json')
const AFTER = process.argv[3] || path.join(SNAP, 'after.json')

const SCALE = [
  { px: 11, name: 'micro' }, { px: 12, name: 'dense' }, { px: 13, name: 'small' },
  { px: 14, name: 'base' }, { px: 16, name: 'lead' }, { px: 18, name: 'title' },
  { px: 22, name: 'headline' }, { px: 26, name: 'display' }, { px: 32, name: 'hero' },
]
const ON_SCALE = new Set(SCALE.map((s) => s.px))
const TOP = Math.max(...ON_SCALE)

function fold(px) {
  let best = null
  for (const s of SCALE) {
    const d = Math.abs(s.px - px)
    if (!best || d < best.d || (d === best.d && s.px < best.px)) best = { ...s, d }
  }
  return best
}
const num = (size) => (/^\d+(\.\d+)?px$/.test(size) ? parseFloat(size) : null)
const byPx = (a, b) => (num(a) ?? 0) - (num(b) ?? 0)
const groupsOf = (file) => JSON.parse(fs.readFileSync(file, 'utf8')).groups

const before = groupsOf(BEFORE)
const after = groupsOf(AFTER)

let same = 0, expected = 0
const regressions = []
const onlyOneSide = []

for (const group of new Set([...Object.keys(before), ...Object.keys(after)])) {
  const b = before[group] || {}
  const a = after[group] || {}
  for (const p of new Set([...Object.keys(b), ...Object.keys(a)])) {
    const bs = b[p]?.sizes
    const as = a[p]?.sizes
    if (!bs || !as) {
      onlyOneSide.push(`${group}  ${p}  ${bs ? '仅 before' : '仅 after'}`)
      continue
    }
    const bSizes = bs, aSizes = as
    const removed = Object.keys(bSizes).filter((s) => !(s in aSizes)).sort(byPx)
    const added = Object.keys(aSizes).filter((s) => !(s in bSizes)).sort(byPx)
    if (!removed.length && !added.length) { same += 1; continue }

    // 折叠是**多对一**的（9 和 10 都归 micro 11），所以不能按序号配对，只能按集合判：
    // 每个消失的旧尺寸，必须正好是它自己的归档结果；每个新增尺寸，必须是某个旧尺寸归档来的。
    const expectedAdds = new Map()
    for (const s of removed) {
      const bp = num(s)
      const where = `${group}  ${p}  ${s}  「${b[p].sample}」`
      if (bp === null) { regressions.push(where + ' (非纯数值尺寸)'); continue }
      if (bp > TOP) { regressions.push(where + ' 消失，顶档以上大字应保持不动'); continue }
      if (ON_SCALE.has(bp)) { regressions.push(where + ' 已在档位上的尺寸消失/被改动'); continue }
      const want = fold(bp).px
      expectedAdds.set(`${want}px`, (expectedAdds.get(`${want}px`) || 0) + 1)
      // 归到的那一档必须确实存在于 after（可能本来就有、也可能是新增的）
      if (`${want}px` in aSizes) {
        expected += 1
      } else {
        regressions.push(`${where} 应折叠成 ${want}px，after 里没有这一档`)
      }
    }
    for (const s of added) {
      if (!expectedAdds.has(s) && !(s in bSizes)) {
        regressions.push(`${group}  ${p}  多出未预期的尺寸 ${s}  「${b[p]?.sample ?? ''}」`)
      }
    }
  }
}

console.log(`比对：${path.basename(BEFORE)} → ${path.basename(AFTER)}`)
console.log(`  未变化            : ${same}`)
console.log(`  预期内折叠          : ${expected}`)
console.log(`  只存在一侧（页面态差异）: ${onlyOneSide.length}`)
console.log(`  回归/需解释        : ${regressions.length}`)
for (const r of regressions.slice(0, 40)) console.log('   ! ' + r)
if (regressions.length > 40) console.log(`   …另有 ${regressions.length - 40} 条`)
if (onlyOneSide.length) console.log('   （单侧示例）' + onlyOneSide.slice(0, 5).join(' | '))
process.exit(regressions.length ? 1 : 0)

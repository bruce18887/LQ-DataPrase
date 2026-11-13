#!/usr/bin/env node
/**
 * 批1 台账用：数「被改写的 e2e 用例条数」。
 *
 * 口径（写死在脚本里，别凭印象报数）：把每个 e2e spec 文件按**顶层** `test(` / `test.only(` /
 * `test.skip(` / `test.describe(` 切成块，用**用例全名**（describe 前缀 + test 标题原文）当身份，
 * 对比 master 版与工作区版：
 *   added    = 只在新版出现
 *   modified = 两版都有、块体正文不同
 *   deleted  = 只在旧版出现
 * 判据异源：这个数只是台账，不进任何断言。
 */
import { execFileSync } from 'node:child_process'
import path from 'node:path'

const ROOT = path.resolve(import.meta.dirname, '..')
const git = (...a) => execFileSync('git', a, { cwd: ROOT, encoding: 'utf-8', maxBuffer: 64 << 20 })

const files = git('diff', '--name-only', 'master', '--', 'frontend/e2e')
  .split('\n')
  .filter((f) => /\.spec\.ts$/.test(f))

function readAt(rev, file) {
  try {
    return git('show', `${rev}:${file}`)
  } catch {
    return ''
  }
}

/** 切顶层块：返回 [{ name, body }]，name = describe 链 + test 标题拼接 */
function parseCases(src) {
  const lines = src.split('\n')
  const cases = []
  const describeStack = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const d = line.match(/^\s*test\.describe\(\s*(['"`])(.*?)\1/)
    if (d) {
      describeStack.push({ title: d[2], indent: line.match(/^\s*/)[0].length })
      continue
    }
    // 出栈：本行缩进 ≤ 栈顶缩进说明那个 describe 结束了
    while (
      describeStack.length &&
      line.match(/^(\s*)[})\]]/) &&
      line.match(/^\s*/)[0].length <= describeStack[describeStack.length - 1].indent
    ) {
      describeStack.pop()
    }
    const t = line.match(/^\s*test(?:\.(?:only|skip|fixme|fail|slow))?\(\s*(['"`])(.*?)\1/)
    if (!t) continue
    const indent = line.match(/^\s*/)[0].length
    const kind = (line.match(/test\.(only|skip|fixme|fail|slow)/) || [, 'run'])[1]
    let end = i
    let depth = 0
    for (let j = i; j < lines.length; j++) {
      for (const ch of lines[j]) {
        if (ch === '{' || ch === '(' || ch === '[') depth++
        else if (ch === '}' || ch === ')' || ch === ']') depth--
      }
      end = j
      if (depth <= 0 && j > i) break
      if (depth <= 0 && j === i && /\}\s*\)\s*(?:\.\w+\([^)]*\)\s*)*;?\s*$/.test(lines[j])) break
    }
    cases.push({
      name: [...describeStack.map((s) => s.title), t[2]].join(' › '),
      kind,
      body: lines.slice(i, end + 1).join('\n').trim(),
    })
    i = end
  }
  return cases
}

const rows = []
for (const file of files) {
  const oldCases = parseCases(readAt('master', file))
  const newCases = parseCases(readAt('HEAD', file))
  const oldMap = new Map(oldCases.map((c) => [c.name, c]))
  const newMap = new Map(newCases.map((c) => [c.name, c]))
  let added = 0
  let modified = 0
  let deleted = 0
  const names = { added: [], modified: [], deleted: [] }
  for (const [name, c] of newMap) {
    const o = oldMap.get(name)
    if (!o) {
      added++
      names.added.push(name)
    } else if (o.body !== c.body) {
      modified++
      names.modified.push(name)
    }
  }
  for (const name of oldMap.keys()) {
    if (!newMap.has(name)) {
      deleted++
      names.deleted.push(name)
    }
  }
  rows.push({ file: file.replace('frontend/e2e/', ''), total: newMap.size, added, modified, deleted, names })
}

let T = { total: 0, added: 0, modified: 0, deleted: 0 }
for (const r of rows) {
  console.log(
    `${r.file.padEnd(48)} 用例 ${String(r.total).padStart(3)}  +${r.added}  ~${r.modified}  -${r.deleted}`,
  )
  T.total += r.total
  T.added += r.added
  T.modified += r.modified
  T.deleted += r.deleted
}
console.log(`\n合计：现有用例 ${T.total} 条（+新增 ${T.added}、~改写 ${T.modified}、-删除 ${T.deleted}）`)
console.log('\n--- 改写明细 ---')
for (const r of rows) {
  if (!r.names.modified.length && !r.names.added.length && !r.names.deleted.length) continue
  console.log(`\n[${r.file}]`)
  for (const n of r.names.added) console.log(`  + ${n}`)
  for (const n of r.names.modified) console.log(`  ~ ${n}`)
  for (const n of r.names.deleted) console.log(`  - ${n}`)
}

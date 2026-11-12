#!/usr/bin/env node
/**
 * intro-check — 产品介绍书（docs/intro/，VitePress 工程）维护期防漂移检查。
 *
 * 用法：node scripts/intro/check.mjs
 * 判据（任一失败 exit 1）：
 *   1. public/assets 与 data.ts 的 SHOTS 引用闭环（无缺失、无孤儿）；
 *   2. 版本同源：config.mts 从 frontend/package.json 读版本；除版本历程章外不得硬编码当前版本号；
 *   3. config.mts sidebar/nav 的每个 link 都有对应 md 文件；
 *   4. theme/components 目录与 theme/index.ts 注册闭环；
 *   5. 红线扫描：真实料号 / 外迁兄弟工程名 / 演示凭据字面量 / 私有样例名不得出现；
 *   6. 快速上手保留服务器形态访问网址。
 * 维护流程与触发时机见 docs/superpowers/specs/2026-11-12-intro-booklet-design.md 与 CLAUDE.md。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const INTRO = path.join(ROOT, 'docs', 'intro')
const fails = []
const ok = (cond, msg) => { if (!cond) fails.push(msg) }
const read = (p) => fs.readFileSync(p, 'utf8')
const walk = (dir, exts) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
  const full = path.join(dir, e.name)
  if (e.isDirectory()) return e.name === 'node_modules' || e.name === 'dist' || e.name === 'cache' ? [] : walk(full, exts)
  return exts.includes(path.extname(e.name)) ? [full] : []
})

// 1. assets 闭环
const data = read(path.join(INTRO, '.vitepress', 'theme', 'data.ts'))
const refs = [...data.matchAll(/src: '\/assets\/([^']+)'/g)].map((m) => m[1])
const onDisk = fs.readdirSync(path.join(INTRO, 'public', 'assets'))
refs.forEach((r) => ok(onDisk.includes(r), `引用了不存在的截图 public/assets/${r}`))
onDisk.forEach((f) => ok(refs.includes(f), `孤儿截图未被引用 public/assets/${f}`))

// 2. 版本同源
const cfg = read(path.join(INTRO, '.vitepress', 'config.mts'))
ok(/readFileSync\(.*package\.json/.test(cfg), 'config.mts 未从 frontend/package.json 读版本')
const pkg = JSON.parse(read(path.join(ROOT, 'frontend', 'package.json')))
const hard = walk(INTRO, ['.md', '.ts', '.mts', '.vue'])
  .filter((f) => !f.endsWith('11-versions.md'))
  .filter((f) => read(f).includes('v' + pkg.version))
ok(hard.length === 0, `当前版本号硬编码于：${hard.map((f) => path.relative(INTRO, f)).join(', ')}（应走 config 注入）`)

// 3. 导航链接闭环
const links = [...cfg.matchAll(/link: '([^']+)'/g)].map((m) => m[1])
links.forEach((l) => {
  const rel = l === '/' ? 'index.md' : l.replace(/^\//, '') + '.md'
  ok(fs.existsSync(path.join(INTRO, rel)), `导航 link ${l} 无对应文件 ${rel}`)
})

// 4. 组件注册闭环
const compDir = path.join(INTRO, '.vitepress', 'theme', 'components')
const comps = fs.readdirSync(compDir).filter((f) => f.endsWith('.vue')).map((f) => f.replace(/\.vue$/, ''))
const theme = read(path.join(INTRO, '.vitepress', 'theme', 'index.ts'))
comps.forEach((c) => ok(theme.includes(`components/${c}.vue`) || theme.includes(`/${c}'`) || new RegExp(`\\b${c}\\b`).test(theme), `组件 ${c} 未在 theme/index.ts 注册`))

// 5. 红线扫描
const forbidden = [
  [/BPC\d{4,}|AFA\d{6,}|CP0\d{3}\.\d+/i, '真实料号'],
  [/ExcelAddin|LightVBA|SFTP Searcher/i, '外迁兄弟工程名'],
  [/admin123|user123|Demo12345|demo123/, '演示凭据字面量'],
  [/Trim_Weight|Site2\.csv/i, '私有样例文件名'],
]
const sources = walk(INTRO, ['.md', '.ts', '.mts', '.vue'])
for (const [re, label] of forbidden) {
  const hit = sources.filter((f) => re.test(read(f)))
  ok(hit.length === 0, `红线命中（${label}）：${hit.map((f) => path.relative(INTRO, f)).join(', ')}`)
}

// 6. 服务器形态入口
ok(read(path.join(INTRO, 'guide', '02-quickstart.md')).includes('https://125.69.67.169:18124'), '快速上手缺服务器形态访问网址')

if (fails.length) {
  console.error(`INTRO-CHECK FAIL (${fails.length})`)
  fails.forEach((f) => console.error(' - ' + f))
  process.exit(1)
}
console.log(`INTRO-CHECK PASS · 截图 ${refs.length} · 导航 ${links.length} · 组件 ${comps.length} · 源文件 ${sources.length} · 版本 v${pkg.version} 同源`)
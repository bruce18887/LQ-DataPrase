#!/usr/bin/env node
/**
 * intro-check — 产品介绍书（docs/intro/）维护期防漂移检查。
 *
 * 用法：node scripts/intro/check.mjs
 * 判据（任一失败 exit 1）：
 *   1. 引用的 assets 全部存在，且 assets 目录无孤儿文件；
 *   2. 版本徽标 / 封面版本芯片与 frontend/package.json 同源；
 *   3. 目录锚点全部落到真实 section id；
 *   4. 热点按钮都带 data-title/data-text；截图 figure 与 img 一一对应；
 *   5. 红线扫描：真实料号 / 外迁兄弟工程名 / 演示凭据字面量 / 私有样例名不得出现；
 *   6. 快速上手保留服务器形态访问网址提示。
 * 维护流程与触发时机见 docs/superpowers/specs/2026-11-12-intro-booklet-design.md。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const INTRO = path.join(ROOT, 'docs', 'intro')
const html = fs.readFileSync(path.join(INTRO, 'index.html'), 'utf8')
const fails = []
const ok = (cond, msg) => { if (!cond) fails.push(msg) }

// 1. assets 引用闭环
const refs = [...html.matchAll(/src="assets\/([^"]+)"/g)].map((m) => m[1])
const onDisk = fs.readdirSync(path.join(INTRO, 'assets'))
refs.forEach((r) => ok(onDisk.includes(r), `引用了不存在的截图 assets/${r}`))
onDisk.forEach((f) => ok(refs.includes(f), `孤儿截图未被引用 assets/${f}`))

// 2. 版本同源
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'frontend', 'package.json'), 'utf8'))
const badge = html.match(/class="ver-badge">v([^<]+)</)
ok(badge && badge[1] === pkg.version, `顶栏徽标 v${badge?.[1]} 与 package.json ${pkg.version} 不同源`)
const chip = html.match(/版本 v([0-9.]+)</)
ok(chip && chip[1] === pkg.version, `封面版本芯片 v${chip?.[1]} 与 package.json ${pkg.version} 不同源`)

// 3. 目录锚点
const anchors = [...html.matchAll(/class="toc" href="#([^"]+)"/g)].map((m) => m[1])
anchors.forEach((a) => ok(html.includes(`id="${a}"`), `目录锚点 #${a} 无对应 section`))

// 4. 热点与截图结构
const hs = [...html.matchAll(/<button class="hs"[^>]*>/g)].map((m) => m[0])
hs.forEach((h) => ok(h.includes('data-title=') && h.includes('data-text='), '热点缺 data-title/data-text'))
const figs = (html.match(/<figure class="shot">/g) || []).length
const imgs = (html.match(/<div class="shot-frame">\s*<img/g) || []).length
ok(figs === imgs && figs > 0, `截图 figure(${figs}) 与 img(${imgs}) 不一一对应`)
ok((html.match(/class="mock"/g) || []).length >= 10, '复刻界面数量异常（<10）')

// 5. 红线扫描
const forbidden = [
  [/BPC\d{4,}|AFA\d{6,}|CP0\d{3}\.\d+/i, '真实料号'],
  [/ExcelAddin|LightVBA|SFTP Searcher/i, '外迁兄弟工程名'],
  [/admin123|user123|Demo12345|demo123/, '演示凭据字面量'],
  [/Trim_Weight|Site2\.csv/i, '私有样例文件名'],
]
forbidden.forEach(([re, label]) => ok(!re.test(html), `红线命中：${label}`))

// 6. 服务器形态入口提示
ok(/https:\/\/125\.69\.67\.169:18124/.test(html), '快速上手缺服务器形态访问网址')

if (fails.length) {
  console.error(`INTRO-CHECK FAIL (${fails.length})`)
  fails.forEach((f) => console.error(' - ' + f))
  process.exit(1)
}
console.log(`INTRO-CHECK PASS · 截图 ${refs.length} · 热点 ${hs.length} · 目录 ${anchors.length} · 版本 v${pkg.version}`)
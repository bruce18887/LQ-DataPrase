#!/usr/bin/env node
/**
 * e2e_preview_supervised — 前端 preview 的监督壳（只在 slot 池模式下挂上）。
 *
 * 为什么要它（2026-10-15，判据不是"更健壮"而是"拿得到证据"）：池跑到中途，某个 slot 的
 * `vite preview` 会**无声消失** —— 整条 `cmd→npm→vite` 链从进程表里没了、stderr 一条异常都没有、
 * 同 slot 的 Django 继续正常记请求，之后该 slot 每条用例约 500ms 就 `ERR_CONNECTION_REFUSED`，
 * 一整轮因此作废（带看门狗的 6 轮里 4 轮）。Playwright 直接把 `npm run preview` 当 webServer 起，
 * 孩子没了**没人记账** —— 缺的正是退出码与信号。这里代一层：
 *   ① 每次结束都记 `E2E_PREVIEW_LOG`（pid / code / signal / 存活时长 / 第几次），
 *      「被外部终止」与「自己崩」在这条日志上是两种形状，那正是现在最想知道的；
 *   ② 还有额度就重新起一个，让一轮不再因为一次失联整轮作废。
 *
 * 关停必须走**树杀**：`child.kill()` 在 Windows 只杀 cmd 那一层，npm/vite 会活下来占着端口，
 * 下一轮的 strictPort 就撞在孤儿进程上 —— 那是比掉线更糟的失败模式。
 */
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const CMD = process.env.ComSpec || 'C:\\Windows\\System32\\cmd.exe'
const LOG = process.env.E2E_PREVIEW_LOG || ''
const MAX_RESTART = Number(process.env.E2E_PREVIEW_MAX_RESTART ?? 3)
const RESPAWN_DELAY_MS = Number(process.env.E2E_PREVIEW_RESPAWN_DELAY_MS ?? 1000)
/**
 * 直接起 vite，不起 `npm run preview`。
 * 探针实测（`tasks/e2e-slot-probe/probe-npm-exit-shape.mjs`）：`cmd /c npm run preview` 这层壳会
 * **活得比它的 vite 久**（杀掉 vite 之后壳才以 code=1 退出），于是"子进程退出"这个信号在壳形态下
 * 既滞后又分不清是谁死了 —— 监督的目的就是拿到**服务进程**的退出码/信号。
 * 直起 vite 后：我的直接子进程 == 端口上的监听进程（探针里逐次核 PID 验证），
 * code/signal 才有意义，重生也不会出现"壳还在、又起一个服务"的双监听。
 */
const VITE_BIN = process.env.E2E_PREVIEW_VITE_BIN || path.resolve('node_modules', 'vite', 'bin', 'vite.js')
const VITE_ARGS = (process.env.E2E_PREVIEW_ARGS || 'preview').split(' ').filter(Boolean)

let restarts = 0
let childPid = null
let closing = false

function note(msg) {
  if (!LOG) return
  try { fs.appendFileSync(LOG, `${new Date().toISOString()} ${msg}\n`) } catch { /* 取证不能拖垮服务 */ }
}

function treeKill(pid, why) {
  if (!pid) return
  note(`treeKill pid=${pid}（${why}）`)
  try {
    spawnSync(CMD, ['/c', 'taskkill', '/F', '/T', '/PID', String(pid)], { stdio: 'ignore', timeout: 15_000 })
  } catch (e) { note(`treeKill 失败: ${e.message}`) }
}

function start() {
  const t0 = Date.now()
  const n = restarts + 1
  const child = spawn(process.execPath, [VITE_BIN, ...VITE_ARGS], { cwd: process.cwd(), stdio: 'inherit', env: process.env })
  childPid = child.pid
  note(`child pid=${childPid} 第 ${n} 次启动 ${process.execPath} ${[VITE_BIN, ...VITE_ARGS].join(' ')}`)

  child.on('error', (e) => note(`spawn error pid=${childPid}: ${e.message}`))
  child.on('exit', (code, signal) => {
    const lifeMs = Date.now() - t0
    note(`exit pid=${childPid} code=${code} signal=${signal} 存活=${lifeMs}ms 第 ${n} 次`)
    childPid = null
    if (closing) { process.exit(code ?? 0); return }
    // 秒退通常意味着端口/包没准备好，重生只会刷日志 —— 让编排器按 INFRA 处理而不是无限重启
    if (lifeMs < 3_000 && n > 1) { note(`⇒ 存活不足 3s 且已是第 ${n} 次，不再重生`); process.exit(code ?? 1) }
    if (restarts >= MAX_RESTART) {
      note(`⇒ 重生额度 ${MAX_RESTART} 用尽，监督器退出（该 slot 之后会成片拒连，由看门狗记 INFRA）`)
      process.exit(code ?? 1)
    }
    restarts += 1
    note(`⇒ 重新起 preview（已用 ${restarts}/${MAX_RESTART}，${RESPAWN_DELAY_MS}ms 后）`)
    setTimeout(start, RESPAWN_DELAY_MS)
  })
}

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP', 'exit']) {
  process.on(sig, () => {
    if (sig === 'exit') { treeKill(childPid, '监督器退出兜底'); return }
    closing = true
    note(`收到 ${sig}`)
    treeKill(childPid, `转发 ${sig}`)   // Playwright 收尾走这条：不留孤儿占端口
    process.exit(0)
  })
}

note(`# 监督器 pid=${process.pid} cwd=${process.cwd()} 额度=${MAX_RESTART}`)
start()

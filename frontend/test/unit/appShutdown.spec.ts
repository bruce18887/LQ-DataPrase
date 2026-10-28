/**
 * T2：Electron 退出路径（`electron/app-shutdown.ts`）。
 *
 * 为什么这批判据必须存在：`frontend/e2e/electron/electron.spec.ts` 不启动 Electron，
 * 只跑纯函数 —— 所以主进程的退出接线在门禁里是**零覆盖**的。实测也证实了另一半：dev 档
 * 复用外部后端（managed=false），真起一次桌面实例只能验到「跳过」那一半，托管 python 的
 * 回收路径没法在开发机上安全地跑（打包验收要动 build.bat，它带 taskkill）。把判据抽成
 * 注入式的纯模块，这两半才都能在 T2 里被真的按下去。
 *
 * 跑法：cd frontend && npx vitest run test/unit/appShutdown.spec.ts
 */
import { describe, expect, it } from 'vitest'

import type { ChildProcess } from 'child_process'

import { killBackendOnExit, stopBackendBeforeQuit } from '../../../electron/app-shutdown'
import type { BackendInfo } from '../../../electron/backend-info'

type BeforeQuitListener = (event: { preventDefault(): void }) => void

interface FakeApp {
  on(event: 'before-quit', listener: BeforeQuitListener): void
  quit(): void
}

function makeFakeApp() {
  const listeners: BeforeQuitListener[] = []
  const state = { quitCalls: 0, preventCalls: 0 }
  const app: FakeApp = {
    on: (_event, listener) => {
      listeners.push(listener)
    },
    quit: () => {
      state.quitCalls += 1
    },
  }
  return {
    app,
    state,
    /** 模拟 Electron 派发一次 before-quit。 */
    fire: () => {
      for (const l of listeners) l({ preventDefault: () => (state.preventCalls += 1) })
    },
  }
}

function deferred() {
  let resolve!: () => void
  let reject!: (err: unknown) => void
  const promise = new Promise<void>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** 等 promise 链上的微任务全部落地（.catch/.finally 是两级，给足三轮）。 */
async function flush(times = 3): Promise<void> {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
}

function info(patch: Partial<BackendInfo> = {}): BackendInfo {
  return {
    port: 8123,
    pid: 4242,
    process: { exitCode: null } as unknown as ChildProcess,
    managed: true,
    shutdownToken: 'tok',
    ...patch,
  }
}

function makeDeps(opts: { info?: BackendInfo | null; stop?: (i: BackendInfo) => Promise<void> } = {}) {
  const fake = makeFakeApp()
  const logs: { level: 'info' | 'error'; message: string }[] = []
  let current: BackendInfo | null = opts.info === undefined ? info() : opts.info
  const setCalls: (BackendInfo | null)[] = []
  return {
    fake,
    state: fake.state,
    logs,
    setCalls,
    deps: {
      app: fake.app,
      getInfo: () => current,
      setInfo: (next: BackendInfo | null) => {
        current = next
        setCalls.push(next)
      },
      stop: opts.stop ?? (async () => {}),
      log: (level: 'info' | 'error', message: string) => {
        logs.push({ level, message })
      },
    },
  }
}

describe('stopBackendBeforeQuit', () => {
  it('挂了后端才拦退出：dev 档复用外部后端时一条都不动（managed=false 的跳过面）', () => {
    const { deps, fake, state } = makeDeps({ info: null })
    stopBackendBeforeQuit(deps)
    fake.fire()
    expect(state.preventCalls).toBe(0)
    expect(state.quitCalls).toBe(0)
  })

  it('先拦住退出，stop 没落地之前绝不 quit（旧 async 监听器写法就是在这里失守的）', async () => {
    const gate = deferred()
    let stopCalls = 0
    const managedFlags: boolean[] = []
    const { deps, fake, state } = makeDeps({
      stop: (i) => {
        stopCalls += 1
        managedFlags.push(i.managed)
        return gate.promise
      },
    })
    stopBackendBeforeQuit(deps)
    fake.fire()

    expect(state.preventCalls).toBe(1)
    expect(stopCalls).toBe(1)
    expect(managedFlags).toEqual([true])
    // 关键顺序断言：此时 stop 还没 resolve，退出必须仍被按住
    expect(state.quitCalls).toBe(0)

    gate.resolve()
    await flush()
    expect(state.quitCalls).toBe(1)
  })

  it('停完清空引用，下一次 before-quit 放行而不是把自己吊死', async () => {
    let stopCalls = 0
    const { deps, fake, setCalls, state } = makeDeps({
      stop: async () => {
        stopCalls += 1
      },
    })
    stopBackendBeforeQuit(deps)
    fake.fire()
    await flush()

    expect(stopCalls).toBe(1)
    expect(state.quitCalls).toBe(1)
    expect(setCalls).toEqual([null])

    // 我们自己那句 app.quit() 会再派发一次 before-quit
    fake.fire()
    await flush()
    expect(stopCalls).toBe(1)
    expect(state.preventCalls).toBe(1)
    expect(state.quitCalls).toBe(1)
  })

  it('停失败也要退出：不能因为后端没停成就把应用卡在退出里', async () => {
    const { deps, fake, logs, state } = makeDeps({
      stop: () => Promise.reject(new Error('shutdown endpoint 无响应')),
    })
    stopBackendBeforeQuit(deps)
    fake.fire()
    await flush()

    expect(state.quitCalls).toBe(1)
    const err = logs.filter((l) => l.level === 'error')
    expect(err.length).toBe(1)
    expect(err[0].message).toContain('shutdown endpoint 无响应')
  })

  it('退出过程的日志走 info 级且带可 grep 的前缀（取证就靠这一行认主进程活到了哪一步）', async () => {
    const { deps, fake, logs } = makeDeps()
    stopBackendBeforeQuit(deps)
    fake.fire()
    await flush()

    expect(logs.map((l) => `${l.level}:${l.message}`)).toEqual([
      'info:[electron] before-quit, stopping backend before exit',
    ])
  })
})

describe('killBackendOnExit', () => {
  function kills(i: BackendInfo | null, platform: NodeJS.Platform) {
    const calls: { cmd: string; args: string[] }[] = []
    killBackendOnExit(i, { platform, killSync: (cmd, args) => calls.push({ cmd, args }) })
    return calls
  }

  it('只杀自己托管的：外部后端（dev 档 :8000）一律不动', () => {
    expect(kills(info({ managed: false }), 'win32')).toEqual([])
    expect(kills(null, 'win32')).toEqual([])
  })

  it('没有 PID 或已经退出（exitCode 非空）的进程不杀', () => {
    expect(kills(info({ pid: null }), 'win32')).toEqual([])
    expect(
      kills(info({ process: { exitCode: 0 } as unknown as ChildProcess }), 'win32')
    ).toEqual([])
    // 对照组：同一个进程只把 exitCode 换成 null 就必须杀 —— 证明承重的是那个判定，不是桩
    expect(
      kills(info({ process: { exitCode: null } as unknown as ChildProcess }), 'win32').length
    ).toBe(1)
  })

  it('Windows 按 PID 强杀，绝不按镜像名全量杀（build.bat 的误伤教训）', () => {
    const calls = kills(info(), 'win32')
    expect(calls).toEqual([{ cmd: 'taskkill', args: ['/F', '/PID', '4242'] }])
    const flat = calls[0].args.join(' ')
    expect(flat).not.toContain('/IM')
    expect(flat.toLowerCase()).not.toContain('python')
  })

  it('POSIX 走 kill <pid>（不带信号参数 = SIGTERM，让 Django 自己收摊）', () => {
    expect(kills(info(), 'linux')).toEqual([{ cmd: 'kill', args: ['4242'] }])
  })

  it('process 句柄已丢但 PID 还活着时照杀不误 —— 兜底就是为了这种半死状态', () => {
    expect(kills(info({ process: null }), 'win32')).toEqual([
      { cmd: 'taskkill', args: ['/F', '/PID', '4242'] },
    ])
  })
})

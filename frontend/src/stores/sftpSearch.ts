/**
 * 搜索 store —— SSE 流的所有权与跨路由驻留（计划 Task 14 / spec §3.8、§3.9 第 5 条）。
 *
 * ## 为什么流活在这里
 * `postSse` 就是一个 `fetch` + `ReadableStream` 的读循环，它本身跟任何组件都没有关系。
 * 把这个循环的所有者从组件换成 Pinia store 之后，它与组件生命周期**再无关系**：切路由、
 * 关组件、keep-alive 停用都不构成中断它的理由，因为没有任何地方在卸载路径上持有它的
 * `abort`。「搜索跑 6 分钟，用户切去看图表」期间结果继续累积，回来还在（spec §1.2 驻留）。
 *
 * ## 刻意不 abort —— 请勿「顺手补上」
 * 本文件**不导入** `onBeforeUnmount` / `onDeactivated`，也绝不写任何在卸载/停用钩子里
 * 调 `abort()` 的代码（spec §3.9 第 5 条：只有「显式取消」与「退出应用」才 abort）。
 * 这与 2026-09-09 的下载**故意不同**：`SftpBrowser.vue:182-191` 在 `onBeforeUnmount`
 * 里 abort 两条下载流，那里的语义是「离开页面即停止传输」，且下载是秒到分钟级的短任务。
 * 把那一套照搬到搜索，「跨页面驻留」这个需求当场失效 —— 后来人加 abort 之前请先读这段。
 *
 * 全文件只有两处 abort，都是用户显式表达的意图：`cancel()`（点取消）与
 * `removeRun()`（删掉一条正在跑的运行；删掉看不见的东西却让它继续跑才是泄漏）。
 * 应用退出时页面销毁，浏览器自己掐掉连接，后端 `timeout` 兜在制品（spec §3.9 第 5 条）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { sftpSearchApi } from '../api/sftpSearch'
import type {
  CandidateItem,
  DoneEvent,
  MatchItem,
  SearchEngine,
  SearchError,
  SearchEvent,
  SearchNotice,
  SearchSpec,
} from '../api/sftpSearch'

/** 会话内运行历史条数上限（计划 Global Constraints 的前端常量，别处不要再写这个数） */
export const RUN_HISTORY_KEEP = 20

/**
 * 取消冷却时长：abort 之后后端线程池与临时连接还在收尾（最坏 `READ_TIMEOUT_SEC` = 15s，
 * 通常毫秒级），立刻再开一条流会在同一批临时连接上打架。
 *
 * **归属：冷却只住在本 store 里**（计划 Task 17 Step 6 给了两个候选落点，这里选定第一个）。
 * `SftpBrowser.vue` 的 `startCooldown()` 只管下载那条共享连接的冷却，与本常量同值纯属
 * 巧合（成因不同：那边是池连接，这边是搜索自开的 N 条临时连接）。Task 17 接线时
 * 把 `inCancelCooldown` 并进 `transferActive` 即可，**不要**两处各冷却一次 ——
 * 同一次取消被记进两个时钟，改一处忘一处就出现「按钮一半禁着一半没禁」。
 */
export const CANCEL_COOLDOWN_MS = 1200

export type SearchRunStatus = 'running' | 'done' | 'cancelled' | 'partial' | 'error'

/** `progress` 事件的载荷快照（三态：total 为 null 时是不定档） */
export interface SearchProgressState {
  stage: string
  done: number
  total: number | null
  elapsed_s: number
  files_scanned: number
  bytes_scanned: number
}

export interface SearchRun {
  id: number
  /** 原样留着：历史条目「再搜一次」就是把它送回 `start()` */
  spec: SearchSpec
  status: SearchRunStatus
  engine: SearchEngine | null
  engineReason: string
  workersActual: number
  candidates: CandidateItem[]
  matches: MatchItem[]
  /** 摘要化前的条数：`compacted` 之后 UI 只能读这两个数 */
  candidateCount: number
  matchCount: number
  /** 数组是否已被摘要化清空（见 `compactHistory`） */
  compacted: boolean
  progress: SearchProgressState | null
  notices: SearchNotice[]
  errors: SearchError[]
  startedAt: number
  finishedAt: number | null
  /** `done` 事件载荷：`truncated` / `limits_hit` 决定那条不可关闭的黄色提示 */
  done?: DoneEvent
  /** `null` = 已结束。Vue 的 reactive 不代理 AbortController 这类宿主对象，存进来仍是原实例 */
  abort: AbortController | null
}

/** 尚未收到 `hello` 之前的 stage 也要能显示，所以进度初值在这里造一次 */
function emptyProgress(stage: string): SearchProgressState {
  return { stage, done: 0, total: null, elapsed_s: 0, files_scanned: 0, bytes_scanned: 0 }
}

export const useSftpSearchStore = defineStore('sftpSearch', () => {
  /** 最新在前；`runs[0]` 是唯一保留全量结果的那条 */
  const runs = ref<SearchRun[]>([])
  const activeRunId = ref<number | null>(null)
  /** 冷却用一个会自己翻回 false 的 ref，而不是在 computed 里比 `Date.now()`：
   *  时间的流逝不会让 computed 重新求值，那样按钮会一直禁着不再回来。 */
  const inCancelCooldown = ref(false)
  let cooldownTimer: ReturnType<typeof setTimeout> | null = null
  let nextId = 1

  const activeRun = computed(
    () => runs.value.find(r => r.id === activeRunId.value) ?? null,
  )
  /** 有没有任何一条流还在跑 —— 下载互斥读它（Task 17 Step 5），不是「activeRun 在跑」 */
  const isRunning = computed(() => runs.value.some(r => r.status === 'running'))
  /** chip 要显示的就是 activeRun 本身，所以它比 `isRunning` 多一层条件 */
  const chipVisible = computed(() => activeRun.value?.status === 'running')
  /** 「开始搜索」按钮的唯一判据：冷却与并发都只在这里说一次，页面别自己再拼一遍 */
  const canStart = computed(() => !isRunning.value && !inCancelCooldown.value)

  function find(id: number): SearchRun | null {
    return runs.value.find(r => r.id === id) ?? null
  }

  /**
   * 摘要化：全量结果只留最近一次。上限是 5000 候选 + 2000 命中，20 条历史都留数组
   * 就是十几万个常驻对象；而历史的价值是「条件还在能重跑 + 上次搜出多少」，
   * 不是把那 5000 行再渲染一遍。
   * 仍在跑的**历史**流不裁：它还在 push，裁了用户会看到计数不动（正确性优先于省内存）。
   */
  function compactHistory(): void {
    for (let i = 1; i < runs.value.length; i++) {
      const run = runs.value[i]
      if (run.status === 'running' || run.compacted) continue
      run.candidateCount = Math.max(run.candidateCount, run.candidates.length)
      run.matchCount = Math.max(run.matchCount, run.matches.length)
      run.candidates = []
      run.matches = []
      run.compacted = true
    }
  }

  function beginCooldown(): void {
    inCancelCooldown.value = true
    if (cooldownTimer) clearTimeout(cooldownTimer)
    cooldownTimer = setTimeout(() => {
      inCancelCooldown.value = false
      cooldownTimer = null
    }, CANCEL_COOLDOWN_MS)
  }

  function createRun(spec: SearchSpec, abort: AbortController): SearchRun {
    return {
      id: nextId++,
      spec,
      status: 'running',
      engine: null,
      engineReason: '',
      workersActual: 0,
      candidates: [],
      matches: [],
      candidateCount: 0,
      matchCount: 0,
      compacted: false,
      progress: emptyProgress('listing'),
      notices: [],
      errors: [],
      startedAt: Date.now(),
      finishedAt: null,
      abort,
    }
  }

  /** 一次搜索：建 run → 交给 `postSse` → 事件回灌 `apply` → finally 收口。永不 reject。 */
  async function start(spec: SearchSpec): Promise<void> {
    const ctrl = new AbortController()
    const run = createRun(spec, ctrl)
    const id = run.id
    runs.value.unshift(run)
    // 超上限淘汰最旧的一条。计划 Step 1 写的是 `runs.pop()`，这里走 `removeRun()`：
    // 直接 pop 掉一条**还在跑**的最旧运行，它的读循环仍在跑（apply/finalize 此后再
    // 找不到那个 id），就成了没人认领、也没人 abort 的僵尸流。
    while (runs.value.length > RUN_HISTORY_KEEP) {
      removeRun(runs.value[runs.value.length - 1].id)
    }
    activeRunId.value = id
    compactHistory()
    // 从这一行起只用 id 通过 `find()` / `apply()` / `finalize()` 触碰这条 run：
    // unshift 之后数组里那份是响应式代理，继续改 `createRun` 返回的裸对象
    // 不会触发任何视图更新（Pinia 的常见坑）。
    try {
      await sftpSearchApi.run(spec, e => apply(id, e), ctrl.signal)
    } catch (e: unknown) {
      recordStreamFailure(id, e)
    } finally {
      // 关键收口点：取消路径上 `postSse` 抛的是 AbortError，而无论抛不抛、
      // 也无论 `cancel()` 有没有已经定稿，流一旦结束都必须走完这里
      //（`finalize` 幂等，重复调用只是重排一次摘要）。
      finalize(id)
    }
  }

  /** 事件分派：`candidates` / `match` 是 push（批合成帧只增不换），`progress` 覆盖。 */
  function apply(id: number, e: SearchEvent): void {
    const run = find(id)
    if (!run) return                        // run 已被 removeRun 删掉：迟到事件就地丢弃
    switch (e.kind) {
      case 'hello':
        run.engine = e.engine
        run.engineReason = e.engine_reason
        run.workersActual = e.workers_actual
        return
      case 'stage':
        // 注意别从这里取候选数：`stage:'scanning'` 的 candidates 是**扫描目标数**
        // （one_per_folder 之后），只有 stage:'done' 才是候选总数（runner.py:202）。
        run.progress = run.progress ? { ...run.progress, stage: e.stage } : emptyProgress(e.stage)
        return
      case 'candidates':
        run.candidates.push(...e.items)
        // total_so_far 是后端累计的权威值，比数组长度可靠（上限裁掉的不算在数组里）
        run.candidateCount = e.total_so_far
        return
      case 'match':
        run.matches.push(...e.items)
        run.matchCount = run.matches.length
        return
      case 'progress':
        run.progress = {
          stage: e.stage,
          done: e.done,
          total: e.total,
          elapsed_s: e.elapsed_s,
          files_scanned: e.files_scanned,
          bytes_scanned: e.bytes_scanned,
        }
        return
      case 'notice':
        // 按 code 去重：同一个钳位/截断码反复出现对用户是同一条信息（后端 _limit 也去重，
        // 但 grep_fallback 这类仍可能带不同后缀，取第一条即可）
        if (!run.notices.some(n => n.code === e.code)) run.notices.push(e)
        return
      case 'error':
        // 按 path+message 去重：一个目录里几百个文件报同一句时只留一行
        if (!run.errors.some(x => x.path === e.path && x.message === e.message)) {
          if (e.scope === 'fatal') console.warn('[sftpSearch] fatal in-stream error:', e.message)
          run.errors.push(e)
        }
        return
      case 'done':
        run.done = e
        run.matchCount = Math.max(run.matchCount, e.matched)
        // 显式取消已经定稿为 'cancelled'，迟到的 done 不许把它改回 done/partial
        if (run.status === 'running') {
          run.status = e.cancelled ? 'cancelled' : (e.truncated ? 'partial' : 'done')
        }
        return
    }
  }

  /**
   * 流外失败（`400 {"error": msg}`，含未连接哨兵）变成一条 `scope:'fatal'` 的 error 记录。
   * AbortError 不算失败：`cancel()` 已经当场定稿了。
   */
  function recordStreamFailure(id: number, e: unknown): void {
    const run = find(id)
    if (!run) return
    const err = e as { name?: string; message?: string }
    if (err?.name === 'AbortError') return
    const message = err?.message || '搜索请求失败'
    console.warn('[sftpSearch] stream failed:', message)
    if (!run.errors.some(x => x.path === null && x.message === message)) {
      run.errors.push({ kind: 'error', scope: 'fatal', path: null, message })
    }
  }

  /**
   * 取消：**当场定稿，不指望事件**。后端最坏 15s 才收得拢（spec §3.9 第 3 条），
   * 用户点完取消必须立刻看到「已取消」。
   *
   * 09-09 记过的缺陷形态正好相反：AbortError 在 api 层就被静默吞掉
   * （`api/sftp.ts` 的 `if (e?.name === 'AbortError') return`），组件的 catch 根本不
   * 触发，于是取消之后进度卡一直挂着 —— 那次的修复是 abort 完立即显式复位。
   * 本 store 同构照办：`status` / `finishedAt` 在 abort 之前就写好，后面的
   * `finalize()` 只是补一次幂等收口，事件与 catch 都不参与「取消成功没有」的判定。
   * （搜索这条路 `run()` 不吞 AbortError，所以 catch 也在，但它对 AbortError
   * 直接返回——取消不该再被记一次失败。）
   */
  function cancel(id?: number): void {
    const run = find(id ?? activeRunId.value ?? -1)
    if (!run || run.status !== 'running') return
    run.status = 'cancelled'
    run.finishedAt = Date.now()
    beginCooldown()
    run.abort?.abort()
    finalize(run.id)
  }

  /** 收口：无论流是正常结束、被取消还是断在半路，这里都是最后一个碰到它的地方。 */
  function finalize(id: number): void {
    const run = find(id)
    if (!run) return
    run.abort = null
    // status 仍是 running = 没收到 done 就断了（网络断开 / 后端崩），
    // 不能记成 done：用户会以为搜完了，而结果集其实残缺。
    if (run.status === 'running') run.status = 'error'
    if (run.finishedAt === null) run.finishedAt = Date.now()
    compactHistory()
  }

  function removeRun(id: number): void {
    const run = find(id)
    if (!run) return
    if (run.status === 'running') {
      // 删除一条正在跑的运行就是用户显式取消它（见文件顶部「只有两处 abort」）
      run.status = 'cancelled'
      run.finishedAt = Date.now()
      beginCooldown()
      run.abort?.abort()
    }
    runs.value = runs.value.filter(r => r.id !== id)
    if (activeRunId.value === id) {
      activeRunId.value = runs.value.find(r => r.status === 'running')?.id ?? runs.value[0]?.id ?? null
    }
    compactHistory()
  }

  /** 清掉已结束的历史条目（进行中的一律留着） */
  function clearFinished(): void {
    runs.value = runs.value.filter(r => r.status === 'running')
    if (activeRunId.value !== null && !find(activeRunId.value)) {
      activeRunId.value = runs.value[0]?.id ?? null
    }
  }

  return {
    runs, activeRunId, inCancelCooldown,
    activeRun, isRunning, chipVisible, canStart,
    start, apply, cancel, finalize, removeRun, clearFinished,
  }
})

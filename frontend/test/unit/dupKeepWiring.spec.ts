/**
 * T2（源侧绊线）：重复项保留选择的**接线**形状。
 *
 * 为什么这一层需要它：`dupKeep.spec.ts` 钉的是纯函数，`duplicate-keep.spec.ts` 钉的是
 * 浏览器终态；中间那层「组件到底有没有真的用这些函数、有没有把 keep_ids 真的送出去」
 * 在两边都没有牙 —— 组件不装 jsdom（本仓 T2 约定），而 e2e 只看结果，
 * 「按钮文案写死『全部』但函数照常算」这种回退在 e2e 里照样绿。
 *
 * 跑：cd frontend && npx vitest run test/unit/dupKeepWiring.spec.ts
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SRC = (rel: string) => new URL(`../../src/${rel}`, import.meta.url)
/** 整行注释不参与判定：为什么这么接线必须能写在注释里，否则下一个人会当废话删掉。 */
const codeOf = (t: string) => t.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')
const read = (rel: string) => codeOf(readFileSync(SRC(rel), 'utf8'))

const card = () => read('pages/data/components/DuplicateFilesCard.vue')
const dialog = () => read('pages/data/components/ConsistencyCheckDialog.vue')
const api = () => read('api/datafiles.ts')

describe('重复文件卡的接线', () => {
  it('选择与汇总都走 utils/dupKeep，不在组件里现算字符串', () => {
    const c = card()
    expect(c).toMatch(/from '[^']*utils\/dupKeep'/)
    for (const fn of ['resolveKeepIds', 'keepIdForGroup', 'deleteSummaryText', 'truncatedNoteText', 'applyStrategyToUntouched']) {
      expect(c, `组件里少了 ${fn}`).toContain(`${fn}(`)
    }
  })
  it('按钮数字来自当前选择，「全部」这种写死措辞不许回来', () => {
    const c = card()
    expect(c).toMatch(/\{\{\s*summaryText\s*\}\}/)
    expect(c).not.toMatch(/删除全部重复项|删除全部/)
    expect(c).toMatch(/我已确认按以上选择删除/)
  })
  it("选中态有结构钩子（按文案筛抓不到'画错行'）", () => {
    const c = card()
    expect(c).toMatch(/data-testid="dup-keep-row"/)
    expect(c).toMatch(/:data-keep="f\.id === keepFor\(group\)/)
  })
  it('策略标签不许承诺「默认」—— 默认恒为最早，只有点「应用」才轮到策略（终审 F2 的谎话控件）', () => {
    const c = card()
    /**
     * 缺陷形状：标签写「未改选的组默认保留」+ 两颗 radio「最早导入 / 最新导入」，读起来像
     * 「默认跟着这颗 radio 走」；而 `keepIdForGroup` 压根不读 `strategy`（默认恒为 `files[0]`
     * =最早），alert 那句「未改选的组默认保留最早导入的那条」才是真相。同一个屏幕两句互斥，
     * 用户拨到「最新导入」不点应用 ⇒ 被物理删掉的是最新那份（§5.5 已否掉回收站）。
     * 判据只认**标签那个文本节点**（`class="dup-strategy-label">` 紧跟的那串），
     * 因为模板里那段 WHY 注释按 `codeOf` 的逐行规则只有首行算注释、续行仍算代码 ——
     * 它必然要写出「默认保留」这个词来讲明为什么禁它。`[B3A-F2A]` 在浏览器里钉同一句。
     */
    expect(c).toMatch(/class="dup-strategy-label">[^<]*只作用未改选的组[^<]*</)
    expect(c, '标签一旦带上「默认」，就与 alert 那句「默认保留最早」打对台').not.toMatch(
      /class="dup-strategy-label">[^<]*默认/,
    )
    // 真相那句必须还在 alert 里，且是「最早」而不是「按策略」
    expect(c).toMatch(/未改选的组默认保留最早导入的那条/)
  })
  it('fix 事件带 keep_ids 上行', () => {
    const c = card()
    /**
     * 钉整条链而不是只钉 `emit('fix', resolveKeepIds(` 出现过：
     * 变异 M15（按钮改 `@click="emit('fix')"`）会让 `submit` 变成**死代码**，
     * 那行字符串仍在文件里 ⇒ 只查字符串的判据照样绿。按钮 → submit → resolveKeepIds
     * 三段必须连成一条，断在任何一环都红。
     */
    expect(c).toMatch(/@click="submit"/)
    expect(c).toMatch(/function submit\(\) \{\s*emit\('fix',\s*resolveKeepIds\(/)
    // 上行载荷必须是「已展示每组的保留项」，不是 choice 的残值（漏送默认项 = 服务端按默认删）
    expect(c).not.toMatch(/emit\('fix',\s*\[/)
  })
  it('「应用到未改选的 N 组」的 N 与实际覆盖组数同源（不许用 size 反推）', () => {
    const c = card()
    expect(c).toMatch(/data-testid="dup-apply-strategy"/)
    expect(c).toMatch(/应用到未改选的 \{\{\s*untouched\.length\s*\}\} 组/)
    /**
     * N 的唯一来源 = 「切片里没有改选键的组数」本身（filter + choice.has(groupKey)）。
     * `groups.length - choice.size` 在 choice 含切片外陈旧键时会比实际覆盖组数**小**，
     * 那句话就成了吹牛 —— 而「把 untouched 换成减出来的数」那种变异只有这条抓得住。
     * 判据按形状放宽（换行 / 形参名不改），但**硬禁** `choice.value.size` 出现在组件里：
     * Map 的 size 在这张卡上没有任何合法用途，写它就是在反推。
     */
    expect(c, 'untouched 必须由 groups.filter + choice.has(groupKey) 得出')
      .toMatch(/const untouched = computed\(\(\)[\s\S]{0,160}?props\.groups\.filter\([\s\S]{0,90}?choice\.value\.has\(groupKey\(/)
    expect(c, '不许用 choice.value.size 反推组数').not.toMatch(/choice\.value\.size/)
  })
})

/**
 * Task 7 的接线判据：**源码派生守卫，不用人记得改回来**。
 *
 * 为什么不是 `describe.skip`：skip 的解除是一个人工步骤，而本批已经出现过一次
 * 「解除动作只活在注释里」的形状（Task 6 交付时台账还没建、计划 Task 7 又写着
 * 「此刻这两条应该正红着」—— 与 skip 的现状互相矛盾）。
 * 判据自己看磁盘：`api/datafiles.ts` 里出现 `keep_ids` == Task 7 已落地 == 这两条真跑；
 * 没落地就 skip，且 skipped 数会随 Task 7 归零（台账按实测 skipped 数对账）。
 * 判例同 `firstScreenChunks.spec.ts` 的 `describe.skipIf(!built)`。
 */
const API_LANDED = /keep_ids/.test(api())
describe.skipIf(!API_LANDED)('对话框与 api 的接线（api 出现 keep_ids 即自动生效）', () => {
  it('对话框把 keep_ids 交给 api，并把 remaining_groups 拼进回执', () => {
    const d = dialog()
    expect(d).toMatch(/fixConsistency\(action,\s*keepIds\)/)
    expect(d).toMatch(/remainingGroupsNote\(/)
  })
  it('请求体真的带 keep_ids', () => {
    expect(api()).toMatch(/keep_ids/)
    expect(api()).toMatch(/remaining_groups\?: number/)
  })
})

describe('反向探针（改注释/换行/无关改名都不许红）', () => {
  it('多行 import 同判据', () => {
    const c = card()
    expect(c).toMatch(/applyStrategyToUntouched,/)
    expect(codeOf('// applyStrategyToUntouched(\n// resolveKeepIds(')).toBe('')
  })
})

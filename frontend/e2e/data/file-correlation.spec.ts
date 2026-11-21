import { test, expect } from '@playwright/test'
import { SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { elSelectByPlaceholder, popperOf, SERIAL_POPPER, visibleSelectOptions } from '../helpers/elplus'
import { expectWindowRows, windowItems, MAX_WINDOW_ROWS } from '../helpers/selectV2'

/**
 * 文件相关性对比（数据管理「文件对比」tab，2026-08-21 重构 / 2026-08-28 优化）。
 *
 * 覆盖（2026-08-28 优化后）：
 * 1. 序列选择改为「搜索序列号」输入框勾选（默认前 10 颗，交互与查看数据
 *    搜索测试项一致）；
 * 2. Limit 对比与测试值对比拆分为两个视图（默认测试值对比，Limit 列不再
 *    占固定列宽）；
 * 3. 切走 tab 再切回结果仍在（重型表格 v-if 卸载/重挂的回归）；
 * 4. 导出 Excel 下载（双 Sheet 内容由后端测试覆盖，e2e 保持轻量）。
 */

/** 选择两个种子文件（BPD60320_FT vs BPD60320_QA1） */
async function pickFilePair(
  section: import('@playwright/test').Locator,
  page: import('@playwright/test').Page,
) {
  const file1 = elSelectByPlaceholder(section, '文件1 (ATE)')
  await file1.click()
  await expect
    .poll(
      () => visibleSelectOptions(page).count(),
      { timeout: 15_000, message: '文件列表应加载出选项' },
    )
    .toBeGreaterThan(0)
  // FileSelect 迁 `el-select-v2` 后 DOM 只有虚拟窗口那约 10 行：种子文件不在首屏时
  // 按 hasText 硬找会等到超时（目标行根本没渲染）。先把文件名打进过滤框再点，
  // 过滤后候选集只剩命中项，目标必在窗口内。
  await file1.locator('input').first().fill(SEEDED_FILES.BUYOFF_FT)
  await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_FT }).first().click()
  // 等上一个下拉的关闭动画结束，避免两个 dropdown 并存时 .first() 命中已隐藏选项
  await page.waitForTimeout(600)

  const file2 = elSelectByPlaceholder(section, '文件2 (Bench)')
  await file2.click()
  await file2.locator('input').first().fill(SEEDED_FILES.BUYOFF_QA1)
  await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.BUYOFF_QA1 }).first().click()
  await page.waitForTimeout(600)
}

/**
 * 从 `.fc-serial-hint` 取「已选 N」的 N（解析不出返回 -1，让 poll 红得可读）。
 *
 * 为什么要有这个：Enter 全选那条判据原来只比 **形状** `/已选 (\d+) \/ 共 \d+ 颗/`，
 * 而基线那 10 颗本身就在形状里 —— Enter 一点没生效也照样绿。迁 `el-select-v2` 后
 * 这层盲区必须闭掉：v2 自己在过滤 input 上绑了 Enter（`select-v2/src/select.mjs:227`，
 * `withKeys(withModifiers(onKeyboardSelect, ['stop','prevent']), ['enter'])`），
 * 它与组件 `@keydown.capture` 的「全选匹配」是同一条键的两种结果（+1 vs +整个匹配集），
 * 光比形状分辨不了。取数比较是唯一能分辨这两者的证据。
 */
function selectedSerialCount(section: import('@playwright/test').Locator): Promise<number> {
  return section.locator('.fc-serial-hint').textContent().then((t) => {
    const m = /已选 (\d+) \/ 共 (\d+) 颗/.exec(t ?? '')
    return m ? Number(m[1]) : -1
  })
}

/**
 * 默认勾选的序列数（本文件的「基线」）。
 *
 * 界从它推，不是经验值：
 * - 现测来源 = `FileCorrelationSection.vue` 拉完公共序列后的 `list.slice(0, 10)`，
 *   页面上的落点 = `FileCorrelationControls.vue` 的 `serialsHint`（`已选 N / 共 M 颗（最多 200）`）；
 * - `已选 > 基线` = 「Enter 全选确实改变了选择」的下界；
 * - `匹配数 > 基线 + 1` = 「已选 ≥ min(匹配数, 200)」那句在 Enter 被 v2 抢走时仍能红的前提
 *   （v2 的 Enter 净增最多 1 颗，见下面那条用例里的变异实测）。
 * 本文件其它用例里同型的「已选 10」形状断言也一并走 `BASELINE_HINT`，让基线值只有一个落点。
 */
const BASELINE_SERIALS = 10

/**
 * 已选序列上限（组件里 `SerialSelector.vue` 的 `MAX_SELECTED`，两处必须同值）。
 *
 * 界由它推，两处判据共用：`min(匹配数, 上限)` 是「Enter 全选后已选数」的下界，
 * `已选 N / 共 M 颗（最多 N）` 是「全选按钮触到顶」的提示形状。上限的存在理由在组件侧
 * （el-table 没有列虚拟化，200 序列 × 4 列 ≈ 800 列已到现实极限），本文件不复述。
 */
const MAX_SELECTED_SERIALS = 200

/** 「已选 <基线> / 共 N 颗」的形状判据（数字部分仍由 `\\d+` 兜，只有基线提出来） */
const BASELINE_HINT = new RegExp(`已选 ${BASELINE_SERIALS} / 共 \\d+ 颗`)

/**
 * 必然匹配不到的关键词：公共序列是 `number[]`，label 走 `String(序列号)` ⇒ 只可能是数字，
 * 字母 `z` 永远匹配不到 ⇒ 用它把「匹配集为空」这个前提做实，代价是一行都渲染不出来。
 */
const NO_MATCH_QUERY = 'zzzznope'

test.describe('@p2 文件对比（数据管理）', { tag: ['@p2', '@data'] }, () => {
  test('面板控件齐全：文件选择/阈值/规则/序列勾选器/ignore 勾选', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    // 两个文件选择器
    await expect(elSelectByPlaceholder(section, '文件1 (ATE)')).toBeVisible()
    await expect(elSelectByPlaceholder(section, '文件2 (Bench)')).toBeVisible()

    // 误差阈值输入（默认 3，precision 1 → 显示 "3.0"）
    const threshold = section.locator('.fc-opt').filter({ hasText: '误差阈值' }).locator('.el-input-number input')
    await expect(threshold).toBeVisible()
    await expect(threshold).toHaveValue('3.0', { timeout: 5000 })

    // Limit Diff 规则单选：默认 A（Diff 必须为 0）
    const ruleGroup = section.locator('.el-radio-group').first()
    await expect(ruleGroup.locator('.el-radio-button').filter({ hasText: 'A：Diff 必须为 0' }))
      .toHaveClass(/is-active/)

    // 规则 C：选中后出现「变化容差」输入（默认 30.0），切回 A 后隐藏
    await ruleGroup.locator('.el-radio-button').filter({ hasText: 'C：变化' }).click()
    const tol = section.locator('.fc-opt').filter({ hasText: '变化容差' }).locator('.el-input-number input')
    await expect(tol).toBeVisible()
    await expect(tol).toHaveValue('30.0', { timeout: 5000 })

    /*
     * 盒宽判据（2026-10-24 普查）。这两个控件写了显式 `style="width: 92px"`，
     * 1280×720 实测 **外层 92 / 内部 <input> 30** —— 外层等于声明值 ⇒ **没有**被同级
     * 文案挤过（export-timeout 那个同型缺陷的形状是外层 150→84、内部→0），所以外层阈值
     * 按「不得小于声明宽」取 90。
     * ⚠ 内部 30px 是这版设计自己的取舍（`.fc-opt` 是 label 在上的列布局，控件窄不是挤压）；
     *   要不要把 92px 加宽属视觉取向，**待拍板**，本用例不替它决定，只防它退化成挤没。
     */
    for (const opt of ['误差阈值', '变化容差']) {
      const box = section.locator('.fc-opt').filter({ hasText: opt }).locator('.el-input-number').first()
      const outer = await box.boundingBox()
      expect(outer?.width, `${opt}：外层小于声明的 92px，说明被同级内容挤过`).toBeGreaterThanOrEqual(90)
      const inner = await box.locator('input').first().boundingBox()
      expect(inner?.width, `${opt}：内部 <input> 归零，用户看不见也点不着`).toBeGreaterThanOrEqual(20)
    }

    await ruleGroup.locator('.el-radio-button').filter({ hasText: 'A：Diff 必须为 0' }).click()
    await expect(tol).toHaveCount(0)

    // 序列选择器（替换原「序列上限」输入框）：未选文件时提示仅对比 Limit
    await expect(elSelectByPlaceholder(section, '搜索序列号')).toBeVisible()
    await expect(section.locator('.fc-serial-hint')).toContainText('无公共序列，仅对比 Limit')

    // ignore no limit / ignore no data 默认不勾选（2026-09-09 需求 5）
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Limit' })).not.toHaveClass(/is-checked/)
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Data' })).not.toHaveClass(/is-checked/)

    // 分析 / 导出按钮
    await expect(section.getByRole('button', { name: '分析', exact: true })).toBeVisible()
    await expect(section.getByRole('button', { name: '导出Excel' })).toBeVisible()
  })

  test('选两文件 → 默认前10颗 → 分析 → 测试值表格 → 切 Limit 视图', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    await pickFilePair(section, page)

    // 公共序列加载完成 → 默认勾选前 10 颗
    const hint = section.locator('.fc-serial-hint')
    await expect(hint).toContainText(BASELINE_HINT, { timeout: 15_000 })

    await section.getByRole('button', { name: '分析', exact: true }).click()

    // 总结卡片
    const summary = section.locator('.fc-summary')
    await expect(summary).toBeVisible({ timeout: 30_000 })
    await expect(summary.locator('.metric-card').first().locator('.metric-label')).toContainText('公共序列')
    await expect
      .poll(
        () => summary.locator('.metric-card').first().locator('.metric-value').textContent(),
        { timeout: 10_000 },
      )
      .toMatch(/\d+/)

    // 默认视图 = 测试值对比：Parameters + Data A 的 Limit/单位 + 判定 + 每序列块；
    // B 侧 Limit（LSL B/USL Diff）不在本视图。
    // 注意：ignore 开关默认关闭（2026-09-09 需求 5）后，无 limit 的元数据行
    // （Part_No 等，unit 列文案恰为 "Unit"）也进入数据视图 → 取首个（表头）
    const table = section.locator('.fc-table')
    await expect(table).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-table-info')).toContainText('Data A VS Data B')
    await expect(table.getByText('Parameters', { exact: true })).toBeVisible()
    await expect(table.getByText('LSL A', { exact: true })).toBeVisible()
    await expect(table.getByText('USL A', { exact: true })).toBeVisible()
    await expect(table.getByText('Unit', { exact: true }).first()).toBeVisible()
    await expect(table.getByText('判定', { exact: true })).toBeVisible()
    await expect(table.getByText('ATE', { exact: true }).first()).toBeVisible()
    await expect(table.getByText('LSL B', { exact: true })).toHaveCount(0)
    await expect(table.getByText('USL Diff', { exact: true })).toHaveCount(0)
    // ag-grid 行 + 判定单元格（虚拟化后 DOM 仍渲染首屏行）
    await expect(table.locator('.ag-row').first()).toBeVisible({ timeout: 20_000 })
    await expect(table.locator('.fc-verdict-cell').first()).toBeVisible()

    // 切换 Limit 对比视图：Limit 列齐全、无序列块
    await section.locator('.el-radio-button').filter({ hasText: 'Limit 对比' }).click()
    await expect(table.getByText('LSL A', { exact: true })).toBeVisible()
    await expect(table.getByText('USL Diff', { exact: true })).toBeVisible()
    await expect(table.getByText('LSL B', { exact: true })).toBeVisible()
    await expect(table.getByText('USL B', { exact: true })).toBeVisible()
    await expect(table.getByText('ATE', { exact: true })).toHaveCount(0)
    await expect(table.getByText('% Diff', { exact: true })).toHaveCount(0)

    // 切回测试值对比
    await section.locator('.el-radio-button').filter({ hasText: '测试值对比' }).click()
    await expect(table.getByText('ATE', { exact: true }).first()).toBeVisible()
    await expect(table.getByText('LSL B', { exact: true })).toHaveCount(0)
    await expect(table.getByText('LSL A', { exact: true })).toBeVisible()
  })

  test('切走其它 tab 再切回：结果保留（重型表格 v-if 卸载/重挂回归）', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(BASELINE_HINT, { timeout: 15_000 })
    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 20_000 })

    // 切到「文件列表」再切回：表格（v-if）重新挂载且结果仍在
    await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()
    await expect(page.locator('.tab-btn').filter({ hasText: '文件列表' })).toHaveClass(/active/)
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()
    await expect(section.locator('.fc-summary')).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 20_000 })
    await expect(section.locator('.fc-serial-hint')).toContainText(BASELINE_HINT)
  })

  test('序列勾选：搜索 Enter 全选匹配 / 清空 → 仅对比 Limit', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(BASELINE_HINT, { timeout: 15_000 })

    // 打开序列下拉 → 过滤 '1' → Enter 全选匹配（与搜索测试项一致的交互）。
    // 注意：已选序列后占位文本消失，不能再用占位符定位 → 用容器 class；
    // 下拉 teleport 到 body，footer 提示必须从**本控件自己的** popper 里取
    // （`popper-class` 是实例级身份，谓词见 helpers/elplus.ts 的 SERIAL_POPPER +
    // `popperOf`：本页还有两个文件选择器的 .el-select-dropdown，收起的过渡帧里
    // 全局 :visible 会挑中正在退出的那一份）。
    const serialSel = section.locator('.fc-serial-sel .el-select')
    const serialPopper = popperOf(page, SERIAL_POPPER)
    // 首击即开（automatic-dropdown）且组件在打开时显式聚焦过滤框（EP 2.14 会把
    // 焦点困在 tabindex=-1 wrapper 上，不补聚焦则打字丢失）→ 打开即可直接打字
    await serialSel.click()
    await expect(serialPopper).toBeVisible()
    // 未输入关键词时 footer 那句不许出现（`v-if="kw && matches.length > 0"`）—— 与 col 族
    // view-data.spec.ts:739 同一条反例，挡「复制了 footer 却不接 kw」显示「匹配 0 项」这种谎话
    await expect(serialPopper.locator('.match-hint')).toHaveCount(0)
    await page.keyboard.type('1')
    const matchHint = serialPopper.locator('.match-hint')
    await expect(matchHint).toContainText('按 Enter 全选', { timeout: 5000 })
    // Enter **之前**取匹配数：Enter 后 selectMatches() 会清空过滤，footer 提示随之消失。
    const matchedCount = Number(/匹配 (\d+) 项/.exec((await matchHint.textContent()) ?? '')?.[1])
    // 前提（界由基线推出来，不是经验值）：v2 自己的 Enter 最多加 1 颗 ⇒ 要让下面
    // 「已选 ≥ min(匹配数, 200)」那句在 Enter 被 v2 抢走时**必红**，匹配数必须严格大于
    // 基线 + 1：只要求 > 基线的话，匹配数恰好 = 基线 + 1 时「v2 抢走 Enter 多加 1 颗」
    // 也能凑到同一个数。另一半界须 > MAX_WINDOW_ROWS，否则下面那条窗口行数判据恒真（红了换关键词，别删用例）。
    expect(
      matchedCount,
      `搜 '1' 只匹配 ${matchedCount} 项：撑不起「全选 vs 只选高亮」，也让窗口行数那条判据失去牙齿`,
    ).toBeGreaterThan(Math.max(BASELINE_SERIALS + 1, MAX_WINDOW_ROWS))
    /*
     * 反截断正向判据（Task 9B 给五族补齐的那两条，形式与 param-dropdown-full-list 逐字同构）：
     *  - 行数：已过滤状态下量，候选就是上面那个 matchedCount（2026-11-13 现测 1,113 项）。
     *    挡的回退只有一种：**虚拟化没生效 / 有人把候选集原样挂回 DOM**（迁回 el-select，
     *    或给 v2 配一个不裁剪的渲染层）—— 那种实现下这一屏是 1,113 行而不是约 11 行。
     *    footer 与下面「已选 ≥ min(N, 上限)」两条在同一个实现下一样会绿，只有这条兜得住。
     *    界与推导在 helpers/selectV2.ts；红了是换关键词（要匹配数 > 界），不是把这条删掉。
     *  - footer 逐字：现存的 `toContainText('按 Enter 全选')` 与那条 `匹配 (\\d+) 项` 的解析
     *    合起来仍放得过「匹配 N 项，按 Enter 全选，仅显示前 300」这种文案（两支各自都还成立），
     *    整串比掉才叫逐字。N 是从这句 DOM 里解析的，它的**数值**正确性不由本条兜 ——
     *    由下面 Enter 之后那句「已选 ≥ min(matchedCount, MAX_SELECTED)」跨源兜（DOM 计数 vs 已选集）。
     */
    await expectWindowRows(windowItems(page, SERIAL_POPPER), matchedCount, '序列下拉（搜 "1" 后）')
    await expect(matchHint).toHaveText(`匹配 ${matchedCount} 项，按 Enter 全选`)
    await page.keyboard.press('Enter')
    // 形状判据（原有，保持不动）+ 语义判据：已选数必须严格大于基线
    await expect
      .poll(() => section.locator('.fc-serial-hint').textContent())
      .toMatch(/已选 (\d+) \/ 共 \d+ 颗/)
    await expect
      .poll(() => selectedSerialCount(section), { timeout: 10_000 })
      .toBeGreaterThan(BASELINE_SERIALS)
    const afterEnter = await selectedSerialCount(section)
    // 并集 ⊇ 匹配集 ⇒ 已选数至少等于匹配数（超过 200 时被 MAX_SELECTED 裁到 200）。
    // 这一句才是「Enter 归组件而不是归 v2」的量级证据。
    // ⚠ 病状值是**基线本身**，不是「基线 +1」：2026-11-13 变异实测（把 onSelectKeydown 的
    // Enter 分支改成不拦截）红在上一句 `Expected: > 10, Received: 10` —— v2 自己选中的那个
    // 高亮项本来就在默认勾选的前 10 颗里，多选它净增 0 颗。所以上一句那个 `> 基线` 就是
    // 「Enter 到底归谁」的开关；下面这句给出量级。
    // 同轮现测：种子对 BPD60320_FT/BPD60320_QA1 搜 '1' 匹配 1113 项 ⇒ 下面等价于断
    // 「已选 ≥ 200」，而 clamp 的上界正是 200，所以 Enter 后已选恰好 200
    // （v2 的 :multiple-limit 没有把这条 emit 半路截掉）。
    expect(afterEnter).toBeGreaterThanOrEqual(Math.min(matchedCount, MAX_SELECTED_SERIALS))

    /*
     * 命名陷阱判据（Task 6 复审的「头号陷阱」，此前在现仓**零覆盖**）。
     *
     * 组件里那个 computed 必须叫 `selectOptions`、不能叫 `options`：props 已有
     * `options: number[]`（= 全部公共序列），两边同名时模板解析的是 setup 里的那个 computed，
     * `:disabled="options.length === 0"` 就从「有没有公共序列」变成「过滤后有没有匹配项」。
     * **空关键词时两者恰好等价**（computed 那支返回全量）⇒ 本文件其余用例在它改名后照样全绿
     * （2026-11-13 变异实测），唯一露馅的时刻是「搜一个匹配不到的串」。下面这段就是那个时刻。
     *
     * 位置选在 Enter 全选**之后**：那时面板还开着（selectMatches 只清过滤框、不收面板），
     * 不必重开下拉，也不用再碰文件选择器。
     */
    await page.keyboard.type(NO_MATCH_QUERY)
    // 前提坐实「匹配集为空」：footer 的「按 Enter 全选」是 `v-if="kw && matches.length > 0"`
    // ⇒ 消失；el-select-v2 在 `filteredOptions.length === 0` 时渲染 #empty 槽（组件里那支
    // `.empty-hint`「无匹配序列」）。两句在正确实现与注入的 bug 下**都成立**，它们不判别，
    // 只保证下面那句禁没禁的判断不是建立在「其实还有匹配项」上。
    await expect(matchHint).toHaveCount(0)
    await expect(serialPopper.locator('.empty-hint')).toBeVisible()
    // 病状判据：匹配集为空**不等于**没有公共序列 ⇒ 控件不许变成禁用态。
    // 定位器按 EP 2.14 源码取：`select-v2/src/select.mjs:55-61` 把 `is("disabled", selectDisabled)`
    // 挂在 `.el-select__wrapper` 上，**不在** `.el-select` 根节点 —— 写根节点这条会恒绿。
    await expect(serialSel.locator('.el-select__wrapper')).not.toHaveClass(/is-disabled/)
    // 反向防呆：上面那句若写歪成恒真（定位器指向根本没这个类的节点），这里清掉关键词后
    // 已选数必须还是 Enter 那次的值 —— 打字/清理都不该动到选择，动到了就是这段写坏了。
    await serialSel.locator('input').first().fill('')
    await expect.poll(() => selectedSerialCount(section), { timeout: 10_000 }).toBe(afterEnter)
    await expect(serialSel.locator('.el-select__wrapper')).not.toHaveClass(/is-disabled/)
    await page.keyboard.press('Escape')

    /*
     * clearFilterInput 判据（批4 刀五a，T3）：**关掉之后，关键词不得残留**。
     *
     * 判的是 `kw` 派生的 UI，不是 input 的值：EP v2 在 `watch(expanded)` 的 `expanded:false`
     * 分支里自己把 `states.inputValue` 置空（`select-v2/src/useSelect.mjs`）⇒「关后 input
     * 为空」在组件侧一行清理都没有时也成立，那句只作辅助。
     *
     * 为什么残留会露馅：公共序列是 `number[]`，label 走 `String(序列号)` ⇒ 只可能是数字，
     * 字母关键词永不命中；`kw` 一旦没清，`selectOptions = toOptions(matches)` 就是空数组
     * ⇒ `#empty` 槽（`.empty-hint`「无匹配序列」）顶掉整个候选列表。空关键词时它回到全量。
     *
     * ⚠ 承重的是**收起那一刻**的隐藏面板，不是重开后的面板：`persistent` 默认 true
     * （`select-v2/src/defaults.mjs:188`）⇒ 收起的 popper 内容仍挂在 DOM，漏清时它里面就
     * 只剩一条 `.empty-hint`、候选 0 行。而**重开时 v2 自己会洗掉组件的 `kw`**：同一个
     * `watch(expanded)` 的 `if (val)` 支调 `handleQueryChange("")` → `filterMethod("")`
     * ⇒ `filterText = ''`。2026-11-19 变异实测：注释掉关闭分支的 `clearFilterInput()` 后，
     * 「重开后 `.empty-hint` 为 0」照样绿（隐藏面板里那条是 1）—— 所以重开那几句只当
     * 用户可见的收尾，牙齿全在下面那对 `[aria-hidden="true"]` 判据上。
     *
     * 关面板必须**点外部**、不能用 Escape：`select-v2/src/useSelect.mjs` 的 `handleEsc`
     * 在 `inputValue` 非空时只清 query、不收面板 —— 那等于替被测的 `clearFilterInput`
     * 把关键词洗掉，变异就证不出红。
     */
    await serialSel.click()
    await expect(serialPopper).toBeVisible()
    await page.keyboard.type(NO_MATCH_QUERY)
    await expect(serialPopper.locator('.empty-hint')).toBeVisible()
    // 点外部用控件**上方**那行 label，不点下面的 `.fc-serial-hint`：下拉面板正从控件下方展开，
    // 会盖住那行提示文案（2026-11-19 实测换成点它 ⇒ 红在 `<div class="empty-hint">无匹配序列</div>
    // … intercepts pointer events`，重试 15s 后 timeout）。
    // 这条 label 没有 for= ⇒ 点它既不聚焦控件也不触发任何 handler，只走 v2 的
    // `handleClickOutside` → expanded=false → visible-change(false)。
    await section.locator('.fc-opt-label').filter({ hasText: '对比序列' }).click()
    await expect(serialPopper).toBeHidden()
    // ↓ 承重：收起的那份 popper（`aria-hidden="true"`）里 kw 必须已被组件清掉
    const hiddenSerialPopper = page.locator(`.el-popper.${SERIAL_POPPER}[aria-hidden="true"]`)
    await expect(
      hiddenSerialPopper.locator('.empty-hint'),
      '收起后 kw 已被清 ⇒ 隐藏面板里不该留下「无匹配序列」',
    ).toHaveCount(0)
    // 轮询而不是取一次快照：候选是收起那一刻才重新挂回的，差一帧就读到 0 行 —— 那是
    // 时序噪声，不是漏清。真正漏清的实现永远停在 0 行（与上一条 `.empty-hint` 互为正反证）。
    await expect
      .poll(
        () => hiddenSerialPopper.locator('.el-select-dropdown__item').count(),
        { message: '收起那份 popper 里应挂回全量候选；实测漏清时这里恒为 0 行' },
      )
      .toBeGreaterThan(0)
    // 用户可见收尾，不承重：重开后面板同样是全量（v2 自己也会洗 query）
    await serialSel.click()
    await expect(serialPopper).toBeVisible()
    await expect(serialPopper.locator('.empty-hint')).toHaveCount(0)
    await expect(serialPopper.locator('.match-hint')).toHaveCount(0)
    await expect(serialSel.locator('input').first()).toHaveValue('')
    // 前提：重开后的候选数（= 全量公共序列，从提示文案的「共 N 颗」取）必须远大于窗口界，
    // 否则「没有 .empty-hint」在漏清与清干净两种实现下都成立，上面那两条就没有牙齿。
    const totalSerials = Number(
      /共 (\d+) 颗/.exec((await section.locator('.fc-serial-hint').textContent()) ?? '')?.[1],
    )
    expect(totalSerials, '候选数须大于窗口界，否则上面那条没有牙齿').toBeGreaterThan(MAX_WINDOW_ROWS)
    await expectWindowRows(windowItems(page, SERIAL_POPPER), totalSerials, '序列下拉（收起后隐藏面板无残留过滤）')
    await page.keyboard.press('Escape') // 空关键词 ⇒ EP 真的收起面板（非空时 handleEsc 只清 query）
    await expect(serialPopper).toBeHidden()

    // 全选按钮 → 触达上限（提示形状「已选 N / 共 M 颗（最多 N）」只在已选数触顶时出现）
    // ⚠ 这条路走的是组件的 selectAll()→clamp()，**不经过** v2 的 :multiple-limit
    // （那个只约束「在面板里点选」）；上面 Enter 那条的匹配集若超过上限，clamp 同样
    // 把它裁到上限 —— 两处都由组件的 MAX_SELECTED 兜底，本用例的上限判据对两者都成立。
    await section.getByRole('button', { name: '全选' }).click()
    await expect
      .poll(() => section.locator('.fc-serial-hint').textContent())
      .toMatch(
        new RegExp(`已选 ${MAX_SELECTED_SERIALS} / 共 \\d+ 颗（最多 ${MAX_SELECTED_SERIALS}）`),
      )

    // 清空 → 未选择提示
    await section.getByRole('button', { name: '清空' }).click()
    await expect(section.locator('.fc-serial-hint')).toContainText('未选择')

    // 空选 → 分析 → limits_only 防呆提示
    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-alert')).toContainText('没有可对比的序列', { timeout: 15_000 })
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 15_000 })
  })

  test('规则C 双侧容差：放宽过度标 FAIL，调大容差回 PASS', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(BASELINE_HINT, { timeout: 15_000 })

    // 选规则 C（默认容差 30）→ 分析 → Limit 视图
    await section.locator('.el-radio-group').first()
      .locator('.el-radio-button').filter({ hasText: 'C：变化' }).click()
    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 30_000 })
    await section.locator('.el-radio-button').filter({ hasText: 'Limit 对比' }).click()

    // 汇总卡文案插值实际容差（2026-09-09 规则C 升级双侧容差）
    await expect(section.locator('.fc-summary'))
      .toContainText('规则C：B 变化幅度 ≤ 30% 允许', { timeout: 15_000 })

    // 种子对 lkg_VCC_SNSP_6V：A -50/50 → B -70/70（放宽 40% > 30）→ FAIL
    const wideRow = section.locator('.el-table__row').filter({
      has: page.getByText('lkg_VCC_SNSP_6V', { exact: true }),
    })
    await expect(wideRow.locator('.verdict-badge')).toHaveText('FAIL', { timeout: 15_000 })

    // 容差调到 50 → 重新分析 → 同一行回 PASS（容差驱动放宽判定）
    const tol = section.locator('.fc-opt').filter({ hasText: '变化容差' }).locator('.el-input-number input')
    await tol.fill('50')
    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(wideRow.locator('.verdict-badge')).toHaveText('PASS', { timeout: 30_000 })
  })

  test('跨程序同名异拼法（仅大小写不同）测试项仍配对，系统列不冒充测试项', async ({ page }) => {
    // 回归（2026-09-20 用户 DebugData 报告）：CTA8290D 写 lkg_Vin_8V、
    // CTA8280F 写 lkg_VIN_8V，精确名比较会把它判成「两文件没有的项」→ 缺项。
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })

    // 与 `pickFilePair` 同一形状：FileSelect 走 `el-select-v2` 后 DOM 只有虚拟窗口那约 10 行，
    // 不过滤就点等于赌目标文件恰在首屏（2026-11-22 收口）。先填文件名再点。
    const file1 = elSelectByPlaceholder(section, '文件1 (ATE)')
    await file1.click()
    await expect
      .poll(() => visibleSelectOptions(page).count(), { timeout: 15_000 })
      .toBeGreaterThan(0)
    await file1.locator('input').first().fill(SEEDED_FILES.CTA8290D_FT)
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.CTA8290D_FT }).first().click()
    await page.waitForTimeout(600)
    const file2 = elSelectByPlaceholder(section, '文件2 (Bench)')
    await file2.click()
    await file2.locator('input').first().fill(SEEDED_FILES.CTA8280F_FT)
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.CTA8280F_FT }).first().click()
    await page.waitForTimeout(600)

    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 30_000 })
    await section.locator('.el-radio-button').filter({ hasText: 'Limit 对比' }).click()

    // 文件 A 的拼写入表 → 忽略大小写配对成功（修前此行不存在）
    await expect(
      section.locator('.el-table__row').filter({ hasText: 'lkg_Vin_8V' }).first(),
    ).toBeVisible({ timeout: 15_000 })

    // 记录级系统列已按格式剔除，不冒充测试项（修前 X_COORD 会稳定判 FAIL）
    await expect(section.locator('.el-table__row').filter({ hasText: 'X_COORD' })).toHaveCount(0)
    await expect(section.locator('.el-table__row').filter({ hasText: 'Site_No' })).toHaveCount(0)
  })

  test('导出 Excel 触发模板命名下载', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)

    const downloadPromise = page.waitForEvent('download')
    await section.getByRole('button', { name: '导出Excel' }).click()
    const download = await downloadPromise
    // 默认导出文件名模板：{file1}_vs_{file2}_correlation.xlsx
    expect(download.suggestedFilename()).toMatch(/BPD60320_FT_vs_BPD60320_QA1_correlation\.xlsx/)
  })

  test('Limit 视图判定列排序：FAIL 排前 → 反向 PASS 在前', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(BASELINE_HINT, { timeout: 15_000 })

    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 30_000 })

    await section.locator('.el-radio-button').filter({ hasText: 'Limit 对比' }).click()
    const table = section.locator('.fc-table')
    const verdictHeader = table.getByText('判定', { exact: true })
    await expect(verdictHeader).toBeVisible()

    const firstRowVerdict = () =>
      table.locator('.el-table__row').first().locator('.verdict-badge').textContent()

    // 升序（第一次点击）：FAIL rank 0 → 在前（种子对 limit 有同有异，FAIL/PASS 均存在）
    await verdictHeader.click()
    await expect.poll(firstRowVerdict, { timeout: 10_000 }).toBe('FAIL')
    // 降序（第二次点击）：PASS 在前
    await verdictHeader.click()
    await expect.poll(firstRowVerdict, { timeout: 10_000 }).toBe('PASS')
  })
})

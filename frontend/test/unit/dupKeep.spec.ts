/**
 * T2：重复项保留选择的纯函数层（批3a · 第 3 项）。
 *
 * 跑：cd frontend && npx vitest run test/unit/dupKeep.spec.ts
 *
 * 判据异源：所有期望值都是手写字面量（组数、字节数、id、整句文案）。
 * 拿实现去算期望值等于让同一段代码给自己盖章 —— 档/取整/键拼法错了会一起错。
 *
 * 组件层不在这里：卡片渲染由 T3（duplicate-keep.spec.ts）钉，接线形状由
 * dupKeepWiring.spec.ts 的源侧绊线钉。本层不起组件（本仓无 jsdom）。
 */
import { describe, expect, it } from 'vitest'
import {
  STRATEGY_LABELS,
  applyStrategyToUntouched,
  deleteSummary,
  deleteSummaryText,
  groupKey,
  keepIdForGroup,
  resolveKeepIds,
  remainingGroupsNote,
  strategyKeepId,
  truncatedNoteText,
  dupImportText,
} from '../../src/utils/dupKeep'
import type { DuplicateGroup } from '../../src/api/datafiles'

function files(...pairs: Array<[number, string, number?]>) {
  // [id, created_at, file_size?] —— **一个文件一个三元组**，不要把多个文件写进同一条扁平
  // 数组：`files([10, 't1', 11, 't2'])` 在 helper 眼里只是「id=10、时间=t1、大小=11」这**一个**
  // 文件（第 4 个元素超出元组长度），组里就只剩 1 份 ⇒ 该删 0 个、策略永远退回 files[0]。
  // 这种形状 TS 会报 TS2345，`npm run build`（vue-tsc -b 含 test/unit）拦得住，别关掉它。
  // file_size 缺省 500，与所属组一致（分组键含它 ⇒ 组内恒等）。
  return pairs.map(([id, created_at, file_size]) => ({
    id,
    filename: 'x.csv',
    file_size: file_size ?? 500,
    file_type: 'single' as const,
    batch_name: '',
    sub_batch: '',
    created_at,
  }))
}

function group(filename: string, members: ReturnType<typeof files>, size = 500): DuplicateGroup {
  return { filename, file_size: size, files: members }
}

describe('groupKey', () => {
  it('同名同大小同组，任一维不同就换组', () => {
    expect(groupKey(group('a.csv', files([1, 't'])))).toBe('a.csv|500')
    expect(groupKey(group('a.csv', files([1, 't']), 600))).toBe('a.csv|600')
    expect(groupKey(group('A.CSV', files([1, 't'])))).toBe('A.CSV|500')
    expect(groupKey(group('a.csv', files([1, 't'])))).toBe(groupKey(group('a.csv', files([2, 't']))))
    expect(groupKey(group('a.csv', files([1, 't'])))).not.toBe(groupKey(group('b.csv', files([1, 't']))))
  })
  it('文件名里带竖线也不与别的组撞键', () => {
    // 'a|500' 大小 1000 与 'a' 大小 5001000… 之类的拼法歧义：右段恒为数字，
    // 想撞必须让左段吃掉一个 '|' 后右段仍是同一个数 —— 构造不出来，钉两条实测值。
    expect(groupKey(group('a|500', files([1, 't']), 1000))).toBe('a|500|1000')
    expect(groupKey(group('a', files([1, 't']), 500))).toBe('a|500')
    expect(groupKey(group('a|500', files([1, 't']), 1000))).not.toBe(groupKey(group('a', files([1, 't']), 500)))
  })
})

describe('保留项裁决', () => {
  const g = group('a.csv', files([10, '2026-01-02T00:00:00+00:00'], [11, '2026-01-01T00:00:00+00:00']))
  it('未改选时用默认保留项 = files[0] = id 最小', () => {
    expect(keepIdForGroup(g, new Map())).toBe(10)
  })
  it('改选过的组用改选值', () => {
    expect(keepIdForGroup(g, new Map([['a.csv|500', 11]]))).toBe(11)
  })
  it('策略「最早/最新」比 created_at，与 id 大小无关', () => {
    // 两条是「后端会给的样子」：id 升序，但时间与 id 倒挂（id 大的那条反而更早导入）
    expect(strategyKeepId(g, 'earliest')).toBe(11)
    expect(strategyKeepId(g, 'latest')).toBe(10)
  })
  it('created_at 相同时裁决落在 id 最小（靠 files 已升序，不靠额外比 id）', () => {
    const same = '2026-01-01T00:00:00+00:00'
    const tie = group('t.csv', files([29, same], [30, same]))
    expect(strategyKeepId(tie, 'earliest')).toBe(29)
    expect(strategyKeepId(tie, 'latest')).toBe(29)
    expect(keepIdForGroup(tie, new Map())).toBe(29)
    // 反向探针：数组顺序反过来就不是这个形状了（Task 3 有一条 T1 钉后端不会给这种输入）
    const flipped = group('t.csv', files([30, same], [29, same]))
    expect(strategyKeepId(flipped, 'earliest')).toBe(30)
  })
  it('只有两颗策略：体积最大是谎话控件，已作废', () => {
    // 重复判定口径是 (filename, file_size) 精确相等 ⇒ 组内 file_size 恒等（实测 73/73 组），
    // 「体积最大」在数学上永远等于「按 id 最小」。谁加回来这条就红。
    expect(Object.keys(STRATEGY_LABELS).sort()).toEqual(['earliest', 'latest'])
    // 基数之外还要钉**文案归谁**：只比 keys 时，把两枚 label 互换（点「最早导入」拿到最新那份）
    // 是 16 例全绿的（2026-11-15 复审变异 MF）—— 那颗按钮照样是谎话控件，只是换了个谎法。
    expect(STRATEGY_LABELS.earliest).toBe('最早导入')
    expect(STRATEGY_LABELS.latest).toBe('最新导入')
  })
})

describe('applyStrategyToUntouched', () => {
  const a = group('a.csv', files([10, '2026-01-01T00:00:00+00:00'], [11, '2026-01-02T00:00:00+00:00']))
  const b = group('b.csv', files([20, '2026-01-01T00:00:00+00:00'], [21, '2026-01-02T00:00:00+00:00']))
  it('只覆盖未改选的组，改选过的原样保留', () => {
    const before = new Map<string, number>([['b.csv|500', 20]])
    const after = applyStrategyToUntouched([a, b], before, 'latest')
    expect(after.get('a.csv|500')).toBe(11)
    // 说明文字挂在 expect(value, message) 上，不是 toBe 的第二参（toBe 只收一个参数，
    // 写错位置会 TS2554，且运行时那句话根本不会出现在失败信息里）。
    expect(after.get('b.csv|500'), '用户手选过的那组不许被一键策略覆盖').toBe(20)
    expect(before.get('a.csv|500'), '原 Map 必须不被就地改').toBeUndefined()
  })
})

describe('resolveKeepIds', () => {
  it('每组一枚、按 groups 顺序、含未改选的默认值', () => {
    // 归因：`[10, 20]` 钉**顺序**，`[10, 21]`（空 choice）钉**逐组全覆盖** ——
    // 后者就是「前端退化成只上报改选过的组」那个回退的拦阻（2026-11-15 变异实测 1 红）。
    // 后端对白名单内的部分覆盖照样返回 200、未列出的组按默认留最早 ⇒ 这个回退在 T1/T3 都不可见，
    // 只有这一条看得见，别再把它当重复断言删掉。
    const a = group('a.csv', files([10, 't1'], [11, 't2']))
    const b = group('b.csv', files([21, 't1'], [20, 't2']))
    expect(resolveKeepIds([a, b], new Map([['b.csv|500', 20]]))).toEqual([10, 20])
    expect(resolveKeepIds([a, b], new Map())).toEqual([10, 21])
    expect(resolveKeepIds([], new Map())).toEqual([])
  })
})

describe('汇总与文案', () => {
  const g2 = group('a.csv', files([1, 't'], [2, 't']), 500)
  const g3 = group('b.csv', files([3, 't', 1024], [4, 't', 1024], [5, 't', 1024]), 1024)
  it('deleteSummary 只数已展示组：每组删 (len-1) 个', () => {
    expect(deleteSummary([g2, g3])).toEqual({ count: 3, bytes: 500 + 2 * 1024 })
  })
  it('按钮文案把数字来自当前选择，不写死「全部」', () => {
    expect(deleteSummaryText([g2, g3])).toBe('按选择删除 3 个（2.5 KB）')
    expect(deleteSummaryText([g2])).toBe('按选择删除 1 个（500 B）')
  })
  it('truncatedNote：超过切片才说话，且说的是本批处理多少', () => {
    expect(truncatedNoteText(73, 50)).toBe(
      '共 73 组重复，本批处理前 50 组，其余 23 组本批不处理，重新检查后可继续。',
    )
    expect(truncatedNoteText(50, 50)).toBe('')
    expect(truncatedNoteText(1, 1)).toBe('')
  })
  it('旧的「删除操作将作用于全部」这句必须消失', () => {
    // 独立输入（51/50 而不是上一例用过的 73/50）：同输入时这句被上面那条 toBe
    // 严格蕴含，永远出不了声 —— 2026-11-15 复审判它是装饰性断言。
    expect(truncatedNoteText(51, 50)).not.toMatch(/作用于全部|仅显示/)
    expect(truncatedNoteText(73, 51)).not.toMatch(/作用于全部|仅显示/)
    // M12 同族：删前这句**不许承诺已经处理完**（`本批不处理` 必须在），
    // 也不许写成「未处理」那种听上去像实测的说法 —— 见下面判定①那条交叉断言。
    expect(truncatedNoteText(51, 50)).toMatch(/本批不处理/)
    expect(truncatedNoteText(51, 50)).not.toMatch(/已处理|已完成/)
  })
  it('remainingGroupsNote：0 组不啰嗦', () => {
    expect(remainingGroupsNote(0)).toBe('')
    expect(remainingGroupsNote(23)).toBe('，删除后仍判定为重复的有 23 组')
    // 0 由 `!remaining` 吃掉，负数与缺字段走 `<= 0` 那半 —— 不钉就是没人看管的分支
    expect(remainingGroupsNote(undefined)).toBe('')
    expect(remainingGroupsNote(-1)).toBe('')
  })
  it('删前那句与删后那句必须是**两个不同的说法**（终审 F2 判定①）', () => {
    // 同一个屏幕上卡片（删前算术：总组数 − 已展示）与 toast（删后服务端实测 remaining_groups）
    // 同时出现。共用「另有 N 组未处理」这个词就等于让算术值冒充实测值 —— 而
    // `_duplicate_files.py` 的 docstring 明写实测是**刻意**选的（部分失败时两者不等）。
    const card = truncatedNoteText(73, 50)
    const receipt = remainingGroupsNote(23)
    expect(card).not.toMatch(/仍判定为重复/)
    expect(receipt).not.toMatch(/未处理|本批不处理/)
    expect(card).not.toBe(receipt)
  })
  it('dupImportText 带年份（跨月的两份要分得出先后，短形态会跨年读错）', () => {
    expect(dupImportText('2026-08-10T14:09:42.332806+00:00')).toMatch(/2026/)
    expect(dupImportText('2026-08-10T14:09:42.332806+00:00')).not.toMatch(/[上下]午/)
    // 时钟分量必须有：同一天两次导入是这张卡的常态（实测样本差两个月，但重跑导入就差几秒），
    // 只剩日期时「最早/最新」两行的时间列逐字相同 —— 变异把 toLocaleString 换成
    // toLocaleDateString 后 16 例全绿（2026-11-15 复审 ME），就是缺这一条。
    expect(dupImportText('2026-08-10T14:09:42.332806+00:00')).toMatch(/\d{1,2}:\d{2}:\d{2}/)
    expect(dupImportText('')).toBe('--')
    expect(dupImportText('not-a-date')).toBe('--')
  })
})

import { describe, expect, it } from 'vitest'

import {
  BOUNDED_KEYWORD_MIN_MATCHES,
  BOUNDED_KEYWORD_SCAN_NAMES,
  countKeywordMatches,
  pickBoundedKeyword,
} from '../../e2e/helpers/boundedKeywordCore'

/**
 * T2：造关键词的**三条界**（扫描窗口 / 匹配下界 / 上限 cap）—— 纯核，不开浏览器。
 *
 * 为什么值得单独钉（与 `paramListGuard.spec.ts` 同一条理由）：`pickBoundedKeyword` 决定导出族
 * 那条用例「输入关键词 → Enter」一次选中多少个参数。它坏了在 e2e 里只有两种表现：① 干净地
 * throw「造不出关键词」（整条红，而归因要点开 e2e 才知道是启发式的问题）；② 选中上千项
 * （慢，而且「全选一小撮」那条分支根本没测到）。判定住进纯核后，假名字表就能逐条钉界。
 *
 * **判据异源纪律**：本文件钉的是「造关键词怎么判」，**不是**「真浏览器里 Enter 真选中了 N 项」——
 * 后者仍由 `e2e/exports/exports.spec.ts` 兜（footer 的 `匹配 N 项` 取组件渲染侧读数、
 * `已选 N / 共 M` 取交互结果，与本文件的假名字表无关）。别在这里假装验了浏览器行为。
 *
 * 每条用例都写明**它区分哪两种坏法**（Task 2 的教训：`sortPrefixFirst(['XPAR1','PAR1'],'PAR1')`
 * 在坏实现下也一样绿 ⇒ 恒真断言不算覆盖）。所有期望值都是手数出来的，反推写在注释里；
 * 名字表刻意避开真实参数名，免得哪天产品名单变了这里跟着抖。
 */

/** 首字符互不相同的填充名字表（`A1`/`B2`/…）：每个名字第 1 级前缀就只匹配它自己 */
const uniqueFirst = (n: number) =>
  Array.from({ length: n }, (_, i) => `${String.fromCharCode(65 + i)}${i + 1}`)

describe('阶梯跳带：从短往长试前缀，第一个落进 [2, cap] 的就是答案', () => {
  it('首个候选命中 / 必须跳到第二个候选 / 跨过整带 / 全部塌到下界以下', () => {
    // ① 首个候选命中：25 个 `A*` ⇒ 前缀 'a' 匹配 26 个 > cap=20，必须再走一级到 'a1' 才落进带里。
    //    'ZZZa1' 刻意排在**窗口之外**（下标 25）且 'a1' 只出现在中段：匹配规则写成 startsWith 就漏它。
    const fan = [...Array.from({ length: 25 }, (_, i) => `A${i + 1}`), 'ZZZa1', 'BZ2', 'BZ3']
    // ② 必须跳到第二个候选：'Q1' 的首字符全表唯一（匹配 1 个 < 下界）⇒ 那记 break 只该停掉
    //    **这一条名字**的阶梯，外层要继续试 'PAR1'。
    const jump = ['Q1', 'PAR1', 'PAR2']
    // ③ 跨过整带：cap=2 时 'a'/'aa' 都是 3 个（> cap），'aa1' 塌到 1 ⇒ 3 → 1 直接跨过 [2, 2]。
    const dense = ['AA1', 'AA2', 'AA3']
    // ④ 全部塌到下界以下：两个名字首字符互异，每个候选第 1 级就只有 1 个匹配。
    const sparse = ['A1', 'B2']

    expect({
      // 坏法一：不看上限 cap（`count >= 2` 就 return）⇒ 给出 {kw:'a', count:26}，导出侧一次选中 26 个；
      // 坏法二：把命中写成 startsWith / 忘了两侧转小写 ⇒ 'ZZZa1' 不进分子，得 {kw:'a1', count:11}。
      首个候选命中: pickBoundedKeyword(fan, 20),
      // 坏法一：把那记 break 理解成「整个搜索到此为止」（改成 return null、或 break 外层）⇒ null；
      // 坏法二：扫描窗口 < 2 个名字 ⇒ 连第二个候选都够不着，同样 null。
      跳到第二个候选: pickBoundedKeyword(jump, 20),
      // 坏法一：cap 判断丢掉 ⇒ {kw:'a', count:3}（越界值被当答案交出去）；
      // 坏法二：`count >= 2 && count <= cap` 的 `&&` 写成 `||` ⇒ 第一级就 return，同上越界。
      跨过整带: pickBoundedKeyword(dense, 2),
      // 坏法一：下界 2 丢掉（`count <= cap` 就 return）⇒ {kw:'a', count:1}：
      //        「全选匹配」退化成「选中一项」，而这正是下界存在的唯一理由（纯核注释里的原话）。
      全部塌到下界以下: pickBoundedKeyword(sparse, 20),
    }).toEqual({
      首个候选命中: { kw: 'a1', count: 12 }, // A1 + A10..A19 + ZZZa1 = 12，且 12 ≤ 20
      跳到第二个候选: { kw: 'p', count: 2 }, // PAR1 + PAR2；'q' 那一级被跳过而不是把整趟搜索带走
      跨过整带: null,
      全部塌到下界以下: null,
    })

    // 期望值 12 / 越界 26 的独立来源：不是把实现里那行 filter 抄一遍，是分开数出来的两个量。
    expect(countKeywordMatches(fan, 'a1')).toBe(12)
    expect(countKeywordMatches(fan, 'a')).toBeGreaterThan(20)
  })
})

describe('扫描窗口：只试前 BOUNDED_KEYWORD_SCAN_NAMES 个名字，这道界是真在拦', () => {
  it('首字符全唯一 ⇒ null；解从窗口外挪到窗口末位 ⇒ 结果必须翻', () => {
    // 窗口必须容得下 2 个名字，否则「跳到第二个候选」在本文件里没有对照物（也是纯核那条
    // 「换下一个名字」的语义失效的形状）——先把自己依赖的前提钉住。
    expect(BOUNDED_KEYWORD_SCAN_NAMES).toBeGreaterThan(1)

    // 唯一有解的一对名字（'Z1'/'Z2' 共享首字符 z）放在**窗口外的第一个下标**上。
    const beyond = [...uniqueFirst(BOUNDED_KEYWORD_SCAN_NAMES), 'Z1', 'Z2']
    // 同一份表少一个填充名字 ⇒ 那一对落进窗口最后一个位置。
    const inside = [...uniqueFirst(BOUNDED_KEYWORD_SCAN_NAMES - 1), 'Z1', 'Z2']

    expect({
      // 坏法一：下界丢掉 ⇒ 窗口内第一个名字就交出 {kw:'a', count:1}；
      // 坏法二：无视窗口、对全集扫 ⇒ 捞到窗口外的 'Z1' 返回 {kw:'z', count:2}。
      //        窗口是**代价**换的（上千项不做全量扫描）：它的对价就是「解藏在第 N+1 个名字里
      //        时造不出 ⇒ 红给调用方」，所以这里必须期望 null，改成全量扫描等于偷偷换了策略。
      解在窗口外: pickBoundedKeyword(beyond, 20),
      // 坏法：窗口边界差一个（少试一个名字 / slice 写反）⇒ 连窗口末位都够不着，退回 null。
      解在窗口末位: pickBoundedKeyword(inside, 20),
    }).toEqual({
      解在窗口外: null,
      解在窗口末位: { kw: 'z', count: 2 },
    })

    // 上面那条 null 的**成因**必须说得出：窗口内每个名字的首字符都只匹配它自己（低于下界），
    // 不是「碰巧数组没取到」。这条把 ① 与「窗口把解切掉了」两件事分开 —— 缺了它，
    // 「解在窗口外」这条 null 在「下界被丢掉」的实现下也会红，但红得看不出该怪哪一界。
    expect(countKeywordMatches(beyond, 'a')).toBeLessThan(BOUNDED_KEYWORD_MIN_MATCHES)
  })
})

describe('退化输入：契约是 null，不是抛、也不是「空串关键词」', () => {
  it('空数组 / 只有一个空串 / cap=0 三种退化形状都给 null', () => {
    // 空表是本判据最容易翻车的一档：调用方 `paramKeysFromHistogram` 明确允许「当前口径 0 项」
    // （见 params.ts 里 listParams 那段），所以 all=[] 是真实会传进来的形状。
    // 坏法一：实现改写成先取 `all[0]` 再量长度 ⇒ TypeError。e2e 侧表现为整条用例红在调用栈上，
    //        而不是干净的「造不出」，归因要点开浏览器 —— 抽纯核就是为了这一步能在 T2 里看见。
    // 坏法二：`?? { kw: '', count: 0 }` 这种「兜个默认值」⇒ 调用方 fill('') 等于不过滤，
    //        Enter 直接全选上千项：**比 null 危险得多，而且 e2e 那边全是绿的**（footer 会老实地
    //        写「匹配 M 项」，只是 M 是全集）。所以这里断的是 toBeNull，不是 toBeFalsy/不抛。
    expect({
      空表: pickBoundedKeyword([], 20),
      空表且cap退化到1: pickBoundedKeyword([], 1),
      唯一名字是空串: pickBoundedKeyword([''], 20),
      cap为0: pickBoundedKeyword(['PAR1', 'PAR2'], 0),
    }).toEqual({
      空表: null,
      空表且cap退化到1: null,
      唯一名字是空串: null,
      cap为0: null,
    })

    expect(countKeywordMatches([], 'a')).toBe(0)
  })
})

describe('cap 与下界的关系：[2, cap] 是**闭**区间，cap < 2 时它是空集', () => {
  it('cap=1 造不出（区间为空），而匹配数恰好等于 cap 时必须放行', () => {
    const pair = ['PAR1', 'PAR2'] // 现成的解是 'p'（匹配 2 个）
    expect({
      // 坏法一：cap 丢掉 / 给 cap 兜底下界（`Math.max(2, cap)`）⇒ 返回 {kw:'p', count:2}：
      //        调用方要「最多 1 个」被静默放宽成 2 个，上限这个参数就白传了；
      // 坏法二：下界丢掉 ⇒ 一路走到全名 'par1'（匹配 1 个）也当成答案返回 {kw:'par1', count:1}。
      // cap=1 时区间 [2,1] 本就是空集 ⇒ 唯一正确输出是 null（由调用方红，不是这里放行）。
      cap小于下界: pickBoundedKeyword(pair, 1),
      // 坏法：上限写成严格小于（`count < cap`）⇒ count === cap 这一档被拒，阶梯继续走长、
      //      最后塌到 1 ⇒ 退回 null。这在 e2e 侧是「明明有解却 throw 造不出关键词」的假红，
      //      而上面几条 cap 远大于匹配数的用例**全都抓不到**它 —— 边界只有这一条钉得住。
      匹配数等于cap: pickBoundedKeyword(pair, 2),
    }).toEqual({
      cap小于下界: null,
      匹配数等于cap: { kw: 'p', count: 2 },
    })
  })
})

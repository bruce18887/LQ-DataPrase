/**
 * T2：`e2e/admin/admin.spec.ts`（Task 11 起还有 `e2e/admin/audit.spec.ts`）的「残留前缀表」与
 * 「实际建号名字」不许各自漂移。
 *
 * 为什么要这颗绊线：该文件的 afterAll 有两条清理规则 —— `mine`（本 worker 建过的名字，无条件
 * 回收）与「命中残留前缀表 **且** 建号满 10 分钟」（跨轮尸体兜底）。前者只活在单个 worker 的内存
 * 里，worker 崩了就随它没了，跨轮兜底因此是**唯一**一道不依赖进程存活的闸。而那份表是手抄的：
 * 名字在每个建号用例里各写一次（模板串），表在 afterAll 的正则里只写一次，两处没有任何东西连着。
 * 再多一个家族（比如新加一条 `e2e_unlock_` 用例）一旦忘了进表，就**只有** `mine` 会收它 —— 平时
 * 全绿，直到某次 worker 崩掉，那个账号一直留在 e2e 的夹具库里（串行 = `test/e2e-data/db.sqlite3`，
 * 池 = 各 slot 自己那份，见 `docs/reference/testing-gates.md` §1），且没有任何测试会红。这正是本仓
 * 用源扫描 T2 钉死的形状（同 `roleLabelHygiene.spec.ts`、`localStorageHygiene.spec.ts`）。
 *
 * 判据三类、共 10 例（Task 11 起覆盖两份 spec：admin.spec.ts 七例 + audit.spec.ts 三例）：
 * ① 集合相等（双向，红字指名动的是哪一侧）+ 两侧非空；② 抽取器自证 —— 合成源
 * 里加一个家族，抽取集合必须真的长出来（否则 ① 是在比两个空集合），真实漂移形状（`edit`→`edit2`）
 * 要走等式而不是抛，表里抹掉一个家族要报缺，不认识的形状必须抛；③ 反向探针必须保持绿：改变量名 /
 * 换正则里分支的先后顺序，两侧集合都不许变（判据不能焊在版式上）。
 *
 * 跑：`cd frontend && npx vitest run test/unit/e2eTempAccounts.spec.ts`（node 环境，不开浏览器）
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const ADMIN_SPEC = new URL('../../e2e/admin/admin.spec.ts', import.meta.url)

/**
 * 建号名字的**唯一**已知形状：`e2e_<family>_${Date.now()}`（反引号模板串、家族段是小写开头的
 * `[a-z0-9]*`、时间戳结尾）。家族段允许数字，是为了让 `e2e_edit2_` 这类**新家族**走到下面的等式
 * 判据上（红字会指名「建号侧多了 edit2，表没跟上」），而不是走到「形状不认识」那一步 —— 抛是
 * 兜底，不是诊断。任何以 `` `e2e_ `` 开头的模板串都必须是这个形状，否则抛：形状一变（加随机后缀、
 * 换成常量、家族名带下划线）抽取会静默少一个家族，而「少了」在这颗绊线上恰好等于「什么都测不到」。
 */
const GEN_SHAPE = /^`e2e_([a-z][a-z0-9]*)_\$\{Date\.now\(\)\}`$/
const ALT_SHAPE = /^[a-z][a-z0-9]*$/
const GEN_ALL = /`e2e_[^`]*`/g
/** 残留表：`/^e2e_(a|b|c)_/` 形状的**恰好一条**正则。多于一条 = 出现了第二份表，也要抛。 */
const RESIDUE_SHAPE = /\/\^e2e_\(([^)]*)\)_\//g

/** 整行注释不参与判定（`//` 开头、`/* … *\/` 块、块内 `*` 行）—— 理由同 roleLabelHygiene。 */
const codeOf = (text: string): string =>
  text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')

/** 实际生成出来的临时账号家族集合。 */
function generatedFamilies(src: string): Set<string> {
  const literals = [...codeOf(src).matchAll(GEN_ALL)].map((m) => m[0])
  const unknown = literals.filter((t) => !GEN_SHAPE.test(t))
  if (unknown.length) {
    throw new Error(
      `临时账号名出现了抽取器不认识的形状：${unknown.join(' , ')}\n` +
        `认的只有 \`e2e_<family>_\${Date.now()}\`。要么把它改回这个形状，要么来教本文件的抽取器，` +
        `别让它静默少算一个家族（少算 = 绊线恒绿）。`,
    )
  }
  if (!literals.length) {
    throw new Error('一个 e2e_ 临时账号名都没抓到：建号写法变了，抽取器要重新对形状')
  }
  return new Set(literals.map((t) => GEN_SHAPE.exec(t)![1]))
}

/** afterAll 残留判据里列出的家族集合。 */
function residueFamilies(src: string): Set<string> {
  const hits = [...codeOf(src).matchAll(RESIDUE_SHAPE)]
  if (hits.length !== 1) {
    throw new Error(
      `残留前缀表应有恰好一条 /^e2e_(…)_/ 正则，实到 ${hits.length} 条` +
        (hits.length > 1 ? ' —— 冒出了第二份表，先合并再说' : ' —— 表被删了或换了写法，重新对形状'),
    )
  }
  const alts = hits[0][1].split('|').map((s) => s.trim())
  if (alts.some((a) => !ALT_SHAPE.test(a))) {
    throw new Error(`残留表里出现了非「家族名」的分支：${hits[0][1]}（嵌套组/转义本抽取器不认）`)
  }
  return new Set(alts)
}

/**
 * 读文件留在顶层，**解析必须在用例内**（`test/unit/audit.spec.ts` 的注释定过这个口径）：
 * 顶层 parse 一旦抛，vitest 会把这 7 条报成一次收集失败（整文件 0 例），而形状坏了本该只红在
 * 「抽取器自证」那一条命名用例上——名字里写着「形状不认识」，这才是要给人看的那句话。
 */
const SRC = readFileSync(ADMIN_SPEC, 'utf8')
/** Task 11 起有第二份表：`e2e/admin/audit.spec.ts` 自己建临时账号、自己清场，表在它自己文件里。 */
const AUDIT_SRC = readFileSync(new URL('../../e2e/admin/audit.spec.ts', import.meta.url), 'utf8')
const GEN = () => generatedFamilies(SRC)
const RES = () => residueFamilies(SRC)

/** 双向差集，拆成纯函数好让「自证」那条直接喂合成源。 */
function drift(gen: Set<string>, res: Set<string>): { onlyGenerated: string[]; onlyInTable: string[] } {
  const has = (s: Set<string>, v: string) => s.has(v)
  return {
    onlyGenerated: [...gen].filter((f) => !has(res, f)).sort(),
    onlyInTable: [...res].filter((f) => !has(gen, f)).sort(),
  }
}

describe('残留表 ↔ 建号名字（admin.spec.ts 的两份清单必须同源）', () => {
  it('两侧都不是空集（否则下面那条等式是在比两个空集合）', () => {
    expect(GEN().size, '建号侧一个家族都没抽到').toBeGreaterThan(0)
    expect(RES().size, '残留侧一个家族都没抽到').toBeGreaterThan(0)
  })

  it('建号家族集合 == 残留表家族集合，红字指名动的是哪一侧', () => {
    const { onlyGenerated, onlyInTable } = drift(GEN(), RES())
    expect(
      onlyGenerated,
      `建号用例加了家族 ${onlyGenerated.join('/')} 而 afterAll 的残留表没跟上 —— ` +
        `动了建号那一侧：把家族名补进 admin.spec.ts 的 /^e2e_(…)_/ 与规则 (b) 的对应表。` +
        `漏了它，这种账号只被本 worker 的 mine 收，worker 崩掉就永久留档。`,
    ).toEqual([])
    expect(
      onlyInTable,
      `残留表列了 ${onlyInTable.join('/')} 而本文件已没有对应的建号用例 —— 动了清理那一侧：` +
        `删掉表里的家族，同时删掉规则 (b) 里那一行对应关系（留着不会漏删，但会让下一个人以为还有）。`,
    ).toEqual([])
  })
})

describe('抽取器自证与反向探针', () => {
  /** 反引号字符：合成源要用它拼模板串字面量，写在单引号里最省事。 */
  const BQ = '`'

  it('合成源里加一个 e2e_unlock_ 家族：抽取集合必须真的长出来，且等式当场判红并指名', () => {
    const grown = `${SRC}\nconst madeUp = ${BQ}e2e_unlock_\${Date.now()}${BQ}\n`
    const gen2 = generatedFamilies(grown)
    expect([...gen2].sort(), '抽取器看不见新家族 ⇒ 整颗绊线恒绿').toEqual(
      [...GEN(), 'unlock'].sort(),
    )
    expect(drift(gen2, RES()).onlyGenerated, '漏进表的家族必须被 drift 点名').toEqual(['unlock'])
  })

  it('真实漂移形状（建号那侧改了家族名、表没跟上）：走等式判据而不是抛', () => {
    // 搜索串用**单引号**：这里面是 admin.spec.ts 的字面文本，不能被本文件的模板串插值掉。
    const renamed = SRC.replace('`e2e_edit_${Date.now()}`', '`e2e_edit2_${Date.now()}`')
    expect(renamed, '探针没改动源码，等于什么都没测').not.toBe(SRC)
    const gen2 = generatedFamilies(renamed) // 形状认识（家族段允许数字）⇒ 不抛，交给等式去红
    expect(gen2).toEqual(new Set([...GEN()].map((f) => (f === 'edit' ? 'edit2' : f))))
    const d = drift(gen2, RES())
    expect(d.onlyGenerated, '新家族没被点名 ⇒ 表漏收这一族时没人会知道').toEqual(['edit2'])
    expect(d.onlyInTable, '旧家族没被点名 ⇒ 表里留了一条已经不存在的前缀').toEqual(['edit'])
  })

  it('未知形状（多了一段随机后缀）要抛，而不是静默少算；注释里出现同样的字面量则不算', () => {
    const odd = `${SRC}\nconst madeUp = ${BQ}e2e_odd_\${Date.now()}_\${Math.random()}${BQ}\n`
    expect(() => generatedFamilies(odd)).toThrow(/不认识的形状/)
    // 反向：整行注释里写这种字面量（把机制写进注释是允许的）不参与判定
    expect(() => generatedFamilies(`// const x = ${BQ}e2e_odd_${BQ}\n${SRC}`)).not.toThrow()
  })

  it('两份表等价本身能被「表里删掉一个家族」杀掉：抹掉 edit 后必须报缺', () => {
    const shrunk = SRC.replace('/^e2e_(user|toggle|edit|reset)_/', '/^e2e_(user|toggle|reset)_/')
    expect(shrunk).not.toBe(SRC)
    expect(drift(generatedFamilies(shrunk), residueFamilies(shrunk)).onlyGenerated).toEqual(['edit'])
  })

  it('反向探针（必须绿）：改变量名、换正则分支顺序，两侧集合都不许变', () => {
    const renamed = SRC.replace(/\buniqueName\b/g, 'tmpAccount')
    expect(renamed, '探针没改动源码，等于什么都没测').not.toBe(SRC)
    expect(generatedFamilies(renamed), '抽取判据焊在变量名上了').toEqual(GEN())

    const reordered = SRC.replace('e2e_(user|toggle|edit|reset)_', 'e2e_(reset|edit|toggle|user)_')
    expect(reordered, '探针没改动源码，等于什么都没测').not.toBe(SRC)
    expect(residueFamilies(reordered), '残留表判据焊在分支顺序上了').toEqual(RES())
  })
})

/**
 * Task 11 起有**第二份表**：`e2e/admin/audit.spec.ts` 自己建临时账号（e2e_audit_）、自己清场。
 * 判据必须**按文件各算一次**，而不是把两张表并成一张 —— 并表等于让 audit 那边的漏项由 admin
 * 的 afterAll 代偿，而 admin 的 worker 根本不知道 audit 的 worker 建了什么（`mine` 是进程内的）。
 */
describe('第二份表（audit.spec.ts）：等式在各自文件内闭合', () => {
  const BQ = '`'

  it('audit.spec.ts 的建号家族 == 它自己 afterAll 的残留表家族', () => {
    const gen = generatedFamilies(AUDIT_SRC)
    expect([...gen].sort(), '建号侧空集 ⇒ 下面的等式是在比两个空集合').not.toEqual([])
    expect(drift(gen, residueFamilies(AUDIT_SRC)), 'audit.spec.ts 的两份清单对不上（红字会指名动的是哪一侧）')
      .toEqual({ onlyGenerated: [], onlyInTable: [] })
  })

  it('两张表不互抄：admin 的表里没有 audit 族，audit 的表里只有 audit 族', () => {
    expect(RES().has('audit'), '把 audit 族塞进 admin.spec.ts 的表：那边根本没有对应的建号用例，跨文件的兜底也不存在').toBe(false)
    expect([...generatedFamilies(AUDIT_SRC)].sort()).toEqual(['audit'])
    expect([...residueFamilies(AUDIT_SRC)].sort()).toEqual(['audit'])
    expect([...RES()].sort()).toEqual(['edit', 'reset', 'toggle', 'user'])
  })

  it('抽取器自证（audit 侧）：合成副本里加一个家族要被 drift 点名；把表抹掉、形状改坏都要抛', () => {
    const grown = generatedFamilies(`${AUDIT_SRC}\nconst madeUp = ${BQ}e2e_unlock_\${Date.now()}${BQ}\n`)
    expect(drift(grown, residueFamilies(AUDIT_SRC)).onlyGenerated, '漏进表的家族必须被点名，否则只有 mine 会收它').toEqual(['unlock'])
    expect(() => residueFamilies(AUDIT_SRC.replace('/^e2e_(audit)_/', 'u.username'))).toThrow(/恰好一条/)
    expect(() => generatedFamilies(`${AUDIT_SRC}\nconst odd = ${BQ}e2e_odd_\${Math.random()}${BQ}\n`)).toThrow(/不认识的形状/)
  })
})

/**
 * T2：角色标签 —— 唯一语义来源 utils/roleLabel + 三处委托（§7.3，spec
 * `docs/superpowers/specs/2026-11-05-account-role-audit-design.md`）。
 *
 * 三层判据，从最有牙到最弱：① roleLabel 的语义（真单测）：administrator→「管理员」，**其余一切取值**
 * →「用户」——对将来任何第三种角色都成立，§7.3 的兜底由它承重（T3 碰不到那条分支：种子里既没有第三种
 * 账号，choices 也拒第三种角色）。② 委托形状（读源码，弱但便宜）：三个调用点只 import、全仓只有一份
 * 定义；形状判据会焊在版式上，所以配两条**必须保持绿**的反向探针（import 拆行 / 无关局部变量改名）。
 * ③ 词汇禁令（全仓扫代码行）：比较、字段赋值、查表键三种形状里的角色取值必须在展示白名单内。
 * 渲染出来的文案由 T3 的 global.spec.ts 断 .user-role 那两条看着，本层不起组件。
 *
 * 跑：cd frontend && npx vitest run test/unit/roleLabelHygiene.spec.ts
 */
import { readFileSync, readdirSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { roleLabel } from '../../src/utils/roleLabel'

const SRC_ROOT = new URL('../../src/', import.meta.url)
const E2E_ROOT = new URL('../../e2e/', import.meta.url)
/** 后端角色的唯一事实来源：清单从它读，不在本文件抄一份。 */
const MODELS_PY = new URL('../../../apps/accounts/models.py', import.meta.url)
const FILES = {
  util: 'utils/roleLabel.ts', topbar: 'components/layout/Topbar.vue',
  dialog: 'components/layout/AccountDialog.vue', mgmt: 'pages/admin/UserManagement.vue',
} as const
/** 展示白名单 ≠ 后端 choices 的副本：后端加新角色不等于前端立刻显示它（§7.3 要的是落兜底）。 */
const DISPLAY_ROLES = ['administrator', 'user']
/** 已被迁移 0012 归并掉的历史角色：不许被分支，也不许作为名字出现在代码行里。 */
const LEGACY_NAME = /\bviewer\b|查看者/
/** 本地又写一份 roleLabel 的三种写法（函数 / 常量 / 箭头赋值）。 */
const DEFINES = /\b(?:function|const|let|var)\s+roleLabel\b|\broleLabel\s*=\s*\(/
/** 操作数是不是「角色」的访问路径：整词 role、x.role、x?.role、驼峰结尾 xRole。 */
const ROLE_PATH = /(?:^|[^\w$])[a-z_]*role$|[0-9A-Za-z_]Role$/

/** 整行注释不参与判定：兜底为什么存在就得能写在注释里，否则下一个人会当冗余删掉。 */
const codeOf = (text: string): string => text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')
const readSrc = (rel: string): string => codeOf(readFileSync(new URL(rel, SRC_ROOT), 'utf8'))

function walk(dir: URL, base = ''): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((ent) => {
    const rel = base ? `${base}/${ent.name}` : ent.name
    return ent.isDirectory() ? walk(new URL(`${ent.name}/`, dir), rel) : /\.(ts|vue)$/.test(ent.name) ? [rel] : []
  })
}

/**
 * 代码里的「角色取值」：`x.role === 'a'`、`'a' !== x.role`、`{ role: 'a' }`。已知边界：只认名字里带
 * role 的访问路径（`const r = u.role` 后接 `r === 'guest'` 抓不到）且要求同行 —— 形状判据的代价。
 */
function roleValues(code: string): string[] {
  const out: string[] = []
  for (const m of code.matchAll(/([^\s()!=]+)\s*[!=]==\s*'([a-z_]+)'/g)) if (ROLE_PATH.test(m[1])) out.push(m[2])
  for (const m of code.matchAll(/'([a-z_]+)'\s*[!=]==\s*([^\s()!=]+)/g)) if (ROLE_PATH.test(m[2])) out.push(m[1])
  for (const m of code.matchAll(/\brole\s*:\s*'([a-z_]+)'/g)) out.push(m[1])
  return out
}

/** 查表形状 `角色: '标签'` 的键 —— 只在 utils/roleLabel.ts 里当角色清单读（映射是它唯一的职责）。 */
const lookupKeys = (code: string): string[] => [...code.matchAll(/^\s*([a-z_]+)\s*:\s*'[^']*'\s*,?\s*$/gm)].map((m) => m[1])

/** `ROLE_CHOICES = [('administrator', 'Administrator'), …]` → 每项首元。 */
function roleChoices(py: string): string[] {
  const block = /ROLE_CHOICES\s*=\s*\[([\s\S]*?)\n\s*\]/.exec(py)
  if (!block) throw new Error('找不到 ROLE_CHOICES 列表')
  return [...block[1].matchAll(/\(\s*'([a-z_]+)'/g)].map((m) => m[1])
}

/** **每一个** `<el-select v-model="….role">` 块里的 option 取值（单行与多行写法都认）。 */
function roleSelectBlocks(code: string): string[][] {
  const blocks = [...code.matchAll(/<el-select\b[^>]*v-model="[^"]*\.role"[^>]*>([\s\S]*?)<\/el-select>/g)]
  return blocks.map((b) => [...b[1].matchAll(/value="'?([a-z_]+)'?"/g)].map((o) => o[1]))
}

/** 委托形状：有没有从 utils/roleLabel 导入、有没有真按名字调用（折叠空白 ⇒ 多行 import 同判据）。 */
const delegation = (code: string): { imports: boolean; calls: boolean } => {
  const flat = code.replace(/\s+/g, ' ')
  return {
    imports: /import\s*\{[^}]*\broleLabel\b[^}]*\}\s*from\s*'[^']*utils\/roleLabel'/.test(flat),
    calls: /\broleLabel\(/.test(flat),
  }
}

describe('判据 ①：utils/roleLabel 的语义（§7.3 兜底的正主）', () => {
  it('administrator 得「管理员」，user 得「用户」，其余一切取值落「用户」', () => {
    expect(roleLabel('administrator')).toBe('管理员')
    expect(roleLabel('user')).toBe('用户')
    const unknown: Array<string | undefined | null> = ['viewer', 'guest', 'tester', 'ADMINISTRATOR', '', undefined, null]
    for (const v of unknown) expect(roleLabel(v), `roleLabel(${String(v)}) 给出的不是兜底「用户」`).toBe('用户')
  })
})

describe('判据 ②：三个调用点只做委托', () => {
  it('每个调用点都从 utils/roleLabel 导入 roleLabel 并按名字调用', () => {
    for (const rel of [FILES.topbar, FILES.dialog, FILES.mgmt]) {
      const d = delegation(readSrc(rel))
      expect(d.imports, `${rel} 没有从 utils/roleLabel 导入 roleLabel`).toBe(true)
      expect(d.calls, `${rel} 导入了却没调用（模板里是不是还留着本地那份？）`).toBe(true)
    }
  })

  it('全仓 roleLabel 的定义只有 utils/roleLabel.ts 一处', () => {
    const defs = walk(SRC_ROOT).filter((rel) => DEFINES.test(readSrc(rel)))
    expect(defs, `又冒出一份本地 roleLabel：${defs.join(', ')}`).toEqual([FILES.util])
  })

  it('反向探针（必须绿）：import 拆成多行、无关局部变量改名，委托判据不改结论', () => {
    const topbar = readSrc(FILES.topbar)
    const split = topbar.replace(
      "import { roleLabel } from '../../utils/roleLabel'",
      "import {\n  roleLabel,\n} from '../../utils/roleLabel'",
    )
    const renamed = topbar.replace(/\bsearchQuery\b/g, 'keywordBox')
    for (const [name, mutated] of [['import 拆行', split], ['无关局部变量改名', renamed]] as const) {
      expect(mutated, `探针「${name}」没改动源码，等于什么都没测`).not.toBe(topbar)
      expect(delegation(mutated), `探针「${name}」下委托判据变了（判据焊在版式上了）`).toEqual(delegation(topbar))
    }
  })
})

describe('判据 ③：全仓代码行不出现第三种角色', () => {
  it('src/ 与 e2e/ 的每个角色取值（比较 / 字段赋值 / util 的查表键）都在展示白名单内', () => {
    const offenders: string[] = []
    for (const [root, tag] of [[SRC_ROOT, 'src'], [E2E_ROOT, 'e2e']] as const) {
      for (const rel of walk(root)) {
        const code = codeOf(readFileSync(new URL(rel, root), 'utf8'))
        const values = [...roleValues(code), ...(rel === FILES.util ? lookupKeys(code) : [])]
        for (const v of values) if (!DISPLAY_ROLES.includes(v)) offenders.push(`${tag}/${rel} 分支到 ${v}`)
        if (LEGACY_NAME.test(code)) offenders.push(`${tag}/${rel} 代码行提到历史角色名`)
      }
    }
    expect(offenders, `§7.3 禁止第三种角色，这些地方还在分支/显示：\n${offenders.join('\n')}`).toEqual([])
  })
})

describe('判据 ④：角色下拉与后端 ROLE_CHOICES 同步（清单从模型读）', () => {
  it('UserManagement.vue 里**每个** `v-model="….role"` 下拉都与模型同集合，并报出动的是哪一侧', () => {
    const backend = roleChoices(readFileSync(MODELS_PY, 'utf8'))
    const blocks = roleSelectBlocks(readSrc(FILES.mgmt))
    expect(blocks.length, '一个角色下拉都没抓到：抽取锚点或页面结构变了，这条判据要重新对形状').toBeGreaterThan(0)
    blocks.forEach((opts, i) => {
      const extra = opts.filter((v) => !backend.includes(v))
      const missing = backend.filter((v) => !opts.includes(v))
      expect(extra, `第 ${i + 1} 个下拉多出 ${extra.join('/')} —— 前端加了后端没有的选项：改页面，本测试不用动`).toEqual([])
      expect(missing, `第 ${i + 1} 个下拉缺 ${missing.join('/')} —— 后端 choices 已加而前端没跟上：下拉选项与 types 的 User.role 一起补`).toEqual([])
    })
  })
})

describe('抽取器自证（否则全仓断言是在比空集合）', () => {
  const SAMPLE = `
// 注释里的 if (role === 'guest') return '访客' 不算分支
if (role === 'administrator') return '管理员'
const LABELS = {
  administrator: '管理员',
  guest: '访客',
}`

  it('比较（两种操作数顺序）/ 字段赋值 / 查表键都抓得住；整行注释里的不算，换成第三种角色就会被点名', () => {
    expect(roleValues(codeOf(SAMPLE))).toEqual(['administrator'])
    expect(roleValues("const draft = { username: '', role: 'user' }")).toEqual(['user'])
    expect(roleValues("if ('guest' === u.role) pick()")).toEqual(['guest'])
    expect(lookupKeys(codeOf(SAMPLE))).toEqual(['administrator', 'guest'])
    expect(codeOf(SAMPLE)).not.toContain("if (role === 'guest')")
    const bad = codeOf(SAMPLE).replace("if (role === 'administrator')", "if (role === 'guest')")
    expect(roleValues(bad).filter((v) => !DISPLAY_ROLES.includes(v)), '绊线恒绿 —— 它其实抓不到 guest').toEqual(['guest'])
  })

  it('下拉抽取认单行与多行写法、忽略非角色下拉；委托判据认多行 import 也认得出缺导入', () => {
    const two = '<el-select v-model="newUser.role"><el-option value="user" /></el-select>' +
      '<el-select v-model="f.role">\n  <el-option\n    value="guest"\n  />\n</el-select>'
    expect(roleSelectBlocks(two)).toEqual([['user'], ['guest']])
    expect(roleSelectBlocks('<el-select v-model="f.kind"><el-option value="guest" /></el-select>')).toEqual([])
    expect(delegation("import {\n  roleLabel,\n} from '../../utils/roleLabel'\nroleLabel(u.role)")).toEqual({
      imports: true, calls: true,
    })
    expect(delegation('const roleLabel = computed(() => FALLBACK_LABEL)')).toEqual({ imports: false, calls: false })
    expect(DEFINES.test('roleLabel(row.role)')).toBe(false)
    expect(roleChoices("ROLE_CHOICES = [\n    ('administrator', 'A'),\n    ('tester', 'T'),\n]")).toEqual(['administrator', 'tester'])
  })
})

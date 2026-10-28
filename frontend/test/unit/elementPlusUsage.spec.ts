/**
 * T2：Element Plus 用量绊线（`src/constants/element-plus-usage.ts`）。
 *
 * 为什么要在这一步就先钉住：按需注册（把 `app.use(ElementPlus)` + `dist/index.css`
 * 换成逐件）唯一的失败方式是「某件漏了注册或漏了样式入口」，而它在界面上表现为
 * 「按钮没圆角 / 下拉不定位」这种**功能仍然能用**的畸形 —— 现有 e2e 全绿也照样放行。
 * 所以先把两份事实钉死：① src 的真实用量逐字等于清单，双向；② 清单里每一件都确实
 * 有逐件注册的入口（`es/components/<name>/style/css.mjs`）。第二条现在没人用，它是
 * 下一批的可行性预检：入口缺一件，那批就会走到一半才发现。
 *
 * ⚠ 已知扫不到的一种形状：`<component :is="'el-xxx'">` 这种动态标签。全仓没用过
 *   （下面的用例 4 会把它也钉住：出现即红，别静默漏）。
 *
 * 跑：cd frontend && npx vitest run test/unit/elementPlusUsage.spec.ts
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import {
  EP_DIRECTIVES,
  EP_PROGRAMMATIC,
  EP_TEMPLATE_COMPONENTS,
} from '../../src/constants/element-plus-usage'

const SRC_ROOT = new URL('../../src/', import.meta.url)
const EP_ES = new URL('../../node_modules/element-plus/es/components/', import.meta.url)

const TAG = /<(el-[a-z0-9]+(?:-[a-z0-9]+)*|El[A-Z][A-Za-z0-9]*)[\s/>]/g
/** 服务式组件走具名调用，不是标签。（刻意不带 g：`.test()` 在多份文件间会带着 lastIndex 走。） */
const PROGRAM_API: Record<string, RegExp> = {
  // `ElMessage(` / `ElMessage.success(`，但 ElMessageBox 的 B 挡在这里，两者分得开
  message: /\bElMessage\s*[.(]/,
  'message-box': /\bElMessageBox\s*[.(]/,
}
const DIRECTIVE_API: Record<string, RegExp> = {
  // 带修饰符的写法（v-loading.fullscreen.lock）也得算命中
  loading: /\bv-loading\b/,
}
/** 动态标签：按需注册后 :is 挂上来的组件不在清单里就是静默没样式。 */
const DYNAMIC_IS = /<component\b[^>]*:is=["']{1,2}el-([a-z-]+)["']{1,2}/g

/** kebab ↔ Pascal 归一到 kebab，再去掉 `el-` 前缀（清单里只留真名）。 */
function toName(raw: string): string {
  const kebab = raw.startsWith('el-')
    ? raw
    : 'el-' + raw.slice(2).replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
  return kebab.slice(3)
}

function collect(files: { path: string; text: string }[]) {
  const names = new Set<string>()
  const apis = new Set<string>()
  const directives = new Set<string>()
  const apiFiles: Record<string, string[]> = {}
  let occurrences = 0
  const dynamicIs: string[] = []
  for (const f of files) {
    for (const m of f.text.matchAll(TAG)) {
      names.add(toName(m[1]))
      occurrences += 1
    }
    for (const [name, re] of Object.entries(PROGRAM_API)) {
      if (re.test(f.text)) {
        apis.add(name)
        apiFiles[name] = [...(apiFiles[name] || []), f.path]
      }
    }
    for (const [name, re] of Object.entries(DIRECTIVE_API)) {
      if (re.test(f.text)) directives.add(name)
    }
    for (const m of f.text.matchAll(DYNAMIC_IS)) {
      dynamicIs.push(m[1])
    }
  }
  return { names, apis, directives, apiFiles, occurrences, dynamicIs }
}

/** 真实 src 的扫描结果只算一次（一次遍历 ~240 个文件）。惰性求值：目录出错时落在用例里而不是整文件注册前。 */
let realCache: { path: string; text: string }[] | null = null
function realFiles() {
  if (realCache) return realCache
  const root = fileURLToPath(SRC_ROOT)
  const out: { path: string; text: string }[] = []
  function walk(dir: string): void {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const p = `${dir}/${entry.name}`
      if (entry.isDirectory()) walk(p)
      else if (/\.(vue|ts)$/.test(entry.name)) out.push({ path: p, text: readFileSync(p, 'utf-8') })
    }
  }
  walk(root)
  realCache = out
  return out
}

describe('element-plus 用量绊线', () => {
  it('判定内核自证：三种写法形状都抓得住，且不误抓 class', () => {
    const s = collect([
      {
        path: 'a.vue',
        text:
          '<template><el-button>ok</el-button><ElIcon />\n<el-select\n' +
          '  v-model="x"><el-button-group /><div class="el-button">不该算</div></template>',
      },
    ])
    expect([...s.names].sort()).toEqual(['button', 'button-group', 'icon', 'select'])
    // class 上的 el-* 不是标签使用：漏算会虚增清单，误算会让清单出现没人用的名字
    expect(s.occurrences).toBe(4)
  })

  it('内核认得服务式、指令与动态 :is 三种用法，且拼错的标签名会原样冒出来', () => {
    const s = collect([
      {
        path: 'b.ts',
        text:
          "ElMessage.success('x'); ElMessageBox.confirm('y'); <el-buton /> v-loading=\"f\"" +
          `<component :is="'el-avatar'" />`,
      },
    ])
    expect([...s.apis].sort()).toEqual(['message', 'message-box'])
    expect([...s.directives]).toEqual(['loading'])
    // 服务式正则一旦带上 g，lastIndex 就跨文件带着走：只断言「命中过」抓不到这种失真，
    // 必须数**命中的文件** —— 这条就是给上面那句「刻意不带 g」的注释兜底的。
    const two = collect([
      { path: 'a.ts', text: 'ElMessage("x")' },
      { path: 'b.ts', text: 'ElMessage("y")' },
    ])
    expect(two.apiFiles.message).toEqual(['a.ts', 'b.ts'])
    // 这条同时是给下面那条「全仓没有动态 :is」的反证：谓词不是恒空，是能抓到的
    expect(s.dynamicIs).toEqual(['avatar'])
    // 今天整包注册下 <el-buton> 只会静默什么都不渲染；绊线必须把它当**陌生名字**报出来
    expect(s.names.has('buton')).toBe(true)
    expect(EP_TEMPLATE_COMPONENTS).not.toContain('buton')
  })

  it('真实 src 的模板用量逐字等于清单（双向、排序后逐字符比对）', () => {
    const used = [...collect(realFiles()).names].sort()
    expect(used).toEqual([...EP_TEMPLATE_COMPONENTS].sort())
  })

  it('清单不许有重复名字，也不许靠空集合蒙过上一条', () => {
    const list = [...EP_TEMPLATE_COMPONENTS]
    expect(new Set(list).size).toBe(list.length)
    const s = collect(realFiles())
    // 空扫描 / 目录拼错时这条先红，而不是让上面那条比一个空集合 == 空清单
    expect(list.length).toBe(49)
    expect(s.occurrences).toBeGreaterThan(300)
    for (const must of ['button', 'select', 'form-item', 'table-column']) {
      expect(s.names.has(must), `缺少必然存在的 ${must}`).toBe(true)
    }
  })

  it('服务式与指令两份清单各自逐字等于实测', () => {
    const s = collect(realFiles())
    expect([...s.apis].sort()).toEqual([...EP_PROGRAMMATIC].sort())
    expect([...s.directives].sort()).toEqual([...EP_DIRECTIVES].sort())
  })

  it('逐件注册的入口都存在：es/components/<name>/style/css.mjs', () => {
    const missing = [...EP_TEMPLATE_COMPONENTS, ...EP_PROGRAMMATIC, ...EP_DIRECTIVES].filter(
      (name) => !statSyncExists(`${EP_ES.href}${name}/style/css.mjs`)
    )
    expect(missing).toEqual([])
  })

  it('动态 :is 挂 el-* 的写法全仓没有（有就必须进清单，否则按需注册静默缺件）', () => {
    expect(collect(realFiles()).dynamicIs).toEqual([])
  })

  it('注册名单逐字等于清单：installables = 模板 49 件 + 提供 v-loading 的 ElLoading', () => {
    const p = pluginLists()
    expect(p.installed.length).toBe(new Set(p.installed).size)
    expect(p.installed.sort()).toEqual(
      [...EP_TEMPLATE_COMPONENTS, 'loading'].map(toPascal).sort()
    )
    // 装进去的每一件都必须在 import 名单里（TS 也会红，但这条给的是「哪个名字漂了」）
    const notImported = p.installed.filter((n) => !p.imported.has(n))
    expect(notImported, `installables 里有没 import 的名字: ${notImported.join(', ')}`).toEqual([])
  })

  it('样式入口逐字等于清单全集（52 件），且没有重复行', () => {
    const p = pluginLists()
    const expectStyled = [...EP_TEMPLATE_COMPONENTS, ...EP_PROGRAMMATIC, ...EP_DIRECTIVES].sort()
    expect(p.styled.length).toBe(new Set(p.styled).size)
    expect(p.styled.sort()).toEqual(expectStyled)
  })

  it('main.ts 里整包注册不许复活，且 EP 样式必须排在自有主题覆盖之前', () => {
    const main = readFileSync(fileURLToPath(MAIN), 'utf-8')
    expect(main).not.toMatch(/import ElementPlus from 'element-plus'/)
    expect(main).not.toMatch(/element-plus\/dist\/index\.css/)
    expect(main).toMatch(/setupElementPlus\(app\)/)
    // 层叠顺序：EP 的样式在前，我们对 .el-* 的夜晚覆盖才能按老顺序赢
    const ep = main.indexOf('./plugins/element-plus')
    const theme = main.indexOf('./styles/element-plus-theme.css')
    expect(ep).toBeGreaterThanOrEqual(0)
    expect(theme).toBeGreaterThanOrEqual(0)
    expect(ep, 'EP 样式必须在自有主题 CSS 之前引入').toBeLessThan(theme)
  })
})

const PLUGIN = new URL('../../src/plugins/element-plus.ts', import.meta.url)
const MAIN = new URL('../../src/main.ts', import.meta.url)

/** kebab ↔ EP 导出名：`breadcrumb-item` → `ElBreadcrumbItem`。 */
function toPascal(kebab: string): string {
  return 'El' + kebab.split('-').map((s) => s[0].toUpperCase() + s.slice(1)).join('')
}

function pluginLists() {
  const text = readFileSync(fileURLToPath(PLUGIN), 'utf-8')
  const installBlock = /const installables = \[([\s\S]*?)\n\]/.exec(text)
  const importBlock = /import \{([\s\S]*?)\} from 'element-plus'/.exec(text)
  const installed = installBlock
    ? [...installBlock[1].matchAll(/^\s+(El[A-Z][A-Za-z]*),$/gm)].map((m) => m[1])
    : []
  const imported = new Set(
    importBlock ? [...importBlock[1].matchAll(/\b(El[A-Z][A-Za-z]*)\b/g)].map((m) => m[1]) : []
  )
  const styled = [...text.matchAll(/es\/components\/([a-z0-9-]+)\/style\/css'/g)].map((m) => m[1])
  return { installed, imported, styled }
}

function statSyncExists(url: string): boolean {
  try {
    return statSync(fileURLToPath(url)).isFile()
  } catch {
    return false
  }
}

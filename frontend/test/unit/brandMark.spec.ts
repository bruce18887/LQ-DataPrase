/**
 * T2：品牌母版守门（frontend/public/favicon.svg）。
 *
 * 历史根因（本文件存在的理由）：**曾经**的母版是 16 个高斯模糊椭圆经 mask 裁进闪电轮廓的
 * 合成件，实测其 16px 帧带 100 个实心色阶（同尺寸单色版为 1 个）——任务栏图标糊成一团的根因。
 * 现用母版已按 D2 去模糊改单色（spec §1.2/§2.1），所以本文件锁死的是「不得把模糊/遮罩/多色阶
 * 加回来」，以及尾针必须宽到能在小尺寸站住。
 *
 * 底板形制（Task 9）起，母版的 filter/mask 禁令还多了一重身份：它是 G1「符号糊边」这一维
 * **不花像素余量、覆盖所有帧**的第一层防线（icon-audit.cjs 的 G1 表注释与 spec §7-9 都点名到这里）。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const svg = readFileSync(new URL('../../public/favicon.svg', import.meta.url), 'utf8')
const comp = readFileSync(new URL('../../src/components/common/AppLogo.vue', import.meta.url), 'utf8')

describe('品牌母版 favicon.svg', () => {
  it('不含任何滤镜与遮罩（模糊是 16px 糊边的根因）', () => {
    expect(svg).not.toMatch(/<filter|feGaussianBlur|<mask|mask=/)
  })

  it('只有一条 path，且为单色 class 驱动', () => {
    expect(svg.match(/<path/g) ?? []).toHaveLength(1)
    expect(svg).toMatch(/<path\s+class="b"/)
  })

  it('viewBox 零留白：紧贴 48×46 剪影（内缩由生成器按帧尺寸分档注入）', () => {
    // 原注释说「留白由生成器按帧尺寸注入」——D7 第二轮语义已改：底板**铺满整帧**（外边距恒 0），
    // 分档吃的是符号内缩（icon-lib.cjs 的 insetPct），所以这句按现状改写（Task 11 顺手闭台账项）。
    expect(svg).toMatch(/viewBox="0 0 48 46"/)
  })

  it('尾针左界已加宽到 x=19.4（原 23.925 只有 4.2% 画布宽，16px 下必然化开）', () => {
    expect(svg).toContain('L19.4 33.937')
    expect(svg).not.toContain('V33.937')
  })

  it('双主题色走 token 值：light #2563eb / night #f9a825', () => {
    expect(svg).toMatch(/\.b\{fill:#2563eb\}/)
    expect(svg).toMatch(/prefers-color-scheme:\s*dark[\s\S]*?fill:#f9a825/)
  })
})

describe('AppLogo 与母版同源', () => {
  // I5：同一件「形状」现存在三处——母版 viewBox、组件模板自己的 viewBox、组件里那条
  // `size * 46 / 48` 的比例式，外加 `d` 字面量。此前只有第一处有守门（上面那条 :24 断言），
  // 另外两份各改一半时**没有任何测试会红**。下面三条把它们逐一接进同源判据：
  // 一律「两侧都解析出来再比」，不许各抄一个硬编字面量（抄来的字面量只会跟着一起漂）。
  it('组件里的 path d 与 favicon.svg 完全一致（防两处形状各改一半）', () => {
    const masterD = /<path[^>]*\sd="([^"]+)"/.exec(svg)
    const compD = /const d = '([^']+)'/.exec(comp)
    // 先分别钉住「两侧都真的解析到了」，否则漂了的一侧会先炸成 TypeError，看不出是哪一侧（同仓 appIcon.spec.ts 的写法）
    expect(masterD, 'favicon.svg 里没解析到 <path d>（母版形状被改名/被拆成多条 path？）').not.toBeNull()
    expect(compD, "AppLogo.vue 里没解析到 `const d = '…'`（字面量被搬进模板了？见下面 :d=\"d\" 那条）").not.toBeNull()
    expect(compD![1]).toBe(masterD![1])
  })

  it('组件模板的 viewBox 与母版 viewBox 同源相等', () => {
    const masterVb = /\sviewBox="([^"]+)"/.exec(svg)
    const compVb = /\sviewBox="([^"]+)"/.exec(comp)
    expect(masterVb, 'favicon.svg 没有 viewBox').not.toBeNull()
    expect(compVb, 'AppLogo.vue 模板没有 viewBox').not.toBeNull()
    // 归一化空白后再比：只允许「同一份几何、不同写法」通过，不允许两套数字
    const norm = (v: string) => v.trim().split(/\s+/).join(' ')
    expect(norm(compVb![1]), '组件 viewBox 与母版 viewBox 已经分家').toBe(norm(masterVb![1]))
  })

  it('模板真的吃 `:d="d"`（把 d 硬编回模板、留着没用的 const d，这条必须红）', () => {
    const pathTag = /<path[^>]*>/.exec(comp)
    expect(pathTag, 'AppLogo.vue 模板里找不到 <path>').not.toBeNull()
    expect(pathTag![0], ':d 绑定不见了（形状改成模板字面量？）').toMatch(/:d="d"/)
    expect(pathTag![0], '模板里不许同时出现字面量 d —— 那份 const d 就成了没人读的第二个家').not.toMatch(/\sd="M/)
  })

  it('AppLogo 的 `size * 46 / 48` 比例式与母版 viewBox 的实际宽高一致', () => {
    // 46/48 不许硬编：分母/分子都从母版 viewBox 解析出来，母版一改这一行就跟着要求改组件。
    const vb = /\sviewBox="[\d.-]+\s+[\d.-]+\s+([\d.eE+-]+)\s+([\d.eE+-]+)"/.exec(svg)
    expect(vb, '母版 viewBox 解析不出宽高').not.toBeNull()
    const masterW = Number(vb![1])
    const masterH = Number(vb![2])
    const expr = /const height = computed\(\(\) => ([^\n]+?)\)\)/.exec(comp)
    expect(expr, 'AppLogo.vue 的 height computed 被改写或删掉了（非正方形状靠它避免被拉扁）').not.toBeNull()
    const nums = (expr![1].match(/\d+(?:\.\d+)?/g) ?? []).map(Number)
    // 顺序也是契约的一部分：分子=母版高、分母=母版宽（按宽定高）。等价但换序的写法同样要红一次，
    // 逼改的人明确决定「比例式还是不是从同一份 viewBox 推出来的」。
    expect(nums, `height 表达式里的数字必须恰是母版 viewBox 的 [高, 宽] = [${masterH}, ${masterW}]，实得 ${nums.join(', ')}`).toEqual([masterH, masterW])
  })
})

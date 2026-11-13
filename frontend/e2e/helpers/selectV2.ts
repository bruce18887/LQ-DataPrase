import { expect, type Locator, type Page } from '@playwright/test'

import { popperOf } from './elplus'

/**
 * `el-select-v2` 反截断判据的唯一落点（批1 Task 9B）。
 *
 * 为什么要有这个文件：「虚拟化真的生效」在 DOM 上只有一个可读形状 —— 窗口行数是常数，
 * 不是全集条数。Task 5 把这条写在 `analysis/param-dropdown-full-list.spec.ts` 里，
 * Task 9C 又在 `data/view-data.spec.ts` 里复制了**第二份** `MAX_WINDOW_ROWS`：两份界值
 * 各改各的，漂移时只红一族。Task 9B 要给序列 / 测试列 / 导出 / 固定列四族补同一条判据，
 * 再复制就是五份 ⇒ 收进来，五族共用一个界。
 */

/**
 * 虚拟窗口允许出现的最大行数。上界由 EP 默认值推出：`select-v2/src/defaults.mjs` 的
 * `height:274 / itemHeight:34` ≈ 9 行，加 overscan 实测 11 行（2026-11-13）。留到 20 是
 * 给「以后有人调高面板」的余量；真正的判据是「远小于全集」，不是「等于 11」。
 *
 * 它同时是「不虚拟化、但也不截断」这种回退的唯一哨兵：那种实现下 DOM 会等于全集
 * （Task 5 实测 1,723 行、Task 9C 实测 1,728 行），这条必红，而 footer 那一族判据照样绿。
 *
 * ⚠ 前提是「当下这一屏的候选数」严格大于它，候选数小于界时这条恒真（见 `expectWindowRows`）。
 */
export const MAX_WINDOW_ROWS = 20

/** 某实例 popper 里的选项行（v2 的虚拟窗口只渲染这几行） */
export function windowItems(page: Page, popperClass: string): Locator {
  return popperOf(page, popperClass).locator('.el-select-dropdown__item')
}

/**
 * 「窗口行数上限」这条判据的可复用形状：断言 DOM 行数 `< MAX_WINDOW_ROWS`，返回实测值。
 *
 * `candidates`（当下这一屏真正够得着的候选数，**从响应侧取**而不是数 DOM）只进失败消息，
 * 不进断言 —— 前提本身留给各用例自己断（`param-dropdown-full-list` 断「夹具 > 旧封顶 300」，
 * `view-data` 断「夹具是千列级」），因为各族的前提语义不同，塞进公共入口就是替五族拍板。
 * `label` 也只进消息：五族共用同一条界，红了得一眼看出是哪一族。
 */
export async function expectWindowRows(items: Locator, candidates: number, label: string): Promise<number> {
  const rows = await items.count()
  expect(
    rows,
    `DOM 里只该有虚拟窗口那几行（${label}：实测 ${rows} 行 / 当下候选 ${candidates} 项，界 ${MAX_WINDOW_ROWS}）`,
  ).toBeLessThan(MAX_WINDOW_ROWS)
  return rows
}

/**
 * 末项在窗口里的状态：`{ inDom, inViewport }`。
 *
 * 为什么走 DOM 而不是 Playwright 定位器：`:text-is()` 只匹配**最小**的那个元素，而选项行
 * 里面还有 `.param-option > .param-name > span` 三层，`li:text-is("X")` 永不命中
 * （2026-11-13 实测假红一次）；`hasText` 反过来是子串匹配，'VTH' 会冒充 'VTH_2'。
 * 逐字比较只能在 DOM 侧做，`toBeVisible()` 也答不出「被滚动视口裁掉了」这一半。
 */
export async function tailRowState(
  page: Page,
  popperClass: string,
  target: string,
): Promise<{ inDom: boolean; inViewport: boolean }> {
  return page.evaluate(({ popper, needle }) => {
    // 与 `helpers/elplus.ts` 的 `popperOf` 同一套谓词（`[aria-hidden="false"]`）：
    // 这里是页内 querySelector，够不到 helper，所以谓词只能重写一遍 —— 两种写法并存是
    // 故意的，代价是改谓词时必须两处同改：只改 helper 而漏掉这里，本条判的就是另一个
    // 面板（已关闭的那个 aria-hidden="true" 的兄弟 popper），于是 inDom 恒 false ⇒ 假红。
    const panel = document.querySelector(`.el-popper.${popper}[aria-hidden="false"]`)
    const rows = panel ? [...panel.querySelectorAll('.el-select-dropdown__item')] : []
    const hit = rows.find((r) => (r.textContent ?? '').trim() === needle)
    if (!hit) return { inDom: false, inViewport: false }
    // 最近的可滚祖先 = 虚拟列表的视口（不写死 EP 内部类名，v1/v2 都拿得到）。
    // body/documentElement 必须排除：整页可滚时它们同样满足 scrollHeight>clientHeight，
    // 一旦窗口自身没撑起来，末项就会被「页面滚动的位置」判成「在窗口里可见」—— 那是假绿，
    // 而本用例唯一承重的就是「窗口滚到了末尾」。找不到合格祖先 ⇒ inViewport:false ⇒ 红。
    let vp: HTMLElement | null = hit.parentElement
    while (vp && vp.scrollHeight <= vp.clientHeight + 1 && vp !== document.body) {
      vp = vp.parentElement
    }
    if (!vp || vp === document.body || vp === document.documentElement) {
      return { inDom: true, inViewport: false }
    }
    const a = vp.getBoundingClientRect()
    const b = hit.getBoundingClientRect()
    return { inDom: true, inViewport: b.top >= a.top - 1 && b.bottom <= a.bottom + 1 }
  }, { popper: popperClass, needle: target })
}

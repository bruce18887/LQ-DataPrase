import { type Page } from '@playwright/test'

/**
 * 浏览器侧带 token 的一次读/写请求。返回 `{status, body}` 而不是 throw ——
 * 调用方要拿状态码当断言对象（`expect(imp.status).toBe(201)`），
 * 改成抛异常就等于把断言搬进 helper，用例再也看不到状态码。
 *
 * 唯一来源纪律：此前 `repair-center.spec.ts` 与 `disk-usage-chip.spec.ts` 各存一份同形副本，
 * 后者的注释原话是「出现第三份时就把它搬进 `e2e/helpers/`，别再往 spec 里复制」。
 * 本文件就是那次落地；刀一 拆出的 `duplicate-keep.spec.ts` 是第三个消费者。
 * 其余形态不同的 fetch 封装（返回已裁剪的对象、或走 `page.request`）**不在收编范围**，
 * 合并它们会改掉用例语义 —— 见设计稿 §2.1 与 §4。
 */

export function apiGet(page: Page, url: string) {
  return page.evaluate(async (u) => {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`/api/v1${u}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    return { status: res.status, body: await res.json() }
  }, url)
}

export function apiPost(page: Page, url: string, body: unknown) {
  return page.evaluate(async ({ u, b }) => {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`/api/v1${u}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(b),
    })
    return { status: res.status, body: await res.json() }
  }, { u: url, b: body })
}

/**
 * 角色 → 展示名的唯一语义来源（spec `docs/superpowers/specs/2026-11-05-account-role-audit-design.md` §7.3）。
 * Topbar / 个人资料弹窗 / 用户管理三处只做委托，别再各留一份本地实现。
 */

// 兜底吞掉一切未知取值是有意的：迁移 0012 只改跑过它的库，没跑到的机器仍可能读回历史角色值，
// 而 §7.3 规定那种行不得显示第三个角色名 —— 后端 choices 将来新增角色时同理，先落「用户」。
const FALLBACK_LABEL = '用户'

export function roleLabel(role: string | undefined | null): string {
  return role === 'administrator' ? '管理员' : FALLBACK_LABEL
}

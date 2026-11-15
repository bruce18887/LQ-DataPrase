/** 用户管理新增/编辑对话框的载荷：按 mode 分叉，提交侧不用再猜哪些字段非空。 */
export interface UserFormUser {
  username: string
  display_name: string
  email: string
  role: string
}

export type UserFormPayload =
  | { mode: 'create'; username: string; password: string; role: string }
  | { mode: 'edit'; display_name: string; email: string; role: string }

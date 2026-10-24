/**
 * 后端子进程的 env 构造。
 *
 * 单独成模块只为了能被 T2 直接断言：`electron/backend.ts` 顶层 `import { app } from 'electron'`，
 * node 环境的 vitest 取不到 Electron 运行时，因此没法连它的 spawn 一起测。
 */

export interface BackendEnvInput {
  /** 运行时用户数据目录（库/media/staticfiles 的锚点）。 */
  userDataPath: string
  /** 本次启动专用的优雅关闭令牌，见 backend.ts 里生成处。 */
  shutdownToken: string
}

/**
 * 在继承父进程 env 的前提下补齐 stdio 编码与缓冲口径。
 *
 * `PYTHONIOENCODING=utf-8` 治的是打包版的中文乱码：Django 的日志 handler 写 stderr/stdout，
 * Windows 上那条流的默认编码是本机 cp936，而 Electron 侧用 `data.toString()`（UTF-8）解 ——
 * 两边不一致，中文日志就成了乱码。仓里其它 spawn 早已是这个写法
 * （frontend/e2e/global-setup.ts:25、scripts/e2e_nightly.mjs:236），只有这里漏了。
 *
 * ⚠ 刻意**不**设 `PYTHONUTF8=1`：它除 stdio 之外还会把 `open()` 的默认文本编码从本机
 * locale（中文 Windows = cp936）改成 UTF-8，而 `apps/` 下有 25 处测试用不带 `encoding=`
 * 的文本模式 `open(...,'w')` 写夹具（2026-10-24 实测计数；产品代码里剩下的 bare open 全是
 * 二进制模式，不受影响）—— 那等于把整个测试套件的读写语义一起换掉，而治乱码用不着这么大范围。
 * 这条由 test/unit/backendEnv.spec.ts 钉住，别再"顺手加严"。
 */
export function buildBackendEnv(
  base: NodeJS.ProcessEnv,
  input: BackendEnvInput,
): NodeJS.ProcessEnv {
  return {
    ...base,
    PYTHONUNBUFFERED: '1',      // 逐行 flush，否则启动横幅卡在块缓冲里、端口探测超时
    PYTHONIOENCODING: 'utf-8',
    LQDP_BASE_DIR: input.userDataPath,
    LQDP_SHUTDOWN_TOKEN: input.shutdownToken,
  }
}

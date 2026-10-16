/**
 * T2：图标路径推导 + AppUserModelID 一致性。
 *
 * APP_ID 与 electron-builder.yml 的 appId 是同一份信息写两处（Windows 靠它把
 * 任务栏分组与快捷方式归到同一应用）。仓库里已经因为“页面级元数据写两份”漂过
 * 一次（lessons.md:1587），所以这里用一条读文件的断言钉住，而不是再建一个共享常量
 * —— yml 不是 TS，抽公共常量要引 yaml 解析器，得不偿失。
 */
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import * as os from 'node:os'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { APP_ID, resolveIconPath, iconFileExists } from '../../../electron/app-icon'

describe('APP_ID 与 electron-builder.yml 的 appId 同源', () => {
  it('两处字面量一致', () => {
    const yml = readFileSync(new URL('../../../electron-builder.yml', import.meta.url), 'utf8')
    const m = /^appId:\s*(\S+)\s*$/m.exec(yml)
    expect(m).not.toBeNull()
    expect(APP_ID).toBe(m![1])
  })
})

describe('resolveIconPath', () => {
  const norm = (p: string) => p.replace(/\\/g, '/')

  it('打包态走 resources 下的 icon.ico（extraResources 的落点），且必须是绝对路径', () => {
    const p = resolveIconPath({ packaged: true, resourcesPath: '/app/resources', electronDistDir: 'D:/x' })
    expect(norm(p)).toBe('/app/resources/icon.ico')
    expect(path.isAbsolute(p)).toBe(true)
  })

  it('dev 态走仓库 build/icon.ico：electron-dist 的上两级是仓库根', () => {
    expect(norm(resolveIconPath({ packaged: false, resourcesPath: '', electronDistDir: '/repo/frontend/electron-dist' })))
      .toMatch(/\/repo\/build\/icon\.ico$/)
  })

  it('打包态 resourcesPath 缺失时返回空串——降级到无图标，绝不猜 asar 外层数', () => {
    expect(resolveIconPath({ packaged: true, resourcesPath: '', electronDistDir: '/repo/frontend/electron-dist' }))
      .toBe('')
  })

  it('相对 resourcesPath 就得到相对路径（M5：上面那条 isAbsolute 只因为夹具是绝对路径才成立）', () => {
    // 这条不是「发现缺陷」而是**把守卫的真实边界写清楚**：resolveIconPath 只做 path.join，
    // 不 resolve、不猜。真正保证打包态拿到绝对路径的是 Electron 自己（process.resourcesPath
    // 恒为绝对路径），不是这个函数。所以 :31 的 isAbsolute 断言是**夹具属性**而不是行为属性，
    // 别把它读成「函数会把相对输入掰绝对」。
    const p = resolveIconPath({ packaged: true, resourcesPath: 'relative/res', electronDistDir: 'D:/x' })
    expect(norm(p)).toBe('relative/res/icon.ico')
    expect(path.isAbsolute(p)).toBe(false)
  })
})

/**
 * 'icon.ico' 这个名字同时写在 electron-builder.yml 的 extraResources.to: 和
 * app-icon.ts 的 path.join 里——与 APP_ID 同一类"一份信息写两处"的漂移面
 * （lessons.md:1587），用同一条 yml 读取钉住。
 */
describe('icon.ico 文件名与 electron-builder.yml 的 extraResources 同源', () => {
  it('extraResources 的 to: 与 resolveIconPath 打包态产出的文件名一致', () => {
    const yml = readFileSync(new URL('../../../electron-builder.yml', import.meta.url), 'utf8')
    const m = /from:\s*"?build\/icon\.ico"?\s*\n\s*to:\s*"?([^"\s#]+)"?/.exec(yml)
    expect(m).not.toBeNull()
    const runtimeName = path.basename(resolveIconPath({ packaged: true, resourcesPath: '/app/resources', electronDistDir: 'D:/x' }))
    expect(m![1]).toBe(runtimeName)
  })
})

describe('iconFileExists', () => {
  it('空串与不存在路径一律 false，不抛', () => {
    expect(iconFileExists('')).toBe(false)
    expect(iconFileExists('/nope/definitely/not/here.ico')).toBe(false)
  })

  it('存在的文件为 true', () => {
    expect(iconFileExists(fileURLToPath(new URL('../../public/favicon.svg', import.meta.url)))).toBe(true)
  })
})

/**
 * I2：生成器在「playwright 加载不到」那一步的两条分支。
 *
 * 判据是**退出码**，不是日志措辞，所以只能真跑一次进程；但绝不允许为了测试去删仓库里的
 * `build/icon.ico`（那是 Task 10 打包验证的输入），也不允许让测试起 Chromium。做法：把
 * tracked 的脚本连同它的三个纯函数模块与两份输入资产**拷进 os.tmpdir 的一次性目录**，
 * 副本里没有 `frontend/node_modules/playwright` → require 必失败，正好只命中被问的那条分支；
 * `build/icon.ico` 在不在由夹具自己决定。ROOT 由脚本自己的 `__dirname/..` 推出，因此产物路径
 * 落在临时目录内，仓库的 build/ 全程不被触碰。
 */
describe('gen-icon.ico.js：playwright 缺席时，降级只在有东西可降的时候成立（I2）', () => {
  const REPO = (rel: string) => fileURLToPath(new URL('../../../' + rel, import.meta.url))
  const COPIED = [
    'scripts/gen-icon.ico.js',
    'scripts/icon-lib.cjs',
    'scripts/icon-metrics.cjs',
    'scripts/icon-audit.cjs',
    'frontend/public/favicon.svg',
    'frontend/src/styles/design-tokens.css',
  ]

  function runWithoutPlaywright(existingIco: boolean) {
    const root = mkdtempSync(path.join(os.tmpdir(), 'gen-icon-i2-'))
    try {
      for (const rel of COPIED) {
        const dest = path.join(root, rel)
        mkdirSync(path.dirname(dest), { recursive: true })
        cpSync(REPO(rel), dest)
      }
      mkdirSync(path.join(root, 'build'), { recursive: true })
      if (existingIco) writeFileSync(path.join(root, 'build', 'icon.ico'), 'fixture: 上一轮的产物')
      const r = spawnSync(process.execPath, [path.join(root, 'scripts', 'gen-icon.ico.js')], {
        cwd: root,
        encoding: 'utf8',
      })
      return `${r.stdout ?? ''}${r.stderr ?? ''}\n[exit=${r.status}]`
    } finally {
      rmSync(root, { recursive: true, force: true }) // 只删本轮 mkdtemp 出来的副本目录，不碰任何原件
    }
  }

  it('既有 build/icon.ico 在 → 保持降级放行（退出 0），日志点名留的是哪份产物', () => {
    const log = runWithoutPlaywright(true)
    expect(log).toMatch(/\[exit=0\]/)
    expect(log).toMatch(/build\/icon\.ico/)
    // 两条分支不许糊在一起：有产物时不能出现「没有可降级」那句
    expect(log).not.toMatch(/没有可降级/)
  })

  it('没有 build/icon.ico → 非零退出，文案点名「没有可降级的既有产物」并给出下一步', () => {
    const log = runWithoutPlaywright(false)
    // 退出 0 在这里是**缺陷**：win.icon / extraResources / nsis.installerIcon|uninstallerIcon
    // 与 lq_dataprase.spec 的 icon= 随后都会硬失败，报错点更远且更难读。
    expect(log).toMatch(/\[exit=1\]/)
    expect(log).toMatch(/没有可降级的既有产物/)
    expect(log).toMatch(/node scripts\/gen-icon\.ico\.js/) // 可执行的下一步，不是「请联系维护者」
  })
})

/**
 * Task 13：PyInstaller 的缓存每轮必须清干净，且它的临时树不与图标资产同树。
 *
 * 缺陷现场（task-10 报告 §6 实测、task-13 报告 §4.3 当代复现）：`npm run pyinstaller` 曾跑出
 * **全绿日志 + 上一代图标**。承重机理在读码级就钉死了：EXE 的缓存判据 `_GUTS` 里 `icon` 用的是
 * `_check_guts_eq`（`.venv/.../PyInstaller/building/api.py:683` → `building/utils.py:47`，只做
 * `old != new` 的值比较），而 icon 在 `EXE.__init__` 里已被 `_makeabs` 归一成**绝对路径字符串
 * 列表**（api.py:591-595）——比的是那串路径，文件字节与 mtime 全程不参与，`_GUTS` 里也没有任何
 * 针对 icon 的 mtime/字节检查。所以 workpath 跨 run 存活时，换掉的 icon 字节不会被察觉。
 * task-13 S2 在**已隔离**的 workpath 上不带 `--clean` 交出与上一代 md5 一字不差的 exe（报告 §4.3
 * 表）：**只搬目录修不了陈旧，`--clean` 才是修它的那一环**。
 *
 * `--workpath build/pyi-work` 的定位是**卫生**而非修复：把 PyInstaller 的临时树移出装着交付图标
 * 的那个目录，纯粹是不把构建垃圾堆在交付资产旁边。清理圈的真实半径见 `building/build_main.py`：
 * `:1147-1150` 先把 spec 名拼进 workpath，`:1162-1170` 只 glob `workpath/<specnm>/` 的**内容**——
 * 因此 `--clean` 从来够不到 `build/icon.ico`（哪怕 workpath 用默认 `build/` 也够不到）；简报那条
 * 「--clean 是对着自家资产的上了膛的枪」已被 task-13 §2.4 的 decoy 实验否证，本注释是它的更正。
 * `--clean` 真正的外溢是同一轮还清 `CONF['cachedir']`（Windows 默认 `%LOCALAPPDATA%\pyinstaller`，
 * 机器共享的用户级缓存），命令用 `PYINSTALLER_CONFIG_DIR` 把它关进仓库，口径与一轮重建的实测记录见
 * package.json 的 `_pyiWorkpathNote`。
 *
 * 本守卫钉三条契约（与文首 APP_ID↔electron-builder.yml 那条同一物种：读配置本体推导、不建共享常量）：
 *  1) 命令必须显式带 `--clean`（修陈旧）与 `--workpath`（卫生），且 workpath 解析后既不等于、也不把
 *     `build/icon.ico` / `icon.png` 圈在自己子树内（资产与缓存树不相交这条是目录卫生的判据，
 *     与清理语义无关）；`PYINSTALLER_CONFIG_DIR` 也钉住，否则机器共享缓存被清这件事
 *     又悄悄回来了；
 *  2) `dist:win` / `dist:win:dir` 必须仍**委托**给 `npm run pyinstaller`：把 PyInstaller 调用就地
 *     内联进任一条，1) 的两条断言会全绿而真实发布链已经回归（守卫吃的是 package.json 的现值）；
 *  3) 两条路都只读 package.json / lq_dataprase.spec 的现值推导，不在测试里复写第二份
 *     字面量（路径口径以 `icon=` 按 .spec 所在目录解析为准，PyInstaller building/api.py
 *     的 _makeabs，spec:448 注释同源）。
 *
 * 另一条实测事实解释了为什么「搬家」藏不住旧图而「同目录」能：`checking EXE` 把目标**绝对路径**
 * 钉进 TOC，workpath 一搬家必触发 `Building because name changed` 全量重建（task-13 报告 §1.1
 * 与 E1/E1b）；陈旧只在**同一 workpath 跨 run 存活**时出现——默认 `build/` 恰好满足这一点，
 * 而 `build/pyi-work` 加上 `--clean` 把这条路堵死（复现 S2 / 转绿 S3）。
 */
describe('npm run pyinstaller：强制干净重建，且 workpath 与 build/ 图标资产分离（Task 13）', () => {
  const REPO = (rel: string) => fileURLToPath(new URL('../../../' + rel, import.meta.url))

  it('package.json 的 pyinstaller 命令显式带 --workpath 与 --clean（并钉住仓库本地缓存目录）', () => {
    const pkg = JSON.parse(readFileSync(REPO('package.json'), 'utf8')) as { scripts: Record<string, string> }
    const cmd = pkg.scripts.pyinstaller
    expect(cmd).toContain('lq_dataprase.spec')
    const wp = /--workpath(?:=|\s)+"?([^\s"&]+)"?/.exec(cmd)
    expect(wp).not.toBeNull()
    expect(cmd).toMatch(/--clean(\s|"|&)/)
    // 陈旧靠 --clean 修（机理见文首 _GUTS 那条），搬家只是卫生：两者缺一都别想绿灯出货旧图标。
    // PYINSTALLER_CONFIG_DIR 把 --clean 的第二刀（CONF['cachedir']，默认 %LOCALAPPDATA%\pyinstaller，
    // 机器共享）关进仓库；读码依据 configure.py:55-56，运行时未验（守卫只钉命令形态）。
    expect(cmd).toMatch(/PYINSTALLER_CONFIG_DIR=/)
  })

  it('dist:win 与 dist:win:dir 仍委托给 npm run pyinstaller，不各自内联 PyInstaller 调用', () => {
    const pkg = JSON.parse(readFileSync(REPO('package.json'), 'utf8')) as { scripts: Record<string, string> }
    // 委托是「一条命令改两处」的唯一防线：内联之后上面两条断言照样绿，发布链却已经裸奔。
    expect(pkg.scripts['dist:win']).toContain('npm run pyinstaller')
    expect(pkg.scripts['dist:win:dir']).toContain('npm run pyinstaller')
  })

  it('--workpath 解析后既不等于、也不包住 build/icon.ico 与 icon.png 所在目录', () => {
    const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
    const pkg = JSON.parse(readFileSync(REPO('package.json'), 'utf8')) as { scripts: Record<string, string> }
    const wp = /--workpath(?:=|\s)+"?([^\s"&]+)"?/.exec(pkg.scripts.pyinstaller)
    expect(wp).not.toBeNull()
    // npm scripts 的 cwd 是 package.json 所在目录（仓库根），相对 workpath 按此解析。
    const workpath = path.resolve(repoRoot, wp![1].replace(/\\/g, '/'))

    // icon= 按 .spec 所在目录解析；lq_dataprase.spec 就在仓库根 → 资产目录 = root/build。
    const specSrc = readFileSync(REPO('lq_dataprase.spec'), 'utf8')
    const iconRel = /icon\s*=\s*['"]([^'"]+)['"]/.exec(specSrc)
    expect(iconRel).not.toBeNull()
    const iconAbs = path.resolve(repoRoot, iconRel![1].replace(/\//g, path.sep))
    const iconDir = path.dirname(iconAbs)
    const pngAbs = path.resolve(iconDir, 'icon.png') // 生成器与 .ico 同目录落盘（gen-icon.ico.js OUT_PNG）

    // (1) 不得是同一个目录：同树则缓存树与资产重写共享一条路径
    expect(workpath).not.toBe(iconDir)
    // (2) 资产不得落在 workpath 子树内：path.relative 以 .. 开头 ⇒ 在圈外。
    // rel === '' 意味着 workpath 直接指到资产文件本身，那是最坏的重合，不许放过。
    for (const asset of [iconAbs, pngAbs]) {
      const rel = path.relative(workpath, asset)
      expect(rel.startsWith('..') || path.isAbsolute(rel)).toBe(true)
    }
  })
})

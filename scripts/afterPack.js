/**
 * afterPack hooks for the LQ-DataPrase Windows packaging.
 *
 * Background (worked out empirically on this machine):
 *   - The local real-time antivirus (Tencent PC Manager; Windows Defender is
 *     disabled here) scans the freshly-unpacked ~180 MB app exe. A lock held
 *     during that scan makes electron-builder's rcedit fail with
 *     "Fatal error: Unable to commit changes". Waiting for the exe to become
 *     freely writable BEFORE rcedit is not enough: rcedit's own write (it now
 *     also embeds build/icon.ico, restarting the resource tree) triggers a NEW
 *     scan that collides with rcedit's commit (EndUpdateResource). Hence a
 *     plain wait cannot win this race deterministically.
 *   - electron-builder calls afterPack BEFORE signAndEditResources (rcedit),
 *     and afterPack runs before the NSIS/zip targets compress win-unpacked, so
 *     this hook owns the job when win.signAndEditExecutable is false.
 *
 * What this hook does (win build, signAndEditExecutable === false):
 *   1. Runs rcedit itself (same command electron-builder would run, same
 *      app-builder machinery, same cached rcedit binary) with an exponential
 *      backoff loop (2s, 5s, 10s, 20s, 40s, 60s, 90s, 120s …). Each retry
 *      re-opens the file; by the time the scan finishes one of them wins and
 *      the exe carries the icon + version metadata. Total patience ~6 min;
 *      after that we log loudly and continue (a metadata-less exe is better
 *      than a failed build, and electron-builder's packaging is not blocked).
 *   2. Keeps the old "wait until the exe is writable" probe for the case
 *      where signAndEditExecutable is left at its default true (harmless,
 *      zero-cost when the file is already free).
 *
 * NOTE: `afterPack` is resolved relative to process.cwd(); all supported
 * flows (scripts\electron-builder.cmd, npm run dist:win, build.bat) run
 * electron-builder from the repo root, so ./scripts/afterPack.js works.
 */
const path = require('path')

const ROOT = path.join(__dirname, '..')
const FRONTEND_NODE_MODULES = path.join(ROOT, 'frontend', 'node_modules')

// --- rcedit backoff control -------------------------------------------------

const RCEDIT_RETRY_DELAYS_MS = [
  2000, 5000, 10000, 20000, 40000, 60000, 90000, 120000, 120000,
]

// --- wait-for-release probe (default signAndEditExecutable path) ------------

const PROBE_INTERVAL_MS = 1000
const PROGRESS_LOG_MS = 30 * 1000
const TIMEOUT_MS = 10 * 60 * 1000

function waitUntilOpenForWrite(file, timeoutMs, label) {
  const fs = require('fs')
  const started = Date.now()
  let lastProgressLog = started
  return new Promise((resolve) => {
    const check = () => {
      if (Date.now() - started >= timeoutMs) {
        console.warn(`[afterPack] ${label} still locked after 10 min, proceeding anyway`)
        return resolve()
      }
      try {
        const fd = fs.openSync(file, 'r+')
        fs.closeSync(fd)
        const waitedSec = ((Date.now() - started) / 1000).toFixed(1)
        if (Number(waitedSec) > 0.5) {
          console.log(`[afterPack] ${label} openable for write after ${waitedSec}s`)
        }
        return resolve()
      } catch {
        if (Date.now() - lastProgressLog >= PROGRESS_LOG_MS) {
          lastProgressLog = Date.now()
          console.log(
            `[afterPack] ${label} still locked (${Math.round((Date.now() - started) / 1000)}s), waiting`
          )
        }
        setTimeout(check, PROBE_INTERVAL_MS)
      }
    }
    check()
  })
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Locate the cached rcedit binary (%LOCALAPPDATA%\electron-builder\Cache\
 * winCodeSign\winCodeSign-*\rcedit-x64.exe, or $ELECTRON_BUILDER_CACHE).
 * Returns null when electron-builder hasn't downloaded winCodeSign yet.
 */
function findCachedRcedit() {
  const fs = require('fs')
  const os = require('os')
  const cacheRoot =
    process.env.ELECTRON_BUILDER_CACHE ||
    (process.platform === 'win32'
      ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'electron-builder', 'Cache')
      : path.join(os.homedir(), '.cache', 'electron-builder'))
  let dirs = []
  try {
    dirs = fs.readdirSync(path.join(cacheRoot, 'winCodeSign'), { withFileTypes: true })
      .filter((d) => d.isDirectory() && d.name.startsWith('winCodeSign-'))
      .map((d) => path.join(cacheRoot, 'winCodeSign', d.name))
  } catch {
    return null
  }
  // latest version dir wins (winCodeSign-2.6.0 > ...)
  dirs.sort().reverse()
  for (const dir of dirs) {
    const exe = path.join(dir, process.platform === 'win32' ? 'rcedit-x64.exe' : 'rcedit')
    if (fs.existsSync(exe)) {
      return exe
    }
  }
  return null
}

/**
 * Run rcedit directly with no builder-util error logging (executeAppBuilder
 * prints a scary "⨯ cannot execute" error for every failed attempt even when
 * the very next retry succeeds).
 */
function runRceditDirect(rceditExe, args) {
  const { spawn } = require('child_process')
  return new Promise((resolve, reject) => {
    const child = spawn(rceditExe, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true })
    let stderr = ''
    child.stderr.on('data', (d) => (stderr += d))
    child.on('error', reject)
    child.on('close', (code) => {
      if (code === 0) {
        resolve()
      } else {
        reject(new Error(`rcedit exited with ${code}: ${stderr.trim().slice(0, 300)}`))
      }
    })
  })
}

/**
 * The exact rcedit invocation electron-builder's WinPackager.signAndEditResources
 * would run, executed with the cached rcedit binary (falling back to the
 * app-builder wrapper which downloads it on fresh machines), with our own
 * backoff loop on top.
 */
async function runRceditWithBackoff(packager, exe, label) {
  const appInfo = packager.appInfo
  const args = [
    exe,
    '--set-version-string', 'FileDescription', appInfo.description || appInfo.productName,
    '--set-version-string', 'ProductName', appInfo.productName,
    '--set-version-string', 'LegalCopyright', appInfo.copyright,
    '--set-file-version', appInfo.shortVersion || appInfo.buildVersion,
    '--set-product-version',
    appInfo.shortVersionWindows || appInfo.getVersionInWeirdWindowsForm(),
    '--set-version-string', 'InternalName', path.basename(exe, '.exe'),
    '--set-version-string', 'OriginalFilename', '',
  ]
  if (appInfo.companyName != null) {
    args.push('--set-version-string', 'CompanyName', appInfo.companyName)
  }
  if (typeof packager.getIconPath === 'function') {
    try {
      const iconPath = await packager.getIconPath()
      if (iconPath != null) {
        args.push('--set-icon', iconPath)
      }
    } catch (e) {
      console.warn(`[afterPack] icon resolution skipped: ${e.message}`)
    }
  }

  let rceditExe = findCachedRcedit()
  if (rceditExe == null) {
    // No cached winCodeSign yet (fresh machine): let app-builder download it.
    // executeAppBuilder prints ⨯ on failure — acceptable here, it only happens
    // while rcedit is being provisioned.
    console.log(`[afterPack] cached rcedit not found, delegating to app-builder`)
  }

  for (const delayMs of RCEDIT_RETRY_DELAYS_MS) {
    if (delayMs > 0) {
      await sleep(delayMs)
    }
    try {
      if (rceditExe != null) {
        await runRceditDirect(rceditExe, args)
      } else {
        const { executeAppBuilder } = require(path.join(
          FRONTEND_NODE_MODULES,
          'builder-util',
          'out',
          'util'
        ))
        await executeAppBuilder(['rcedit', '--args', JSON.stringify(args)], undefined, {}, 0)
      }
      console.log(`[afterPack] rcedit ${label} OK (embedded icon + version metadata)`)
      return
    } catch (e) {
      console.log(`[afterPack] rcedit ${label} attempt failed (${e.message}), retrying`)
    }
  }
  console.error(
    `[afterPack] rcedit ${label} failed after all backoff attempts; ` +
      'the exe will lack the icon/version metadata'
  )
}

// NOTE: export via `module.exports` (not `exports.default`).
// electron-builder resolves hooks with resolveFunction(): for the app package
// (frontend/package.json has "type": "module") it loads the hook through a
// dynamic import(), whose namespace.default is the CJS module.exports — an
// `exports.default` wrapper would yield an object and fail with
// "handler is not a function". Plain module.exports works under both the
// dynamic-import and the require() resolution paths.
module.exports = async function afterPack(context) {
  const { appOutDir, packager } = context
  const exe = path.join(appOutDir, `${packager.appInfo.productFilename}.exe`)
  const label = path.basename(exe)
  const fs = require('fs')
  if (!fs.existsSync(exe)) {
    return
  }

  if (
    packager.platformSpecificBuildOptions != null &&
    packager.platformSpecificBuildOptions.signAndEditExecutable === false
  ) {
    await runRceditWithBackoff(packager, exe, label)
    return
  }

  // Default path: electron-builder runs rcedit itself — just wait for the
  // post-unpack scan to release the file first.
  await waitUntilOpenForWrite(exe, TIMEOUT_MS, label)
}

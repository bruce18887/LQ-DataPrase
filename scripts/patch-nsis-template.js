#!/usr/bin/env node
/**
 * Patch electron-builder's vendored NSIS templates so the installer shows the
 * files it is extracting/copying, instead of a frozen progress bar.
 *
 * Background: with a large payload (PyInstaller bundle, loose files) the NSIS
 * progress bar reaches ~100% as soon as app-64.7z is written to $PLUGINSDIR,
 * then Nsis7z::Extract + CopyFiles run for minutes with NO visible feedback.
 * The template both hides the detail log (`SetDetailsPrint none`) and copies
 * silently (`CopyFiles /SILENT`), so the user sees a stuck bar with no file
 * list. The NSIS UI thread is blocked during those phases, so the detail log
 * is the ONLY progress signal available.
 *
 * Patches (both marked with `; [LQ-DataPrase patch]`):
 *  1. installSection.nsh: `SetDetailsPrint none` -> `textonly`
 *     (full per-file log; `lastused` only shows the last line, which does not
 *     convey progress for thousands of files)
 *  2. extractAppPackage.nsh: `CopyFiles /SILENT` -> `CopyFiles`
 *     (drop the /SILENT flag so each copied file produces a "Copy: ..." line)
 *
 * The templates live in node_modules and are wiped by `npm install`, so this
 * patch is re-applied at the start of every packaging run (see package.json
 * `dist:win`). Idempotent: skips if the new patch is already present;
 * upgrades the v1 patch (lastused) if found. Fails loudly if the expected
 * template text is not found, so an electron-builder upgrade that changes the
 * template cannot silently disable the patch.
 */
const fs = require('fs')
const path = require('path')

const MARKER = '; [LQ-DataPrase patch]'
const V1_MARKER = 'SetDetailsPrint lastused ; [LQ-DataPrase patch]'

const INSTALL_SECTION = path.join(
  __dirname,
  '..',
  'node_modules',
  'app-builder-lib',
  'templates',
  'nsis',
  'installSection.nsh'
)

const EXTRACT_PACKAGE = path.join(
  __dirname,
  '..',
  'node_modules',
  'app-builder-lib',
  'templates',
  'nsis',
  'include',
  'extractAppPackage.nsh'
)

// --- installSection.nsh -----------------------------------------------------

const SECTION_V1 = `\${IfNot} \${Silent}
  SetDetailsPrint lastused ${MARKER} show detail log (progress bar is frozen during Nsis7z::Extract + CopyFiles)
  DetailPrint "正在安装 LQ-DataPrase，正在解压应用文件，首次安装可能需要几分钟，请耐心等待…"
\${endif}`

const SECTION_V2 = `\${IfNot} \${Silent}
  SetDetailsPrint textonly ${MARKER} full per-file log (lastused shows only one line)
  DetailPrint "正在安装 LQ-DataPrase，正在解压应用文件，首次安装可能需要几分钟，请耐心等待…"
\${endif}`

const SECTION_ORIGINAL = `\${IfNot} \${Silent}
  SetDetailsPrint none
\${endif}`

// --- extractAppPackage.nsh --------------------------------------------------

const COPY_V1 = `CopyFiles /SILENT "$PLUGINSDIR\\7z-out\\*" $OUTDIR`

const COPY_V2 = `CopyFiles "$PLUGINSDIR\\7z-out\\*" $OUTDIR ${MARKER} no /SILENT so per-file "Copy: ..." lines are shown`

function replaceOnce(file, pairs, label) {
  if (!fs.existsSync(file)) {
    console.error(`[patch-nsis-template] ${label} template not found: ${file}`)
    process.exit(1)
  }
  let source = fs.readFileSync(file, 'utf8')
  for (const [oldText, newText] of pairs) {
    if (source.includes(newText)) {
      console.log(`[patch-nsis-template] ${label}: already patched (new), skipping`)
      return
    }
  }
  for (const [oldText, newText] of pairs) {
    if (source.includes(oldText)) {
      source = source.replace(oldText, newText)
      fs.writeFileSync(file, source, 'utf8')
      console.log(`[patch-nsis-template] ${label}: patched`)
      return
    }
  }
  console.error(
    `[patch-nsis-template] ${label}: expected template text not found. ` +
      'electron-builder template may have changed; check manually:\n' +
      `  ${file}`
  )
  process.exit(1)
}

// installSection.nsh: v1 (lastused) upgrade takes precedence, then original
replaceOnce(INSTALL_SECTION, [
  [SECTION_V1, SECTION_V2],
  [SECTION_ORIGINAL, SECTION_V2],
], 'installSection.nsh')

// extractAppPackage.nsh: CopyFiles /SILENT -> CopyFiles (with detail output)
replaceOnce(EXTRACT_PACKAGE, [
  [COPY_V1, COPY_V2],
], 'extractAppPackage.nsh')

console.log('[patch-nsis-template] all templates up to date')

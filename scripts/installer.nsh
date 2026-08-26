; ============================================================
; LQ-DataPrase - NSIS custom hooks (electron-builder nsis.include)
;
; electron-builder 的内置卸载逻辑只在检测到 --delete-app-data 参数时才
; 删除用户数据目录；常规卸载不删。此钩子在卸载时交互式询问是否删除：
;   用户数据位于 %APPDATA%\lq-dataprase\
;   （db.sqlite3、media/、secret.key、日志 —— Electron 通过 LQDP_BASE_DIR
;    传递给 Python 后端，见 electron/backend.ts）
;
; electron-builder 在卸载段末尾 !insertmacro customUnInstall
; （templates/nsis/uninstaller.nsh）。此文件同时编译进安装包与卸载程序，
; 宏只在卸载上下文被调用。
;
; 实现要点（均为实测得出的约束）：
;   - 不要使用 "/SD IDNO"：NSIS MessageBox 解析遇到 /SD 后会把后续 token
;     吞掉，产生 "could not resolve label <消息文本>" 编译错误。
;     静默卸载（uninstaller /S，含升级时的旧版卸载）改用 ${Silent} 守卫，
;     静默时直接跳过询问。
;   - 用相对跳转（IDYES +2 / Goto +1），避免自定义命名标签。
;   - 文件编码 UTF-8（无 BOM）+ CRLF；用 .NET API 读写时显式传
;     UTF8Encoding(false)（本机 PowerShell 5.1 默认 GBK 会损坏中文）。
; ============================================================

!macro customUnInstall
  ; --delete-app-data 时内置逻辑已删除，不再重复询问
  ${ifNot} $isDeleteAppData == "1"
    ${ifNot} ${Silent}
      MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "是否同时删除 LQ-DataPrase 的用户数据（数据库、已上传的数据文件、日志）？$\r$\n$\r$\n位置：$APPDATA\lq-dataprase$\r$\n删除后数据无法恢复，请确认已备份。" IDYES +2
      Goto +1
      RMDir /r "$APPDATA\lq-dataprase"
    ${endif}
  ${endif}
!macroend

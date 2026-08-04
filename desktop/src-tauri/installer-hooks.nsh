; 翻譯蒟蒻 NSIS 安裝鉤子
; 升級前先終止仍在執行的 App 與引擎(系統匣背景模式會鎖住 konjac-engine.exe)
!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec 'taskkill /F /IM konjac-desktop.exe /T'
  nsExec::Exec 'taskkill /F /IM konjac-engine.exe /T'
  Sleep 800
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /IM konjac-desktop.exe /T'
  nsExec::Exec 'taskkill /F /IM konjac-engine.exe /T'
  Sleep 800
!macroend

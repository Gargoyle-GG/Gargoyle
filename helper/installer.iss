; The Gargoyle app's installer (Inno Setup 6), built by tools/build_downloads.py:
;   ISCC.exe /DAppVersion=1.2.0 /DSource=<the PyInstaller GargoyleApp folder> /O<output folder> installer.iss
;
; Installs for the current Windows user only (no admin rights) into
; %LOCALAPPDATA%\Programs\Gargoyle, with a Start menu shortcut, optionally a desktop
; shortcut and starting with Windows, and an uninstaller in Windows' Apps list. Running a
; newer GargoyleSetup.exe updates it in place, closing the running app first.
; The app's own settings (%APPDATA%\Gargoyle) are left alone by updates and uninstalling.
;
; The app's "Update now" (helper/self_update.py) runs this quietly with /fromapp=1: then the
; choices made since in the app (Damage tooltips, starting with Windows) and the desktop
; shortcut are left as they are, and the app's window opens again afterwards.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z
#endif
#ifndef Source
  #error Pass /DSource=<the PyInstaller GargoyleApp folder>
#endif

[Setup]
; (Never change AppId: it's how a new version finds the one already installed.)
AppId={{6E3B1F0A-5C2D-4B8E-9A47-2F1D8C3E7B90}
AppName=Gargoyle
AppVersion={#AppVersion}
AppVerName=Gargoyle {#AppVersion}
AppPublisher=Gargoyle
AppPublisherURL=https://gargoyle.gg
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Gargoyle
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=GargoyleSetup
SetupIconFile=assets\gargoyle.ico
UninstallDisplayIcon={app}\GargoyleApp.exe
UninstallDisplayName=Gargoyle
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; A running Gargoyle is asked to quit before its files are replaced (CloseGargoyle below;
; Windows' own closing is the fallback), and is started again afterwards.
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a Gargoyle shortcut on the desktop"; Flags: unchecked
Name: "startup"; Description: "Start Gargoyle when Windows starts (it waits quietly in the tray)"; Flags: unchecked
Name: "tooltips"; Description: "Also install Damage tooltips: a breakdown of your spells' damage and healing on their tooltips in game (turn it on or off in game in Gargoyle's options)"

[InstallDelete]
; The old version's libraries go before the new ones are copied in.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[INI]
; The "Also install Damage tooltips" tick, for the app to read once (addon_install.installer_choice):
; the app installs that addon itself, from Gargoyle's signed release, like the Gargoyle addon.
Filename: "{app}\choices.ini"; Section: "addons"; Key: "tooltips"; String: "1"; Tasks: tooltips; Check: not FromApp; Flags: uninsdeletesection
Filename: "{app}\choices.ini"; Section: "addons"; Key: "tooltips"; String: "0"; Tasks: not tooltips; Check: not FromApp; Flags: uninsdeletesection

[Icons]
Name: "{autoprograms}\Gargoyle"; Filename: "{app}\GargoyleApp.exe"
Name: "{autodesktop}\Gargoyle"; Filename: "{app}\GargoyleApp.exe"; Tasks: desktopicon; Check: not FromApp

[Registry]
; The same per-user entry the app's own "Start with Windows" switch uses (helper/startup.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Gargoyle"; ValueData: """{app}\GargoyleApp.exe"" --tray"; Tasks: startup; Check: not FromApp
; Removed when Gargoyle is uninstalled, however it was turned on.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Gargoyle"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\GargoyleApp.exe"; Description: "Open Gargoyle"; Flags: nowait postinstall skipifsilent
; (After a quiet update, Gargoyle comes back by itself: in the tray, or its window after Update now.)
Filename: "{app}\GargoyleApp.exe"; Parameters: "{code:RestartParameters}"; Flags: nowait; Check: WizardSilent

[Code]
// Run by the app's own "Update now" (/fromapp=1)?
function FromApp(): Boolean;
begin
  Result := ExpandConstant('{param:fromapp|0}') = '1';
end;

function RestartParameters(Param: String): String;
begin
  if FromApp() then
    Result := ''
  else
    Result := '--tray';
end;

// Before installing over it or uninstalling it: a running Gargoyle (maybe waiting in the
// tray) is asked to quit, by leaving a "quit" file in its settings folder that it looks for
// every second. Only if it hasn't gone after a few seconds is it closed by force.
procedure CloseGargoyle();
var
  Code, I: Integer;
  QuitFile: String;
begin
  if not CheckForMutexes('GargoyleApp') then
    exit;
  QuitFile := ExpandConstant('{userappdata}\Gargoyle\quit');
  SaveStringToFile(QuitFile, 'quit', False);
  for I := 1 to 50 do begin
    if not CheckForMutexes('GargoyleApp') then
      break;
    Sleep(100);
  end;
  if CheckForMutexes('GargoyleApp') then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM GargoyleApp.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  DeleteFile(QuitFile);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseGargoyle();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    CloseGargoyle();
  // Settings, and this PC's link to the account, are kept (installing again picks them up)
  // unless you say otherwise. Quiet uninstalls keep them.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Also remove Gargoyle''s settings from this PC, including its link to your Gargoyle account?' + #13#10#13#10 +
              'Choose No to keep them for next time.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\Gargoyle'), True, True, True);
end;

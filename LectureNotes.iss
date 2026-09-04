; 강의 노트 설치 프로그램 (Inno Setup)
;
; 빌드 순서:
;   1) .venv\Scripts\pyinstaller LectureNotes.spec --noconfirm
;   2) "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" LectureNotes.iss
; 결과물: installer\LectureNotes-Setup-<버전>.exe

#define AppName "강의 노트"
#define AppVersion "1.0.0"
#define AppPublisher "Peter"
#define AppExe "LectureNotes.exe"

[Setup]
; 이 GUID로 같은 앱임을 알아보고 덮어쓰기/제거를 처리합니다. 절대 바꾸지 마세요.
AppId={{0AC195F7-7815-4410-B164-91B208733256}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}

; 관리자 권한 없이 설치합니다. 받는 사람이 UAC 창을 만나지 않고, 회사·학교
; 노트북처럼 권한이 막힌 PC에서도 설치됩니다. {autopf}는 이 설정에서
; %LOCALAPPDATA%\Programs 로 풀립니다.
PrivilegesRequired=lowest
DefaultDirName={autopf}\LectureNotes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; 앱이 실행 중이면 설치를 멈추고 종료를 안내합니다. 창을 닫아도 트레이에 남는
; 구조라 자동으로 닫게 두면 프로세스가 살아남아 파일이 잠긴 채로 설치가
; 깨집니다. 녹음 중일 수도 있어 강제 종료도 하지 않습니다.
AppMutex=LectureNotes-running
CloseApplications=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=installer
OutputBaseFilename=LectureNotes-Setup-{#AppVersion}
SetupIconFile=assets\LectureNotes.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
; 둘 다 기본 체크입니다. 자동 녹음은 앱이 떠 있어야만 동작하므로, 시작 프로그램
; 등록을 꺼두면 정작 이 앱의 핵심 기능이 조용히 안 되는 상태로 설치됩니다.
; 원하지 않으면 설치 화면에서 체크를 풀면 되고, 기본값을 바꾸려면 아래 두 줄
; 끝에 `; Flags: unchecked` 를 붙이세요.
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"
Name: "startupicon"; Description: "Windows를 켤 때 자동으로 실행 (자동 녹음을 쓰려면 필요합니다)"; GroupDescription: "추가 작업:"

[Files]
Source: "dist\LectureNotes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

[Code]
function DataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\LectureNotes');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // 녹음·녹취록·요약·API 키는 설치 폴더가 아니라 사용자 폴더에 있습니다.
  // 지우지 않고, 어디에 남아 있는지만 알려줍니다.
  // 조용한 제거(/SILENT)에서는 띄우지 않습니다 -- 아무도 못 보는 창 때문에
  // 제거가 끝나지 않고 멈춰 있게 됩니다.
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent())
     and DirExists(DataDir()) then
    MsgBox('녹음 파일과 요약, 설정은 지우지 않았습니다.' #13#10 #13#10
      + DataDir() + #13#10 #13#10
      + '다시 설치하면 그대로 이어서 쓸 수 있습니다.' #13#10
      + '완전히 지우려면 위 폴더를 직접 삭제하세요.',
      mbInformation, MB_OK);
end;

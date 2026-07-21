; 원천징수 자동화 Inno Setup 설치 스크립트
; 빌드: python build.py (ISCC 자동 실행 — /DAppVersion 으로 버전 주입)

; 버전은 build.py가 src/version.py를 읽어 /DAppVersion 으로 전달한다.
; 직접 ISCC 실행 시(define 없음) 폴백값 사용.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppName=원천징수 자동화
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=세무법인
AppPublisherURL=https://example.com
AppSupportURL=https://example.com

; %LOCALAPPDATA%에 설치 → 관리자 권한 불필요
DefaultDirName={localappdata}\원천징수자동화
DefaultGroupName=원천징수 자동화

; 출력 설정
OutputDir=installer_output
OutputBaseFilename=원천징수자동화_설치
; LZMA(ultra64) 압축은 Windows Defender 휴리스틱 오탐(0x800700E1)을 유발하는
; 문서화된 패턴이다. zip(deflate)으로 변경하여 LZMA 서명을 제거.
; 용량 손실은 build.py 의 Qt 미사용 모듈 exclude(번들 859→~315MB)가 상쇄한다.
Compression=zip
SolidCompression=yes

; 아이콘
UninstallDisplayIcon={app}\원천징수자동화.exe

; 제어판 "프로그램 및 기능"에 표시될 정보
UninstallDisplayName=원천징수 자동화
; 제거 확인 메시지
Uninstallable=yes

; 관리자 권한 불필요 (localappdata에 설치)
PrivilegesRequired=lowest

; 자동 업데이트: 실행 중인 앱을 감지/종료하여 파일 잠금 충돌(반쪽 덮어쓰기) 방지.
; AppMutex는 앱(gui_main)이 생성하는 명명 뮤텍스와 반드시 일치해야 함.
; 재실행은 cmd 래퍼가 담당하므로 RestartApplications=no (이중 실행 방지).
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no
AppMutex=WithholdingTaxAutomation_SingleInstance

; 항상 개인 시작 메뉴 그룹 사용
AlwaysUsePersonalGroup=yes

; 설치 중 화면 설정
SetupIconFile=
WizardStyle=modern

; 라이선스 표시 안함
DisableWelcomePage=no

; 이전 버전 자동 제거
AppId={{B8F3C1A2-7D4E-4A9F-8B2C-6E1D3F5A9C04}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
korean.WelcomeLabel2=원천징수 자동화 프로그램을 설치합니다.%n%n계속하려면 [다음]을 클릭하세요.

[Code]
function ChromeInstalled: Boolean;
var
  RegPath: string;
begin
  { 고정 경로 3종: 64비트 / 32비트(x86) / 사용자 단위 설치.
    x86 경로 누락 시 해당 PC에서 자동 업데이트 무인 설치(/VERYSILENT)가
    이 게이트에서 조용히 exit 1 → 앱 재실행 불발로 "업데이트만 조용히 실패"한다. }
  Result :=
    FileExists('C:\Program Files\Google\Chrome\Application\chrome.exe') or
    FileExists('C:\Program Files (x86)\Google\Chrome\Application\chrome.exe') or
    FileExists(ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe'));
  { 비표준 설치 경로 대비: Windows App Paths 등록값(설치 시 Chrome 이 기록) }
  if not Result then
    if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe', '', RegPath) or
       RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe', '', RegPath) then
      Result := FileExists(RegPath);
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if not ChromeInstalled then
  begin
    // 이 프로그램은 모든 자동화가 Chrome CDP 제어에 의존하므로 Chrome 이 없으면
    // 설치해도 무용지물이다. 비전공자가 "설치는 됐는데 안 된다"에 빠지지 않도록
    // 설치 단계에서 명확히 차단하고 Chrome 설치를 안내한다.
    MsgBox(
      'Google Chrome이 설치되어 있지 않습니다.' + #13#10 + #13#10 +
      '이 프로그램은 모든 기능이 Chrome 을 필요로 합니다.' + #13#10 +
      '먼저 Chrome 을 설치한 뒤 이 설치파일을 다시 실행해 주세요.' + #13#10 + #13#10 +
      'Chrome 다운로드: https://www.google.com/chrome/',
      mbError, MB_OK);
    Result := False;
  end;
end;

[InstallDelete]
; 이전 admin 설치 잔여 바로가기 제거
Type: files; Name: "{commonprograms}\원천징수 자동화\*"
Type: filesandordirs; Name: "{commonprograms}\원천징수 자동화"

[Files]
; PyInstaller onedir 빌드 결과물 전체 복사
Source: "dist\원천징수자동화\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 바탕화면 바로가기 (현재 사용자)
Name: "{userdesktop}\원천징수 자동화"; Filename: "{app}\원천징수자동화.exe"
; 시작 메뉴 — 프로그램 + 제거
Name: "{group}\원천징수 자동화"; Filename: "{app}\원천징수자동화.exe"
; 제거 바로가기: unins000.exe 직접 참조 시 Windows가 필터링하므로 cmd 경유
Name: "{group}\원천징수 자동화 제거"; Filename: "{cmd}"; Parameters: "/c ""{uninstallexe}"""; Flags: runminimized

[UninstallRun]
; 제거 전 실행 중인 프로그램 종료
Filename: "taskkill"; Parameters: "/F /IM 원천징수자동화.exe"; Flags: runhidden; RunOnceId: "KillApp"

[Run]
; 설치 완료 후 실행 체크박스
Filename: "{app}\원천징수자동화.exe"; Description: "프로그램 실행"; Flags: nowait postinstall skipifsilent

; [UninstallDelete] 제거됨 — 사용자 데이터(DB/결과)는
; %LOCALAPPDATA%\원천징수자동화-data 에 저장되므로 설치 폴더 삭제(업그레이드/제거)와
; 무관하게 보존된다.

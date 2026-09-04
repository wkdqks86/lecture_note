# 강의 노트 앱

강의를 녹음 → (faster-whisper, 로컬 GPU) 텍스트 변환 → (Claude API) 요약/정리까지
자동으로 처리하는 데스크톱 앱.

## 요구사항

- Python 3.10+
- NVIDIA GPU + CUDA (RTX A3000 Laptop 기준 large-v3 모델을 float16으로 실행)
- Anthropic API 키

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

faster-whisper가 CUDA를 쓰려면 `cuBLAS`/`cuDNN` 런타임 DLL이 필요합니다.
`requirements.txt`에 포함된 `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`를 설치하면
전체 CUDA Toolkit 없이도 GPU를 쓸 수 있고, `app/transcriber.py`가 실행 시 해당
DLL 경로를 자동으로 등록합니다.

- `Library cublas64_12.dll is not found` 같은 오류가 나면: 위 두 패키지가 제대로
  설치됐는지 (`pip show nvidia-cublas-cu12`) 확인하세요.
- 그래도 GPU 초기화에 실패하면 `Transcriber`가 자동으로 CPU(int8)로 폴백합니다 —
  속도는 느려지지만 앱이 죽지는 않습니다.

`.env.example`을 `.env`로 복사하고 `ANTHROPIC_API_KEY`를 채워 넣으세요.

## 실행

```bash
python main.py
```

## 구조

```
app/
  paths.py        # BASE_DIR(코드 위치)와 DATA_DIR(사용자 데이터 위치)를 분리해서 관리
  db.py           # SQLite: 강의 메타데이터
  recorder.py     # 마이크 녹음 (sounddevice)
  transcriber.py  # faster-whisper STT
  summarizer.py   # Claude API 요약/정리
  schedule.py     # 교시 시간표 설정 (schedule.json 읽기/쓰기)
  auto_recorder.py # 시간표 기준 자동 녹음 시작/종료 (QTimer로 시각 감시)
  utils.py        # 파일 해시 등 공용 유틸
  ui/
    main_window.py
```

### 데이터는 어디에 저장되나 (중요)

**개발 중(`python main.py`로 직접 실행)**: 프로젝트 루트에 그대로 저장됩니다
(`recordings/`, `transcripts/`, `summaries/`, `models/`, `lecture_notes.db`,
`schedule.json`, `.env`).

**exe로 빌드한 뒤**: 위 파일들은 exe 폴더가 아니라 **`%LOCALAPPDATA%\LectureNotes\`**
(보통 `C:\Users\<사용자>\AppData\Local\LectureNotes\`)에 저장됩니다. exe 폴더 안에는
프로그램 파일만 있고 사용자 데이터는 없습니다 — **exe를 재빌드하거나 새 버전으로
통째로 교체해도 녹음/녹취록/설정이 절대 삭제되지 않도록** 일부러 분리해뒀습니다.
(예전 버전은 exe 옆에 저장했었는데, 재빌드할 때마다 배포 폴더가 통째로 새로 만들어지면서
실제 녹음 데이터가 삭제되는 사고가 있었습니다 — 이 구조는 그걸 근본적으로 막기 위한 것입니다.)

## 자동 녹음 (시간표 기준)

사이드바의 "자동 녹음 설정"에서 켜면, 등록된 교시 시간에 맞춰 자동으로 녹음을 시작하고
끝나면 자동으로 녹취/요약까지 진행합니다. 기본 시간표는 아래와 같고, 필요하면
`schedule.json`(위치는 "데이터는 어디에 저장되나" 참고)을 직접 수정하거나(시간 변경)
앱 안에서 교시별로 켜고 끌 수 있습니다.

| 교시 | 시간 | 교시 | 시간 |
|---|---|---|---|
| 1 | 09:00–09:55 | 5 | 14:00–14:55 |
| 2 | 10:00–10:55 | 6 | 15:00–15:55 |
| 3 | 11:00–11:55 | 7 | 16:00–16:55 |
| 4 | 12:00–12:55 | 8 | 17:00–17:55 |

- **앱이 켜져 있어야** 동작합니다. 창을 닫아도 시스템 트레이 아이콘으로 계속 실행되니,
  창은 닫아도 되지만 완전히 종료(트레이 메뉴 "종료")하면 안 됩니다.
- 트레이 아이콘에 빨간 점이 뜨면 현재 자동 녹음 중이라는 뜻입니다. 왼쪽 목록 아래
  상태 줄에도 같은 내용이 표시되고, 누르면 상태 창이 열립니다.
- "자동 녹음 상태"에서 **지금 종료**를 누르면 그 교시는 오늘 다시 시작되지 않습니다.
  (예: 3교시가 11:20에 일찍 끝나 종료를 눌러도, 11:55까지 다시 녹음되지 않습니다.)
- 수동 녹음("+ 새 강의 녹음")과 자동 녹음은 마이크를 동시에 쓸 수 없어서, 자동 녹음
  중엔 수동 녹음이 막히고 반대로 수동 녹음 중엔 자동 녹음이 잠깐 대기합니다.
- 시간대는 한국 시간(UTC+9) 고정입니다.
- 앱은 한 번에 하나만 실행됩니다. 이미 켜져 있는 상태에서 exe를 다시 실행하면 새 창이
  뜨는 대신 원래 창이 앞으로 나옵니다. (예전에는 실행할 때마다 프로세스가 늘어나면서
  여러 개의 자동 녹음이 같은 `.wav` 파일에 동시에 기록돼, 녹음이 비거나 깨졌습니다.)
- 매일 아침 컴퓨터를 켤 때 앱도 같이 켜지길 원하면, `dist/LectureNotes/LectureNotes.exe`의
  바로가기를 Windows 시작프로그램 폴더(`Win+R` → `shell:startup`)에 넣어두세요.

## 실행 파일(exe) 빌드

VSCode/터미널 없이 다른 사람도 실행할 수 있도록 PyInstaller로 배포용 exe를 만들 수 있습니다.
Whisper 모델(large-v3 약 3GB)은 exe에 포함하지 않고, 최초 실행 시 인터넷으로 자동 다운로드합니다.

```bat
pip install -r requirements.txt  REM pyinstaller 포함
pyinstaller LectureNotes.spec --noconfirm

REM 공유받는 사람용 초기 세팅 안내문 (API 키 등록 방법 등). 빌드할 때마다
REM dist\LectureNotes\가 새로 만들어지므로 빌드 후 다시 복사해 넣습니다.
copy USER_README.txt dist\LectureNotes\README.txt
```

빌드 설정은 `LectureNotes.spec`에 있습니다 (포함할 패키지, 제외할 `nvidia`, 아이콘).
명령줄 옵션 대신 이 파일을 고치세요 — `.gitignore`가 `*.spec`을 무시하지만 이 파일만은
예외로 추적합니다. 없이 빌드하면 CUDA가 다시 포함되어 2.3GB로 불어납니다.

앱 아이콘(`assets/LectureNotes.ico`)은 트레이 아이콘을 그리는 코드에서 생성합니다.
`_build_app_icon()`을 고쳤다면 다시 만들어 주세요:

```bat
.venv\Scripts\python tools\make_icon.py
```

사용자 데이터(`recordings/`, `transcripts/`, `summaries/`, `models/`, `lecture_notes.db`,
`schedule.json`, `.env`)는 `%LOCALAPPDATA%\LectureNotes\`에 저장되고 `dist/LectureNotes/`
안에는 안 들어가므로, **재빌드해도 지울 파일이 없습니다** — 별도로 백업/복사해둘 필요가
없어졌습니다.

결과물은 `dist/LectureNotes/` 폴더에 생성됩니다 (`LectureNotes.exe` + `_internal/` +
`README.txt`). **`dist/LectureNotes/` 폴더 전체를 그대로 복사(또는 zip)해서 배포**해야
합니다 (exe 파일 하나만 옮기면 동작하지 않습니다). `README.txt`는 `USER_README.txt`
(프로젝트 루트)가 원본이고, 처음 받는 사람이 API 키를 등록하는 방법을 안내합니다 —
내용을 고칠 땐 `USER_README.txt`를 수정하세요.

- 배포 폴더 크기는 약 346MB입니다. 용량이 큰 두 가지는 빌드에 넣지 않고 필요할 때
  인터넷에서 받습니다: Whisper 모델(large-v3, 약 3GB)과 CUDA 런타임(약 1.3GB).
- `--onedir` 대신 `--onefile`을 쓰지 마세요 — 실행할 때마다 배포 폴더 전체를 임시
  폴더에 풀어야 해서 시작이 매우 느려지고, 앱 데이터 경로 처리와도 맞지 않습니다.
- `.env`의 `ANTHROPIC_API_KEY`는 exe에 포함되지 않으므로, 처음 실행한 뒤
  `%LOCALAPPDATA%\LectureNotes\.env` 파일을 직접 만들어 넣어주세요 (`ANTHROPIC_API_KEY=...`
  한 줄). 예전 버전에서 exe 옆에 `.env`를 뒀던 경우 첫 실행 시 자동으로 옮겨줍니다.
- 다른 PC에 NVIDIA GPU가 없거나 GPU 초기화에 실패하면 `Transcriber`가 자동으로
  CPU + medium 모델로 전환됩니다 (large-v3보다 빠르지만 정확도는 약간 낮음).

## 설치 파일(setup.exe) 만들기

`dist/LectureNotes/` 폴더를 그대로 건네주는 대신, 더블클릭 한 번으로 설치되는
`setup.exe`를 만들 수 있습니다. [Inno Setup](https://jrsoftware.org/isinfo.php)이
필요합니다 (`winget install JRSoftware.InnoSetup`).

```bat
REM 1) 먼저 exe를 빌드해 둡니다 (위 "실행 파일(exe) 빌드" 참고)
pyinstaller LectureNotes.spec --noconfirm
copy USER_README.txt dist\LectureNotes\README.txt

REM 2) 설치 파일 컴파일
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" LectureNotes.iss
```

결과물은 `installer\LectureNotes-Setup-<버전>.exe` 입니다. 346MB 폴더가 약 92MB로
압축되므로, 배포할 때는 이 파일 하나만 건네주면 됩니다.

- **관리자 권한이 필요 없습니다.** `%LOCALAPPDATA%\Programs\LectureNotes`에 설치되어
  UAC 창이 뜨지 않고, 권한이 제한된 회사·학교 PC에서도 설치됩니다.
- 설치 화면에서 바탕화면 바로가기와 **Windows 시작 시 자동 실행**을 선택할 수 있고,
  둘 다 기본으로 켜져 있습니다. 자동 녹음은 앱이 떠 있어야 동작하기 때문입니다.
- **앱이 실행 중이면 설치가 중단되고 종료 안내가 뜹니다.** 창을 닫아도 트레이에 남는
  구조라 설치 프로그램이 창만 닫게 두면 프로세스가 살아남아 파일이 잠긴 채 설치가
  깨집니다. 이를 위해 앱이 `LectureNotes-running` 뮤텍스를 잡고, `.iss`의 `AppMutex`가
  그것을 확인합니다 (`app/single_instance.py`). 녹음 중일 수도 있으므로 강제 종료는
  하지 않습니다.
- **제거해도 녹음·요약·설정은 지워지지 않습니다.** 사용자 데이터는 설치 폴더가 아니라
  `%LOCALAPPDATA%\LectureNotes\`에 있어서, 제거 후 다시 설치하면 그대로 이어집니다.
  제거가 끝나면 데이터가 어디 남아 있는지 안내창으로 알려줍니다.
- 버전을 올릴 땐 `LectureNotes.iss`의 `AppVersion`만 고치면 됩니다. `AppId`(GUID)는
  같은 앱임을 알아보고 덮어쓰기·제거를 처리하는 값이라 **절대 바꾸지 마세요.**

### GPU 가속 (CUDA 런타임 자동 다운로드)

cuBLAS/cuDNN DLL은 압축을 풀면 1.9GB로, 예전 빌드 2.27GB의 85%를 차지했습니다.
NVIDIA GPU가 있는 PC에서만 쓸모가 있으므로 exe에 넣지 않고, `app/cuda_runtime.py`가
PyPI의 공식 휠(`nvidia-cublas-cu12`, `nvidia-cuda-nvrtc-cu12`, `nvidia-cudnn-cu12`)에서
필요한 DLL만 받아 `%LOCALAPPDATA%\LectureNotes\cuda\`에 풀어둡니다.
(다운로드 1.3GB → 압축 해제 후 약 2.0GB, DLL 16개.)

- NVIDIA GPU가 감지되면 **첫 실행 때 한 번** 다운로드를 권하는 창이 뜹니다. 이후에는
  **설정 → GPU 가속 설정**에서 언제든 받거나 지울 수 있습니다.
- 받지 않아도 앱은 그대로 동작합니다 (CPU + medium 모델). 인터넷이 없거나 다운로드에
  실패해도 마찬가지라, 가속은 "되면 빨라지는" 선택 사항입니다.
- 사용자 데이터와 같은 곳에 저장되므로 exe를 새 버전으로 교체해도 다시 받지 않습니다.
- 받는 도중 **중지**를 눌러도 안전합니다. 임시 폴더(`cuda.part`)에 받은 뒤 완료된
  경우에만 제자리로 옮기므로, 중간에 끊긴 파일이 설치된 것처럼 남지 않습니다.
- 버전은 `PACKAGES`에 고정돼 있고, 내려받은 파일은 SHA-256으로 검증합니다.
- 개발 환경(`.venv`)에서는 `requirements.txt`로 설치한 pip 패키지를 그대로 쓰므로
  따로 받을 필요가 없습니다 — `_cuda_dll_dirs()`가 두 위치를 모두 확인합니다.

## 다음 단계 후보

- 요약 결과 PDF 내보내기
- 화자 분리(diarization)
- 실행 파일에 `.env` 없이도 앱 안에서 API 키 입력받는 설정 화면

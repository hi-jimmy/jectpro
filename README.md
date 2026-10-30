# 서울 실거래 리포트

서울열린데이터광장 OA-21275 **서울시 부동산 실거래가 정보**를 수집해 웹에서 조회하는 Django 프로젝트입니다. 공식 Open API 서비스명은 `tbLnOpendataRtmsV`이며 JSON 경로 형식은 `/{인증키}/json/tbLnOpendataRtmsV/{시작}/{끝}/`입니다. 요청 범위는 페이지당 최대 1,000건입니다. API는 매일 1회 갱신되고, 필터 입력은 접수연도, 자치구코드, 자치구명, 법정동코드, 지번구분, 지번구분명, 본번, 부번, 건물명, 계약일, 건물용도 순서의 선택 경로 인자입니다.

응답에는 `list_total_count`, `RESULT.CODE`, `RESULT.MESSAGE`와 21개 필드(`RCPT_YR`, `CGG_CD`, `CGG_NM`, `STDG_CD`, `STDG_NM`, `LOTNO_SE`, `LOTNO_SE_NM`, `MNO`, `SNO`, `BLDG_NM`, `CTRT_DAY`, `THING_AMT`, `ARCH_AREA`, `LAND_AREA`, `FLR`, `RGHT_SE`, `RTRCN_DAY`, `ARCH_YR`, `BLDG_USG`, `DCLR_SE`, `OPBIZ_RESTAGNT_SGG_NM`)가 포함됩니다. 계약금액은 만원, 면적은 ㎡입니다. 인증키는 서울열린데이터광장에서 별도로 신청해야 합니다.

## 실행

Python 3.9 이상을 준비한 뒤 프로젝트 폴더에서 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

로그인: `http://127.0.0.1:8000/`  
관리자: `http://127.0.0.1:8000/admin/`

## Render 배포

프로젝트에는 Render Blueprint 설정(`render.yaml`), 빌드 스크립트(`build.sh`), Python 3.11 설정이 포함되어 있습니다. Render PostgreSQL을 사용하고, 로컬 Windows에서는 기존 SQLite를 계속 사용합니다. PythonAnywhere 설정은 필요하지 않습니다.

### GitHub에 올리기

1. GitHub에서 저장소를 만듭니다(공개/비공개 모두 가능).
2. 프로젝트 루트에서 Git을 초기화하고 코드를 올립니다. `.gitignore`가 가상환경, `.env`, SQLite 데이터베이스, 데이터 백업 파일을 제외하는지 확인하고 `db.sqlite3`나 API 키가 커밋되지 않았는지 먼저 확인하세요.
3. GitHub 저장소에 프로젝트를 push합니다.

### Render에서 서비스 만들기

1. Render에 로그인하고 **New → Blueprint**에서 GitHub 저장소를 연결합니다.
2. Render가 저장소 루트의 `render.yaml`을 읽어 `seoulhomes` 웹 서비스와 PostgreSQL을 만들도록 진행합니다.
3. Blueprint 생성 및 첫 배포를 확인합니다. 빌드 과정에서 의존성 설치, 정적 파일 수집, 데이터베이스 마이그레이션이 실행됩니다.
4. Render 대시보드에서 서비스 URL을 열어 로그인 화면과 정적 파일을 확인합니다.
5. 웹 서비스의 **Shell**에서 `python manage.py createsuperuser`를 실행하면 관리자 계정을 만들 수 있습니다.

Render가 제공하는 `DATABASE_URL`을 사용하므로 PostgreSQL 접속 비밀번호를 직접 코드에 넣을 필요가 없습니다. `DJANGO_SECRET_KEY`는 Blueprint가 자동 생성합니다. Render의 `RENDER_EXTERNAL_HOSTNAME`으로 공개 호스트가 자동 허용됩니다. 공개 데이터 화면을 채우려면 Render 서비스 환경변수에 `SEOUL_API_KEY`를 비밀값으로 추가하고 Shell에서 필요한 데이터셋을 동기화하세요.

```bash
python manage.py sync_seoul_data --sample --limit 5
python manage.py sync_open_data --dataset living --sample --limit 5
python manage.py sync_open_data --dataset store --sample --limit 5
python manage.py sync_open_data --dataset sales --sample --limit 5
```

### SQLite 데이터와 무료 플랜 주의사항

Git에 `db.sqlite3`를 올리지 않도록 설정되어 있습니다. 따라서 Render PostgreSQL에는 기존 로컬 데이터가 자동으로 복사되지 않습니다. 현재 샘플 등 공공데이터는 배포 후 Render Shell에서 동기화 명령을 실행해 다시 채울 수 있습니다. 계정 정보를 이전해야 한다면 데이터 이전을 별도로 준비해야 하며, `dumpdata` 파일을 공개 저장소에 올리지 마세요.

Blueprint는 이전에 선택한 무료 사용 기준으로 설정되어 있습니다. Render의 무료 웹 서비스는 15분 동안 요청이 없으면 잠들고, 무료 PostgreSQL은 생성 후 30일에 만료되며 그 뒤 데이터가 삭제될 수 있습니다. 또한 무료 플랜은 프로덕션 용도로 권장되지 않습니다. 사이트를 계속 운영하거나 회원 계정을 보존하려면 만료 전에 유료 PostgreSQL로 업그레이드하고 백업 정책을 마련하세요. 정책은 [Render 무료 플랜 안내](https://render.com/docs/free)에서 확인할 수 있습니다.

## API 데이터 수집

PowerShell에서 발급된 인증키를 환경변수로 설정하고 수집합니다.

```powershell
$env:SEOUL_API_KEY="발급받은_인증키"
python manage.py sync_seoul_data --year 2025 --limit 1000
```

추가 옵션은 `--district-code 11680`, `--building-use 아파트`입니다. 실제 요청 URL은 한 번에 최대 1,000건씩 페이지를 나누며, 저장된 데이터는 같은 레코드의 값이 갱신됩니다. 공식 샘플 키는 최대 5건 테스트 용도이며 `python manage.py sync_seoul_data --sample --limit 5`로 확인할 수 있습니다.

## MariaDB

Docker가 설치된 환경에서 `docker compose up -d db`를 실행하고, PowerShell 환경변수를 아래처럼 지정한 뒤 마이그레이션합니다.

```powershell
$env:DB_ENGINE="mysql"
$env:DB_NAME="seoulhomes"
$env:DB_USER="seoulhomes"
$env:DB_PASSWORD="seoulhomes-local"
$env:DB_HOST="127.0.0.1"
$env:DB_PORT="3306"
python manage.py migrate
```

현재 로컬 설정은 SQLite 기본값이므로 MariaDB가 아직 없어도 화면과 로그인 기능을 먼저 실행할 수 있습니다. 배포 환경에서는 Django 비밀키와 DB 비밀번호를 반드시 강한 값으로 바꾸고 `DJANGO_DEBUG=0`으로 설정하세요.

## 회원가입 및 비밀번호 재설정

로그인 화면에서 별도 `로그인`, `아이디 생성`, `비밀번호 찾기` 동작을 제공합니다. 가입 시 이메일 주소가 필수이며, 비밀번호 재설정 링크는 개발 기본 설정에서 실행 중인 터미널로 출력됩니다. 실제 메일을 보내려면 `.env.example`의 `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` 값을 SMTP 정보로 설정하세요.

## 추가 데이터셋과 Open API

서울 Open API는 `http://openapi.seoul.go.kr:8088/{인증키}/json/{서비스명}/{시작}/{끝}/{필터}/` 경로 형식입니다. 응답 공통 필드는 `list_total_count`, `RESULT.CODE`, `RESULT.MESSAGE`, `row`이며 요청당 최대 1,000건, 샘플 인증키는 최대 5건입니다.

| 메뉴      | 데이터셋 / 서비스명                         | 주요 필드                                                                      | 갱신 및 주의                                           |
| --------- | ------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------ |
| 생활인구  | OA-22784 / `Se250MSpopLocalResd`            | `YMD`, `TT`, `H_DNG_CD`, `CELL_ID`, `SPOP`, 남성 `M00`~`M70`, 여성 `F00`~`F70` | 매일 갱신, API는 4일 전 자료, 3명 이하 값은 `*` 비식별 |
| 점포      | OA-15577 / `VwsmTrdarStorQq`                | `STDR_YYQU_CD`, `TRDAR_CD`, `SVC_INDUTY_CD`, 점포수, 개업·폐업률/점포수        | 연간 메타 갱신, 분기 코드로 필터                       |
| 추정매출  | OA-15572 / `VwsmTrdarSelngQq`               | 분기·상권·업종, `THSMON_SELNG_AMT/CO`, 요일·시간·성별·연령별 매출/건수         | 분기 갱신, 금액 원, 2021년 이후 제공 안내              |
| 상권영역  | OA-15560 / 공식 Open API 명세 확인되지 않음 | 미리보기: 상권 코드/명, X/Y, 자치구/행정동, 영역 면적                          | 공식 ZIP/SHP 파일, 설명에 EPSG:5181 명시               |
| 서울 격자 | 250m SHP 파일                               | 격자 ID, 행정동 속성, polygon geometry                                         | EPSG:5179, 생활인구의 `CELL_ID`와 연결                 |

세 API는 같은 `SEOUL_API_KEY`를 사용합니다. 샘플키로 각 5행을 시험 적재하려면:

```powershell
python manage.py sync_open_data --dataset living --sample --limit 5
python manage.py sync_open_data --dataset store --sample --limit 5
python manage.py sync_open_data --dataset sales --sample --limit 5
```

발급키로 수집하는 예시입니다. 상권 데이터는 양이 많으므로 분기별로 나누어 실행할 수 있습니다.

```powershell
$env:SEOUL_API_KEY="발급받은_인증키"
python manage.py sync_open_data --dataset living --limit 1000
python manage.py sync_open_data --dataset store --quarter 20252 --limit 1000
python manage.py sync_open_data --dataset sales --quarter 20252 --limit 1000
```

상권영역 공식 ZIP은 압축 안의 SHP를 EPSG:5181 좌표 그대로 가져옵니다.

```powershell
python manage.py import_seoul_area path\to\official_trade_area.zip
```

250m 격자 파일을 내려받아 압축 해제한 뒤 `.shp`, `.shx`, `.dbf`, `.prj`를 같은 디렉터리에 두고 실행합니다. `.prj`를 읽어 EPSG:5179인지 확인한 후 격자 ID, 행정동 코드, geometry와 속성을 저장합니다.

```powershell
python manage.py import_seoul_grid path\to\grid.shp
```

EPSG:5181 상권영역과 EPSG:5179 인구격자는 서로 다른 좌표계이므로 공간 연산 전에 GIS 도구로 공통 좌표계로 변환해야 합니다. API 원본 필드 전체는 `SeoulOpenRecord.payload`에 보존됩니다. 데이터 메뉴와 차트는 로그인 후 이용할 수 있습니다. 현재 데이터베이스에는 공식 API 샘플로 생활인구·점포·매출 각 5건이 적재되어 있습니다. 파일 다운로드가 필요한 영역/격자는 원본 파일이 로컬에 아직 없으므로 위 명령으로 넣을 수 있습니다.

## 통합 분석 대시보드

로그인 후 `/analysis/`에서 생활인구·점포·추정매출·상권영역의 기간, 자치구, 시간대, 업종별 집계와 차트를 확인할 수 있습니다. 대시보드는 `static/data/seoul_analytics.json`만 읽으며, 공개 원본 ZIP 전체를 웹 서비스나 데이터베이스에 올리지 않습니다.

원본 ZIP은 로컬에 보관하고 프로젝트 가상환경에서 집계 파일을 생성합니다. 전체 파일을 압축 해제하지 않고 순차 처리합니다. 빠른 검증에는 `--max-living-files 1`을 사용하고, 전체 집계 시에는 해당 옵션을 생략합니다.

```powershell
python manage.py build_seoul_analytics "C:\Users\user\Downloads\jectpro" --max-living-files 1
python manage.py build_seoul_analytics "C:\Users\user\Downloads\jectpro"
```

생성된 JSON은 공개 공공데이터의 집계값입니다. 생활인구 합계가 `*`로 비식별된 행은 생활인구 합계에서 제외하며, 대시보드에 제외 수를 표시합니다. 원본 ZIP이나 개인용 데이터 백업은 GitHub에 추가하지 마세요. JSON을 갱신한 뒤 코드와 함께 GitHub에 push하면 Render가 정적 분석 데이터를 배포합니다.

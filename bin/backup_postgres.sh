#!/bin/bash
# ===================================================================
# PostgreSQL 백업 스크립트 (시놀로지 환경)
# ===================================================================
#
# 📝 설명:
# - Docker 컨테이너에서 실행 중인 PostgreSQL 데이터베이스 백업
# - database.yml 설정 파일에서 인증 정보 자동 로드
# - 로그 파일 분리 (일반 로그 + 에러 로그)
# - 자동 로그 로테이션 (크기 기반)
#
# 🔧 사용법:
#   ./backup_postgres.sh <DB명> [백업경로] [보관일수]
#
# 📌 예시:
#   ./backup_postgres.sh tripgether
#   ./backup_postgres.sh tripgether /volume1/projects/tripgether/backup/postgres-tripgether
#   ./backup_postgres.sh tripgether /volume1/projects/backup/postgres/tripgether 60
#
# ===================================================================

# ===================================================================
# 설정 및 상수
# ===================================================================

# 설정 파일 경로
CONFIG_FILE="/volume1/projects/suh-project/config/database.yml"

# 백업 기본 경로
DEFAULT_BACKUP_BASE="/volume1/projects/backup/postgres"

# 백업 보관 일수 (기본값)
DEFAULT_RETENTION_DAYS=30

# 디스크 최소 여유 공간 (GB)
MIN_DISK_SPACE_GB=10

# 로그 로테이션 설정
LOG_MAX_SIZE=$((10 * 1024 * 1024))       # 일반 로그: 10MB
ERROR_LOG_MAX_SIZE=$((5 * 1024 * 1024))  # 에러 로그: 5MB
LOG_MAX_BACKUPS=5                        # 일반 로그 보관 개수
ERROR_LOG_MAX_BACKUPS=10                 # 에러 로그 보관 개수 (더 오래 보관)

# 색상 코드 (터미널 출력용)
COLOR_RESET="\033[0m"
COLOR_INFO="\033[0;36m"
COLOR_SUCCESS="\033[0;32m"
COLOR_WARN="\033[0;33m"
COLOR_ERROR="\033[0;31m"

# ===================================================================
# YAML 파싱 함수
# ===================================================================

# database.yml에서 postgres 설정 값 읽기
get_postgres_config() {
    local key=$1
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo ""
        return 1
    fi
    
    # postgres 섹션에서 키 값 추출
    grep -A 10 "^postgres:" "$CONFIG_FILE" | \
    grep "^\s*${key}:" | \
    sed 's/.*"\(.*\)"/\1/' | \
    tr -d ' ' | \
    head -1
}

# ===================================================================
# 로그 함수
# ===================================================================

# 일반 로그 (INFO, SUCCESS, WARN)
log() {
    local message="$1"
    local level="${2:-INFO}"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_message="[${timestamp}] [${level}] ${message}"
    
    # 터미널 출력 (색상 포함)
    case "$level" in
        "SUCCESS")
            echo -e "${COLOR_SUCCESS}${log_message}${COLOR_RESET}"
            ;;
        "WARN")
            echo -e "${COLOR_WARN}${log_message}${COLOR_RESET}"
            ;;
        "ERROR")
            echo -e "${COLOR_ERROR}${log_message}${COLOR_RESET}"
            ;;
        *)
            echo -e "${COLOR_INFO}${log_message}${COLOR_RESET}"
            ;;
    esac
    
    # 로그 파일에 기록 (색상 코드 제외)
    if [ -n "$GENERAL_LOG" ]; then
        echo "[${timestamp}] [${level}] ${message}" >> "$GENERAL_LOG"
    fi
}

# 에러 로그 (일반 로그 + 에러 로그 파일 둘 다 기록)
log_error() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_message="[${timestamp}] [ERROR] ${message}"
    
    # 터미널 출력
    echo -e "${COLOR_ERROR}${log_message}${COLOR_RESET}"
    
    # 일반 로그 파일에 기록
    if [ -n "$GENERAL_LOG" ]; then
        echo "[${timestamp}] [ERROR] ${message}" >> "$GENERAL_LOG"
    fi
    
    # 에러 로그 파일에 기록
    if [ -n "$ERROR_LOG" ]; then
        echo "[${timestamp}] [ERROR] ${message}" >> "$ERROR_LOG"
    fi
}

# 성공 로그
log_success() {
    log "$1" "SUCCESS"
}

# 경고 로그
log_warn() {
    log "$1" "WARN"
}

# ===================================================================
# 로그 로테이션 함수
# ===================================================================

rotate_log() {
    local log_file=$1
    local max_size=$2
    local max_backups=$3
    
    # 파일 존재 확인
    if [ ! -f "$log_file" ]; then
        return 0
    fi
    
    # 파일 크기 확인 (시놀로지 호환)
    local size=$(stat -c%s "$log_file" 2>/dev/null || stat -f%z "$log_file" 2>/dev/null)
    
    # 크기 초과 시 로테이션
    if [ "$size" -gt "$max_size" ]; then
        # 기존 백업 로테이션 (역순으로)
        for i in $(seq $((max_backups - 1)) -1 1); do
            if [ -f "${log_file}.${i}.gz" ]; then
                mv "${log_file}.${i}.gz" "${log_file}.$((i + 1)).gz"
            fi
        done
        
        # 현재 로그 압축
        gzip -c "$log_file" > "${log_file}.1.gz"
        
        # 새 로그 시작
        > "$log_file"
        
        # 오래된 백업 삭제
        if [ -f "${log_file}.$((max_backups + 1)).gz" ]; then
            rm "${log_file}.$((max_backups + 1)).gz"
        fi
    fi
}

# ===================================================================
# 백업 검증 함수
# ===================================================================

validate_backup() {
    local backup_file=$1
    
    # 1. 파일 존재 확인
    if [ ! -f "$backup_file" ]; then
        log_error "백업 파일이 생성되지 않았습니다: $backup_file"
        return 1
    fi
    
    # 2. 파일 크기 확인 (최소 1KB)
    local file_size=$(stat -c%s "$backup_file" 2>/dev/null || stat -f%z "$backup_file" 2>/dev/null)
    if [ "$file_size" -lt 1024 ]; then
        log_error "백업 파일이 너무 작습니다: ${file_size} bytes"
        rm -f "$backup_file"
        return 1
    fi
    
    # 3. gzip 파일 무결성 확인
    if ! gzip -t "$backup_file" 2>/dev/null; then
        log_error "백업 파일이 손상되었습니다: $backup_file"
        rm -f "$backup_file"
        return 1
    fi
    
    log_success "백업 파일 검증 완료"
    return 0
}

# ===================================================================
# 디스크 공간 확인 함수
# ===================================================================

check_disk_space() {
    local path=$1
    
    # 디스크 여유 공간 확인 (GB 단위)
    local available_kb=$(df "$path" | tail -1 | awk '{print $4}')
    local available_gb=$((available_kb / 1024 / 1024))
    
    log "디스크 여유 공간: ${available_gb}GB"
    
    if [ "$available_gb" -lt "$MIN_DISK_SPACE_GB" ]; then
        log_error "디스크 공간 부족: ${available_gb}GB 남음 (최소 ${MIN_DISK_SPACE_GB}GB 필요)"
        return 1
    fi
    
    return 0
}

# ===================================================================
# 사용법 출력
# ===================================================================

usage() {
    echo "사용법: $0 <DB명> [백업경로] [보관일수]"
    echo ""
    echo "인수:"
    echo "  DB명        (필수) 백업할 데이터베이스 이름"
    echo "  백업경로    (선택) 백업 저장 경로 (기본값: /volume1/projects/backup/postgres/\${DB명})"
    echo "  보관일수    (선택) 백업 보관 일수 (기본값: 30일)"
    echo ""
    echo "예시:"
    echo "  $0 tripgether"
    echo "  $0 tripgether /volume1/projects/tripgether/backup/postgres-tripgether"
    echo "  $0 tripgether /volume1/projects/backup/postgres/tripgether 60"
    echo ""
    exit 1
}

# ===================================================================
# 메인 로직
# ===================================================================

main() {
    # ---------------------------------------------------------------
    # 1. 인수 파싱 및 검증
    # ---------------------------------------------------------------
    
    if [ -z "$1" ]; then
        echo "❌ 에러: DB명을 입력해주세요."
        echo ""
        usage
    fi
    
    DB_NAME="$1"
    BACKUP_DIR="${2:-${DEFAULT_BACKUP_BASE}/${DB_NAME}}"
    RETENTION_DAYS="${3:-${DEFAULT_RETENTION_DAYS}}"
    
    # ---------------------------------------------------------------
    # 2. 디렉토리 생성
    # ---------------------------------------------------------------
    
    # 백업 디렉토리 생성
    if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
        echo "❌ 에러: 백업 디렉토리 생성 실패: $BACKUP_DIR"
        echo "   권한을 확인해주세요."
        exit 1
    fi
    
    # 로그 디렉토리 생성
    LOG_DIR="${BACKUP_DIR}/log"
    if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
        echo "❌ 에러: 로그 디렉토리 생성 실패: $LOG_DIR"
        exit 1
    fi
    
    # ---------------------------------------------------------------
    # 3. 로그 파일 초기화
    # ---------------------------------------------------------------
    
    GENERAL_LOG="${LOG_DIR}/${DB_NAME}.log"
    ERROR_LOG="${LOG_DIR}/${DB_NAME}_error.log"
    
    # 로그 파일이 없으면 생성
    touch "$GENERAL_LOG" 2>/dev/null
    touch "$ERROR_LOG" 2>/dev/null
    
    # ---------------------------------------------------------------
    # 4. 로그 로테이션 (백업 시작 전)
    # ---------------------------------------------------------------
    
    rotate_log "$GENERAL_LOG" "$LOG_MAX_SIZE" "$LOG_MAX_BACKUPS"
    rotate_log "$ERROR_LOG" "$ERROR_LOG_MAX_SIZE" "$ERROR_LOG_MAX_BACKUPS"
    
    # ---------------------------------------------------------------
    # 5. 백업 시작 로그
    # ---------------------------------------------------------------
    
    log "=========================================="
    log "PostgreSQL 백업 시작: ${DB_NAME}"
    log "=========================================="
    log "백업 경로: ${BACKUP_DIR}"
    log "보관 일수: ${RETENTION_DAYS}일"
    log "로그 경로: ${LOG_DIR}"
    
    # ---------------------------------------------------------------
    # 6. 설정 파일 파싱
    # ---------------------------------------------------------------
    
    log "설정 파일 로드 중: ${CONFIG_FILE}"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        log_error "설정 파일을 찾을 수 없습니다: $CONFIG_FILE"
        exit 1
    fi
    
    DB_USER=$(get_postgres_config "username")
    DB_PASS=$(get_postgres_config "password")
    CONTAINER=$(get_postgres_config "container_name")
    
    if [ -z "$DB_USER" ] || [ -z "$DB_PASS" ] || [ -z "$CONTAINER" ]; then
        log_error "설정 파일 파싱 실패: username, password, container_name을 확인해주세요"
        exit 1
    fi
    
    log_success "설정 파일 로드 완료"
    log "컨테이너: ${CONTAINER}"
    log "사용자: ${DB_USER}"
    
    # ---------------------------------------------------------------
    # 7. Docker 컨테이너 상태 확인
    # ---------------------------------------------------------------
    
    log "Docker 컨테이너 상태 확인 중..."
    
    if ! docker ps --format "{{.Names}}" | grep -q "^${CONTAINER}$"; then
        log_error "Docker 컨테이너 '${CONTAINER}'가 실행 중이 아닙니다"
        log_error "다음 명령어로 확인하세요: docker ps"
        exit 1
    fi
    
    log_success "Docker 컨테이너 '${CONTAINER}' 실행 확인"
    
    # ---------------------------------------------------------------
    # 8. 디스크 공간 확인
    # ---------------------------------------------------------------
    
    if ! check_disk_space "$BACKUP_DIR"; then
        exit 1
    fi
    
    # ---------------------------------------------------------------
    # 9. 백업 실행
    # ---------------------------------------------------------------
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"
    
    log "백업 진행 중..."
    log "파일: ${BACKUP_FILE}"
    
    # 시작 시간 기록
    START_TIME=$(date +%s)
    
    # pg_dump 실행 (비밀번호는 환경 변수로 전달)
    export PGPASSWORD="$DB_PASS"
    
    if docker exec -t "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" 2>/dev/null | gzip > "$BACKUP_FILE"; then
        # 종료 시간 기록
        END_TIME=$(date +%s)
        ELAPSED=$((END_TIME - START_TIME))
        
        # 백업 파일 크기
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        
        log_success "백업 성공!"
        log "   파일: ${BACKUP_FILE}"
        log "   크기: ${BACKUP_SIZE}"
        log "   소요 시간: ${ELAPSED}초"
    else
        unset PGPASSWORD
        log_error "백업 실패: pg_dump 명령어 실패"
        log_error "데이터베이스 '${DB_NAME}'이 존재하는지 확인해주세요"
        exit 1
    fi
    
    unset PGPASSWORD
    
    # ---------------------------------------------------------------
    # 10. 백업 검증
    # ---------------------------------------------------------------
    
    log "백업 파일 검증 중..."
    
    if ! validate_backup "$BACKUP_FILE"; then
        exit 1
    fi
    
    # ---------------------------------------------------------------
    # 11. 오래된 백업 삭제
    # ---------------------------------------------------------------
    
    log "오래된 백업 삭제 중 (${RETENTION_DAYS}일 이상)..."
    
    DELETED_COUNT=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +$RETENTION_DAYS -type f 2>/dev/null | wc -l)
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +$RETENTION_DAYS -type f -delete 2>/dev/null
    
    if [ "$DELETED_COUNT" -gt 0 ]; then
        log "삭제된 백업 파일: ${DELETED_COUNT}개"
    else
        log "삭제할 오래된 백업 없음"
    fi
    
    # ---------------------------------------------------------------
    # 12. 백업 통계
    # ---------------------------------------------------------------
    
    TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f 2>/dev/null | wc -l)
    TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
    
    log "=========================================="
    log "백업 통계"
    log "=========================================="
    log "총 백업 파일: ${TOTAL_BACKUPS}개"
    log "총 사용 용량: ${TOTAL_SIZE}"
    log "최신 백업: ${BACKUP_FILE}"
    
    # ---------------------------------------------------------------
    # 13. 백업 완료
    # ---------------------------------------------------------------
    
    log "=========================================="
    log_success "백업 완료!"
    log "=========================================="
    
    exit 0
}

# 메인 함수 실행
main "$@"


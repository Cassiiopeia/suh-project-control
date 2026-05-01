#!/bin/bash
# ===================================================================
# MongoDB 백업 스크립트 (시놀로지 환경)
# ===================================================================
#
# 📝 설명:
# - Docker 컨테이너에서 실행 중인 MongoDB 데이터베이스 백업
# - database.yml 설정 파일에서 인증 정보 자동 로드
# - sudo 권한으로 Docker 명령어 실행
# - mongodump --archive --gzip 형식 사용
# - 로그 파일 분리 (일반 로그 + 에러 로그)
# - 자동 로그 로테이션 (크기 기반)
#
# 🔧 사용법:
#   ./backup_mongo.sh <DB명> [백업경로] [보관일수]
#
# 📌 예시:
#   ./backup_mongo.sh romrom
#   ./backup_mongo.sh romrom /volume1/projects/backup/mongo/romrom 60
#
# ⚠️ 주의사항:
#   - Docker 명령어 실행을 위해 sudo 권한이 필요합니다
#   - database.yml의 password가 sudo 비밀번호로 사용됩니다
#   - 시놀로지 작업 스케줄러에서는 'kimchi' 사용자로 실행하세요
#
# ===================================================================

# ===================================================================
# 설정 및 상수
# ===================================================================

# 설정 파일 경로
CONFIG_FILE="/volume1/projects/suh-project/config/database.yml"

# 백업 기본 경로
DEFAULT_BACKUP_BASE="/volume1/projects/backup/mongo"

# 백업 보관 일수 (기본값)
DEFAULT_RETENTION_DAYS=30

# 디스크 최소 여유 공간 (GB)
MIN_DISK_SPACE_GB=10

# 로그 로테이션 설정
LOG_MAX_SIZE=$((10 * 1024 * 1024))       # 일반 로그: 10MB
ERROR_LOG_MAX_SIZE=$((5 * 1024 * 1024))  # 에러 로그: 5MB
LOG_MAX_BACKUPS=5                        # 일반 로그 보관 개수
ERROR_LOG_MAX_BACKUPS=10                 # 에러 로그 보관 개수

# 색상 코드 (터미널 출력용)
COLOR_RESET="\033[0m"
COLOR_INFO="\033[0;36m"
COLOR_SUCCESS="\033[0;32m"
COLOR_WARN="\033[0;33m"
COLOR_ERROR="\033[0;31m"

# ===================================================================
# YAML 파싱 함수
# ===================================================================

# database.yml에서 mongo 섹션의 설정 값 읽기
get_mongo_config() {
    local mongoConfigKey=$1

    if [ ! -f "$CONFIG_FILE" ]; then
        echo ""
        return 1
    fi

    # mongo 섹션에서 키 값 추출 (sed로 mongo: 부터 다음 섹션 직전까지)
    sed -n '/^mongo:/,/^[^ ]/p' "$CONFIG_FILE" | \
    grep "^\s*${mongoConfigKey}:" | \
    sed -E 's/.*"(.*)".*/\1/' | \
    head -1
}

# ===================================================================
# 로그 함수
# ===================================================================

log() {
    local logMessage="$1"
    local logLevel="${2:-INFO}"
    local logTimestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local formattedLog="[${logTimestamp}] [${logLevel}] ${logMessage}"

    case "$logLevel" in
        "SUCCESS")
            echo -e "${COLOR_SUCCESS}${formattedLog}${COLOR_RESET}"
            ;;
        "WARN")
            echo -e "${COLOR_WARN}${formattedLog}${COLOR_RESET}"
            ;;
        "ERROR")
            echo -e "${COLOR_ERROR}${formattedLog}${COLOR_RESET}"
            ;;
        *)
            echo -e "${COLOR_INFO}${formattedLog}${COLOR_RESET}"
            ;;
    esac

    if [ -n "$GENERAL_LOG" ]; then
        echo "[${logTimestamp}] [${logLevel}] ${logMessage}" >> "$GENERAL_LOG"
    fi
}

log_error() {
    local errorMessage="$1"
    local errorTimestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local formattedError="[${errorTimestamp}] [ERROR] ${errorMessage}"

    echo -e "${COLOR_ERROR}${formattedError}${COLOR_RESET}"

    if [ -n "$GENERAL_LOG" ]; then
        echo "[${errorTimestamp}] [ERROR] ${errorMessage}" >> "$GENERAL_LOG"
    fi

    if [ -n "$ERROR_LOG" ]; then
        echo "[${errorTimestamp}] [ERROR] ${errorMessage}" >> "$ERROR_LOG"
    fi
}

log_success() {
    log "$1" "SUCCESS"
}

log_warn() {
    log "$1" "WARN"
}

# ===================================================================
# 로그 로테이션 함수
# ===================================================================

rotate_log() {
    local rotateLogPath=$1
    local rotateMaxSize=$2
    local rotateMaxBackups=$3

    if [ ! -f "$rotateLogPath" ]; then
        return 0
    fi

    local currentLogSize=$(stat -c%s "$rotateLogPath" 2>/dev/null || stat -f%z "$rotateLogPath" 2>/dev/null)

    if [ "$currentLogSize" -gt "$rotateMaxSize" ]; then
        for backupIndex in $(seq $((rotateMaxBackups - 1)) -1 1); do
            if [ -f "${rotateLogPath}.${backupIndex}.gz" ]; then
                mv "${rotateLogPath}.${backupIndex}.gz" "${rotateLogPath}.$((backupIndex + 1)).gz"
            fi
        done

        gzip -c "$rotateLogPath" > "${rotateLogPath}.1.gz"
        > "$rotateLogPath"

        if [ -f "${rotateLogPath}.$((rotateMaxBackups + 1)).gz" ]; then
            rm "${rotateLogPath}.$((rotateMaxBackups + 1)).gz"
        fi
    fi
}

# ===================================================================
# 백업 검증 함수
# ===================================================================

validate_backup() {
    local backupArchivePath=$1

    # 1. 파일 존재 확인
    if [ ! -f "$backupArchivePath" ]; then
        log_error "백업 파일이 생성되지 않았습니다: $backupArchivePath"
        return 1
    fi

    # 2. 파일 크기 확인 (최소 1KB)
    local backupFileSize=$(stat -c%s "$backupArchivePath" 2>/dev/null || stat -f%z "$backupArchivePath" 2>/dev/null)
    if [ "$backupFileSize" -lt 100 ]; then
        log_error "백업 파일이 너무 작습니다: ${backupFileSize} bytes"
        rm -f "$backupArchivePath"
        return 1
    fi

    # 3. gzip 무결성 확인
    if ! gzip -t "$backupArchivePath" 2>/dev/null; then
        log_error "백업 파일이 손상되었습니다: $backupArchivePath"
        rm -f "$backupArchivePath"
        return 1
    fi

    log_success "백업 파일 검증 완료"
    return 0
}

# ===================================================================
# 디스크 공간 확인 함수
# ===================================================================

check_disk_space() {
    local diskCheckPath=$1

    local availableKb=$(df "$diskCheckPath" | tail -1 | awk '{print $4}')
    local availableGb=$((availableKb / 1024 / 1024))

    log "디스크 여유 공간: ${availableGb}GB"

    if [ "$availableGb" -lt "$MIN_DISK_SPACE_GB" ]; then
        log_error "디스크 공간 부족: ${availableGb}GB 남음 (최소 ${MIN_DISK_SPACE_GB}GB 필요)"
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
    echo "  DB명        (필수) 백업할 MongoDB 데이터베이스 이름"
    echo "  백업경로    (선택) 백업 저장 경로 (기본값: /volume1/projects/backup/mongo/\${DB명})"
    echo "  보관일수    (선택) 백업 보관 일수 (기본값: 30일)"
    echo ""
    echo "예시:"
    echo "  $0 romrom"
    echo "  $0 romrom /volume1/projects/backup/mongo/romrom 60"
    echo ""
    exit 1
}

# ===================================================================
# 메인 로직
# ===================================================================

main() {
    # 1. 인수 파싱
    if [ -z "$1" ]; then
        echo "❌ 에러: DB명을 입력해주세요."
        echo ""
        usage
    fi

    TARGET_DB_NAME="$1"
    BACKUP_DIR="${2:-${DEFAULT_BACKUP_BASE}/${TARGET_DB_NAME}}"
    RETENTION_DAYS="${3:-${DEFAULT_RETENTION_DAYS}}"

    # 2. 디렉토리 생성
    if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
        echo "❌ 에러: 백업 디렉토리 생성 실패: $BACKUP_DIR"
        exit 1
    fi

    LOG_DIR="${BACKUP_DIR}/log"
    if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
        echo "❌ 에러: 로그 디렉토리 생성 실패: $LOG_DIR"
        exit 1
    fi

    # 3. 로그 파일 초기화
    GENERAL_LOG="${LOG_DIR}/${TARGET_DB_NAME}.log"
    ERROR_LOG="${LOG_DIR}/${TARGET_DB_NAME}_error.log"

    touch "$GENERAL_LOG" 2>/dev/null
    touch "$ERROR_LOG" 2>/dev/null

    # 4. 로그 로테이션
    rotate_log "$GENERAL_LOG" "$LOG_MAX_SIZE" "$LOG_MAX_BACKUPS"
    rotate_log "$ERROR_LOG" "$ERROR_LOG_MAX_SIZE" "$ERROR_LOG_MAX_BACKUPS"

    # 5. 백업 시작 로그
    log "=========================================="
    log "MongoDB 백업 시작: ${TARGET_DB_NAME}"
    log "=========================================="
    log "백업 경로: ${BACKUP_DIR}"
    log "보관 일수: ${RETENTION_DAYS}일"
    log "로그 경로: ${LOG_DIR}"

    # 6. 설정 파일 파싱
    log "설정 파일 로드 중: ${CONFIG_FILE}"

    if [ ! -f "$CONFIG_FILE" ]; then
        log_error "설정 파일을 찾을 수 없습니다: $CONFIG_FILE"
        exit 1
    fi

    MONGO_USERNAME=$(get_mongo_config "username")
    MONGO_PASSWORD=$(get_mongo_config "password")
    MONGO_CONTAINER=$(get_mongo_config "container_name")
    MONGO_AUTH_DB=$(get_mongo_config "auth_db")

    # auth_db 기본값
    if [ -z "$MONGO_AUTH_DB" ]; then
        MONGO_AUTH_DB="admin"
    fi

    if [ -z "$MONGO_USERNAME" ] || [ -z "$MONGO_PASSWORD" ] || [ -z "$MONGO_CONTAINER" ]; then
        log_error "설정 파일 파싱 실패: username, password, container_name을 확인해주세요"
        exit 1
    fi

    log_success "설정 파일 로드 완료"
    log "컨테이너: ${MONGO_CONTAINER}"
    log "사용자: ${MONGO_USERNAME}"
    log "인증 DB: ${MONGO_AUTH_DB}"

    # 7. Docker 컨테이너 상태 확인
    log "Docker 컨테이너 상태 확인 중..."

    if ! echo "$MONGO_PASSWORD" | sudo -S /var/packages/ContainerManager/target/usr/bin/docker ps --format "{{.Names}}" 2>/dev/null | grep -q "^${MONGO_CONTAINER}\$"; then
        log_error "Docker 컨테이너 '${MONGO_CONTAINER}'가 실행 중이 아닙니다"
        exit 1
    fi

    log_success "Docker 컨테이너 '${MONGO_CONTAINER}' 실행 확인"

    # 8. 디스크 공간 확인
    if ! check_disk_space "$BACKUP_DIR"; then
        exit 1
    fi

    # 9. 백업 실행
    BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_ARCHIVE_FILE="${BACKUP_DIR}/${TARGET_DB_NAME}_${BACKUP_TIMESTAMP}.archive.gz"

    log "백업 진행 중..."
    log "파일: ${BACKUP_ARCHIVE_FILE}"

    BACKUP_START_TIME=$(date +%s)

    # mongodump --archive --gzip 으로 단일 파일 백업
    # mongo:4.4 이미지의 mongodump 사용
    if echo "$MONGO_PASSWORD" | sudo -S /var/packages/ContainerManager/target/usr/bin/docker exec "$MONGO_CONTAINER" \
        mongodump \
        --username "$MONGO_USERNAME" \
        --password "$MONGO_PASSWORD" \
        --authenticationDatabase "$MONGO_AUTH_DB" \
        --db "$TARGET_DB_NAME" \
        --archive \
        --gzip 2>/dev/null > "$BACKUP_ARCHIVE_FILE"; then
        BACKUP_END_TIME=$(date +%s)
        ELAPSED_SECONDS=$((BACKUP_END_TIME - BACKUP_START_TIME))

        BACKUP_SIZE=$(du -h "$BACKUP_ARCHIVE_FILE" | cut -f1)

        log_success "백업 성공!"
        log "   파일: ${BACKUP_ARCHIVE_FILE}"
        log "   크기: ${BACKUP_SIZE}"
        log "   소요 시간: ${ELAPSED_SECONDS}초"
    else
        log_error "백업 실패: mongodump 명령어 실패"
        log_error "데이터베이스 '${TARGET_DB_NAME}'이 존재하는지 확인해주세요"
        rm -f "$BACKUP_ARCHIVE_FILE"
        exit 1
    fi

    # 10. 백업 검증
    log "백업 파일 검증 중..."

    if ! validate_backup "$BACKUP_ARCHIVE_FILE"; then
        exit 1
    fi

    # 11. 오래된 백업 삭제
    log "오래된 백업 삭제 중 (${RETENTION_DAYS}일 이상)..."

    DELETED_COUNT=$(find "$BACKUP_DIR" -name "${TARGET_DB_NAME}_*.archive.gz" -mtime +$RETENTION_DAYS -type f 2>/dev/null | wc -l)
    find "$BACKUP_DIR" -name "${TARGET_DB_NAME}_*.archive.gz" -mtime +$RETENTION_DAYS -type f -delete 2>/dev/null

    if [ "$DELETED_COUNT" -gt 0 ]; then
        log "삭제된 백업 파일: ${DELETED_COUNT}개"
    else
        log "삭제할 오래된 백업 없음"
    fi

    # 12. 백업 통계
    TOTAL_BACKUP_COUNT=$(find "$BACKUP_DIR" -name "${TARGET_DB_NAME}_*.archive.gz" -type f 2>/dev/null | wc -l)
    TOTAL_USED_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)

    log "=========================================="
    log "백업 통계"
    log "=========================================="
    log "총 백업 파일: ${TOTAL_BACKUP_COUNT}개"
    log "총 사용 용량: ${TOTAL_USED_SIZE}"
    log "최신 백업: ${BACKUP_ARCHIVE_FILE}"

    # 13. 백업 완료
    log "=========================================="
    log_success "백업 완료!"
    log "=========================================="

    exit 0
}

main "$@"

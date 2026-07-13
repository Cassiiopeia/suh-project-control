#!/bin/bash
# ===================================================================
# AI 서버 + SSH + Palworld 포트 포워딩 관리 스크립트 (시놀로지 환경)
# ===================================================================
#
# 📝 설명:
# - AI 서비스: localhost:11435 → 172.30.1.14:11435
# - SSH 서비스: localhost:2023 → 172.30.1.14:2023
# - Python 서버: localhost:11436 → 172.30.1.14:11436
# - Palworld 서버: UDP 8211 → 172.30.1.14:8211
# - 시놀로지 부팅 시 자동 실행되도록 스케줄러 등록
# - iptables 규칙 추가/제거/상태 확인 기능 제공
#
# 🔧 사용법:
#   sudo ./suh_ai_proxy_manager.sh setup      # NAT 규칙 추가
#   sudo ./suh_ai_proxy_manager.sh remove     # NAT 규칙 제거
#   sudo ./suh_ai_proxy_manager.sh status     # 규칙 상태 확인
#   sudo ./suh_ai_proxy_manager.sh install    # 부팅 시 자동 실행 등록
#
# ⚠️ 주의사항:
#   - root 권한이 필요합니다 (sudo 사용)
#   - 시놀로지 재부팅 시 규칙이 초기화될 수 있으므로 install 명령으로 등록하세요
#
# ===================================================================

# ===================================================================
# 설정 및 상수
# ===================================================================

# AI 서비스 포트
AI_LOCAL_PORT=11435
AI_TARGET_IP=172.30.1.14
AI_TARGET_PORT=11435

# SSH 포트 포워딩
SSH_LOCAL_PORT=2023
SSH_TARGET_IP=172.30.1.14
SSH_TARGET_PORT=2023

# Python 서버 포트 포워딩
PYTHON_LOCAL_PORT=11436
PYTHON_TARGET_IP=172.30.1.14
PYTHON_TARGET_PORT=11436

# Palworld 게임 서버 포트 포워딩
PALWORLD_LOCAL_PORT=8211
PALWORLD_TARGET_IP=172.30.1.14
PALWORLD_TARGET_PORT=8211
PALWORLD_PROTOCOL=udp

# 스크립트 경로
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
SCRIPT_PATH="${SCRIPT_DIR}/${SCRIPT_NAME}"

# rc.local 경로
RC_LOCAL="/etc/rc.local"

# ===================================================================
# 로깅 함수
# ===================================================================

log() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] ${message}"
}

log_success() { log "✅ $1"; }
log_error() { log "❌ $1" >&2; }
log_info() { log "ℹ️  $1"; }

# ===================================================================
# 권한 확인
# ===================================================================

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "이 스크립트는 root 권한이 필요합니다."
        log_error "사용법: sudo $0 $*"
        exit 1
    fi
}

# ===================================================================
# iptables 명령어 확인
# ===================================================================

check_iptables() {
    if ! command -v iptables &> /dev/null; then
        log_error "iptables 명령어를 찾을 수 없습니다."
        exit 1
    fi
}

# ===================================================================
# NAT 규칙 반복 적용 함수
# ===================================================================

apply_nat() {
    local LPORT=$1
    local TIP=$2
    local TPORT=$3
    local PROTOCOL=${4:-tcp}

    log_info "규칙 적용: ${PROTOCOL^^} ${LPORT} → ${TIP}:${TPORT}"

    if iptables -t nat -C PREROUTING -p ${PROTOCOL} --dport ${LPORT} -j DNAT --to-destination ${TIP}:${TPORT} 2>/dev/null; then
        log_info "규칙 이미 존재함"
        return
    fi

    iptables -t nat -A PREROUTING -p ${PROTOCOL} --dport ${LPORT} -j DNAT --to-destination ${TIP}:${TPORT}
    iptables -t nat -A POSTROUTING -p ${PROTOCOL} -d ${TIP} --dport ${TPORT} -j MASQUERADE
    log_success "NAT 규칙 추가됨"
}

remove_nat() {
    local LPORT=$1
    local TIP=$2
    local TPORT=$3
    local PROTOCOL=${4:-tcp}

    log_info "규칙 제거: ${PROTOCOL^^} ${LPORT} → ${TIP}:${TPORT}"

    if iptables -t nat -C PREROUTING -p ${PROTOCOL} --dport ${LPORT} -j DNAT --to-destination ${TIP}:${TPORT} 2>/dev/null; then
        iptables -t nat -D PREROUTING -p ${PROTOCOL} --dport ${LPORT} -j DNAT --to-destination ${TIP}:${TPORT}
        iptables -t nat -D POSTROUTING -p ${PROTOCOL} -d ${TIP} --dport ${TPORT} -j MASQUERADE
        log_success "규칙 제거됨"
    else
        log_info "제거할 규칙 없음"
    fi
}

check_single_rule() {
    local NAME=$1
    local LPORT=$2
    local TIP=$3
    local TPORT=$4
    local PROTOCOL=${5:-tcp}

    echo "----- $NAME 규칙 상태 -----"

    if iptables -t nat -C PREROUTING -p ${PROTOCOL} --dport ${LPORT} -j DNAT --to-destination ${TIP}:${TPORT} 2>/dev/null; then
        log_success "활성화됨 (${PROTOCOL^^} ${LPORT} → ${TIP}:${TPORT})"
    else
        log_error "비활성화됨"
    fi

    echo ""
}

# ===================================================================
# 명령 구현
# ===================================================================

setup_nat_rule() {
    log_info "==== NAT 규칙 적용 ===="
    apply_nat $AI_LOCAL_PORT $AI_TARGET_IP $AI_TARGET_PORT
    apply_nat $SSH_LOCAL_PORT $SSH_TARGET_IP $SSH_TARGET_PORT
    apply_nat $PYTHON_LOCAL_PORT $PYTHON_TARGET_IP $PYTHON_TARGET_PORT
    apply_nat $PALWORLD_LOCAL_PORT $PALWORLD_TARGET_IP $PALWORLD_TARGET_PORT $PALWORLD_PROTOCOL
}

remove_nat_rule() {
    log_info "==== NAT 규칙 제거 ===="
    remove_nat $AI_LOCAL_PORT $AI_TARGET_IP $AI_TARGET_PORT
    remove_nat $SSH_LOCAL_PORT $SSH_TARGET_IP $SSH_TARGET_PORT
    remove_nat $PYTHON_LOCAL_PORT $PYTHON_TARGET_IP $PYTHON_TARGET_PORT
    remove_nat $PALWORLD_LOCAL_PORT $PALWORLD_TARGET_IP $PALWORLD_TARGET_PORT $PALWORLD_PROTOCOL
}

check_status() {
    log_info "==== NAT 규칙 상태 ===="

    check_single_rule "AI 서버" $AI_LOCAL_PORT $AI_TARGET_IP $AI_TARGET_PORT
    check_single_rule "SSH 서버" $SSH_LOCAL_PORT $SSH_TARGET_IP $SSH_TARGET_PORT
    check_single_rule "Python 서버" $PYTHON_LOCAL_PORT $PYTHON_TARGET_IP $PYTHON_TARGET_PORT
    check_single_rule "Palworld 게임 서버" $PALWORLD_LOCAL_PORT $PALWORLD_TARGET_IP $PALWORLD_TARGET_PORT $PALWORLD_PROTOCOL

    echo ""
    log_info "PREROUTING 전체 목록:"
    iptables -t nat -L PREROUTING -n --line-numbers

    echo ""

    # rc.local 등록 여부 확인
    if [ -f "$RC_LOCAL" ]; then
        if grep -q "$SCRIPT_PATH.*setup" "$RC_LOCAL" 2>/dev/null; then
            log_success "부팅 시 자동 실행이 등록되어 있습니다."
        else
            log_info "부팅 시 자동 실행이 등록되어 있지 않습니다."
            echo "등록하려면 다음 명령어를 실행하세요:"
            echo "  sudo $0 install"
        fi
    else
        log_info "rc.local 파일이 존재하지 않습니다."
    fi
}

# ===================================================================
# 스케줄러 등록 함수 (rc.local)
# ===================================================================

install_scheduler() {
    log_info "부팅 시 자동 실행 등록 중..."
    
    # rc.local 파일이 없으면 생성
    if [ ! -f "$RC_LOCAL" ]; then
        log_info "rc.local 파일이 없어 생성합니다."
        cat > "$RC_LOCAL" << 'EOF'
#!/bin/sh
# This file is executed at the end of each multiuser runlevel.
# Make sure that the script will "exit 0" on success or any other
# value on error.
EOF
        chmod +x "$RC_LOCAL"
    fi
    
    # 이미 등록되어 있는지 확인
    if grep -q "$SCRIPT_PATH.*setup" "$RC_LOCAL" 2>/dev/null; then
        log_info "이미 부팅 시 자동 실행이 등록되어 있습니다."
        return 0
    fi
    
    # rc.local에 스크립트 추가
    # exit 0 앞에 추가
    if grep -q "^exit 0" "$RC_LOCAL"; then
        # exit 0 앞에 추가
        sed -i "/^exit 0/i ${SCRIPT_PATH} setup" "$RC_LOCAL"
    else
        # 파일 끝에 추가
        echo "${SCRIPT_PATH} setup" >> "$RC_LOCAL"
        echo "exit 0" >> "$RC_LOCAL"
    fi
    
    if [ $? -eq 0 ]; then
        log_success "부팅 시 자동 실행이 등록되었습니다."
        log_info "rc.local 파일: $RC_LOCAL"
        echo ""
        echo "등록된 내용:"
        grep "$SCRIPT_PATH.*setup" "$RC_LOCAL" || echo "  (확인 실패)"
        return 0
    else
        log_error "부팅 시 자동 실행 등록에 실패했습니다."
        return 1
    fi
}

# ===================================================================
# 사용법 출력
# ===================================================================

usage() {
    echo "사용법: sudo $0 <명령어>"
    echo ""
    echo "명령어:"
    echo "  setup      NAT 규칙 추가"
    echo "             - AI 서비스: localhost:${AI_LOCAL_PORT} → ${AI_TARGET_IP}:${AI_TARGET_PORT}"
    echo "             - SSH 서비스: localhost:${SSH_LOCAL_PORT} → ${SSH_TARGET_IP}:${SSH_TARGET_PORT}"
    echo "             - Python 서버: localhost:${PYTHON_LOCAL_PORT} → ${PYTHON_TARGET_IP}:${PYTHON_TARGET_PORT}"
    echo "             - Palworld: UDP ${PALWORLD_LOCAL_PORT} → ${PALWORLD_TARGET_IP}:${PALWORLD_TARGET_PORT}"
    echo "  remove     NAT 규칙 제거"
    echo "  status     NAT 규칙 상태 확인"
    echo "  install    부팅 시 자동 실행 등록 (rc.local)"
    echo ""
    echo "예시:"
    echo "  sudo $0 setup"
    echo "  sudo $0 status"
    echo "  sudo $0 install"
    exit 1
}

# ===================================================================
# 메인 로직
# ===================================================================

main() {
    # 인자 확인
    if [ "$#" -lt 1 ]; then
        usage
    fi
    
    ACTION="$1"
    
    # root 권한 확인 (install 제외한 모든 명령어)
    if [ "$ACTION" != "status" ]; then
        check_root "$@"
    fi
    
    # iptables 확인 (setup, remove, status 명령어)
    if [ "$ACTION" == "setup" ] || [ "$ACTION" == "remove" ] || [ "$ACTION" == "status" ]; then
        check_iptables
    fi
    
    # 액션 실행
    case "$ACTION" in
        setup)
            setup_nat_rule
            ;;
        remove)
            remove_nat_rule
            ;;
        status)
            check_status
            ;;
        install)
            install_scheduler
            ;;
        *)
            log_error "알 수 없는 명령어: $ACTION"
            echo ""
            usage
            ;;
    esac
    
    exit $?
}

# 메인 함수 실행
main "$@"


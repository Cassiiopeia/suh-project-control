#!/bin/bash
# docker_manager.sh
# 스크립트 사용법:
#   sudo ./docker_manager.sh start <container_name>
#   sudo ./docker_manager.sh stop <container_name>
#   sudo ./docker_manager.sh restart <container_name>
#   sudo ./docker_manager.sh status <container_name>
#   sudo ./docker_manager.sh list

# 상수 변수 설정
SUCCESS="SUCCESS"
FAIL="FAIL"

# 공통 JSON 출력 함수
output_json() {
  # 인자: $1: result, $2: message, $3: data (JSON snippet)
  jq -n --arg result "$1" --arg message "$2" --argjson data "$3" '{result: $result, message: $message, data: $data}'
}

# usage 함수: 사용법 출력
usage() {
  echo "Usage:"
  echo "  sudo $0 start <container_name>   : Docker 컨테이너 시작"
  echo "  sudo $0 stop <container_name>    : Docker 컨테이너 중지"
  echo "  sudo $0 restart <container_name> : Docker 컨테이너 재시작"
  echo "  sudo $0 status <container_name>  : Docker 컨테이너 상태 확인"
  echo "  sudo $0 list                     : 실행 중인 Docker 컨테이너 목록 조회"
  exit 1
}

# 인자 개수 체크 및 ACTION 파싱
if [ "$#" -lt 1 ]; then
  usage
fi

ACTION="$1"
CONTAINER_NAME=""
if [[ "$ACTION" == "start" || "$ACTION" == "stop" || "$ACTION" == "restart" || "$ACTION" == "status" ]]; then
  if [ "$#" -ne 2 ]; then
    usage
  fi
  CONTAINER_NAME="$2"
elif [ "$ACTION" == "list" ]; then
  if [ "$#" -ne 1 ]; then
    usage
  fi
else
  usage
fi

DATA=""

case "$ACTION" in
  start)
    # 컨테이너가 이미 실행 중인지 확인
    if [ "$(docker ps -q -f name=^${CONTAINER_NAME}$)" ]; then
      RESULT="$FAIL"
      MESSAGE="컨테이너 '$CONTAINER_NAME'가 이미 실행 중입니다."
      DATA=$(jq -n --arg name "$CONTAINER_NAME" '{container: $name}')
    else
      # 컨테이너 시작 (존재하지 않으면 오류 처리)
      OUTPUT=$(docker start "$CONTAINER_NAME" 2>&1)
      RET_CODE=$?
      if [ $RET_CODE -ne 0 ]; then
        RESULT="$FAIL"
        MESSAGE="컨테이너 '$CONTAINER_NAME' 시작에 실패하였습니다."
        DATA=$(jq -n --arg error "$OUTPUT" '{error: $error}')
      else
        RESULT="$SUCCESS"
        MESSAGE="컨테이너 '$CONTAINER_NAME'가 시작되었습니다."
        DATA=$(jq -n --arg name "$CONTAINER_NAME" '{started: $name}')
      fi
    fi
    ;;
  stop)
    # 컨테이너가 실행 중인지 확인
    if [ -z "$(docker ps -q -f name=^${CONTAINER_NAME}$)" ]; then
      RESULT="$FAIL"
      MESSAGE="컨테이너 '$CONTAINER_NAME'가 실행 중이 아닙니다."
      DATA=$(jq -n --arg name "$CONTAINER_NAME" '{container: $name}')
    else
      OUTPUT=$(docker stop "$CONTAINER_NAME" 2>&1)
      RET_CODE=$?
      if [ $RET_CODE -ne 0 ]; then
        RESULT="$FAIL"
        MESSAGE="컨테이너 '$CONTAINER_NAME' 중지에 실패하였습니다."
        DATA=$(jq -n --arg error "$OUTPUT" '{error: $error}')
      else
        RESULT="$SUCCESS"
        MESSAGE="컨테이너 '$CONTAINER_NAME'가 중지되었습니다."
        DATA=$(jq -n --arg name "$CONTAINER_NAME" '{stopped: $name}')
      fi
    fi
    ;;
  restart)
    # 컨테이너가 존재하는지 확인 (실행 중 여부와 상관없이 재시작 시도)
    if [ -z "$(docker ps -a -q -f name=^${CONTAINER_NAME}$)" ]; then
      RESULT="$FAIL"
      MESSAGE="컨테이너 '$CONTAINER_NAME'가 존재하지 않습니다."
      DATA=$(jq -n --arg name "$CONTAINER_NAME" '{container: $name}')
    else
      OUTPUT=$(docker restart "$CONTAINER_NAME" 2>&1)
      RET_CODE=$?
      if [ $RET_CODE -ne 0 ]; then
        RESULT="$FAIL"
        MESSAGE="컨테이너 '$CONTAINER_NAME' 재시작에 실패하였습니다."
        DATA=$(jq -n --arg error "$OUTPUT" '{error: $error}')
      else
        RESULT="$SUCCESS"
        MESSAGE="컨테이너 '$CONTAINER_NAME'가 재시작되었습니다."
        DATA=$(jq -n --arg name "$CONTAINER_NAME" '{restarted: $name}')
      fi
    fi
    ;;
  status)
    # 컨테이너 상태 확인
    STATUS=$(docker inspect --format '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="컨테이너 '$CONTAINER_NAME'가 존재하지 않습니다."
      DATA=$(jq -n --arg name "$CONTAINER_NAME" '{container: $name}')
    else
      RESULT="$SUCCESS"
      MESSAGE="컨테이너 '$CONTAINER_NAME'의 상태: $STATUS"
      DATA=$(jq -n --arg name "$CONTAINER_NAME" --arg status "$STATUS" '{container: $name, status: $status}')
    fi
    ;;
  list)
    # 실행 중인 모든 컨테이너 목록 조회
    OUTPUT=$(docker ps --format '{"ID": "{{.ID}}", "Name": "{{.Names}}", "Image": "{{.Image}}", "Status": "{{.Status}}"}' | jq -s '.')
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="컨테이너 목록 조회에 실패하였습니다."
      DATA=$(jq -n --arg error "docker ps 명령어 실행 중 오류 발생" '{error: $error}')
    else
      RESULT="$SUCCESS"
      MESSAGE="실행 중인 컨테이너 목록 조회에 성공하였습니다."
      DATA="$OUTPUT"
    fi
    ;;
esac

output_json "$RESULT" "$MESSAGE" "$DATA"
exit 0
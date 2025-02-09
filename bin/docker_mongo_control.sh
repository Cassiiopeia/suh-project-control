#!/bin/bash
# docker_mongo_control.sh
# 스크립트 사용법:
#   sudo ./docker_mongo_control.sh create <database_name>
#   sudo ./docker_mongo_control.sh drop <database_name>
#   sudo ./docker_mongo_control.sh list

# 상수 변수 설정
SUCCESS="SUCCESS"
FAIL="FAIL"

# config/database.yml 파일 경로
DATABASE_YML="$(dirname "$0")/../config/database.yml"

if [ ! -f "$DATABASE_YML" ]; then
  echo "Error: '$DATABASE_YML' 파일을 찾을 수 없습니다."
  exit 1
fi

# MongoDB 자격 증명을 database.yml에서 추출 (mongo 섹션 내의 username, password, auth_db)
MONGO_USERNAME=$(sed -n '/^mongo:/,/^[^ ]/p' "$DATABASE_YML" | grep "username:" | sed -E 's/.*username:[[:space:]]*"(.*)".*/\1/')
MONGO_PASSWORD=$(sed -n '/^mongo:/,/^[^ ]/p' "$DATABASE_YML" | grep "password:" | sed -E 's/.*password:[[:space:]]*"(.*)".*/\1/')
MONGO_AUTH_DB=$(sed -n '/^mongo:/,/^[^ ]/p' "$DATABASE_YML" | grep "auth_db:" | sed -E 's/.*auth_db:[[:space:]]*"(.*)".*/\1/')
# 기본 auth_db가 없으면 "admin"으로 설정
if [ -z "$MONGO_AUTH_DB" ]; then
  MONGO_AUTH_DB="admin"
fi

if [ -z "$MONGO_USERNAME" ] || [ -z "$MONGO_PASSWORD" ]; then
  echo "Error: database.yml에서 MongoDB 자격 증명을 추출하지 못했습니다."
  exit 1
fi

# usage 함수: 사용법 출력
usage() {
  echo "Usage:"
  echo "  sudo $0 create <database_name>   : 데이터베이스 생성 (초기 컬렉션 생성)"
  echo "  sudo $0 drop <database_name>     : 데이터베이스 삭제"
  echo "  sudo $0 list                     : 데이터베이스 목록 조회 (JSON 형식 반환)"
  exit 1
}

# 인자 개수 체크 및 ACTION 파싱
if [ "$#" -lt 1 ]; then
  usage
fi

ACTION="$1"
DB_NAME=""
if [[ "$ACTION" == "create" || "$ACTION" == "drop" ]]; then
  if [ "$#" -ne 2 ]; then
    usage
  fi
  DB_NAME="$2"
elif [ "$ACTION" == "list" ]; then
  if [ "$#" -ne 1 ]; then
    usage
  fi
else
  usage
fi

DETAIL_MSG=""

# 1. Docker 컨테이너 'mongodb' 실행 여부 확인
CONTAINER_ID=$(docker ps --filter "name=^mongodb\$" --format "{{.ID}}")
if [ -z "$CONTAINER_ID" ]; then
  RESULT="$FAIL"
  MESSAGE="Docker 컨테이너 'mongodb'가 실행 중이지 않습니다."
  DETAIL_MSG=$(jq -n --arg info "docker ps 명령어로 'mongodb' 컨테이너를 찾지 못했습니다." '{info: $info}')
  jq -n --arg result "$RESULT" --arg message "$MESSAGE" --argjson detail "$DETAIL_MSG" --arg action "$ACTION" \
    '{result: $result, message: $message, detail: $detail, action: $action}'
  exit 1
fi

case "$ACTION" in
  create)
    # MongoDB는 쓰기 동작 시 데이터베이스가 생성되므로,
    # 임의의 컬렉션("init_collection")을 생성하여 데이터베이스 생성을 유도합니다.
    MONGO_COMMANDS=$(cat <<EOF
use $DB_NAME;
db.createCollection("init_collection");
EOF
)
    OUTPUT=$(docker exec -i mongodb mongo -u "$MONGO_USERNAME" -p "$MONGO_PASSWORD" --authenticationDatabase "$MONGO_AUTH_DB" $DB_NAME --quiet <<EOF
$MONGO_COMMANDS
EOF
)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME' 생성에 실패하였습니다."
      DETAIL_MSG=$(jq -n --arg error "mongo 명령어 실행 중 오류 발생" --arg out "$OUTPUT" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 '$DB_NAME'가 생성되었습니다."
      DETAIL_MSG=$(jq -n --arg db "$DB_NAME" '{created: $db}')
    fi
    ;;
  drop)
    # 데이터베이스 삭제: mongo shell에서 db.dropDatabase() 명령어 실행
    MONGO_COMMANDS=$(cat <<EOF
use $DB_NAME;
db.dropDatabase();
EOF
)
    OUTPUT=$(docker exec -i mongodb mongo -u "$MONGO_USERNAME" -p "$MONGO_PASSWORD" --authenticationDatabase "$MONGO_AUTH_DB" $DB_NAME --quiet <<EOF
$MONGO_COMMANDS
EOF
)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME' 삭제에 실패하였습니다."
      DETAIL_MSG=$(jq -n --arg error "mongo 명령어 실행 중 오류 발생" --arg out "$OUTPUT" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 '$DB_NAME'가 삭제되었습니다."
      DETAIL_MSG=$(jq -n --arg db "$DB_NAME" '{dropped: $db}')
    fi
    ;;
  list)
    # 데이터베이스 목록 조회: db.adminCommand('listDatabases')를 사용하여 JSON 형식으로 출력
    OUTPUT=$(docker exec -i mongodb mongo -u "$MONGO_USERNAME" -p "$MONGO_PASSWORD" --authenticationDatabase "$MONGO_AUTH_DB" --quiet --eval "printjson(db.adminCommand('listDatabases'))")
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 목록 조회에 실패하였습니다."
      DETAIL_MSG=$(jq -n --arg error "mongo 명령어 실행 중 오류 발생" --arg out "$OUTPUT" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 목록 조회에 성공하였습니다."
      DETAIL_MSG=$(echo "$OUTPUT" | jq '.')
    fi
    ;;
esac

jq -n --arg result "$RESULT" --arg message "$MESSAGE" --argjson detail "$DETAIL_MSG" --arg action "$ACTION" \
  '{result: $result, message: $message, detail: $detail, action: $action}'
exit 0

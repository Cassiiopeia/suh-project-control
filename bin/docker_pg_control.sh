#!/bin/bash
# docker_pg_control.sh
# 스크립트 사용법:
#   sudo ./docker_pg_control.sh create <database_name>
#   sudo ./docker_pg_control.sh drop <database_name>
#   sudo ./docker_pg_control.sh list

# 상수 변수 설정
SUCCESS="SUCCESS"
FAIL="FAIL"

# 공통 JSON 출력 함수 (jq 이용)
output_json() {
  # 인자: $1: result, $2: message, $3: data (JSON snippet)
  jq -n --arg result "$1" --arg message "$2" --argjson data "$3" '{result: $result, message: $message, data: $data}'
}

# config/database.yml 파일 경로
DATABASE_YML="$(dirname "$0")/../config/database.yml"

if [ ! -f "$DATABASE_YML" ]; then
  echo "Error: '$DATABASE_YML' 파일을 찾을 수 없습니다."
  exit 1
fi

# PostgreSQL username을 database.yml에서 추출 (postgres 섹션 내의 username)
PG_USERNAME=$(sed -n '/^postgres:/,/^[^ ]/p' "$DATABASE_YML" | grep "username:" | sed -E 's/.*username:[[:space:]]*"(.*)".*/\1/')
if [ -z "$PG_USERNAME" ]; then
  echo "Error: database.yml에서 PostgreSQL username을 추출하지 못했습니다."
  exit 1
fi

# usage 함수: 사용법 출력
usage() {
  echo "Usage:"
  echo "  sudo $0 create <database_name>   : 데이터베이스 생성 및 확장 설치"
  echo "  sudo $0 drop <database_name>     : 데이터베이스 삭제"
  echo "  sudo $0 list                     : 데이터베이스 목록 조회 (JSON 배열 반환)"
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

DATA=""  # data에 넣을 객체 또는 리스트(JSON 문자열)

# 1. Docker 컨테이너 'postgres' 실행 여부 확인
CONTAINER_ID=$(docker ps --filter "name=^postgres\$" --format "{{.ID}}")
if [ -z "$CONTAINER_ID" ]; then
  RESULT="$FAIL"
  MESSAGE="Docker 컨테이너 'postgres'가 실행 중이지 않습니다."
  DATA=$(jq -n --arg info "docker ps 명령어로 'postgres' 컨테이너를 찾지 못했습니다." '{info: $info}')
  output_json "$RESULT" "$MESSAGE" "$DATA"
  exit 1
fi

# 2. 액션에 따른 처리
case "$ACTION" in
  create)
    # psql 명령어들을 here-doc으로 전달하여 DB 생성 및 확장 설치
    PSQL_COMMANDS=$(cat <<EOF
DROP DATABASE IF EXISTS "$DB_NAME";
CREATE DATABASE "$DB_NAME";
\\c "$DB_NAME"
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF
)
    OUTPUT=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres <<EOF
$PSQL_COMMANDS
EOF
)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME' 생성 및 확장 설치에 실패하였습니다."
      DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$OUTPUT" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 '$DB_NAME'가 생성되었으며, 확장(vector, uuid-ossp)이 설치되었습니다."
      DATA=$(jq -n --arg db "$DB_NAME" \
                    --argjson extensions '["vector","uuid-ossp"]' \
                    '{database: $db, extensions: $extensions}')
    fi
    ;;
  drop)
    # 데이터베이스 삭제
    PSQL_COMMANDS="DROP DATABASE IF EXISTS \"$DB_NAME\";"
    OUTPUT=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres <<EOF
$PSQL_COMMANDS
EOF
)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME' 삭제에 실패하였습니다."
      DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$OUTPUT" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 '$DB_NAME'가 삭제되었습니다."
      DATA=$(jq -n --arg db "$DB_NAME" '{dropped: $db}')
    fi
    ;;
  list)
    # 데이터베이스 목록 조회 (템플릿이 아닌 DB만 조회)
    # 쿼리 결과를 JSON 배열로 반환 (psql의 json_agg 사용)
    QUERY="SELECT COALESCE(json_agg(datname), '[]'::json) FROM (SELECT datname FROM pg_database WHERE datistemplate = false) sub;"
    DB_LIST_JSON=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres -t -A -c "$QUERY")
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 목록 조회에 실패하였습니다."
      DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$DB_LIST_JSON" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 목록 조회에 성공하였습니다."
      # DB_LIST_JSON은 이미 JSON 배열 문자열로 나옴 (예: [ "postgres", "kimchi", ... ])
      DATA=$(echo "$DB_LIST_JSON" | jq '.')
    fi
    ;;
esac

# 3. 최종 JSON 결과 출력 및 exit 0
output_json "$RESULT" "$MESSAGE" "$DATA"
exit 0

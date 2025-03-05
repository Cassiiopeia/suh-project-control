#!/bin/bash
# docker_pg_control.sh
# 스크립트 사용법:
#   sudo ./docker_pg_control.sh create <database_name>
#   sudo ./docker_pg_control.sh drop <database_name>
#   sudo ./docker_pg_control.sh list
#   sudo ./docker_pg_control.sh info <database_name>
#   sudo ./docker_pg_control.sh install-plugin <database_name> <plugin1> [plugin2 ...]
#   sudo ./docker_pg_control.sh remove-plugin <database_name> <plugin1> [plugin2 ...] [--cascade]

# 상수 변수 설정
SUCCESS="SUCCESS"
FAIL="FAIL"

# 공통 JSON 출력 함수 (jq 이용)
output_json() {
  jq -n --arg result "$1" --arg message "$2" --argjson data "$3" '{result: $result, message: $message, data: $data}'
}

# config/database.yml 파일 경로
DATABASE_YML="$(dirname "$0")/../config/database.yml"

if [ ! -f "$DATABASE_YML" ]; then
  echo "Error: '$DATABASE_YML' 파일을 찾을 수 없습니다."
  exit 1
fi

# PostgreSQL username을 database.yml에서 추출
PG_USERNAME=$(sed -n '/^postgres:/,/^[^ ]/p' "$DATABASE_YML" | grep "username:" | sed -E 's/.*username:[[:space:]]*"(.*)".*/\1/')
if [ -z "$PG_USERNAME" ]; then
  echo "Error: database.yml에서 PostgreSQL username을 추출하지 못했습니다."
  exit 1
fi

# usage 함수: 사용법 출력
usage() {
  echo "Usage:"
  echo "  sudo $0 create <database_name>               : 데이터베이스 생성"
  echo "  sudo $0 drop <database_name>                 : 데이터베이스 삭제"
  echo "  sudo $0 list                                 : 데이터베이스 목록 조회 (JSON 배열 반환)"
  echo "  sudo $0 info <database_name>                 : 데이터베이스 정보 조회"
  echo "  sudo $0 install-plugin <db> <plugin1> [...]  : 데이터베이스에 플러그인 설치"
  echo "  sudo $0 remove-plugin <db> <plugin1> [...] [--cascade] : 데이터베이스에서 플러그인 삭제"
  exit 1
}

# 인자 개수 체크 및 ACTION 파싱
if [ "$#" -lt 1 ]; then
  usage
fi

ACTION="$1"
DB_NAME=""
CASCADE=""
shift

case "$ACTION" in
  create|drop|info)
    if [ "$#" -ne 1 ]; then
      usage
    fi
    DB_NAME="$1"
    ;;
  list)
    if [ "$#" -ne 0 ]; then
      usage
    fi
    ;;
  install-plugin|remove-plugin)
    if [ "$#" -lt 2 ]; then
      usage
    fi
    DB_NAME="$1"
    shift
    # --cascade 옵션 처리
    PLUGINS=()
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--cascade" ]; then
        CASCADE="CASCADE"
      else
        PLUGINS+=("$1")
      fi
      shift
    done
    if [ ${#PLUGINS[@]} -eq 0 ]; then
      usage
    fi
    ;;
  *)
    usage
    ;;
esac

DATA=""

# Docker 컨테이너 'postgres' 실행 여부 확인
CONTAINER_ID=$(docker ps --filter "name=^postgres\$" --format "{{.ID}}")
if [ -z "$CONTAINER_ID" ]; then
  RESULT="$FAIL"
  MESSAGE="Docker 컨테이너 'postgres'가 실행 중이지 않습니다."
  DATA=$(jq -n --arg info "docker ps 명령어로 'postgres' 컨테이너를 찾지 못했습니다." '{info: $info}')
  output_json "$RESULT" "$MESSAGE" "$DATA"
  exit 1
fi

# 액션에 따른 처리
case "$ACTION" in
  create)
    PSQL_COMMANDS="CREATE DATABASE \"$DB_NAME\";"
    OUTPUT=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres <<EOF
$PSQL_COMMANDS
EOF
)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME' 생성에 실패하였습니다."
      DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$OUTPUT" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 '$DB_NAME'가 생성되었습니다."
      DATA=$(jq -n --arg db "$DB_NAME" '{created: $db}')
    fi
    ;;
  drop)
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
    QUERY="SELECT COALESCE(json_agg(datname), '[]'::json) FROM (SELECT datname FROM pg_database WHERE datistemplate = false) sub;"
    DB_LIST_JSON=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres -t -A -c "$QUERY" 2>&1)
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 목록 조회에 실패하였습니다."
      DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$DB_LIST_JSON" '{error: $error, output: $out}')
    else
      RESULT="$SUCCESS"
      MESSAGE="데이터베이스 목록 조회에 성공하였습니다."
      DATA=$(echo "$DB_LIST_JSON" | jq '.')
    fi
    ;;
  info)
    EXISTS=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME';" 2>/dev/null)
    if [ -z "$EXISTS" ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME'가 존재하지 않습니다."
      DATA=$(jq -n --arg db "$DB_NAME" '{database: $db}')
    else
      QUERY=$(cat <<EOF
SELECT json_build_object(
  'database', '$DB_NAME',
  'size_bytes', pg_database_size('$DB_NAME'),
  'table_count', (SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'),
  'owner', (SELECT rolname FROM pg_roles WHERE oid = (SELECT datdba FROM pg_database WHERE datname = '$DB_NAME')),
  'plugins', COALESCE((SELECT json_agg(extname) FROM pg_extension), '[]'::json)
);
EOF
)
      INFO_JSON=$(docker exec -i postgres psql -U "$PG_USERNAME" -d "$DB_NAME" -t -A -c "$QUERY" 2>&1)
      RET_CODE=$?
      if [ $RET_CODE -ne 0 ]; then
        RESULT="$FAIL"
        MESSAGE="데이터베이스 '$DB_NAME' 정보 조회에 실패하였습니다."
        DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$INFO_JSON" '{error: $error, output: $out}')
      else
        RESULT="$SUCCESS"
        MESSAGE="데이터베이스 '$DB_NAME' 정보 조회에 성공하였습니다."
        DATA=$(echo "$INFO_JSON" | jq '.')
      fi
    fi
    ;;
  install-plugin)
    EXISTS=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME';" 2>/dev/null)
    if [ -z "$EXISTS" ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME'가 존재하지 않습니다."
      DATA=$(jq -n --arg db "$DB_NAME" '{database: $db}')
    else
      PSQL_COMMANDS=""
      for PLUGIN in "${PLUGINS[@]}"; do
        PSQL_COMMANDS+="CREATE EXTENSION IF NOT EXISTS \"$PLUGIN\";"
      done
      OUTPUT=$(docker exec -i postgres psql -U "$PG_USERNAME" -d "$DB_NAME" <<EOF
$PSQL_COMMANDS
EOF
)
      RET_CODE=$?
      if [ $RET_CODE -ne 0 ] || echo "$OUTPUT" | grep -q "ERROR"; then
        RESULT="$FAIL"
        MESSAGE="데이터베이스 '$DB_NAME'에 플러그인 설치에 실패하였습니다."
        DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$OUTPUT" --argjson plugins "$(printf '%s\n' "${PLUGINS[@]}" | jq -R . | jq -s .)" '{error: $error, output: $out, attempted_plugins: $plugins}')
      else
        RESULT="$SUCCESS"
        MESSAGE="데이터베이스 '$DB_NAME'에 플러그인이 설치되었습니다."
        DATA=$(jq -n --arg db "$DB_NAME" --argjson plugins "$(printf '%s\n' "${PLUGINS[@]}" | jq -R . | jq -s .)" '{database: $db, installed_plugins: $plugins}')
      fi
    fi
    ;;
  remove-plugin)
    EXISTS=$(docker exec -i postgres psql -U "$PG_USERNAME" -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME';" 2>/dev/null)
    if [ -z "$EXISTS" ]; then
      RESULT="$FAIL"
      MESSAGE="데이터베이스 '$DB_NAME'가 존재하지 않습니다."
      DATA=$(jq -n --arg db "$DB_NAME" '{database: $db}')
    else
      PSQL_COMMANDS=""
      for PLUGIN in "${PLUGINS[@]}"; do
        PSQL_COMMANDS+="DROP EXTENSION IF EXISTS \"$PLUGIN\" $CASCADE;"
      done
      OUTPUT=$(docker exec -i postgres psql -U "$PG_USERNAME" -d "$DB_NAME" <<EOF
$PSQL_COMMANDS
EOF
)
      RET_CODE=$?
      if [ $RET_CODE -ne 0 ] || echo "$OUTPUT" | grep -q "ERROR"; then
        RESULT="$FAIL"
        MESSAGE="데이터베이스 '$DB_NAME'에서 플러그인 삭제에 실패하였습니다."
        DATA=$(jq -n --arg error "psql 명령어 실행 중 오류 발생" --arg out "$OUTPUT" --argjson plugins "$(printf '%s\n' "${PLUGINS[@]}" | jq -R . | jq -s .)" '{error: $error, output: $out, attempted_plugins: $plugins}')
      else
        RESULT="$SUCCESS"
        MESSAGE="데이터베이스 '$DB_NAME'에서 플러그인이 삭제되었습니다."
        DATA=$(jq -n --arg db "$DB_NAME" --argjson plugins "$(printf '%s\n' "${PLUGINS[@]}" | jq -R . | jq -s .)" '{database: $db, removed_plugins: $plugins}')
      fi
    fi
    ;;
esac

# 최종 JSON 결과 출력
output_json "$RESULT" "$MESSAGE" "$DATA"
exit 0
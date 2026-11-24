#!/usr/bin/env bash
# 원격 명령 1건 실행: SSH 접속 실패 시에만 재시도, 원격 명령 실패는 바로 종료 (#229)
# 사용: ssh_with_retry.sh "<원격 명령>"
# 필요 env 6개: SERVER_HOST, SERVER_USER, SSHPASS(비밀번호), SERVER_SSH_PORT,
#              SSH_RETRY_ATTEMPT_LIMIT, SSH_RETRY_DELAY_MILLISECONDS
set -u

remote_command="$1"

# ssh 자체 오류(접속 거부, handshake reset, 타임아웃) 종료 코드
readonly SSH_CONNECTION_FAILURE_EXIT_CODE=255
retry_delay_seconds=$((SSH_RETRY_DELAY_MILLISECONDS / 1000))

for attempt_number in $(seq 1 "$SSH_RETRY_ATTEMPT_LIMIT"); do
  # 러너는 매번 새 VM > 호스트 키 저장 없이 접속
  sshpass -e ssh \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR \
    -o ConnectTimeout=20 \
    -o ServerAliveInterval=30 \
    -p "$SERVER_SSH_PORT" \
    "$SERVER_USER@$SERVER_HOST" \
    "$remote_command"
  exit_code=$?

  # 접속 성공 (원격 명령 성공·실패 공통) > 그 결과로 종료
  if [ "$exit_code" -ne "$SSH_CONNECTION_FAILURE_EXIT_CODE" ]; then
    exit "$exit_code"
  fi

  echo "[ssh retry] connection failed : attempt ${attempt_number}/${SSH_RETRY_ATTEMPT_LIMIT}"
  if [ "$attempt_number" -lt "$SSH_RETRY_ATTEMPT_LIMIT" ]; then
    sleep "$retry_delay_seconds"
  fi
done

echo "[ssh retry] gave up : ${SSH_RETRY_ATTEMPT_LIMIT} attempts failed"
exit "$SSH_CONNECTION_FAILURE_EXIT_CODE"

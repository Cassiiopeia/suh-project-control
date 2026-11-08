/* 앱 확인할 일 표시 도우미: 수준·결과·사유·방식·규칙·채널 문구, 항목 값 요약, 토큰 이름 규칙 (현황·관리·대시보드 공통, DOM 없음) */
(function () {
  // 항목 수준 > 배지 문구와 색 (ok는 접힌 "정상 n개")
  const LEVEL_BADGES = {
    critical: { label: '긴급', cssClass: 'badge-error' },
    warning: { label: '주의', cssClass: 'badge-warning' },
    info: { label: '참고', cssClass: 'badge-info' },
    ok: { label: '정상', cssClass: 'badge-success' },
  };
  const UNKNOWN_LEVEL_BADGE = { label: '-', cssClass: 'badge-ghost' };
  // state 값 > 문구
  const STATE_LABELS = { ok: '정상', degraded: '저하', down: '중단', unknown: '알 수 없음' };
  // 수집·접수 결과 > 문구 (ok·not_modified만 성공)
  const RESULT_LABELS = {
    ok: '정상', not_modified: '변경 없음', unauthorized: '인증 실패', disabled: '앱에서 꺼짐',
    invalid: '형식 오류', timeout: '시간 초과', error: '오류', stale: '늦은 스냅샷', conflict: '동시 처리',
  };
  const SUCCESS_RESULTS = ['ok', 'not_modified'];
  // 실패 사유 코드 > 문구 (http_<코드>는 따로 처리, 모르는 코드는 원문)
  const ERROR_LABELS = {
    token_missing: '토큰 없음', url_env_missing: '주소 환경변수 없음', too_large: '64KB 초과', not_json: 'JSON 아님',
    timeout: '시간 초과', tls_error: 'TLS 오류', connection_error: '연결 실패', error: '알 수 없는 오류',
    unsupported_version: '지원하지 않는 버전', tick_budget: '수집 시간 상한 초과', too_many_items: '항목 100개 초과',
    duplicate_key: '중복 key', not_object: '객체 아님',
  };
  const HTTP_ERROR_PATTERN = /^http_(\d{3})$/;
  // 수집 방식: pull 관제소가 가져옴 / push 앱이 보냄 / both 둘 다
  const MODE_OPTIONS = [
    { value: 'pull', label: '가져오기 (pull)' }, { value: 'push', label: '앱이 보냄 (push)' }, { value: 'both', label: '둘 다' },
  ];
  // 덮어쓰기 선택지 (서버 LEVEL_POLICIES·ALERT_RULES·OVERRIDE_CHANNEL_KINDS와 같음, 빈 값 = 해제)
  const LEVEL_POLICY_OPTIONS = [
    { value: 'app', label: '앱 값' }, { value: 'info', label: '참고' }, { value: 'warning', label: '주의' },
    { value: 'critical', label: '긴급' }, { value: 'ok', label: '정상 (알림 없음)' },
  ];
  const ALERT_RULE_OPTIONS = [
    { value: 'new', label: '늘면 (new)' }, { value: 'threshold', label: '기준 넘으면' }, { value: 'state', label: '상태 바뀌면' },
    { value: 'level', label: '수준 오르면' }, { value: 'off', label: '알림 안 함' },
  ];
  const CHANNEL_OPTIONS = [
    { value: 'attention', label: '#확인할일' }, { value: 'status', label: '#상태' }, { value: 'error', label: '#에러' },
    { value: 'report', label: '#신고' },
  ];
  // 토큰 환경변수 이름 (app_attention_tokens.py 규칙과 같음: 대문자, '-' > '_', 수집 토큰 구분자 밑줄 2개)
  const PULL_TOKEN_ENV_PREFIX = 'CONTROL_PULL_TOKEN_';
  const EVENT_TOKEN_ENV_PREFIX = 'CONTROL_EVENT_TOKEN_';
  const PULL_TOKEN_SEPARATOR = '__';
  const TOKEN_HEADER_NAME = 'X-Control-Token';
  // 관리 API 오류 코드 > 안내 문구
  const ERROR_MESSAGES = {
    invalid: '입력값을 확인하세요', unknown_project: '등록되지 않은 프로젝트입니다', unknown_source: '없는 소스입니다',
    unknown_item: '없는 항목입니다', source_exists: '이미 있는 소스 id입니다', unavailable: '관제소를 사용할 수 없습니다',
  };

  function levelBadgeOf(level) {
    return LEVEL_BADGES[level] || UNKNOWN_LEVEL_BADGE;
  }

  function describeResult(result) {
    return RESULT_LABELS[result] || result || '기록 없음';
  }

  function isSuccessResult(result) {
    return SUCCESS_RESULTS.indexOf(result) >= 0;
  }

  function describeError(errorCode) {
    if (!errorCode) return '';
    const httpMatch = HTTP_ERROR_PATTERN.exec(errorCode);
    if (httpMatch) return 'HTTP ' + httpMatch[1];
    return ERROR_LABELS[errorCode] || errorCode;
  }

  function describeMode(mode) {
    const option = MODE_OPTIONS.find(function (candidate) { return candidate.value === mode; });
    return option ? option.label : mode;
  }

  function labelOf(options, value) {
    const option = options.find(function (candidate) { return candidate.value === value; });
    return option ? option.label : value;
  }

  function formatNumber(value) {
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
  }

  // 항목 값 > "3건 (전체 182)" / "8.2 / 10 USD" / "저하" (서버 _summarize_value와 같은 모양)
  function formatItemValue(item) {
    if (item.kind === 'count' && item.count !== null && item.count !== undefined) {
      const text = item.count + (item.unit || '건');
      return item.total !== null && item.total !== undefined ? text + ' (전체 ' + item.total + ')' : text;
    }
    if (item.kind === 'gauge' && item.value !== null && item.value !== undefined) {
      const text = formatNumber(item.value) + (item.limit !== null && item.limit !== undefined ? ' / ' + formatNumber(item.limit) : '');
      return item.unit ? text + ' ' + item.unit : text;
    }
    if (item.state) return STATE_LABELS[item.state] || item.state;
    return '-';
  }

  function toEnvId(identifier) {
    return String(identifier || '').toUpperCase().replace(/-/g, '_');
  }

  function pullTokenEnvName(projectId, sourceId) {
    return PULL_TOKEN_ENV_PREFIX + (projectId ? toEnvId(projectId) : '<PROJECT>') + PULL_TOKEN_SEPARATOR
      + (sourceId ? toEnvId(sourceId) : '<SOURCE>');
  }

  function eventTokenEnvName(projectId) {
    return EVENT_TOKEN_ENV_PREFIX + (projectId ? toEnvId(projectId) : '<PROJECT>');
  }

  // push 입구 절대 주소 (관리 화면 ../control 기준, nginx 프리픽스 뒤에서도 같은 호스트)
  function pushIntakeUrl(projectId, sourceId) {
    const base = new URL('../control/attention/', location.href).href;
    return base + (projectId || '<project>') + '/' + (sourceId || '<source>');
  }

  function describeApiFailure(result) {
    const message = ERROR_MESSAGES[result.data.error] || ('요청에 실패했습니다 (' + result.status + ')');
    return result.data.fields ? message + ' : ' + result.data.fields.join(', ') : message;
  }

  window.AppAttentionFormat = {
    MODE_OPTIONS, LEVEL_POLICY_OPTIONS, ALERT_RULE_OPTIONS, CHANNEL_OPTIONS, TOKEN_HEADER_NAME,
    levelBadgeOf, describeResult, isSuccessResult, describeError, describeMode, labelOf, formatItemValue,
    pullTokenEnvName, eventTokenEnvName, pushIntakeUrl, describeApiFailure,
  };
})();

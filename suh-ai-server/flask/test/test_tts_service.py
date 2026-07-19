"""test_tts_service.py — 엔진 수명주기 상태 전이 검증 (docker CLI·어댑터 mock)"""
from types import SimpleNamespace

import pytest

import service.tts_service as tts_service_module
from service.tts_service import TtsService


class FakeDocker:
    """docker CLI 흉내 — images/running 집합으로 상태를 제어하고 호출을 기록한다"""

    def __init__(self, images=(), running=()):
        self.images = set(images)
        self.running = set(running)
        self.calls = []

    def run(self, cmd, **kwargs):
        args = cmd[1:]  # 'docker' 제거
        self.calls.append(args)
        ok = SimpleNamespace(returncode=0, stdout='', stderr='')
        if args[:2] == ['image', 'inspect']:
            if args[2] in self.images:
                return ok
            return SimpleNamespace(returncode=1, stdout='', stderr='No such image')
        if args[0] == 'ps':
            name_filter = args[args.index('--filter') + 1]  # 'name=^X$'
            name = name_filter[len('name=^'):-1]
            return SimpleNamespace(returncode=0,
                                   stdout=name + '\n' if name in self.running else '',
                                   stderr='')
        if args[0] == 'run':
            self.running.add(args[args.index('--name') + 1])
            return ok
        if args[0] == 'stop':
            self.running.discard(args[1])
            return ok
        return ok


@pytest.fixture
def fake(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(tts_service_module.subprocess, 'run', fake.run)
    return fake


def test_state_not_installed(fake):
    states = TtsService().get_engines_state()
    assert all(s['status'] == 'not_installed' for s in states)
    assert {s['id'] for s in states} == set(
        tts_service_module.TTS_ENGINES.keys())


def test_state_running_needs_health(fake, monkeypatch):
    fake.images = {'ghcr.io/remsky/kokoro-fastapi-gpu:latest'}
    fake.running = {'suh-tts-kokoro'}
    monkeypatch.setattr(tts_service_module, 'get_adapter',
                        lambda eid: SimpleNamespace(health=lambda: False))
    states = {s['id']: s['status'] for s in TtsService().get_engines_state()}
    assert states['kokoro'] == 'starting'  # 컨테이너는 떠 있지만 모델 로딩 중


def test_start_requires_image(fake):
    with pytest.raises(ValueError):
        TtsService().start('kokoro')


def test_start_stops_other_engine_first(fake):
    fake.images = {'ghcr.io/remsky/kokoro-fastapi-gpu:latest',
                   'cassiiopeia/suh-tts-cosyvoice:latest'}
    fake.running = {'suh-tts-cosyvoice'}
    TtsService().start('kokoro')
    assert 'suh-tts-cosyvoice' not in fake.running  # 1개만 실행 정책
    assert 'suh-tts-kokoro' in fake.running


def test_start_publishes_port_and_restart_policy(fake):
    fake.images = {'ghcr.io/remsky/kokoro-fastapi-gpu:latest'}
    TtsService().start('kokoro')
    run_call = next(c for c in fake.calls if c[0] == 'run')
    assert '-p' in run_call and '8880:8880' in run_call
    assert '--restart' in run_call and 'unless-stopped' in run_call


def test_get_running_engine(fake):
    fake.running = {'suh-tts-kokoro'}
    assert TtsService().get_running_engine() == 'kokoro'
    fake.running = set()
    assert TtsService().get_running_engine() is None


def test_install_duplicate_rejected(fake, monkeypatch):
    svc = TtsService()
    # 워커 스레드가 실제로 돌지 않게 pull을 무력화
    monkeypatch.setattr(svc, '_pull', lambda *a: None)
    svc._installs['kokoro'] = {'status': 'pulling', 'error': None}
    with pytest.raises(ValueError):
        svc.install('kokoro')


def test_logs_during_install_returns_pull_log(fake):
    svc = TtsService()
    svc._installs['kokoro'] = {'status': 'pulling', 'error': None,
                               'log': ['abc: Pulling fs layer', 'abc: Downloading']}
    out = svc.logs('kokoro')
    assert '다운로드' in out and 'abc: Downloading' in out
    assert fake.calls == []  # docker logs를 호출하지 않아야 한다


def test_logs_no_container_translated(fake, monkeypatch):
    def fake_run(cmd, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=1,
                               stdout='Error response from daemon: No such container: suh-tts-kokoro')

    monkeypatch.setattr(tts_service_module.subprocess, 'run', fake_run)
    with pytest.raises(RuntimeError) as e:
        TtsService().logs('kokoro')
    assert '컨테이너가 아직 없습니다' in str(e.value)


def test_state_includes_install_progress(fake):
    svc = TtsService()
    svc._installs['kokoro'] = {'status': 'pulling', 'error': None,
                               'progress': '레이어 3개 완료 · abc: Downloading'}
    state = {s['id']: s for s in svc.get_engines_state()}
    assert state['kokoro']['status'] == 'installing'
    assert state['kokoro']['install_progress'] == '레이어 3개 완료 · abc: Downloading'


def test_engines_state_cached_within_ttl(fake):
    svc = TtsService()
    first = svc.get_engines_state()
    calls_after_first = len(fake.calls)
    second = svc.get_engines_state()
    assert second == first
    assert len(fake.calls) == calls_after_first  # 캐시 적중 — docker 재호출 없음


def test_cpu_engine_start_keeps_gpu_engine(fake):
    # CPU 엔진(supertonic) 시작 시 GPU 엔진(cosyvoice)은 내리지 않는다
    fake.images = {'cassiiopeia/suh-tts-supertonic:latest',
                   'cassiiopeia/suh-tts-cosyvoice:latest'}
    fake.running = {'suh-tts-cosyvoice'}
    TtsService().start('supertonic')
    assert 'suh-tts-cosyvoice' in fake.running
    assert 'suh-tts-supertonic' in fake.running


def test_gpu_engine_start_keeps_cpu_engine(fake):
    # GPU 엔진 시작 시 CPU 엔진(supertonic)은 그대로 두고 GPU 엔진만 교체
    fake.images = {'cassiiopeia/suh-tts-supertonic:latest',
                   'ghcr.io/remsky/kokoro-fastapi-gpu:latest',
                   'cassiiopeia/suh-tts-cosyvoice:latest'}
    fake.running = {'suh-tts-supertonic', 'suh-tts-cosyvoice'}
    TtsService().start('kokoro')
    assert 'suh-tts-supertonic' in fake.running   # CPU 엔진 유지
    assert 'suh-tts-cosyvoice' not in fake.running  # GPU 엔진은 교체
    assert 'suh-tts-kokoro' in fake.running

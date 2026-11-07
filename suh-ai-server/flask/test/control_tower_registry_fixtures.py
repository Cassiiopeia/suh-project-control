"""관제소 등록 파일 테스트 공통: 최소 등록 파일, 임시 파일 쓰기"""
from __future__ import annotations

import textwrap

MINIMAL_REGISTRY = """
projects:
  - id: elum
    name: 이룸
    services:
      - id: elum-api
        name: 이룸 API
        public: true
        checks:
          external: {url: "https://api.elum.suhsaechan.kr/healthz", expect: [200]}
"""


def write_registry(tmp_path, yaml_text: str) -> str:
    registry_file = tmp_path / "services.yml"
    registry_file.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return str(registry_file)

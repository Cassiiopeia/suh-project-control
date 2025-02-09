#!/bin/bash
# cleanup.sh - 프로젝트 루트에 존재하는 불필요한 dot 파일 및 폴더 제거

# 현재 운영체제 확인
OS=$(uname)
if [ "$OS" != "Linux" ]; then
  echo "현재 OS는 $OS입니다. 이 스크립트는 Linux 환경에서만 실행됩니다. 종료합니다."
  exit 0
fi

# 현재 디렉토리가 프로젝트 루트인지 확인 (config, bin 존재 확인)
if [[ ! -d "config" || ! -d "bin" ]]; then
  echo "Error: 현재 디렉토리가 프로젝트 루트가 아닙니다."
  exit 1
fi

#제거할 파일과 폴더를 정확하게 지정
rm -rf .git .github .gitignore

echo ".git, .github, .gitignore 제거 롼료"
echo "Cleanup 완료."

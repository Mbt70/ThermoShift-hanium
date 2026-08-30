#!/usr/bin/env bash
# 포트가 열릴 때까지 기다린다. systemd 의 ExecStartPre 에서 쓴다.
#
#   scripts/wait-for.sh <호스트> <포트> [초]
#
# 유닛 파일 안에 셸 반복문을 직접 적지 않는 이유:
#   - systemd 는 명령줄에서 `$(...)` 를 확장하지 않는다.
#   - 유닛을 heredoc 으로 생성하면 `$$` 가 셸 PID 로 먼저 치환된다.
#   - /bin/sh 는 Debian 에서 dash 라 bash 전용인 /dev/tcp 를 못 쓴다.
# 세 가지가 겹쳐 조용히 깨지기 쉬우므로 파일로 뺀다.
#
# 시간이 지나도 열리지 않으면 0 으로 끝낸다. 여기서 실패로 끝내면 서비스가
# 아예 안 뜨는데, API 는 DB 가 늦게 올라와도 커넥션 풀이 뒤늦게 붙으므로
# 일단 띄우는 편이 낫다.
set -u

HOST="${1:?호스트를 지정하세요}"
PORT="${2:?포트를 지정하세요}"
TIMEOUT="${3:-60}"

for _ in $(seq 1 "$TIMEOUT"); do
  if (exec 3<>"/dev/tcp/${HOST}/${PORT}") 2>/dev/null; then
    exec 3>&- 2>/dev/null || true
    exit 0
  fi
  sleep 1
done

echo "wait-for: ${HOST}:${PORT} 가 ${TIMEOUT}초 안에 열리지 않았습니다 — 그대로 진행합니다" >&2
exit 0

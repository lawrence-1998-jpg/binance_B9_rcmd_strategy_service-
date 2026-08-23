#!/bin/bash
# Spade BFF API 小工具。用法: spade.sh <path> [json-body]
# 无 body = GET，有 body = POST。JWT 自动缓存到 ~/.b9/.spade_jwt（12h）
set -euo pipefail
BFF=https://bdp-bff.toolsfdg.net
JWTF=~/.b9/.spade_jwt

_fresh_jwt() {
  local t; t=$(cat ~/.b9/spade_token)
  curl -s --max-time 25 -X POST "$BFF/api/personal-token/exchange" \
    -H "Content-Type: application/json" -d "{\"token\":\"$t\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["access_token"])' > "$JWTF"
  chmod 600 "$JWTF"
}
# JWT 超过 11 小时就刷新
if [ ! -s "$JWTF" ] || [ -n "$(find "$JWTF" -mmin +660 2>/dev/null)" ]; then _fresh_jwt; fi
JWT=$(cat "$JWTF")

P="$1"; shift || true
if [ $# -gt 0 ] && [ -n "${1:-}" ]; then
  curl -s --max-time 90 -X POST "$BFF$P" -H "Authorization: Bearer $JWT" \
    -H "Content-Type: application/json" -d "$1"
else
  curl -s --max-time 90 "$BFF$P" -H "Authorization: Bearer $JWT"
fi

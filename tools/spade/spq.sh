#!/bin/bash
# Spade 跑 SQL。用法: spq.sh "<SQL>" [行数上限] [-j]
# 成功 → TSV(或 -j 的 JSON) 到 stdout；失败 → 退出码 1 并把原因打到 stderr。
# 关键：以 queryResponseDto.state 判定成败，绝不把空结果当成功。
set -uo pipefail
S=~/.b9/bin/spade.sh
UID_OKTA="${B9_OKTA_UID:-$(cat ~/.b9/okta_uid 2>/dev/null)}"
[ -z "$UID_OKTA" ]&& { echo "缺 Okta UID: export B9_OKTA_UID=... 或写入 ~/.b9/okta_uid" >&2; exit 1; }

SQL="$1"; [ "$SQL" = "-" ] && SQL=$(cat)
LIM="${2:-1000}"; FMT="${3:-tsv}"

BODY=$(python3 -c 'import json,sys;print(json.dumps({"queryEngine":"Trino476","query":sys.argv[1],"userId":sys.argv[2],"storedVars":{},"limit":int(sys.argv[3])}))' "$SQL" "$UID_OKTA" "$LIM")
QID=$($S /api/bigdata-bquery/queries "$BODY" | python3 -c 'import sys,json;d=json.load(sys.stdin);e=d.get("error");sys.exit("提交失败: "+str(e)) if e else print(d["data"]["id"])') || exit 1

for i in $(seq 1 400); do
  D=$($S "/api/bigdata-bquery/queries/$QID")
  ST=$(printf '%s' "$D" | python3 -c '
import sys,json
try: d=json.load(sys.stdin).get("data") or {}
except Exception: print("WAIT"); sys.exit()
q=d.get("queryResponseDto") or {}
st=q.get("state") or "WAIT"
if st in ("Finished","Succeeded","Success","Successful"): print("OK")
elif st in ("Submitted","Running","Queued","Planning","Started"): print("WAIT")
else:
    ut=q.get("unauthorizedTables") or []
    logs=d.get("logs") or []
    err=[l for l in logs if "ERROR" in l or "error" in l.lower()]
    msg=" | ".join(ut) if ut else (" ".join(err) if err else " ".join(logs[-4:]))
    print("FAIL "+st+" :: "+msg[:600])')
  case "$ST" in
    OK) break ;;
    WAIT) sleep 3 ;;
    *) echo "查询失败 → ${ST#FAIL }" >&2; exit 1 ;;
  esac
done
[ "$ST" = "OK" ] || { echo "查询超时(20min)" >&2; exit 1; }

COLS=$(printf '%s' "$D" | python3 -c '
import sys,json
d=json.load(sys.stdin).get("data") or {}
h=d.get("headers") or []
print("\t".join(x if isinstance(x,str) else (x.get("name","") if isinstance(x,dict) else str(x)) for x in h))')

R=$($S "/api/bigdata-bquery/queries/$QID/results?userName=lawrence.zzz&page=0&pageSize=$LIM")
export COLS FMT
printf '%s' "$R" | python3 -c '
import sys,json,os
d=json.load(sys.stdin)["data"]; rows=d.get("content") or []
if os.environ.get("FMT") in ("-j","json"): print(json.dumps(rows,ensure_ascii=False)); sys.exit()
c=os.environ.get("COLS","").strip()
if c: print(c)
for r in rows: print("\t".join("" if v is None else str(v) for v in r))
n=d.get("totalElements",len(rows)); print("-- %s rows"%n, file=sys.stderr)'

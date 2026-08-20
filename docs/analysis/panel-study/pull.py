import subprocess, sys, json, pathlib
d1, d2, name = sys.argv[1], sys.argv[2], sys.argv[3]
SQL = f"""WITH cohort AS (
  SELECT DISTINCT user_id AS uid
  FROM hive.bnb_dwd.fact_main_asset_ss_d
  WHERE date_key=20260728
    AND token IN ('BTC','ETH','SOL','BNB','XRP','DOGE','PEPE','LINK')
    AND asset_holding_usdt >= 100 AND net_asset_holding_qty > 0
    AND MOD(ABS(from_big_endian_64(xxhash64(to_utf8(user_id)))), 300) = 0
)
SELECT b.date_key, b.symbol, b.distinct_id AS uid,
       COUNT(CASE WHEN b.event='place_order_event' AND hour(b.actual_event_time)<12 THEN 1 END) AS am_ord,
       COUNT(CASE WHEN b.event='place_order_event' AND hour(b.actual_event_time)>=12 THEN 1 END) AS pm_ord,
       COUNT(CASE WHEN b.event IN ('$AppViewScreen','$AppClick') AND hour(b.actual_event_time)<12 THEN 1 END) AS am_view,
       COUNT(CASE WHEN b.event IN ('$AppViewScreen','$AppClick') AND hour(b.actual_event_time)>=12 THEN 1 END) AS pm_view,
       COUNT(CASE WHEN b.event='ModuleView' AND hour(b.actual_event_time)<12 THEN 1 END) AS am_exp,
       COUNT(CASE WHEN b.event='ModuleView' AND hour(b.actual_event_time)>=12 THEN 1 END) AS pm_exp
FROM hive.bnb_dwd.dwd_main_user_traffic_sensor_behavior_di b
JOIN cohort c ON c.uid = b.distinct_id
WHERE b.date_key BETWEEN {d1} AND {d2} AND b.is_login = 1
  AND b.symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT','PEPEUSDT','LINKUSDT')
  AND b.event IN ('place_order_event','$AppViewScreen','$AppClick','ModuleView')
GROUP BY 1,2,3"""
home = pathlib.Path.home()
r = subprocess.run([str(home/'.b9/bin/spq.sh'), SQL, '40000', '-j'],
                   capture_output=True, text=True, timeout=1500)
out = pathlib.Path(f'{name}.json'); out.write_text(r.stdout or '[]')
try: n = len(json.loads(r.stdout))
except Exception: n = f"ERR: {r.stderr[:200]}"
print(f"{name}: rows={n}")

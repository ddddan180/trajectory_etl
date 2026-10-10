"""从清洗表生成出租车活动分析页面（聚合数据，无数据库凭据）。"""
import json
from datetime import datetime
from pathlib import Path
import h3
import psycopg
from plotly.offline import get_plotlyjs
from config import get_database_url

OUT = Path(__file__).resolve().parent / 'output' / 'activity'


def parent_sql(res):
    return f"to_hex(((('x'||lpad(h3_r9,16,'0'))::bit(64)::bigint & ~({15 << 52}::bigint)) | {res << 52}::bigint) | {(1 << (3*(15-res)))-1}::bigint)"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = {'generated_at': datetime.now().astimezone().isoformat(), 'source': 'valid_points_clean'}
    with psycopg.connect(get_database_url(), connect_timeout=5) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET TIME ZONE 'Asia/Shanghai'")
        total, filled, vehicles = conn.execute('SELECT count(*),count(h3_r9),count(DISTINCT vehicle_id) FROM valid_points_clean').fetchone()
        if total != filled: raise RuntimeError('请先完成 H3 回填')
        data['total_points'], data['total_vehicles'] = total, vehicles
        data['coverage'] = [[str(d),int(n),int(v)] for d,n,v in conn.execute('SELECT DATE(recorded_at),count(*),count(DISTINCT vehicle_id) FROM valid_points_clean GROUP BY 1 ORDER BY 1')]
        print('统计分辨率 7 热点及小时变化', flush=True)
        q = f'''WITH p AS (SELECT vehicle_id, DATE(recorded_at)::text d,
            EXTRACT(HOUR FROM recorded_at)::int hr, {parent_sql(7)} cell FROM valid_points_clean)
            SELECT d,hr,cell,count(*),count(DISTINCT vehicle_id) FROM p
            GROUP BY GROUPING SETS ((d,hr,cell),(d,cell),(hr,cell),(cell))'''
        data['hotspots'] = [[d,hr,cell,int(n),int(v)] for d,hr,cell,n,v in conn.execute(q)]
        print('统计分辨率 6 区域间观测转移', flush=True)
        q = f'''WITH p AS (SELECT id,vehicle_id,recorded_at,longitude,latitude,{parent_sql(6)} cell
            FROM valid_points_clean), pairs AS (
            SELECT *,lag(cell) OVER w origin, lag(recorded_at) OVER w prev_time,
            lag(longitude) OVER w prev_lon,lag(latitude) OVER w prev_lat
            FROM p WINDOW w AS (PARTITION BY vehicle_id ORDER BY recorded_at,id)),
            valid AS (SELECT *,EXTRACT(EPOCH FROM recorded_at-prev_time) dt FROM pairs),
            flows AS (SELECT vehicle_id,DATE(recorded_at)::text d,EXTRACT(HOUR FROM recorded_at)::int hr,
            origin,cell destination FROM valid WHERE origin<>cell AND dt>0 AND dt<=600
            AND sqrt(power((longitude-prev_lon)*cos(radians((latitude+prev_lat)/2))*111320,2)
            +power((latitude-prev_lat)*111320,2)) / NULLIF(dt,0) <= 40)
            SELECT d,hr,origin,destination,count(*),count(DISTINCT vehicle_id) FROM flows
            GROUP BY GROUPING SETS ((d,hr,origin,destination),(d,origin,destination),
                (hr,origin,destination),(origin,destination))'''
        data['flows'] = [[d,hr,a,b,int(n),int(v)] for d,hr,a,b,n,v in conn.execute(q)]
    cells = {r[2] for r in data['hotspots']} | {r[2] for r in data['flows']} | {r[3] for r in data['flows']}
    data['cells'] = {c: {'center': list(h3.cell_to_latlng(c)), 'boundary': [[lon,lat] for lat,lon in h3.cell_to_boundary(c)], 'resolution':h3.get_resolution(c)} for c in cells}
    # Verify SQL H3 parent bit conversion against the library.
    sample = '8931aa40173ffff'
    for res in (6,7):
        value=(int(sample,16)&~(15<<52))|(res<<52)|((1<<(3*(15-res)))-1)
        assert format(value,'x')==h3.cell_to_parent(sample,res)
    (OUT/'data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    template = Path('activity_dashboard.html').read_text()
    template = template.replace('__PLOTLY__', get_plotlyjs())
    template = template.replace('__DATA__',json.dumps(data,ensure_ascii=False,separators=(',',':')))
    (OUT/'index.html').write_text(template)
    print(f'已生成 {OUT / "index.html"}，热点聚合 {len(data["hotspots"]):,} 行，流动聚合 {len(data["flows"]):,} 行',flush=True)


if __name__ == '__main__': main()

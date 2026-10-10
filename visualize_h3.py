"""数据库聚合热力图、抽样 GPS 叠加图，使用清洗表已保存的 h3_r9。"""
import argparse
from pathlib import Path

import pandas as pd
import psycopg
from charts import build_gps_h3_maps
from config import get_database_url


def query_map_data(conn, max_overlay_points=5000):
    if max_overlay_points <= 0:
        raise ValueError('max_overlay_points 必须大于 0')
    with conn.cursor() as cursor:
        print('数据库聚合 H3 网格点数、车辆数和中心位置', flush=True)
        cursor.execute('''
            SELECT h3_r9, COUNT(*) AS point_count,
                   COUNT(DISTINCT vehicle_id) AS vehicle_count,
                   AVG(longitude) AS longitude, AVG(latitude) AS latitude
            FROM valid_points_clean
            WHERE h3_r9 IS NOT NULL AND h3_r9 <> ''
            GROUP BY h3_r9
        ''')
        counts = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
        if counts.empty:
            raise ValueError('没有已保存 H3 的 GPS 点，请先运行 gps_h3.py')
        total = int(counts.point_count.sum())
        center = {'lon': float((counts.longitude * counts.point_count).sum() / total),
                  'lat': float((counts.latitude * counts.point_count).sum() / total)}
        target = min(total, max_overlay_points)
        # Row-level sampling avoids the clustering bias of SYSTEM block sampling.
        percent = min(100.0, 200.0 * target / total)
        while True:
            cursor.execute('''
                SELECT vehicle_id, recorded_at, longitude, latitude, h3_r9
                FROM valid_points_clean TABLESAMPLE BERNOULLI (%s) REPEATABLE (42)
                WHERE h3_r9 IS NOT NULL AND h3_r9 <> ''
                ORDER BY random() LIMIT %s
            ''', (percent, target))
            points = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
            if len(points) >= target or percent == 100.0:
                break
            percent = min(100.0, percent * 2)
    print(f'全量 {total:,} 点聚合为 {len(counts):,} 网格；仅传输 {len(points):,} 个叠加点', flush=True)
    return points, counts, total, center


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='output/h3')
    parser.add_argument('--max-overlay-points', type=int, default=5000)
    args = parser.parse_args()
    if args.max_overlay_points <= 0:
        parser.error('--max-overlay-points 必须大于 0')
    with psycopg.connect(get_database_url(), connect_timeout=5) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET TIME ZONE 'Asia/Shanghai'")
        points, counts, total, center = query_map_data(conn, args.max_overlay_points)
    overlay, heatmap = build_gps_h3_maps(
        points, args.max_overlay_points, grid_counts=counts,
        total_points=total, center=center,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename, figure in [('gps_h3_overlay.html', overlay), ('h3_heatmap.html', heatmap)]:
        path = output / filename
        figure.write_html(path, include_plotlyjs=True)
        print(path.resolve(), flush=True)


if __name__ == '__main__':
    main()

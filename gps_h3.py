"""H3 resolution 9 indices for WGS84 GPS points and historical backfill."""
import argparse
import math
from datetime import datetime
from time import perf_counter

import h3
import psycopg

from config import get_database_url

def gps_to_h3(longitude, latitude):
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        raise ValueError("经纬度必须是有限数值")
    # if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
    #     raise ValueError("经纬度超出范围")
    # H3 expects latitude first, unlike the input TXT.
    return h3.latlng_to_cell(latitude, longitude, 9)


def backfill_h3(conn, batch_size=10000):
    if batch_size <= 0:
        raise ValueError("batch_size 必须大于 0")
    
    last_id = None
    total = 0
    total_updated = 0
    batch_number = 0
    started = perf_counter()

    def log(message):
        print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}", flush=True)

    log(f"开始回填 H3，每批最多 {batch_size:,} 条")
    while True:
        batch_started = perf_counter()
        log(f"开始查询第 {batch_number + 1} 批，上一批最大 id={last_id}")
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, longitude, latitude FROM valid_points_clean
                WHERE h3_r9 IS NULL
                  AND (%s::bigint IS NULL OR id > %s)
                  AND longitude BETWEEN -180 AND 180
                  AND latitude BETWEEN -90 AND 90
                ORDER BY id LIMIT %s
            """, (last_id, last_id, batch_size))
            rows = cursor.fetchall()
            if not rows:
                break
            cursor.executemany("""
                UPDATE valid_points_clean SET h3_r9 = %s
                WHERE id = %s AND h3_r9 IS NULL
            """, [(gps_to_h3(lon, lat), point_id) for point_id, lon, lat in rows])
            updated_count = cursor.rowcount
        conn.commit()
        last_id = rows[-1][0]
        total += len(rows)
        total_updated += updated_count
        batch_number += 1
        log(
            f"第 {batch_number} 批已提交：读取 {len(rows):,} 条，"
            f"实际更新 {updated_count:,} 条，id 范围 {rows[0][0]}～{last_id}，"
            f"耗时 {perf_counter() - batch_started:.2f} 秒；"
            f"累计读取 {total:,} 条，累计更新 {total_updated:,} 条"
        )
    log("回填查询结束，开始检查或创建 H3 索引")
    with conn.cursor() as cursor:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_valid_points_clean_h3_r9 ON valid_points_clean (h3_r9)")
    conn.commit()
    log(f"处理完成：共 {batch_number} 批，实际更新 {total_updated:,} 条，总耗时 {perf_counter() - started:.2f} 秒")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为已有 WGS84 GPS 点分批回填 H3 分辨率 9 索引")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()
    database_url = get_database_url()

    with psycopg.connect(database_url) as connection:
        backfill_h3(connection, args.batch_size)

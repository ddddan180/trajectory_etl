import csv
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from gps_h3 import gps_to_h3

from charts import show_gps_count_distribution,show_daily_gps_stats,show_daily_gps_interval

import pandas as pd

from config import get_database_url

# 仅在确认原始时间是北京时间后使用
source_timezone = ZoneInfo("Asia/Shanghai")
data_dir = Path("/Users/bin/Downloads/release/taxi_log_2008_by_id")
file_limit = 1000


def open_and_parse_files(conn):
    records = []
    file_count = 0

    for file_path in sorted(data_dir.iterdir()):
        if not file_path.is_file():
            continue

        file_records = []
        with file_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)

            for line_number, row in enumerate(reader, start=1):
                # 跳过空行
                if not row or all(not value.strip() for value in row):
                    continue

                try:
                    if len(row) != 4:
                        raise ValueError(f"应有 4 列，实际有 {len(row)} 列")

                    vehicle_id = int(row[0].strip())
                    recorded_at = datetime.strptime(
                        row[1].strip(), "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=source_timezone)
                    longitude = float(row[2].strip())
                    latitude = float(row[3].strip())

                    if not -180 <= longitude <= 180:
                        raise ValueError("经度超出范围")
                    if not -90 <= latitude <= 90:
                        raise ValueError("纬度超出范围")
                    h3_r9 = gps_to_h3(longitude, latitude)

                except ValueError as error:
                    print(
                        f"文件 {file_path.name} 第 {line_number} 行解析失败："
                        f"{error}，原始数据：{row}"
                    )
                   
                    continue

                # 可直接作为 psycopg 的写入参数
                file_records.append(
                      (vehicle_id, recorded_at, longitude, latitude)
                )

        records.extend(file_records)
        file_count += 1

        if file_count >= file_limit:
            import_data_to_postgresql(conn, records)
            records.clear()
            file_count = 0
            print(f"已处理 {file_limit} 个文件，数据已导入 PostgreSQL。")

    if records:
        import_data_to_postgresql(conn, records)

def import_data_to_postgresql(conn, records):
    if not records:
        return
    insert_sql = """
        INSERT INTO vehicle_trajectory_original
            (vehicle_id, recorded_at, longitude, latitude)
        VALUES (%s, %s, %s, %s)
    """
    with conn.cursor() as cursor:
        cursor.executemany(insert_sql, records)
        inserted_count = cursor.rowcount
    conn.commit()
    print(f"本批准备插入 {len(records)} 条，数据库报告插入 {inserted_count} 条。")

def data_status(conn): 
    status_sql = """
        SELECT
            CASE
                WHEN longitude BETWEEN 115.42 AND 117.50
                AND latitude BETWEEN 39.47 AND 41.08
                AND longitude IS NOT NULL
                AND latitude IS NOT NULL
                THEN '正常'
                ELSE '异常'
            END AS status,
            COUNT(*) AS cnt
        FROM vehicle_trajectory_original
        GROUP BY status
    """
    with conn.cursor() as cursor:
        cursor.execute(status_sql)
        status_results = cursor.fetchall()
    conn.commit()
    for status, cnt in status_results:
        print(f"{status}: {cnt} 条")
    

def clean_valid_points(conn):
    clean_valid_sql = """
    CREATE TABLE valid_points_clean AS
    SELECT DISTINCT ON (
        vehicle_id, recorded_at, longitude, latitude
    )
        id,
        vehicle_id,
        recorded_at,
        longitude,
        latitude,
        NULL::text AS h3_r9
    FROM vehicle_trajectory_original
    WHERE longitude BETWEEN 115.42 AND 117.50
    AND latitude BETWEEN 39.47 AND 41.08
    ORDER BY
        vehicle_id, recorded_at, longitude, latitude, id;

    ALTER TABLE valid_points_clean
    ADD PRIMARY KEY (id);

    CREATE INDEX idx_clean_vehicle_time
    ON valid_points_clean (vehicle_id, recorded_at);"""
    with conn.cursor() as cursor:
        cursor.execute(clean_valid_sql)
    conn.commit()
    
def get_valid_points(conn, as_dataframe=False):
    """返回有效点元组，附加 h3_r9；视图已有该列时重新计算并替换。"""
    # refresh only when data is updated
    valid_points_sql = """
        SELECT *
        FROM valid_points_clean
    """
    with conn.cursor() as cursor:
        cursor.execute(valid_points_sql)
        valid_points = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

    longitude_index = columns.index("longitude")
    latitude_index = columns.index("latitude")
    h3_index = columns.index("h3_r9") if "h3_r9" in columns else None
    indexed_points = []
    for point in valid_points:
        cell = gps_to_h3(point[longitude_index], point[latitude_index])
        if h3_index is None:
            indexed_points.append(tuple(point) + (cell,))
        else:
            values = list(point)
            values[h3_index] = cell
            indexed_points.append(tuple(values))
    if as_dataframe:
        if h3_index is None:
            columns.append("h3_r9")
        return pd.DataFrame(indexed_points, columns=columns)
    return indexed_points

def get_valid_points_count(conn):
    count_sql = """
        SELECT
    vehicle_id,
    COUNT(*) AS point_count
    FROM valid_points_clean
    GROUP BY vehicle_id
    ORDER BY point_count DESC;
    """
    with conn.cursor() as cursor:
        cursor.execute(count_sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
    return pd.DataFrame(rows, columns=columns)

def get_valid_points_day_count(conn):
    day_count_sql = """
        SELECT
            COUNT(DISTINCT vehicle_id) AS vehicle_count,
            DATE(recorded_at) AS recorded_date,
            COUNT(*) AS point_count
        FROM valid_points_clean
        GROUP BY recorded_date
        ORDER BY recorded_date;
    """
    with conn.cursor() as cursor:
        cursor.execute(day_count_sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
    
    return pd.DataFrame(rows, columns=columns)

def get_valid_points_interval_count(conn):
    interval_count_sql="""
    WITH gps_intervals AS (
    SELECT
        vehicle_id,
        recorded_at,
        EXTRACT(
            EPOCH FROM (
                recorded_at -
                LAG(recorded_at) OVER (
                    PARTITION BY vehicle_id
                    ORDER BY recorded_at, id
                )
            )
        ) AS interval_seconds
    FROM valid_points_clean
    WHERE vehicle_id IS NOT NULL
      AND recorded_at IS NOT NULL
    )
    SELECT
        FLOOR(interval_seconds / 60.0) AS interval_minutes,
        COUNT(*) AS interval_count
    FROM gps_intervals
    WHERE interval_seconds >= 0
    AND interval_seconds < 3600
    GROUP BY 1
    ORDER BY 1;
    """
    # 只统计相邻 GPS 点间隔在 0～不足60分钟之间的数据。
    with conn.cursor() as cursor:
        cursor.execute(interval_count_sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
    
    return pd.DataFrame(rows, columns=columns)

def main():
    database_url =get_database_url()

    with psycopg.connect(database_url) as conn:
        # open_and_parse_files(conn) #导入一次
        # data_status(conn) #数据统计
        # clean_valid_points(conn) #数据清理
        
        #数据图表
        show_gps_count_distribution(get_valid_points_count(conn))
        # show_daily_gps_stats(get_valid_points_day_count(conn))
        # show_daily_gps_interval(get_valid_points_interval_count(conn))


if __name__ == "__main__":
    main()

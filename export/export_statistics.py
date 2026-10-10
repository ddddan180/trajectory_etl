"""从实际数据库统计结果导出 README 使用的三个图表。"""
from pathlib import Path

import psycopg
from config import get_database_url
from etl import get_valid_points_count, get_valid_points_day_count, get_valid_points_interval_count
from charts import show_gps_count_distribution, show_daily_gps_stats, show_daily_gps_interval


def main():
    output = Path(__file__).resolve().parent / 'output' / 'statistics'
    output.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(get_database_url(), connect_timeout=5) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET TIME ZONE 'Asia/Shanghai'")
        if conn.execute("SELECT to_regclass('valid_points_clean')").fetchone()[0] is None:
            raise RuntimeError('valid_points_clean 不存在，请先准备清洗表')
        for query, plot, name in [
            (get_valid_points_day_count, show_daily_gps_stats, 'daily_gps_stats'),
            (get_valid_points_count, show_gps_count_distribution, 'gps_count_distribution'),
            (get_valid_points_interval_count, show_daily_gps_interval, 'daily_gps_interval'),
        ]:
            print(f'查询 {name}', flush=True)
            frame = query(conn)
            frame.to_csv(output / f'{name}.csv', index=False)
            figure = plot(frame, show=False)
            figure.update_layout(font={'family': 'Arial, PingFang SC, sans-serif'}, width=1200, height=650)
            figure.write_html(output / f'{name}.html')
            figure.write_image(str(output / f'{name}.png'), scale=2)
            print(f'已导出 {name}', flush=True)


if __name__ == '__main__':
    main()

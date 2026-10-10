"""将保存的真实每日统计快照导出为 README 图片，不重新查询数据库。"""
import json
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/tmp/tractory-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


def main():
    root = Path(__file__).resolve().parent
    stats = json.loads((root / 'output/data_statistics.json').read_text())
    output = root / 'output/statistics'
    output.mkdir(exist_ok=True)
    font_path = Path('/System/Library/Fonts/PingFang.ttc')
    font = FontProperties(fname=str(font_path)) if font_path.exists() else FontProperties()
    labels = [row[0][5:] for row in stats['daily']]
    for index, name, title in [(1, 'daily_points', '每日 GPS 点数'), (2, 'daily_vehicles', '每日去重车辆数')]:
        values = [row[index] for row in stats['daily']]
        fig, ax = plt.subplots(figsize=(11, 4.8), layout='constrained')
        ax.plot(labels, values, marker='o', color='#2563eb', linewidth=2)
        ax.set_title(title + '（北京时间）', fontproperties=font, fontsize=17)
        ax.set_ylabel('点数' if index == 1 else '车辆数', fontproperties=font)
        ax.ticklabel_format(axis='y', style='plain', useOffset=False)
        ax.grid(axis='y', alpha=.2)
        ax.margins(y=.25)
        for x, y in zip(labels, values):
            ax.annotate(f'{y:,}', (x,y), xytext=(0,10), textcoords='offset points', ha='center', fontsize=10)
        fig.text(.5, .005, '数据快照：' + stats['snapshot_at'][:19] + ' +08:00；首尾日期非完整自然日',
                 ha='center', fontproperties=font, fontsize=9, color='#555555')
        fig.savefig(output / (name+'.png'), dpi=160, bbox_inches='tight')
        plt.close(fig)


if __name__ == '__main__':
    main()

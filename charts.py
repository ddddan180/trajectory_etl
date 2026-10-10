import plotly.express as px
import pandas as pd
import h3
import plotly.graph_objects as go


def _h3_geojson(cells):
    features = []
    for cell in cells:
        ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell)]
        ring.append(ring[0])
        features.append({
            "type": "Feature", "id": cell, "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    return {"type": "FeatureCollection", "features": features}


def build_gps_h3_maps(df, max_overlay_points=5000, *, grid_counts=None, total_points=None, center=None):
    """叠加图抽样展示；热力图统计传入的全部 GPS 点。返回两个 Figure。"""
    if df.empty:
        raise ValueError("没有有效 GPS 点可供绘图")
    if max_overlay_points <= 0:
        raise ValueError("max_overlay_points 必须大于 0")
    points = df.sample(n=min(len(df), max_overlay_points), random_state=42)
    center = center or {"lat": float(df.latitude.mean()), "lon": float(df.longitude.mean())}
    total_points = len(df) if total_points is None else total_points
    overlay_cells = points.h3_r9.unique()
    overlay = go.Figure(go.Choroplethmap(
        geojson=_h3_geojson(overlay_cells), locations=overlay_cells,
        z=[1] * len(overlay_cells), showscale=False,
        colorscale=[[0, "#74b9ff"], [1, "#74b9ff"]],
        marker_opacity=0.18, marker_line_width=1,
        hovertemplate="H3: %{location}<extra></extra>", name="H3 网格",
    ))
    overlay.add_trace(go.Scattermap(
        lat=points.latitude, lon=points.longitude, mode="markers",
        marker={"size": 5, "color": "#d63031"}, name="GPS 点",
        customdata=points[["vehicle_id", "recorded_at", "h3_r9"]].astype(str).values,
        hovertemplate="车辆: %{customdata[0]}<br>时间: %{customdata[1]}"
                      "<br>经度: %{lon}<br>纬度: %{lat}<br>H3: %{customdata[2]}<extra></extra>",
    ))
    counts = grid_counts if grid_counts is not None else df.groupby("h3_r9", as_index=False).agg(
        point_count=("h3_r9", "size"), vehicle_count=("vehicle_id", "nunique")
    )
    heatmap = go.Figure(go.Choroplethmap(
        geojson=_h3_geojson(counts.h3_r9), locations=counts.h3_r9,
        z=counts.point_count, colorscale="YlOrRd", marker_opacity=0.75,
        marker_line_width=0.3, colorbar_title="GPS 点数",
        customdata=counts[["vehicle_count"]].values,
        hovertemplate="H3: %{location}<br>GPS 点数: %{z}"
                      "<br>去重车辆数: %{customdata[0]}<extra></extra>",
    ))
    for fig, title in (
        (overlay, f"GPS 点叠加 H3 网格（展示 {len(points):,} / {total_points:,} 个点）"),
        (heatmap, f"H3 网格热力图（统计 {total_points:,} 个 GPS 点）"),
    ):
        fig.update_layout(title=title, map={"style": "carto-positron", "center": center, "zoom": 10},
                          height=800, margin={"l": 0, "r": 0, "b": 0, "t": 60})
    return overlay, heatmap


def show_gps_count_distribution(df, show=True):
   
    p95 = df["point_count"].quantile(0.95)

    df_main = df[df["point_count"] <= p95]

    fig = px.histogram(
        df_main,
        x="point_count",
        nbins=40,
        title="车辆 GPS 点数分布（P95以内）"
    )

    fig.update_layout(
        xaxis_title="每辆车 GPS 点数",
        yaxis_title="车辆数量"
    )

    if show:
        fig.show()
    return fig

def show_daily_gps_stats(df, show=True):

    fig = px.line(
        df,
        x="recorded_date",
        y="point_count",
        markers=True,
        title="每日 GPS 点数变化趋势",
        labels={
            "recorded_date": "日期",
            "point_count": "GPS 点数"
        }
    )

    fig.update_layout(
        template="plotly_white",
        hovermode="x unified"
    )

    if show:
        fig.show()
    return fig

def show_daily_gps_interval(df, show=True):

    # df 是 PostgreSQL 返回的采样间隔统计结果
    # 字段：interval_minutes, interval_count

    fig = px.bar(
        df,
        x="interval_minutes",
        y="interval_count",
        title="GPS 采样时间间隔分布",
        labels={
            "interval_minutes": "采样间隔（分钟）",
            "interval_count": "GPS 相邻记录数量"
        }
    )

    fig.update_layout(
        template="plotly_white",
        xaxis=dict(
            dtick=5,
            range=[-0.5, 30.5]
        ),
        yaxis_title="相邻 GPS 记录数量",
        bargap=0.05
    )

    if show:
        fig.show()
    return fig

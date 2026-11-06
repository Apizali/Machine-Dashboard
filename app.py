import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# --- Page Config ---
st.set_page_config(
    page_title="Shopfloor OEE Real-Time Telemetry",
    page_icon="⚙️",
    layout="wide",
)

# Auto-refresh every 20 seconds
st_autorefresh(interval=20 * 1000, key="oee_poll")

# --- Google Sheet Data Source ---
SHEET_ID = "12z1zgQCnC8qHg11rADMl88JccXmbvbccxsxhnh-Ihp8"
GID = "1225255672"
CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
)


@st.cache_data(ttl=15)
def load_oee_data(url: str) -> pd.DataFrame:
  data = pd.read_csv(url)

  # Datetime conversions
  data["Timestamp"] = pd.to_datetime(data["Timestamp"], errors="coerce")
  data["StartTime"] = pd.to_datetime(data["StartTime"], errors="coerce")

  # Clean numeric columns
  metric_cols = [
      "Availability",
      "Line Performance",
      "Quality",
      "Line OEE",
      "Throughput",
      "Total Pass",
      "Total Fail",
      "Current Hour UPH",
      "Soft Jam",
      "Hard Jam",
  ]
  for col in metric_cols:
    if col in data.columns:
      data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0)

  return data.sort_values(by="Timestamp")


# --- Helper for Duration to Minutes ---
def duration_to_mins(series: pd.Series) -> pd.Series:
  """Converts 'HH:MM:SS' strings into total minutes."""

  def convert(val):
    if pd.isna(val) or not isinstance(val, str):
      return 0.0
    parts = val.split(":")
    if len(parts) == 3:
      return (
          float(parts[0]) * 60 + float(parts[1]) + float(parts[2]) / 60
      )  # hours*60 + min + sec/60
    return 0.0

  return series.apply(convert)


try:
  df = load_oee_data(CSV_URL)

  # --- Sidebar Controls ---
  st.sidebar.header("🕹️ Station & Time Filters")

  stations = ["All Stations"] + sorted(df["StationID"].dropna().unique().tolist())
  selected_station = st.sidebar.selectbox("Select Station ID", stations)

  # Filter by date range
  min_date = df["Timestamp"].min().date()
  max_date = df["Timestamp"].max().date()
  date_range = st.sidebar.date_input("Filter Date Range", [min_date, max_date])

  # Filter Data
  filtered_df = df.copy()
  if selected_station != "All Stations":
    filtered_df = filtered_df[filtered_df["StationID"] == selected_station]

  if len(date_range) == 2:
    start_d, end_d = date_range
    filtered_df = filtered_df[
        (filtered_df["Timestamp"].dt.date >= start_d)
        & (filtered_df["Timestamp"].dt.date <= end_d)
    ]

  # --- Header Section ---
  st.title("🏭 Real-Time OEE Manufacturing Telemetry")
  latest_record = filtered_df.iloc[-1] if not filtered_df.empty else None

  if latest_record is not None:
    st.caption(
        f"Displaying **{selected_station}** | Last Reported Timestamp:"
        f" **{latest_record['Timestamp']}** (Shift: {latest_record['ShiftName']})"
    )

  # --- Row 1: KPI Cards ---
  avg_oee = filtered_df["Line OEE"].mean()
  avg_avail = filtered_df["Availability"].mean()
  avg_perf = filtered_df["Line Performance"].mean()
  avg_qual = filtered_df["Quality"].mean()

  total_pass = int(filtered_df["Total Pass"].sum())
  total_fail = int(filtered_df["Total Fail"].sum())
  total_parts = total_pass + total_fail

  c1, c2, c3, c4 = st.columns(4)

  c1.metric(
      label="Overall OEE",
      value=f"{avg_oee:.1f}%",
      delta=(
          f"{avg_oee - 85.0:.1f}% vs Target"
          if not np.isnan(avg_oee)
          else "No Data"
      ),
  )
  c2.metric(label="Availability", value=f"{avg_avail:.1f}%")
  c3.metric(label="Performance", value=f"{avg_perf:.1f}%")
  c4.metric(
      label="Quality Rate",
      value=f"{avg_qual:.1f}%",
      delta=f"{total_fail} rejects",
      delta_color="inverse",
  )

  st.divider()

  # --- Row 2: Gauges & Production Summary ---
  col_gauge, col_prod = st.columns([1, 1])

  with col_gauge:
    st.subheader("OEE Primary Gauge")
    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=avg_oee,
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Average OEE (%)", "font": {"size": 20}},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#1f77b4"},
                "steps": [
                    {"range": [0, 50], "color": "#ffb3b3"},  # Low
                    {"range": [50, 75], "color": "#ffe6b3"},  # Medium
                    {"range": [75, 100], "color": "#c6ecc6"},  # Good
                ],
                "threshold": {
                  "line": {"color": "red", "width": 3},
                  "thickness": 0.75,
                  "value": 85,  # World-class benchmark
              },
            },
        )
    )
    fig_gauge.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_gauge, use_container_width=True)

  with col_prod:
    st.subheader("Throughput & Defect Split")
    prod_summary = pd.DataFrame(
        {"Status": ["Passed Units", "Defects"], "Count": [total_pass, total_fail]}
    )
    fig_pie = px.pie(
        prod_summary,
        names="Status",
        values="Count",
        color="Status",
        color_discrete_map={"Passed Units": "#2ca02c", "Defects": "#d62728"},
        hole=0.45,
    )
    fig_pie.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig_pie, use_container_width=True)

  # --- Row 3: Hourly Telemetry Trends ---
  st.subheader("📈 Hourly OEE & Machine Telemetry Trend")
  trend_fig = go.Figure()
  trend_fig.add_trace(
      go.Scatter(
          x=filtered_df["Timestamp"],
          y=filtered_df["Line OEE"],
          mode="lines+markers",
          name="OEE (%)",
          line=dict(color="#1f77b4", width=2),
      )
  )
  trend_fig.add_trace(
      go.Scatter(
          x=filtered_df["Timestamp"],
          y=filtered_df["Availability"],
          mode="lines",
          name="Availability (%)",
          line=dict(color="#2ca02c", dash="dash"),
      )
  )
  trend_fig.add_trace(
      go.Scatter(
          x=filtered_df["Timestamp"],
          y=filtered_df["Line Performance"],
          mode="lines",
          name="Performance (%)",
          line=dict(color="#ff7f0e", dash="dot"),
      )
  )
  trend_fig.update_layout(
      xaxis_title="Time",
      yaxis_title="Percentage (%)",
      hovermode="x unified",
      height=380,
      margin=dict(l=20, r=20, t=30, b=20),
  )
  st.plotly_chart(trend_fig, use_container_width=True)

  # --- Row 4: Machine Loss Breakdown & Jam Counts ---
  col_downtime, col_jam = st.columns([1, 1])

  with col_downtime:
    st.subheader("⏱️ Machine State Duration (Minutes)")
    time_cols = [
        "Productive Time",
        "Standby Time",
        "No Material Time",
        "Unscheduled Down Time",
        "Engineering Time",
    ]
    present_time_cols = [c for c in time_cols if c in filtered_df.columns]

    if present_time_cols:
      durations = {
          c: duration_to_mins(filtered_df[c]).sum() for c in present_time_cols
      }
      downtime_df = pd.DataFrame(
          list(durations.items()), columns=["State", "Total Minutes"]
      )

      fig_bars = px.bar(
          downtime_df,
          x="Total Minutes",
          y="State",
          orientation="h",
          color="State",
          text_auto=".1f",
      )
      fig_bars.update_layout(
          showlegend=False, height=300, margin=dict(l=10, r=10, t=10, b=10)
      )
      st.plotly_chart(fig_bars, use_container_width=True)

  with col_jam:
    st.subheader("🚨 Mechanical Stoppages")
    jam_sum = pd.DataFrame({
        "Stoppage Type": ["Soft Jam", "Hard Jam"],
        "Count": [
            filtered_df["Soft Jam"].sum(),
            filtered_df["Hard Jam"].sum(),
        ],
    })
    fig_jams = px.bar(
        jam_sum,
        x="Stoppage Type",
        y="Count",
        color="Stoppage Type",
        color_discrete_map={"Soft Jam": "#ffbb33", "Hard Jam": "#ff4444"},
        text="Count",
    )
    fig_jams.update_layout(
        showlegend=False, height=300, margin=dict(l=10, r=10, t=10, b=10)
    )
    st.plotly_chart(fig_jams, use_container_width=True)

  # --- Row 5: Raw Feed Log ---
  st.subheader("📋 Recent Shift Log Records")
  display_cols = [
      "Timestamp",
      "ShiftName",
      "StationID",
      "Line OEE",
      "Availability",
      "Line Performance",
      "Quality",
      "Throughput",
      "Total Pass",
      "Total Fail",
  ]
  st.dataframe(
      filtered_df[display_cols].tail(15).iloc[::-1], use_container_width=True
  )

except Exception as err:
  st.error(f"Error loading or parsing OEE dashboard data: {err}")
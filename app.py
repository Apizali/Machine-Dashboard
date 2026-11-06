import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# --- Page Config & Refresh ---
st.set_page_config(page_title="Line Progress & Machine Capability", layout="wide")
st_autorefresh(interval=30 * 1000, key="auto_refresh")  # Refresh every 30 seconds

# --- Header ---
st.title("OEE & Production Line Capability Dashboard")
st.markdown(
    "Total Output Benchmark: <span style='color:#38bdf8'>Station A6</span> | "
    "Hourly Output: <span style='color:#fbbf24'>Current Hour UPH</span>", 
    unsafe_allow_html=True
)

# --- Data Fetching & Parsing Logic ---
@st.cache_data(ttl=15)
def get_master_production_data():
    # Updated Google Sheet ID and GID
    FILE_ID = "12z1zgQCnC8qHg11rADMl88JccXmbvbccxsxhnh-Ihp8"
    GID = "1225255672"
    CSV_URL = f"https://docs.google.com/spreadsheets/d/{FILE_ID}/export?format=csv&gid={GID}"
    
    try:
        # Load raw data without headers first to mimic the row scanning logic
        raw_df = pd.read_csv(CSV_URL, header=None, dtype=str)
        
        # 1. Locate header row (Mimic JS logic: look for 'station' or 'uph')
        header_idx = 0
        for i in range(min(10, len(raw_df))):
            row_str = " ".join(raw_df.iloc[i].fillna("").astype(str).str.lower())
            if "station" in row_str or ("uph" in row_str and "time" in row_str):
                header_idx = i
                break
                
        df = pd.read_csv(CSV_URL, header=header_idx)
        lower_cols = [str(c).lower().replace(" ", "").replace("_", "") for c in df.columns]
        
        # 2. Locate Columns based on JS mapping rules
        def find_col(keywords, default_idx):
            for i, c in enumerate(lower_cols):
                if any(k in c for k in keywords):
                    return df.columns[i]
            return df.columns[default_idx] if default_idx < len(df.columns) else None

        col_map = {
            "station": find_col(["station", "stn", "line"], 2),
            "output": find_col(["currenthouruph", "uph"], 26),
            "throughput": find_col(["throughput"], 18),
            "fail": find_col(["totalfail", "fail"], 20),
            "date": find_col(["timestamp", "start", "date"], 0),
            "avail": find_col(["avail"], 24),
            "perf": find_col(["perf"], 23),
            "qual": find_col(["qual"], 22),
            "oee": find_col(["oee"], 25)
        }
        
        # 3. Clean Types (Parse Numbers & Percentages)
        for key in ["output", "throughput", "fail", "avail", "perf", "qual", "oee"]:
            col_name = col_map[key]
            if col_name and col_name in df.columns:
                # Remove commas, convert to numeric
                df[col_name] = pd.to_numeric(df[col_name].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
                
        # Fix Percentages (if <= 1, multiply by 100)
        for key in ["avail", "perf", "qual", "oee"]:
            col_name = col_map[key]
            if col_name and col_name in df.columns:
                df[col_name] = df[col_name].apply(lambda x: x * 100 if 0 < x <= 1 else x)
                
        # Clean Dates
        date_col = col_map["date"]
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
            df[date_col] = df[date_col].fillna("Unknown")
            
        df[col_map["station"]] = df[col_map["station"]].astype(str).str.upper().str.strip()
        
        return df, col_map, True, "Connected successfully"
    except Exception as e:
        return pd.DataFrame(), {}, False, str(e)

df, cmap, success, msg = get_master_production_data()

if not success or df.empty:
    st.error(f"Failed to connect or sheet is empty: {msg}")
    st.stop()

# Live Diagnostic Bar
st.info(f"**Diagnostic Bar** — Rows Loaded: **{len(df)}** | Station Col: **{cmap['station']}** | Output Source: **{cmap['output']}**")

# --- Planning Parameters Form ---
st.markdown("### Planning Parameters & Demand Targets")
c1, c2, c3, c4 = st.columns(4)
demand_qtr = c1.number_input("Quarterly Demand (Units)", value=30000.0, step=1000.0)
days_wk = c2.number_input("Working Days / Week", value=5, min_value=1, max_value=7)
hrs_day = c3.number_input("Operating Hours / Day", value=21, min_value=1, max_value=24)
wks_qtr = c4.number_input("Weeks / Quarter", value=12, min_value=1, max_value=14)

# Math Calculations
total_working_days = wks_qtr * days_wk
total_operating_hrs = total_working_days * hrs_day
daily_demand_target = (demand_qtr / total_working_days) if total_working_days > 0 else 0
req_uph = (demand_qtr / total_operating_hrs) if total_operating_hrs > 0 else 0
req_takt = (3600 / req_uph) if req_uph > 0 else 0

st.markdown(
    f"**Required Daily Target:** <span style='color:#38bdf8; font-family:monospace;'>{int(daily_demand_target):,}</span> units/day | "
    f"**Required UPH:** <span style='color:#fbbf24; font-family:monospace;'>{req_uph:.1f}</span> UPH | "
    f"**Target Takt Time:** <span style='color:#34d399; font-family:monospace;'>{req_takt:.1f}</span> sec", 
    unsafe_allow_html=True
)
st.divider()

# --- Data Aggregation ---
# 1. Base Aggregations
unique_days = df[df[cmap["date"]] != "Unknown"][cmap["date"]].nunique()
num_days = max(1, unique_days)

# 2. A6 Benchmark Calculations
a6_df = df[df[cmap["station"]].str.contains("A6", na=False)]
a6_total_out = a6_df[cmap["output"]].sum()
a6_avg_daily = a6_total_out / max(1, a6_df[cmap["date"]].nunique())
a6_attainment = (a6_avg_daily / daily_demand_target * 100) if daily_demand_target > 0 else 100
a6_avail = a6_df[cmap["avail"]].replace(0, pd.NA).mean()
a6_qual = a6_df[cmap["qual"]].replace(0, pd.NA).mean()

# 3. Station Matrix Calculations
st_agg = df.groupby(cmap["station"]).agg(
    total_out=(cmap["output"], "sum"),
    fail=(cmap["fail"], "sum"),
    avail_avg=(cmap["avail"], lambda x: x[x>0].mean()),
    perf_avg=(cmap["perf"], lambda x: x[x>0].mean()),
    qual_avg=(cmap["qual"], lambda x: x[x>0].mean()),
    oee_avg=(cmap["oee"], lambda x: x[x>0].mean())
).reset_index()

st_agg["daily_avg"] = st_agg["total_out"] / num_days
st_agg["variance"] = st_agg["daily_avg"] - daily_demand_target
st_agg["attainment"] = (st_agg["daily_avg"] / daily_demand_target * 100).fillna(100)

bottleneck_station = st_agg.loc[st_agg["daily_avg"].idxmin(), cmap["station"]] if not st_agg.empty else "N/A"

# --- KPI Summary Cards ---
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("A6 Cumulative Output", f"{int(a6_total_out):,} u", "Sum of Col AA")
k2.metric("A6 Avg Daily Output", f"{int(a6_avg_daily):,} u/day", f"{a6_df[cmap['date']].nunique()} active days")
k3.metric("Daily Target Attainment", f"{a6_attainment:.1f}%", f"Target: {int(daily_demand_target):,} u/day")
k4.metric("A6 Availability", f"{a6_avail:.1f}%" if pd.notna(a6_avail) else "N/A")
k5.metric("A6 Quality Rate", f"{a6_qual:.1f}%" if pd.notna(a6_qual) else "N/A")
k6.metric("🚨 Line Bottleneck", bottleneck_station, f"Lowest output station", delta_color="inverse")

# --- Charts ---
c_left, c_right = st.columns(2)

with c_left:
    st.subheader("Station A6 Daily Hourly Output vs Target")
    a6_daily = a6_df.groupby(cmap["date"])[cmap["output"]].sum().reset_index()
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(x=a6_daily[cmap["date"]], y=a6_daily[cmap["output"]], name="A6 Output", marker_color="#38bdf8"))
    fig1.add_trace(go.Scatter(x=a6_daily[cmap["date"]], y=[daily_demand_target]*len(a6_daily), name="Target", mode="lines", line=dict(color="#ef4444", dash="dash")))
    fig1.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig1, use_container_width=True)

with c_right:
    st.subheader("Daily Output Comparison Across All Stations")
    colors = ["#38bdf8" if "A6" in s else "#94a3b8" for s in st_agg[cmap["station"]]]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=st_agg[cmap["station"]], y=st_agg["daily_avg"], marker_color=colors, name="Avg Output"))
    fig2.add_trace(go.Scatter(x=st_agg[cmap["station"]], y=[daily_demand_target]*len(st_agg), name="Target", mode="lines", line=dict(color="#ef4444", dash="dash")))
    fig2.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig2, use_container_width=True)

# --- Station Matrix Table ---
st.subheader("Station Capability & OEE Matrix")
st_matrix = st_agg.copy()
st_matrix.columns = ["Station", "Total Col AA Output", "Total Fail", "Avail %", "Perf %", "Qual %", "OEE %", "Daily Avg", "Variance", "Attainment %"]
st_matrix["Daily Target"] = int(daily_demand_target)

# Reorder columns to match HTML table
st_matrix = st_matrix[["Station", "Total Col AA Output", "Daily Avg", "Daily Target", "Variance", "Attainment %", "Avail %", "Perf %", "Qual %", "OEE %"]]

st.dataframe(
    st_matrix.style.format({
        "Total Col AA Output": "{:,.0f}",
        "Daily Avg": "{:,.0f}",
        "Variance": "{:+,.0f}",
        "Attainment %": "{:.1f}%",
        "Avail %": "{:.1f}%",
        "Perf %": "{:.1f}%",
        "Qual %": "{:.1f}%",
        "OEE %": "{:.1f}%"
    }).map(lambda v: 'color: #ef4444' if v < 0 else 'color: #10b981', subset=["Variance"]),
    use_container_width=True,
    hide_index=True
)

# --- Station A6 Daily Log Table ---
st.subheader("Station A6 Daily Output Log")
a6_log = a6_df.groupby(cmap["date"]).agg(
    hours_logged=(cmap["output"], "count"),
    a6_total_out=(cmap["output"], "sum"),
    throughput=(cmap["throughput"], "sum"),
    total_fail=(cmap["fail"], "sum")
).reset_index()

a6_log["Target"] = int(daily_demand_target)
a6_log["Variance"] = a6_log["a6_total_out"] - daily_demand_target
a6_log["Attainment %"] = (a6_log["a6_total_out"] / daily_demand_target * 100).fillna(100)

a6_log.columns = ["Date", "Hours Logged", "A6 Total Output", "Throughput", "Total Fail", "Target", "Variance", "Attainment %"]

st.dataframe(
    a6_log.style.format({
        "A6 Total Output": "{:,.0f}",
        "Throughput": "{:,.0f}",
        "Total Fail": "{:,.0f}",
        "Variance": "{:+,.0f}",
        "Attainment %": "{:.1f}%"
    }).map(lambda v: 'color: #ef4444' if v < 0 else 'color: #10b981', subset=["Variance"]),
    use_container_width=True,
    hide_index=True
)
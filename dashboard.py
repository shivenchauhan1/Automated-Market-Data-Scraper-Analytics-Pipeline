"""
Streamlit Market Analytics Dashboard.
Interactive visual business intelligence interface for real-time market KPIs, sector performance, stock screening, and ETL execution.
Run with: streamlit run dashboard.py
"""

import os
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analytics.kpi_analysis import KPIAnalytics
from analytics.market_analysis import MarketAnalytics
from config.config import get_config
from database.db_connection import get_db_manager
from etl.extract import extract
from etl.load import load_to_database
from etl.transform import transform
from etl.validate import validate, quarantine
from reports.excel_report import generate_excel_report
from reports.google_sheets import update_google_sheets

# ---------------------------------------------------------
# Streamlit Page Setup
# ---------------------------------------------------------
st.set_page_config(
    page_title="Market Analytics Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = get_config()
db = get_db_manager(config)
market_analytics = MarketAnalytics(config, db)
kpi_analytics = KPIAnalytics(config, db)


def load_market_data() -> pd.DataFrame:
    """Load latest market data directly from the relational database."""
    return market_analytics.get_latest_market_data()


# ---------------------------------------------------------
# Pipeline Runner Helper
# ---------------------------------------------------------
def run_pipeline_now():
    """Trigger complete ETL and reporting pipeline directly from UI."""
    with st.status("Executing ETL Pipeline...", expanded=True) as status:
        st.write("🔄 Step 1: Starting run telemetry...")
        run_id = db.start_pipeline_run("Streamlit_UI")
        
        st.write("🌐 Step 2: Scraping multi-page market quotes & API endpoints...")
        raw_data = extract(pages=4, config=config)
        
        st.write("🧹 Step 3: Cleaning, normalizing, and casting data types...")
        transformed = transform(raw_data, config=config)
        
        st.write("🛡️ Step 4: Enforcing Pydantic v2 schema constraints...")
        validated, errs = validate(transformed, config=config)
        quarantine(errs, config=config)
        
        st.write(f"💾 Step 5: Upserting validated records into {db.active_engine.upper()} database...")
        load_summary = load_to_database(validated, db=db, config=config)
        
        st.write("📊 Step 6: Generating styled Excel workbook & updating reports...")
        generate_excel_report(validated, config=config)
        update_google_sheets(validated, config=config)
        
        db.finish_pipeline_run(
            run_id=run_id,
            records_extracted=len(raw_data.get("stocks", [])),
            records_loaded=load_summary["total_records"],
            status="SUCCESS",
        )
        status.update(label="✅ Pipeline Execution Succeeded!", state="complete", expanded=False)
    st.toast("Market database updated successfully!", icon="🎉")


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
with st.sidebar:
    st.title("📈 Market Pipeline")
    st.caption("Automated Data Engineering & Analytics")
    st.divider()

    st.subheader("⚡ On-Demand Execution")
    if st.button("🚀 Run Pipeline Now", use_container_width=True, type="primary"):
        run_pipeline_now()

    st.divider()
    st.subheader("🔍 Filters & Controls")
    df_raw = load_market_data()
    
    if not df_raw.empty:
        all_sectors = ["All Sectors"] + sorted(df_raw["sector"].dropna().unique().tolist())
        selected_sector = st.selectbox("Select Sector", all_sectors)
        
        min_pe = 0.0
        max_pe = float(df_raw["pe_ratio"].max() if "pe_ratio" in df_raw.columns and not df_raw["pe_ratio"].isna().all() else 100.0)
        selected_pe = st.slider("Max P/E Ratio", min_value=min_pe, max_value=max_pe, value=max_pe, step=5.0)

        search_query = st.text_input("Search Symbol or Company", "").strip().upper()
    else:
        selected_sector = "All Sectors"
        selected_pe = 100.0
        search_query = ""

    st.divider()
    st.info(f"**Database Engine:** `{db.active_engine.upper()}`\n\n**Architecture:** `3NF Relational Schema`")


# ---------------------------------------------------------
# Main Page Header & KPIs
# ---------------------------------------------------------
st.title("Market Analytics Dashboard")

if df_raw.empty:
    st.warning("⚠️ No market data found in the database. Click **'Run Pipeline Now'** in the sidebar to extract and populate data.")
    st.stop()

# Compute Breadth and Summary Metrics
gainers_count = int((df_raw["change_percent"] > 0).sum())
losers_count = int((df_raw["change_percent"] < 0).sum())
avg_return = df_raw["change_percent"].mean()
total_mcap = df_raw["market_cap"].sum() if "market_cap" in df_raw.columns else 0.0
kpis = kpi_analytics.get_executive_summary_kpis(df_raw)
breadth = market_analytics.calculate_market_breadth(df_raw)
sector_df = market_analytics.calculate_sector_performance(df_raw)

# 4 Key Metrics as requested
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Companies", f"{len(df_raw)}")
col2.metric("Average Return", f"{avg_return:+.2f}%", delta=f"{avg_return:+.2f}%")
col3.metric("Gainers", f"{gainers_count}", delta=f"{gainers_count} Up")
col4.metric("Losers", f"{losers_count}", delta=f"-{losers_count} Down", delta_color="inverse")
col5.metric("Total Market Cap", f"₹{total_mcap:,.0f} Cr" if total_mcap > 0 else "N/A")

st.divider()

# ---------------------------------------------------------
# Analytics Tabs
# ---------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏆 Top Gainers & Losers",
    "📊 Sector Performance",
    "📋 Market Screener Table",
    "💡 Undervalued Picks",
    "⚙️ Pipeline Telemetry & Logs",
])

# Filtered DataFrame
filtered_df = df_raw.copy()
if selected_sector != "All Sectors":
    filtered_df = filtered_df[filtered_df["sector"] == selected_sector]
if search_query:
    filtered_df = filtered_df[
        filtered_df["symbol"].str.contains(search_query, case=False, na=False) |
        filtered_df["company_name"].str.contains(search_query, case=False, na=False)
    ]
if "pe_ratio" in filtered_df.columns:
    filtered_df = filtered_df[(filtered_df["pe_ratio"].isna()) | (filtered_df["pe_ratio"] <= selected_pe)]


# --- TAB 1: Top Gainers & Losers ---
with tab1:
    g_col, l_col = st.columns(2)

    with g_col:
        st.subheader("🟢 Top Gainers")
        top_gainers = kpi_analytics.get_top_gainers(10, df_raw)
        if not top_gainers.empty:
            st.dataframe(
                top_gainers[["symbol", "company_name", "sector", "close_price", "change_percent", "volume"]].rename(
                    columns={
                        "symbol": "Symbol",
                        "company_name": "Company",
                        "sector": "Sector",
                        "close_price": "Price (₹)",
                        "change_percent": "Change (%)",
                        "volume": "Volume",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with l_col:
        st.subheader("🔴 Top Losers")
        top_losers = kpi_analytics.get_top_losers(10, df_raw)
        if not top_losers.empty:
            st.dataframe(
                top_losers[["symbol", "company_name", "sector", "close_price", "change_percent", "volume"]].rename(
                    columns={
                        "symbol": "Symbol",
                        "company_name": "Company",
                        "sector": "Sector",
                        "close_price": "Price (₹)",
                        "change_percent": "Change (%)",
                        "volume": "Volume",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )


# --- TAB 2: Sector Performance ---
with tab2:
    st.subheader("Sector Performance & Breadth")
    col_chart, col_stats = st.columns([2, 1])

    with col_chart:
        if not sector_df.empty:
            chart = (
                alt.Chart(sector_df)
                .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
                .encode(
                    x=alt.X("sector:N", sort="-y", title="Sector"),
                    y=alt.Y("avg_return_pct:Q", title="Average Return (%)"),
                    color=alt.condition(
                        alt.datum.avg_return_pct > 0,
                        alt.value("#27AE60"),
                        alt.value("#E74C3C"),
                    ),
                    tooltip=["sector", "avg_return_pct", "company_count", "total_market_cap_cr"],
                )
                .properties(height=340)
            )
            st.altair_chart(chart, use_container_width=True)

    with col_stats:
        st.markdown("#### 🎯 Market Breadth")
        st.metric("A/D Ratio", f"{breadth['ad_ratio']}", f"{breadth['market_sentiment']}")
        st.dataframe(
            sector_df[["sector", "avg_return_pct", "company_count"]].rename(
                columns={
                    "sector": "Sector",
                    "avg_return_pct": "Avg Return (%)",
                    "company_count": "Stocks",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


# --- TAB 3: Market Screener Table ---
with tab3:
    st.subheader(f"Screened Equities ({len(filtered_df)} records)")
    
    cols_to_show = [c for c in ["symbol", "company_name", "sector", "industry", "close_price", "change_percent", "volume", "market_cap", "pe_ratio", "eps"] if c in filtered_df.columns]
    
    st.dataframe(
        filtered_df[cols_to_show].rename(
            columns={
                "symbol": "Symbol",
                "company_name": "Company",
                "sector": "Sector",
                "industry": "Industry",
                "close_price": "Price (₹)",
                "change_percent": "Change %",
                "volume": "Volume",
                "market_cap": "M-Cap (Cr)",
                "pe_ratio": "P/E",
                "eps": "EPS",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    report_files = sorted(config.REPORTS_DIR.glob("*.xlsx"), key=os.path.getmtime, reverse=True)
    if report_files:
        with open(report_files[0], "rb") as f:
            st.download_button(
                label=f"📥 Download Excel Report ({report_files[0].name})",
                data=f.read(),
                file_name=report_files[0].name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# --- TAB 4: Undervalued Picks ---
with tab4:
    st.subheader("💡 Undervalued & Profitable Equities")
    st.caption("Companies with positive net profit and low P/E valuation (P/E ≤ 25)")
    undervalued = kpi_analytics.get_undervalued_picks(max_pe=25.0, df=df_raw)
    
    if not undervalued.empty:
        st.dataframe(
            undervalued[[
                "symbol", "company_name", "sector", "close_price", "pe_ratio", "eps", "profit", "market_cap"
            ]].rename(
                columns={
                    "symbol": "Symbol",
                    "company_name": "Company",
                    "sector": "Sector",
                    "close_price": "Price (₹)",
                    "pe_ratio": "P/E",
                    "eps": "EPS",
                    "profit": "Net Profit (Cr ₹)",
                    "market_cap": "M-Cap (Cr ₹)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No companies found matching value criteria.")


# --- TAB 5: Pipeline Telemetry & Logs ---
with tab5:
    st.subheader("⚙️ ETL Pipeline Execution Telemetry")
    runs_df = db.query_to_dataframe("SELECT * FROM scraper_runs ORDER BY start_time DESC LIMIT 15")
    
    if not runs_df.empty:
        st.dataframe(runs_df, use_container_width=True, hide_index=True)
    else:
        st.info("No pipeline run records logged yet.")

    st.subheader("📝 Recent Pipeline Log Tail")
    if config.LOG_FILE_PATH.exists():
        with open(config.LOG_FILE_PATH, "r", encoding="utf-8") as lf:
            lines = lf.readlines()[-30:]
            st.code("".join(lines), language="log")

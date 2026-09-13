"""
Streamlit Market Analytics Dashboard.
Interactive visual business intelligence interface for real-time market KPIs, sector heatmaps, stock screening, and ETL execution.
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
from etl.extract import MarketExtractor
from etl.load import MarketLoader
from etl.transform import MarketTransformer
from etl.validate import MarketValidator
from reports.excel_report import ExcelReportGenerator

# ---------------------------------------------------------
# Streamlit Page Setup
# ---------------------------------------------------------
st.set_page_config(
    page_title="Automated Market Data Scraper & Analytics Pipeline",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = get_config()
db = get_db_manager(config)
market_analytics = MarketAnalytics(config, db)
kpi_analytics = KPIAnalytics(config, db)


# ---------------------------------------------------------
# Pipeline Runner Helper
# ---------------------------------------------------------
def run_pipeline_now():
    """Trigger complete ETL and reporting pipeline directly from UI."""
    with st.status("Executing ETL Pipeline...", expanded=True) as status:
        st.write("🔄 Step 1: Starting run telemetry...")
        run_id = db.start_pipeline_run("Streamlit_UI")
        
        st.write("🌐 Step 2: Scraping multi-page market quotes & API endpoints...")
        extractor = MarketExtractor(config)
        raw_data = extractor.extract_all(total_pages=4, include_api=True)
        
        st.write("🧹 Step 3: Cleaning, normalizing, and casting data types...")
        transformer = MarketTransformer(config)
        transformed = transformer.transform_all(raw_data)
        
        st.write("🛡️ Step 4: Enforcing Pydantic v2 schema constraints...")
        validator = MarketValidator(config)
        validated, errs = validator.validate_all(transformed)
        
        st.write(f"💾 Step 5: Upserting validated records into {db.active_engine.upper()} database...")
        loader = MarketLoader(config, db)
        load_summary = loader.load_all(validated)
        
        st.write("📊 Step 6: Generating styled Excel workbook...")
        excel_gen = ExcelReportGenerator(config)
        report_path = excel_gen.generate_full_report()
        
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
    st.image("https://img.icons8.com/fluency/96/bullish.png", width=64)
    st.title("Market Pipeline")
    st.caption("Automated Data Engineering & Analytics")
    st.divider()

    st.subheader("⚡ On-Demand Execution")
    if st.button("🚀 Run Pipeline Now", use_container_width=True, type="primary"):
        run_pipeline_now()

    st.divider()
    st.subheader("🔍 Filters & Controls")
    df_raw = market_analytics.get_latest_market_data()
    
    if not df_raw.empty:
        all_sectors = ["All Sectors"] + sorted(df_raw["sector"].dropna().unique().tolist())
        selected_sector = st.selectbox("Select Sector", all_sectors)
        
        min_pe = 0.0
        max_pe = float(df_raw["pe_ratio"].max() if not df_raw["pe_ratio"].isna().all() else 100.0)
        selected_pe = st.slider("Max P/E Ratio", min_value=min_pe, max_value=max_pe, value=max_pe, step=5.0)

        search_query = st.text_input("Search Symbol or Company", "").strip().upper()
    else:
        selected_sector = "All Sectors"
        selected_pe = 100.0
        search_query = ""

    st.divider()
    st.info(f"**Database Engine:** `{db.active_engine.upper()}`\n\n**Schema:** `Normalized Relational`")


# ---------------------------------------------------------
# Main Page Header & KPIs
# ---------------------------------------------------------
st.title("📊 Automated Market Data Scraper & Analytics Dashboard")
st.markdown(
    "*An end-to-end Python ETL pipeline extracting multi-page financial data, validating schema integrity, and loading into a relational database.*"
)

if df_raw.empty:
    st.warning("⚠️ No market data found in the database. Click **'Run Pipeline Now'** in the sidebar to initialize and populate data.")
    st.stop()

# Compute Executive KPIs
kpis = kpi_analytics.get_executive_summary_kpis(df_raw)
breadth = market_analytics.calculate_market_breadth(df_raw)

# Top KPI Metric Row
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Companies", f"{kpis['total_companies']}")
k2.metric("Avg Daily Return", f"{kpis['avg_daily_return']:+.2f}%", delta=f"{kpis['avg_daily_return']:+.2f}%")
k3.metric("Total Market Cap", f"₹{kpis['total_market_cap_cr']:,.0f} Cr")
k4.metric("Avg P/E Ratio", f"{kpis['avg_pe_ratio']:.1f}")
k5.metric("Top Gainer", f"{kpis['top_gainer_symbol']}", delta=f"{kpis['top_gainer_change']:+.2f}%")
k6.metric("Top Loser", f"{kpis['top_loser_symbol']}", delta=f"{kpis['top_loser_change']:+.2f}%", delta_color="inverse")

st.divider()

# ---------------------------------------------------------
# Analytics Tabs
# ---------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Sector Analytics",
    "🏆 Top Gainers & Losers",
    "📋 Market Screener Table",
    "💡 Undervalued Picks",
    "⚙️ Pipeline Telemetry & Logs",
])

# Filter working dataframe
filtered_df = df_raw.copy()
if selected_sector != "All Sectors":
    filtered_df = filtered_df[filtered_df["sector"] == selected_sector]
if search_query:
    filtered_df = filtered_df[
        filtered_df["symbol"].str.contains(search_query, case=False, na=False) |
        filtered_df["company_name"].str.contains(search_query, case=False, na=False)
    ]
filtered_df = filtered_df[(filtered_df["pe_ratio"].isna()) | (filtered_df["pe_ratio"] <= selected_pe)]


# --- TAB 1: Sector Analytics ---
with tab1:
    st.subheader("Sector Performance & Breadth")
    sector_df = market_analytics.calculate_sector_performance(df_raw)

    col_chart, col_breadth = st.columns([2, 1])

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
                        alt.value("#27AE60"),  # Green
                        alt.value("#E74C3C"),  # Red
                    ),
                    tooltip=["sector", "avg_return_pct", "company_count", "total_market_cap_cr"],
                )
                .properties(height=340)
            )
            st.altair_chart(chart, use_container_width=True)

    with col_breadth:
        st.markdown("#### 🎯 Market Breadth")
        b1, b2 = st.columns(2)
        b1.metric("🟢 Advancing", f"{breadth['advancers']}")
        b2.metric("🔴 Declining", f"{breadth['decliners']}")
        st.metric("Market Sentiment", breadth["market_sentiment"], f"A/D Ratio: {breadth['ad_ratio']}")

        st.markdown("#### 💰 Sector Market Cap Breakdown")
        st.dataframe(
            sector_df[["sector", "avg_return_pct", "total_market_cap_cr"]].rename(
                columns={
                    "sector": "Sector",
                    "avg_return_pct": "Avg Return (%)",
                    "total_market_cap_cr": "Market Cap (Cr ₹)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


# --- TAB 2: Top Gainers & Losers ---
with tab2:
    st.subheader("Market Movers")
    g_col, l_col = st.columns(2)

    with g_col:
        st.markdown("### 🟢 Top 5 Gainers")
        top_gainers = kpi_analytics.get_top_gainers(5, df_raw)
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
        st.markdown("### 🔴 Top 5 Losers")
        top_losers = kpi_analytics.get_top_losers(5, df_raw)
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


# --- TAB 3: Market Screener Table ---
with tab3:
    st.subheader(f"Screened Equities ({len(filtered_df)} records)")
    
    display_df = filtered_df[[
        "symbol", "company_name", "sector", "industry", "close_price",
        "previous_close", "change_percent", "volume", "market_cap", "pe_ratio", "eps"
    ]].rename(
        columns={
            "symbol": "Symbol",
            "company_name": "Company",
            "sector": "Sector",
            "industry": "Industry",
            "close_price": "Price (₹)",
            "previous_close": "Prev Close (₹)",
            "change_percent": "Change %",
            "volume": "Volume",
            "market_cap": "M-Cap (Cr)",
            "pe_ratio": "P/E",
            "eps": "EPS",
        }
    )

    st.dataframe(
        display_df.style.format({
            "Price (₹)": "₹{:,.2f}",
            "Prev Close (₹)": "₹{:,.2f}",
            "Change %": "{:+.2f}%",
            "Volume": "{:,}",
            "M-Cap (Cr)": "₹{:,.0f}",
            "P/E": "{:.2f}",
            "EPS": "{:.2f}",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # Download Excel Report button
    report_files = sorted(config.REPORTS_DIR.glob("*.xlsx"), key=os.path.getmtime, reverse=True)
    if report_files:
        with open(report_files[0], "rb") as f:
            st.download_button(
                label=f"📥 Download Excel Report ({report_files[0].name})",
                data=f.read(),
                file_name=report_files[0].name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# --- TAB 4: Undervalued Value Picks ---
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

# 1. Imports at the absolute top
import io
import sys
import traceback
import json
import os
import hashlib
import uuid
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st  # <--- MUST be here
import os
from dotenv import load_dotenv
import psycopg  # Make sure you installed this: pip install psycopg[binary]

# Load the variables from your .env file
load_dotenv()

# Get the link you just saved
DB_URL = os.getenv("DATABASE_URL")

# 2. Page configuration (Must come after imports)
st.set_page_config(
    page_title="Interactive Sales Analytics Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# 2. CUSTOM CSS — CLASSIC ELEGANT THEME
#    Loaded dynamically from style.css
# =============================================================================

def local_css(file_name):
    # This gets the directory where app.py lives
    file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(file_path, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# =============================================================================
# 3. CONSTANTS
# =============================================================================



# Plotly theme constant — used on every chart for visual consistency.
PLOTLY_TEMPLATE: str = "plotly_white"

# Background / paper colour injected into every Plotly figure to match the
# app palette.
CHART_BG: str = "rgba(0,0,0,0)"

# =============================================================================
# 4. DATABASE HELPER FUNCTIONS
# =============================================================================

def get_db_connection():
    """Returns a new connection to the PostgreSQL database."""
    return psycopg.connect(DB_URL)

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_files (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    filename VARCHAR(255) NOT NULL,
                    file_data BYTEA NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, filename)
                )
            """)
            conn.commit()

# Call init_db on startup
init_db()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(username: str, password: str) -> bool:
    username = username.strip().lower()
    hashed = hash_password(password)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s AND password_hash = %s", (username, hashed))
            return cur.fetchone() is not None

def register_user(username: str, password: str) -> bool:
    username = username.strip().lower()
    hashed = hash_password(password)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (username, hashed))
                conn.commit()
                return True
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                return False

def get_user_id(username: str):
    username = username.strip().lower()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (username,))
            row = cur.fetchone()
            return row[0] if row else None

def get_user_files(username: str) -> list:
    user_id = get_user_id(username)
    if not user_id:
        return []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM user_files WHERE user_id = %s ORDER BY uploaded_at DESC", (user_id,))
            return [row[0] for row in cur.fetchall()]

def add_file_to_user(username: str, filename: str, file_bytes: bytes) -> bool:
    user_id = get_user_id(username)
    if not user_id:
        return False
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO user_files (user_id, filename, file_data) VALUES (%s, %s, %s)",
                    (user_id, filename, file_bytes)
                )
                conn.commit()
                return True
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                return False

def get_file_data(username: str, filename: str) -> bytes | None:
    user_id = get_user_id(username)
    if not user_id:
        return None
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_data FROM user_files WHERE user_id = %s AND filename = %s", (user_id, filename))
            row = cur.fetchone()
            return row[0] if row else None

# =============================================================================
# 5. SAMPLE DATA GENERATOR
# =============================================================================

def get_sample_data() -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range(start="2026-01-01", periods=100)
    df = pd.DataFrame({
        "Order_Date": dates,
        "Sales": np.random.uniform(50, 1000, 100),
        "Profit": np.random.uniform(-20, 300, 100),
        "Category": np.random.choice(["Technology", "Furniture", "Office Supplies"], 100),
        "Sub_Category": np.random.choice(["Phones", "Chairs", "Binders", "Paper"], 100),
        "Segment": np.random.choice(["Consumer", "Corporate", "Home Office"], 100),
        "Country": ["United States"] * 100,
        "State": np.random.choice(["California", "New York", "Texas"], 100),
        "City": np.random.choice(["Los Angeles", "New York City", "Houston"], 100)
    })
    return df

# =============================================================================
# 6. SESSION-STATE INITIALISATION
# =============================================================================

def init_session_state() -> None:
    defaults: dict = {
        "theme_toggle": False,
        "authenticated": False,
        "current_user": "",
        "login_error": "",
        "signup_error": "",
        "signup_success": "",
        "df_raw": None,
        "df_filtered": None,
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

init_session_state()

# =============================================================================
# 6. HELPER FUNCTIONS
# =============================================================================

def normalise_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip whitespace from all column names, then replace any sequence of
    spaces or hyphens with a single underscore.

    Parameters
    ----------
    df : pd.DataFrame  — DataFrame with potentially messy column names.

    Returns
    -------
    pd.DataFrame  — Same frame with normalised column headers.
    """
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(r"[\s\-]+", "_", regex=True)
    )
    return df


def coerce_numeric(series: pd.Series) -> pd.Series:
    """
    Safely coerce a Series to float, silencing non-numeric values as NaN.

    Parameters
    ----------
    series : pd.Series  — Raw column from an ingested CSV.

    Returns
    -------
    pd.Series  — Float64 series.
    """
    return pd.to_numeric(series, errors="coerce")


def parse_order_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse 'Order_Date' with mixed-format tolerance; drop un-parsable rows
    and sort the frame chronologically.

    Parameters
    ----------
    df : pd.DataFrame  — Normalised DataFrame that must contain 'Order_Date'.

    Returns
    -------
    pd.DataFrame  — Date-sorted DataFrame with NaT rows removed.
    """
    if "Order_Date" not in df.columns:
        st.sidebar.warning("Column 'Order_Date' not found after normalisation.")
        return df

    df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce", dayfirst=True)
    dropped = int(df["Order_Date"].isna().sum())
    if dropped:
        st.sidebar.warning(f"{dropped:,} rows with unparsable dates removed.")
    df = df.dropna(subset=["Order_Date"]).sort_values("Order_Date").reset_index(drop=True)
    return df


def ingest_csv(uploaded_file) -> pd.DataFrame | None:
    """
    Attempt to read the uploaded CSV with sequential encoding fallback.

    Attempt 1 — UTF-8       : universal default.
    Attempt 2 — ISO-8859-1  : Western-European fallback (Latin-1).
    Attempt 3 — Fatal       : any other exception is logged to stderr and
                               None is returned for graceful handling.

    Parameters
    ----------
    uploaded_file : UploadedFile  — Streamlit file-upload object.

    Returns
    -------
    pd.DataFrame | None  — Parsed DataFrame on success; None on failure.
    """
    # ── Attempt 1: UTF-8 ─────────────────────────────────────────────────────
    try:
        df = pd.read_csv(uploaded_file, encoding="utf-8")
        st.sidebar.success("File decoded — UTF-8.")
        return df
    except (UnicodeDecodeError, TypeError):
        uploaded_file.seek(0)
        st.sidebar.info("UTF-8 failed — retrying with ISO-8859-1.")

    # ── Attempt 2: ISO-8859-1 ────────────────────────────────────────────────
    try:
        df = pd.read_csv(uploaded_file, encoding="iso-8859-1")
        st.sidebar.success("File decoded — ISO-8859-1.")
        return df
    except Exception:
        # ── Attempt 3: Fatal ─────────────────────────────────────────────────
        print("[DASHBOARD] STRUCTURAL FAILURE: CSV parse failed on both encodings.",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        st.sidebar.error(
            "Structural failure: file could not be parsed. "
            "Verify the file is a valid CSV."
        )
        return None


def safe_profit_margin(profit: float, sales: float) -> float:
    """Return (profit / sales) * 100, guarding against division by zero."""
    return (profit / sales * 100) if sales != 0.0 else 0.0


# =============================================================================
# 7. SIDEBAR — DATA INGESTION & CASCADING FILTERS
# =============================================================================

def render_sidebar(df_full: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Render the complete sidebar: file uploader, cascading geographic filters
    (Country -> State -> City), and independent Category / Segment filters.
    Apply all selected filters and return the resulting DataFrame slice.

    Cascading logic:
      - State options are derived from rows where Country matches the
        current Country selection.
      - City options are derived from rows where Country AND State match
        the current selections.

    Parameters
    ----------
    df_full : pd.DataFrame | None
        The fully normalised, date-sorted raw DataFrame.  None when no file
        has been ingested.

    Returns
    -------
    pd.DataFrame | None
        Filtered DataFrame, or None if df_full is None.
    """
    with st.sidebar:
        # ── Sidebar header ────────────────────────────────────────────────────
        st.markdown(
            "<p class='dash-title' style='font-size:0.85rem;'>Analytics Platform</p>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

        # ── Data ingestion & Authentication ───────────────────────────────────
        st.markdown("<p class='section-label'>Data Source</p>", unsafe_allow_html=True)

        if not st.session_state["authenticated"]:
            st.info("Please log in or sign up to upload your own data.")
            tab_login, tab_signup = st.tabs(["Log In", "Sign Up"])
            
            with tab_login:
                with st.form("sidebar_login_form"):
                    st.markdown("<p class='login-title' style='font-size:1rem; text-align:left;'>Sign In</p>", unsafe_allow_html=True)
                    log_email = st.text_input("Email", key="log_email")
                    log_pass = st.text_input("Password", type="password", key="log_pass")
                    log_submit = st.form_submit_button("Log In", use_container_width=True)
                    if log_submit:
                        if authenticate(log_email, log_pass):
                            st.session_state["authenticated"] = True
                            st.session_state["current_user"] = log_email.strip().lower()
                            st.session_state["login_error"] = ""
                            st.rerun()
                        else:
                            st.session_state["login_error"] = "Invalid credentials."
                if st.session_state.get("login_error"):
                    st.error(st.session_state["login_error"])
            
            with tab_signup:
                with st.form("sidebar_signup_form"):
                    st.markdown("<p class='login-title' style='font-size:1rem; text-align:left;'>Register</p>", unsafe_allow_html=True)
                    sign_email = st.text_input("Email", key="sign_email")
                    sign_pass = st.text_input("Password", type="password", key="sign_pass")
                    sign_submit = st.form_submit_button("Sign Up", use_container_width=True)
                    if sign_submit:
                        if sign_email and sign_pass:
                            if register_user(sign_email, sign_pass):
                                st.session_state["signup_success"] = "Registration successful! Please log in."
                                st.session_state["signup_error"] = ""
                            else:
                                st.session_state["signup_error"] = "User already exists."
                                st.session_state["signup_success"] = ""
                        else:
                            st.session_state["signup_error"] = "Please fill in all fields."
                            st.session_state["signup_success"] = ""
                
                if st.session_state.get("signup_error"):
                    st.error(st.session_state["signup_error"])
                if st.session_state.get("signup_success"):
                    st.success(st.session_state["signup_success"])
        else:
            current_user = st.session_state["current_user"]
            user_files = get_user_files(current_user)
            
            upload_option = "-- Upload New File --"
            options = [upload_option] + user_files
            
            selected_file = st.selectbox("My Uploads", options=options, index=0)
            
            if selected_file == upload_option:
                uploaded_file = st.file_uploader(
                    label="Upload CSV",
                    type=["csv"],
                    accept_multiple_files=False,
                    help="Accepts UTF-8 and ISO-8859-1 encoded CSV files.",
                )

                if uploaded_file is not None:
                    file_bytes = uploaded_file.getvalue()
                    success = add_file_to_user(current_user, uploaded_file.name, file_bytes)
                    
                    if success:
                        st.success(f"File {uploaded_file.name} saved securely to database!")
                    else:
                        st.info(f"File {uploaded_file.name} is already in your database.")
                    
                    # We can safely use uploaded_file as a file-like object directly for ingest
                    raw = ingest_csv(uploaded_file)
                    if raw is not None:
                        raw = normalise_column_names(raw)
                        for col in ["Sales", "Profit"]:
                            if col in raw.columns:
                                raw[col] = coerce_numeric(raw[col])
                        raw = parse_order_dates(raw)
                        st.session_state["df_raw"] = raw
                    else:
                        st.session_state["df_raw"] = None
                else:
                    st.session_state["df_raw"] = None
            else:
                # Load from database history
                file_bytes = get_file_data(current_user, selected_file)
                if file_bytes:
                    f = io.BytesIO(file_bytes)
                    raw = ingest_csv(f)
                    if raw is not None:
                        raw = normalise_column_names(raw)
                        for col in ["Sales", "Profit"]:
                            if col in raw.columns:
                                raw[col] = coerce_numeric(raw[col])
                        raw = parse_order_dates(raw)
                        st.session_state["df_raw"] = raw
                    else:
                        st.session_state["df_raw"] = None
                else:
                    st.error(f"Saved file not found in database: {selected_file}")
                    st.session_state["df_raw"] = None

        df = st.session_state.get("df_raw")
        if df is None:
            st.markdown(
                "<p style='font-size:0.72rem; color:#64748b;'>"
                "Viewing sample data. Upload a CSV to view your own data.</p>",
                unsafe_allow_html=True,
            )
            df = get_sample_data()

        st.markdown("---")

        # ── Cascading geographic filters ─────────────────────────────────────
        st.markdown(
            "<p class='section-label'>Geographic Filters</p>",
            unsafe_allow_html=True,
        )

        # Helper: return sorted unique values or empty list when column absent.
        def unique_sorted(frame: pd.DataFrame, col: str) -> list:
            if col not in frame.columns:
                return []
            return sorted(frame[col].dropna().unique().tolist())

        # ── Country ───────────────────────────────────────────────────────────
        all_countries = unique_sorted(df, "Country")
        sel_countries = st.multiselect(
            label="Country",
            options=all_countries,
            default=all_countries,
            key="filter_country",
        )

        # Slice to selected countries so downstream options are constrained.
        df_geo = df[df["Country"].isin(sel_countries)] if (
            "Country" in df.columns and sel_countries
        ) else df.copy()

        # ── State (cascades from Country) ─────────────────────────────────────
        all_states = unique_sorted(df_geo, "State")
        sel_states = st.multiselect(
            label="State",
            options=all_states,
            default=all_states,
            key="filter_state",
        )

        df_geo = df_geo[df_geo["State"].isin(sel_states)] if (
            "State" in df_geo.columns and sel_states
        ) else df_geo.copy()

        # ── City (cascades from Country + State) ──────────────────────────────
        all_cities = unique_sorted(df_geo, "City")
        sel_cities = st.multiselect(
            label="City",
            options=all_cities,
            default=all_cities,
            key="filter_city",
        )

        st.markdown("---")

        # ── Independent categorical filters ───────────────────────────────────
        st.markdown(
            "<p class='section-label'>Categorical Filters</p>",
            unsafe_allow_html=True,
        )

        all_categories = unique_sorted(df, "Category")
        sel_categories = st.multiselect(
            label="Category",
            options=all_categories,
            default=all_categories,
            key="filter_category",
        )

        all_segments = unique_sorted(df, "Segment")
        sel_segments = st.multiselect(
            label="Segment",
            options=all_segments,
            default=all_segments,
            key="filter_segment",
        )

        st.markdown("---")
        # ── Session info ──────────────────────────────────────────────────────
        display_session = st.session_state.get('current_user') if st.session_state.get('authenticated') else 'Guest'
        st.markdown(
            f"<p class='dash-session'>Session: "
            f"{display_session}</p>",
            unsafe_allow_html=True,
        )

    # ── Vectorised boolean mask composition ─────────────────────────────────
    # Build each mask only when the column exists, then AND them together.
    mask = pd.Series([True] * len(df), index=df.index)

    def apply_filter(column: str, selections: list) -> None:
        nonlocal mask
        if column in df.columns and selections:
            mask &= df[column].isin(selections)

    apply_filter("Country", sel_countries)
    apply_filter("State", sel_states)
    apply_filter("City", sel_cities)
    apply_filter("Category", sel_categories)
    apply_filter("Segment", sel_segments)

    return df.loc[mask].reset_index(drop=True)


# =============================================================================
# 8. KPI CARDS
# =============================================================================

def render_kpi_cards(df: pd.DataFrame) -> None:
    """
    Render four KPI metric cards in a single equal-width column row:

      1. Total Revenue Volume         — sum(Sales), currency formatted.
      2. Net Commercial Profit        — sum(Profit); colour-inverted when < 0.
      3. Comprehensive Profit Margin  — (Profit / Sales) * 100; zero-safe.
      4. Transaction Log Quantity     — row count.

    Parameters
    ----------
    df : pd.DataFrame  — Filtered DataFrame from which KPIs are computed.
    """
    st.markdown(
        "<p class='section-label'>Key Performance Indicators</p>",
        unsafe_allow_html=True,
    )

    total_sales  : float = float(df["Sales"].sum())  if "Sales"  in df.columns else 0.0
    total_profit : float = float(df["Profit"].sum()) if "Profit" in df.columns else 0.0
    margin       : float = safe_profit_margin(total_profit, total_sales)
    row_count    : int   = len(df)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Revenue Volume",
            value=f"${total_sales:,.2f}",
        )

    with col2:
        # Negative profit: render the metric then overlay a CSS class to invert
        # the value colour.  We use a container to scope the class.
        if total_profit < 0:
            with st.container():
                st.markdown("<div class='kpi-negative'>", unsafe_allow_html=True)
                st.metric(
                    label="Net Commercial Profit",
                    value=f"${total_profit:,.2f}",
                    delta=f"${total_profit:,.2f}",
                    delta_color="inverse",
                )
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.metric(
                label="Net Commercial Profit",
                value=f"${total_profit:,.2f}",
                delta=f"${total_profit:,.2f}",
                delta_color="normal",
            )

    with col3:
        st.metric(
            label="Comprehensive Profit Margin",
            value=f"{margin:.2f}%",
        )

    with col4:
        st.metric(
            label="Transaction Log Quantity",
            value=f"{row_count:,}",
        )


# =============================================================================
# 9. PLOTLY CHART HELPERS
# =============================================================================

def _apply_chart_layout(fig: go.Figure, title: str = "") -> go.Figure:
    """
    Apply consistent dark-theme layout overrides to any Plotly figure.

    Parameters
    ----------
    fig   : go.Figure  — The figure to update.
    title : str        — Optional chart title.

    Returns
    -------
    go.Figure  — Updated figure.
    """
    is_light = st.session_state.get("theme_toggle", False)
    fig.update_layout(
        template="plotly_white" if is_light else "plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        title=dict(
            text=title,
            font=dict(family="Outfit, sans-serif", size=16, color="#111827" if is_light else "#FFFFFF"),
        ),
        font=dict(family="Outfit, sans-serif", color="#374151" if is_light else "#B0B0C0"),
        margin=dict(l=0, r=0, t=50 if title else 0, b=0),
        hovermode="x unified",
        legend=dict(
            bgcolor="rgba(255, 255, 255, 0.85)" if is_light else "rgba(10, 10, 15, 0.8)",
            bordercolor="rgba(0, 0, 0, 0.1)" if is_light else "rgba(255, 255, 255, 0.1)",
            borderwidth=1,
        ),
        xaxis=dict(
            gridcolor="rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.05)",
            linecolor="rgba(0, 0, 0, 0.1)" if is_light else "rgba(255, 255, 255, 0.1)",
            zerolinecolor="rgba(0, 0, 0, 0.1)" if is_light else "rgba(255, 255, 255, 0.1)",
        ),
        yaxis=dict(
            gridcolor="rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.05)",
            linecolor="rgba(0, 0, 0, 0.1)" if is_light else "rgba(255, 255, 255, 0.1)",
            zerolinecolor="rgba(0, 0, 0, 0.1)" if is_light else "rgba(255, 255, 255, 0.1)",
        ),
    )
    return fig


# =============================================================================
# 10. VISUALISATION TABS
# =============================================================================

def render_visualisations(df: pd.DataFrame) -> None:
    """
    Render three tabbed visualisation panels.

    Tab 1 — Commercial Timelines & Velocity
        Daily aggregated Sales line chart (WebGL mode).

    Tab 2 — Categorical Operational Analysis
        Vertical bar chart: Sales by Category.
        Horizontal bar chart: Profit by Sub_Category (Viridis palette).

    Tab 3 — Statistical Inspector
        pandas describe() for Sales and Profit side by side.
        Plotly box plots for outlier isolation.

    Parameters
    ----------
    df : pd.DataFrame  — Filtered DataFrame to visualise.
    """
    st.markdown(
        "<p class='section-label'>Analytical Views</p>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs([
        "Commercial Timelines & Velocity",
        "Categorical Operational Analysis",
        "Statistical Inspector",
    ])

    # ── Tab 1: Time-series line chart ─────────────────────────────────────────
    with tab1:
        if "Order_Date" not in df.columns or "Sales" not in df.columns:
            st.warning("Columns 'Order_Date' and 'Sales' are required for this view.")
        else:
            daily = (
                df.groupby("Order_Date", as_index=False)["Sales"]
                .sum()
                .rename(columns={"Sales": "Daily_Sales"})
            )
            fig_line = px.line(
                daily,
                x="Order_Date",
                y="Daily_Sales",
                labels={"Order_Date": "Order Date", "Daily_Sales": "Revenue ($)"},
                render_mode="webgl",   # WebGL acceleration for large series
            )
            fig_line.update_traces(line_color="#00F0FF", line_width=2.5)
            fig_line = _apply_chart_layout(fig_line, "Daily Revenue Velocity")
            st.plotly_chart(fig_line, use_container_width=True)

    # ── Tab 2: Categorical charts ─────────────────────────────────────────────
    with tab2:
        col_left, col_right = st.columns(2)

        with col_left:
            if "Category" not in df.columns or "Sales" not in df.columns:
                st.warning("Columns 'Category' and 'Sales' required.")
            else:
                cat_sales = (
                    df.groupby("Category", as_index=False)["Sales"]
                    .sum()
                    .sort_values("Sales", ascending=False)
                )
                fig_vbar = px.bar(
                    cat_sales,
                    x="Category",
                    y="Sales",
                    color="Category",
                    labels={"Sales": "Revenue ($)"},
                    text_auto=".2s",
                )
                fig_vbar = _apply_chart_layout(fig_vbar, "Revenue Matrix by Category")
                fig_vbar.update_layout(showlegend=False)
                st.plotly_chart(fig_vbar, use_container_width=True)

        with col_right:
            sub_col = "Sub_Category" if "Sub_Category" in df.columns else None
            if sub_col is None or "Profit" not in df.columns:
                st.warning("Columns 'Sub_Category' and 'Profit' required.")
            else:
                sub_profit = (
                    df.groupby(sub_col, as_index=False)["Profit"]
                    .sum()
                    .sort_values("Profit", ascending=True)
                )
                fig_hbar = px.bar(
                    sub_profit,
                    x="Profit",
                    y=sub_col,
                    orientation="h",
                    color="Profit",
                    color_continuous_scale="Viridis",
                    labels={"Profit": "Net Profit ($)", sub_col: "Sub-Category"},
                    text_auto=".2s",
                )
                fig_hbar = _apply_chart_layout(fig_hbar, "Net Profit by Sub-Category")
                fig_hbar.update_layout(coloraxis_showscale=False)
                st.plotly_chart(fig_hbar, use_container_width=True)

    # ── Tab 3: Statistical inspector ──────────────────────────────────────────
    with tab3:
        numeric_cols = [c for c in ["Sales", "Profit"] if c in df.columns]

        if not numeric_cols:
            st.warning("No numeric columns (Sales, Profit) found for statistics.")
        else:
            # ── Descriptive statistics table ──────────────────────────────────
            st.markdown(
                "<p class='section-label'>Descriptive Statistics</p>",
                unsafe_allow_html=True,
            )
            desc = df[numeric_cols].describe().round(4)
            st.dataframe(desc, use_container_width=True)

            st.markdown("---")

            # ── Box plots ─────────────────────────────────────────────────────
            st.markdown(
                "<p class='section-label'>Outlier Isolation — Box Plots</p>",
                unsafe_allow_html=True,
            )
            box_cols = st.columns(len(numeric_cols))
            for idx, col_name in enumerate(numeric_cols):
                with box_cols[idx]:
                    fig_box = go.Figure()
                    fig_box.add_trace(
                        go.Box(
                            y=df[col_name].dropna(),
                            name=col_name,
                            marker_color="#00F0FF",
                            line_color="#00F0FF",
                            fillcolor="rgba(0, 240, 255, 0.15)",
                            boxmean="sd",   # show mean and standard deviation
                            boxpoints="outliers",
                        )
                    )
                    fig_box = _apply_chart_layout(
                        fig_box,
                        title=f"{col_name} Distribution",
                    )
                    st.plotly_chart(fig_box, use_container_width=True)


# =============================================================================
# 11. DATA GRID INSPECTOR
# =============================================================================

def render_data_grid(df: pd.DataFrame) -> None:
    """
    Render a collapsible expander containing a paginated tabular view of the
    filtered records and a performance-optimised CSV download button whose
    filename is timestamped at runtime.

    The CSV is serialised in-memory via io.BytesIO to avoid writing to the
    container filesystem.

    Parameters
    ----------
    df : pd.DataFrame  — Filtered DataFrame to display and offer for download.
    """
    with st.expander("Data Grid Inspector", expanded=False):
        st.markdown(
            f"<p class='section-label'>"
            f"{len(df):,} records &nbsp;&middot;&nbsp; {len(df.columns)} columns"
            f"</p>",
            unsafe_allow_html=True,
        )

        # ── In-memory CSV serialisation ───────────────────────────────────────
        # Use a BytesIO buffer so no temporary file is created on disk.
        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
        csv_buffer.seek(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"sales_data_export_{timestamp}.csv"

        st.download_button(
            label="Export Filtered Data as CSV",
            data=csv_buffer,
            file_name=download_filename,
            mime="text/csv",
            help=f"Exports {len(df):,} rows. Filename will include runtime timestamp.",
        )

        st.dataframe(df, use_container_width=True, height=380)


# =============================================================================
# 12. DASHBOARD HEADER
# =============================================================================

def render_dashboard_header() -> None:
    """
    Render the top header bar that spans the full content width.  Displays
    the application title on the left and the active user identity with a
    logout button on the right.

    The logout button resets the authentication flag in session state and
    triggers a rerun so the login gate is immediately re-rendered.
    """
    header_left, header_right = st.columns([2, 1])

    with header_left:
        st.markdown(
            "<h1 class='dash-main-title'>Interactive Sales Analytics Dashboard</h1>",
            unsafe_allow_html=True,
        )

    with header_right:
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col1:
            st.toggle("☀️ Light", key="theme_toggle")
        with col2:
            display_user = st.session_state.get('current_user') if st.session_state.get('authenticated') else "Guest"
            st.markdown(
                f"<p class='dash-user-label'>{display_user}</p>",
                unsafe_allow_html=True,
            )
        with col3:
            if st.session_state.get('authenticated'):
                if st.button("Logout", key="logout_btn"):
                    # Clear auth state.
                    st.session_state["authenticated"] = False
                    st.session_state["current_user"] = ""
                    st.session_state["df_raw"] = None
                    st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)


# =============================================================================
# 13. MAIN APPLICATION ENTRY POINT
# =============================================================================

def main() -> None:
    """
    Orchestrate the full dashboard rendering pipeline post-authentication:

      1.  Render the dashboard header (title + logout).
      2.  Render the sidebar (ingestion + cascading filters).
      3.  Guard against no-data state.
      4.  Guard against empty filtered result.
      5.  Render KPI cards.
      6.  Render visualisation tabs.
      7.  Render the data grid inspector.
    """
    
    local_css("style.css")
    
    if st.session_state.get("theme_toggle", False):
        st.markdown("""
        <style>
        :root {
            --bg-main      : #F4F6F8;
            --bg-surface   : rgba(255, 255, 255, 0.85);
            --bg-elevated  : rgba(255, 255, 255, 0.95);
            --text-primary : #000000;
            --text-body    : #1A1A1A;
            --text-muted   : #4A4A4A;
            --border       : rgba(0, 0, 0, 0.1);
            --border-hover : rgba(0, 0, 0, 0.2);
            --shadow-base  : 0 8px 32px 0 rgba(0, 0, 0, 0.05);
            --shadow-glow  : 0 0 20px rgba(0, 240, 255, 0.2);
            --positive     : #00994C;
            --negative     : #D60036;
            --accent       : #007BFF;
            --accent-dim   : #0056b3;
        }
        
        [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
            background-color: rgba(255, 255, 255, 0.7) !important;
        }
        
        [data-testid="stDataFrame"] {
            background: rgba(255, 255, 255, 0.8) !important;
        }
        
        [data-testid="stAlertContainer"] {
            background: rgba(255, 255, 255, 0.9) !important;
        }
        </style>
        """, unsafe_allow_html=True)

    # ── 13.1  Header ──────────────────────────────────────────────────────────
    render_dashboard_header()

    # ── 13.2  Sidebar + filter application ───────────────────────────────────
    df_filtered = render_sidebar(st.session_state.get("df_raw"))

    # ── 13.3  No-data state ───────────────────────────────────────────────────
    if df_filtered is None:
        st.markdown(
            "<div style='text-align:center; padding: 4rem 0;'>"
            "<p style='color: var(--text-muted); font-size: 0.9rem; letter-spacing: 0.1em; "
            "text-transform: uppercase;'>"
            "No dataset loaded. Upload a CSV file from the sidebar to begin.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # ── 13.4  Empty-filter state ──────────────────────────────────────────────
    if df_filtered.empty:
        st.warning(
            "No records match the current filter configuration. "
            "Broaden your selections to view data."
        )
        return

    # ── 13.5  KPI cards ───────────────────────────────────────────────────────
    render_kpi_cards(df_filtered)
    st.markdown("---")

    # ── 13.6  Visualisation tabs ──────────────────────────────────────────────
    render_visualisations(df_filtered)
    st.markdown("---")

    # ── 13.7  Data grid inspector ─────────────────────────────────────────────
    render_data_grid(df_filtered)


# =============================================================================
# 14. SCRIPT ENTRY
# =============================================================================

if __name__ == "__main__":
    main()
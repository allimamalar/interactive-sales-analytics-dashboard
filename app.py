import os
import hashlib
import streamlit as st
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
import pandas as pd
import plotly.express as px

# --- CONFIGURATION ---
load_dotenv()
DB_URL = os.environ.get("DATABASE_URL")

# --- DATABASE CONNECTION (CONFIRMED WORKING) ---
def get_db_connection():
    if not DB_URL:
        st.error("DATABASE_URL is not set.")
        return None
    try:
        return psycopg.connect(DB_URL, row_factory=dict_row)
    except Exception as e:
        st.error(f"Database error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    files TEXT[] DEFAULT '{}'
                );
            """)
            conn.commit()
        conn.close()

init_db()

# --- AUTHENTICATION FUNCTIONS ---
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username: str, password: str) -> bool:
    username = username.strip().lower()
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", 
                        (username, hash_password(password)))
            conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Registration error: {e}")
        return False

# --- MAIN DASHBOARD UI ---
st.set_page_config(page_title="Sales Analytics", layout="wide")
st.title("Interactive Sales Analytics Dashboard")

# Navigation/Auth Tab
menu = ["Dashboard", "Sign Up"]
choice = st.sidebar.selectbox("Menu", menu)

if choice == "Sign Up":
    st.subheader("Create Account")
    new_user = st.text_input("Username")
    new_pass = st.text_input("Password", type='password')
    if st.button("Sign Up"):
        if register_user(new_user, new_pass):
            st.success("Account created successfully!")
        else:
            st.error("Registration failed. User might already exist.")

elif choice == "Dashboard":
    st.subheader("Analytics Overview")
    
    # Placeholder for your data visualization
    # Replace this with your actual dataframe loading logic
    data = {'Category': ['A', 'B', 'C'], 'Sales': [100, 200, 150]}
    df = pd.DataFrame(data)
    
    fig = px.bar(df, x='Category', y='Sales', title="Sales by Category")
    st.plotly_chart(fig, use_container_width=True) # Note: update to width='stretch' if deprecated

# --- SYSTEM STATUS ---
with st.sidebar.expander("System Info"):
    if st.button("Check Database"):
        conn = get_db_connection()
        if conn:
            st.success("Connected!")
            conn.close()
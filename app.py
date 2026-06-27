import os
import hashlib
import streamlit as st
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load variables
load_dotenv()
DB_URL = os.environ.get("DATABASE_URL")

# --- DATABASE CONNECTION ---
def get_db_connection():
    if not DB_URL:
        st.error("DATABASE_URL is not set in environment variables.")
        return None
    try:
        return psycopg.connect(DB_URL, row_factory=dict_row)
    except Exception as e:
        st.error(f"Database connection error: {e}")
        return None

# --- AUTH & DB FUNCTIONS ---
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
        conn.close()
        return False

# --- SAFE INITIALIZATION ---
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

# Run initialization safely
init_db()

# --- MAIN APP UI ---
st.title("Interactive Sales Analytics Dashboard")
st.write("Welcome! If you see this, the app is running correctly.")

# Example test to see if DB is reachable
if st.button("Test Database Connection"):
    conn = get_db_connection()
    if conn:
        st.success("Successfully connected to the database!")
        conn.close()
    else:
        st.error("Could not connect to the database.")

# ... (Continue with your other dashboard UI code here) ...
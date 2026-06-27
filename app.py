import io
import sys
import traceback
import os
import hashlib
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

# Load variables and DB connection
load_dotenv()
DB_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    return psycopg.connect(DB_URL, row_factory=dict_row)

# =============================================================================
# 4. DATABASE CREDENTIAL FUNCTIONS (Replaces JSON)
# =============================================================================

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(username: str, password: str) -> bool:
    username = username.strip().lower()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if row:
                return row["password_hash"] == hash_password(password)
    return False

def register_user(username: str, password: str) -> bool:
    username = username.strip().lower()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", 
                            (username, hash_password(password)))
                conn.commit()
        return True
    except psycopg.errors.UniqueViolation:
        return False

def get_user_files(username: str) -> list:
    username = username.strip().lower()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT files FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            return row["files"] if row else []

def add_file_to_user(username: str, filename: str) -> None:
    username = username.strip().lower()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Append filename to the files array in Postgres
            cur.execute("""
                UPDATE users 
                SET files = array_append(files, %s) 
                WHERE username = %s AND NOT (%s = ANY(files))
            """, (filename, username, filename))
            conn.commit()

# --- Call this function at app startup to ensure table exists ---
def init_db():
    with get_db_connection() as conn:
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

init_db()

# ... (Rest of your original code follows: get_sample_data, render_sidebar, etc.)
def get_db_connection():
    conn = psycopg.connect(DB_URL, row_factory=dict_row)
    print(f"DEBUG: Connected to database: {conn.info.dbname}")
    return conn
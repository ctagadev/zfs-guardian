import sqlite3
import contextlib
import hashlib
import secrets
import re
import os
import time
from fastapi import HTTPException, Header
from app.state import state

DB_PATH = "data/guardian.db"

# --- FUNCIONES DE BASE DE DATOS MÚLTIPLE (LECTURA/ESCRITURA) ---
# Usar manejadores de contexto (with db_read()) asegura que la conexión SQL se cierre de forma segura
# WAL (Write-Ahead Logging) previene que la base de datos se bloquee (Lock) permanentemente si hacemos métricas y consultas simultáneas.

@contextlib.contextmanager
def db_read():
    """Abre la BD en modo de sólo lectura con alta concurrencia mediante WAL."""
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    try: yield conn
    finally: conn.close()

@contextlib.contextmanager
def db_transaction():
    """Abre la BD y empieza una transacción segura BEGIN IMMEDIATE."""
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# --- SEGURIDAD: MANEJO DE CONTRASEÑAS Y SESIONES ---

def hash_password(pwd, salt=None):
    """Genera un hash PBKDF2 súper seguro para las contraseñas."""
    if not salt: salt = secrets.token_hex(16)
    return f"{salt}:{hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000).hex()}"

def verify_password(pwd, hashed):
    """Compara una contraseña plana con el hash almacenado."""
    try:
        salt, h1 = hashed.split(':')
        return h1 == hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000).hex()
    except: return False

def check_password_strength(pwd):
    """Asegura que el administrador configure una contraseña razonablemente difícil."""
    if len(pwd) < 8: return False, "Mínimo 8 caracteres."
    if not re.search(r"[a-z]", pwd): return False, "Falta minúscula."
    if not re.search(r"[A-Z]", pwd): return False, "Falta mayúscula."
    if not re.search(r"\d", pwd): return False, "Falta número."
    if not re.search(r"[^A-Za-z0-9]", pwd): return False, "Falta símbolo especial."
    return True, ""

def get_current_user(authorization: str = Header(None)):
    """Middleware de FastAPI que inyecta la identidad del usuario verificando su Bearer Token."""
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    with db_read() as conn:
        row = conn.execute("SELECT username FROM sessions WHERE token=? AND expires > ?", (token, time.time())).fetchone()
        if not row: raise HTTPException(status_code=401)
    return row[0]

# --- INICIALIZACIÓN DE TABLAS DE LA APLICACIÓN ---

def init_db():
    """Genera el esquema la primera vez que inicia la aplicación y carga en el diccionario STATE la configuración guardada."""
    os.makedirs("data", exist_ok=True)
    with db_transaction() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, val TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, needs_setup INTEGER, totp_secret TEXT, totp_enabled INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT, expires REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS temp_sessions (token TEXT PRIMARY KEY, username TEXT, expires REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS hw_disks (id TEXT PRIMARY KEY, name TEXT, is_active INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS hw_fans (id TEXT PRIMARY KEY, hwmon_path TEXT, pwm_num TEXT, name TEXT, role TEXT, manual_pct INTEGER, hide_ui INTEGER DEFAULT 0, max_rpm INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS stats (ts DATETIME, t_max REAL, pwm INTEGER, systin REAL, eff REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS disk_history (ts DATETIME, disk TEXT, temp REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS zfs_io (ts DATETIME, read_mb REAL, write_mb REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS fan_baseline (pct INTEGER, rpm INTEGER)")

        if not conn.execute("SELECT 1 FROM users").fetchone():
            conn.execute("INSERT INTO users VALUES (?, ?, 1, '', 0)", ("admin", hash_password("admin")))

        for k, v in conn.execute("SELECT key, val FROM config").fetchall():
            if k in state:
                if isinstance(state[k], bool): state[k] = (v == "True")
                elif isinstance(state[k], int): state[k] = int(v)
                elif isinstance(state[k], float): state[k] = float(v)
                elif k not in ["baseline", "disks_data", "fans_data"]: state[k] = str(v)

def save_config(key, val):
    """Utilidad rápida para hacer persistente una configuración en la DB."""
    try:
        with db_transaction() as conn: conn.execute("INSERT OR REPLACE INTO config (key, val) VALUES (?, ?)", (key, str(val)))
    except Exception as e: print(f"DB Error: {e}")

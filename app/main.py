import os
import time
import secrets
import threading
import base64
import io
import pyotp
import qrcode
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles

# --- IMPORTACIONES MODULARES LOCALES ---
from app.state import state, LANGUAGES, t, init_langs
from app.database import (
    init_db, db_read, db_transaction, get_current_user,
    save_config, hash_password, verify_password, check_password_strength
)
from app.hardware import scan_hardware, run_calibration
from app.alerts import _send_telegram, _send_email
from app.core_logic import control_loop

app = FastAPI()

# --- ARRANQUE DE LA APLICACIÓN (STARTUP SEGURO) ---
@app.on_event("startup")
def start():
    """Se ejecuta una vez cuando el motor FastAPI se inicia. Levanta procesos en background."""
    init_db()
    init_langs()
    # Invocamos al guardián térmico para que corra independientemente en un hilo ("Tirabuzón")
    threading.Thread(target=control_loop, daemon=True).start()

# === [ 1. API: INTERNACIONALIZACIÓN (I18N) ] ===

@app.get("/api/lang/list")
def get_lang_list():
    res = []
    for code, data in LANGUAGES.items(): 
        res.append({"code": code, "name": data.get("_name", code), "flag": data.get("_flag", "🌐")})
    return res

@app.get("/api/lang/{code}")
def get_lang(code: str): 
    return LANGUAGES.get(code, LANGUAGES.get("es", {}))


# === [ 2. API: SEGURIDAD (AUTH & 2FA) ] ===

@app.post("/api/login")
def login(data: dict):
    """Pasarela de inicio de sesión con flujo condicional para 2FA o Setup Inicial"""
    with db_read() as conn:
        user = conn.execute("SELECT password, needs_setup, totp_enabled FROM users WHERE username=?", (data.get("username"),)).fetchone()
        
        # Validación cruda
        if not user or not verify_password(data.get("password"), user[0]): 
            raise HTTPException(status_code=401)
            
        # Reenvío a pantalla de cambio de Password Base
        if user[1]: return {"status": "setup_required"}
        
        # Interceptado por sistema Google Authenticator (TOTP)
        if user[2]:
            temp_token = secrets.token_hex(32)
            with db_transaction() as tw: 
                tw.execute("INSERT INTO temp_sessions VALUES (?, ?, ?)", (temp_token, data.get("username"), time.time() + 300))
            return {"status": "2fa_required", "temp_token": temp_token}
            
        token = secrets.token_hex(32)
        
    with db_transaction() as tw: 
        tw.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, data.get("username"), time.time() + 86400))
    return {"status": "ok", "token": token}

@app.post("/api/login/2fa")
def login_2fa(data: dict):
    with db_read() as conn:
        session = conn.execute("SELECT username FROM temp_sessions WHERE token=? AND expires > ?", (data.get("temp_token"), time.time())).fetchone()
        if not session: raise HTTPException(status_code=401)
        
        secret = conn.execute("SELECT totp_secret FROM users WHERE username=?", (session[0],)).fetchone()[0]
        if not pyotp.TOTP(secret).verify(data.get("code")): 
            raise HTTPException(status_code=401)
            
    token = secrets.token_hex(32)
    with db_transaction() as tw:
        tw.execute("DELETE FROM temp_sessions WHERE token=?", (data.get("temp_token"),))
        tw.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, session[0], time.time() + 86400))
    return {"status": "ok", "token": token}

@app.post("/api/setup")
def setup(data: dict):
    """Establece la clave inicial fuerte bloqueando intentos de diccionarios"""
    with db_read() as conn:
        admin = conn.execute("SELECT password FROM users WHERE username=?", (data.get("old_user"),)).fetchone()
        if not admin or not verify_password(data.get("old_pass"), admin[0]): 
            raise HTTPException(status_code=401)
            
    is_valid, msg = check_password_strength(data.get("new_pass"))
    if not is_valid: raise HTTPException(status_code=400, detail=msg)
    
    with db_transaction() as tw:
        tw.execute("DELETE FROM users")
        tw.execute("INSERT INTO users VALUES (?, ?, 0, '', 0)", (data.get("new_user"), hash_password(data.get("new_pass"))))
        tw.execute("DELETE FROM sessions")
    return {"ok": True}

@app.post("/api/user/password")
def change_password(data: dict, token: str = Depends(get_current_user)):
    with db_read() as conn:
        curr = conn.execute("SELECT password FROM users WHERE username=?", (token,)).fetchone()[0]
        if not verify_password(data.get("current_pass"), curr): 
            raise HTTPException(status_code=400, detail="Contraseña actual incorrecta.")
            
    is_valid, msg = check_password_strength(data.get("new_pass"))
    if not is_valid: raise HTTPException(status_code=400, detail=msg)
    
    with db_transaction() as tw:
        tw.execute("UPDATE users SET password=? WHERE username=?", (hash_password(data.get("new_pass")), token))
        tw.execute("DELETE FROM sessions WHERE username=?", (token,))
    return {"ok": True}

@app.get("/api/2fa/status")
def get_2fa_status(u: str = Depends(get_current_user)):
    with db_read() as conn: 
        enabled = conn.execute("SELECT totp_enabled FROM users WHERE username=?", (u,)).fetchone()[0]
    return {"enabled": bool(enabled)}

@app.post("/api/2fa/generate")
def generate_2fa(u: str = Depends(get_current_user)):
    secret = pyotp.random_base32()
    with db_transaction() as tw: 
        tw.execute("UPDATE users SET totp_secret=? WHERE username=?", (secret, u))
        
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=u, issuer_name="ZFS Guardian")
    qr = qrcode.make(uri)
    buf = io.BytesIO()
    qr.save(buf, format='PNG')
    return {"secret": secret, "qr_b64": base64.b64encode(buf.getvalue()).decode('utf-8')}

@app.post("/api/2fa/enable")
def enable_2fa(data: dict, u: str = Depends(get_current_user)):
    with db_read() as conn: 
        secret = conn.execute("SELECT totp_secret FROM users WHERE username=?", (u,)).fetchone()[0]
    if pyotp.TOTP(secret).verify(data.get("code")):
        with db_transaction() as tw: 
            tw.execute("UPDATE users SET totp_enabled=1 WHERE username=?", (u,))
        return {"ok": True}
    raise HTTPException(status_code=400, detail="Código incorrecto")

@app.post("/api/2fa/disable")
def disable_2fa(u: str = Depends(get_current_user)):
    with db_transaction() as tw: 
        tw.execute("UPDATE users SET totp_enabled=0, totp_secret='' WHERE username=?", (u,))
    return {"ok": True}


# === [ 3. API: CONFIGURACIÓN MÚLTIPLE (HARDWARE Y LOGICA) ] ===

@app.get("/api/hardware/scan")
def get_hardware(token: str = Depends(get_current_user)):
    disks, fans, temps = scan_hardware()
    with db_read() as conn:
        saved_d = {r[0]: {"name": r[1], "active": bool(r[2])} for r in conn.execute("SELECT id, name, is_active FROM hw_disks").fetchall()}
        saved_f = {r[0]: {"name": r[1], "role": r[2], "pct": r[3], "hide": bool(r[4]), "max": r[5]} for r in conn.execute("SELECT id, name, role, manual_pct, hide_ui, max_rpm FROM hw_fans").fetchall()}
        
    for d in disks:
        d["saved_name"] = saved_d.get(d["id"], {}).get("name", "")
        d["is_active"] = saved_d.get(d["id"], {}).get("active", False)
    for f in fans:
        s_f = saved_f.get(f["id"], {})
        f["saved_name"] = s_f.get("name", "")
        f["role"] = s_f.get("role", "monitor"); f["pct"] = s_f.get("pct", 50)
        f["hide_ui"] = s_f.get("hide", False); f["max_rpm"] = s_f.get("max", "")
        
    return {"disks": disks, "fans": fans, "temps": temps, "ambient_sensor": state["ambient_sensor_path"], "smart_life_years": state.get("smart_life_years", 10)}

@app.post("/api/hardware/save")
def save_hardware(data: dict, token: str = Depends(get_current_user)):
    try:
        with db_transaction() as conn:
            existing_pct = {r[0]: r[1] for r in conn.execute("SELECT id, manual_pct FROM hw_fans").fetchall()}
            if "disks" in data:
                conn.execute("DELETE FROM hw_disks")
                for d in data["disks"]: 
                    conn.execute("INSERT INTO hw_disks VALUES (?, ?, ?)", (d["id"], d["name"], 1 if d["active"] else 0))
            if "fans" in data:
                conn.execute("DELETE FROM hw_fans")
                for f in data["fans"]:
                    max_rpm = int(f.get("max_rpm", 0)) if f.get("max_rpm") else 0
                    conn.execute("INSERT INTO hw_fans VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f["id"], f["hwmon_path"], f["pwm_num"], f["name"], f["role"], existing_pct.get(f["id"], 50), 1 if f.get("hide_ui") else 0, max_rpm))
            if "ambient_sensor" in data:
                state["ambient_sensor_path"] = data["ambient_sensor"]
                conn.execute("INSERT OR REPLACE INTO config (key, val) VALUES (?, ?)", ("ambient_sensor_path", data["ambient_sensor"]))
            if "smart_life_years" in data and data["smart_life_years"] is not None:
                try:
                    state["smart_life_years"] = int(data["smart_life_years"])
                    conn.execute("INSERT OR REPLACE INTO config (key, val) VALUES (?, ?)", ("smart_life_years", str(state["smart_life_years"])))
                except: pass
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/hardware/identify")
def identify_fan(data: dict, token: str = Depends(get_current_user)):
    """Hace girar un ventilador desconocido al 100% durante 15 segundos para que el usuario oiga cuál es."""
    path, en_path = f"{data['hwmon']}/pwm{data['pwm']}", f"{data['hwmon']}/pwm{data['pwm']}_enable"
    try: 
        open(en_path, "w").write("1")
        open(path, "w").write("255")
        threading.Thread(target=lambda: (time.sleep(15), open(path, "w").write("128"))).start()
    except: return {"ok": False}
    return {"ok": True}

@app.post("/api/set")
def set_params(data: dict, token: str = Depends(get_current_user)):
    """Inyector de diccionario directo para Modos y Switches booleanos"""
    for k in ["mode", "failsafe_enabled", "boost_enabled", "boost_threshold", "language"]:
        if k in data: 
            state[k] = data[k]
            save_config(k, state[k])
            
    if "fan_manual" in data:
        fid, pct = data["fan_manual"]["id"], data["fan_manual"]["pct"]
        with db_transaction() as conn: 
            conn.execute("UPDATE hw_fans SET manual_pct=? WHERE id=?", (pct, fid))
    return {"ok": True}

@app.post("/api/purge")
def trigger_purge(token: str = Depends(get_current_user)):
    """Limpieza temporal de filtros antipolvo forzada por usuario (60 segundos PWM 100%)"""
    if not state["purge_active"]: 
        state["purge_active"] = True
        state["purge_end"] = time.time() + 60
    return {"ok": True}

@app.post("/api/calibrate")
def trigger_calibrate(token: str = Depends(get_current_user)):
    if not state["calibrating"]: 
        threading.Thread(target=run_calibration, daemon=True).start()
    return {"ok": True}


# === [ 4. API: NOTIFICACIONES (ALERTAS & TEST) ] ===

@app.get("/api/config/alerts")
def get_alerts_config(token: str = Depends(get_current_user)):
    """Devuelve la configuración con las contraseñas anonimizadas para la UI"""
    tg_tok = state.get("telegram_token", "")
    masked_tg = f"••••••••••••••••{tg_tok[-4:]}" if len(tg_tok) > 4 else (f"••••{tg_tok[-2:]}" if tg_tok else "")
    return {
        "telegram_token": masked_tg,
        "telegram_chat_id": state.get("telegram_chat_id", ""),
        "smtp_server": state.get("smtp_server", ""),
        "smtp_port": state.get("smtp_port", 587),
        "smtp_user": state.get("smtp_user", ""),
        "smtp_dest": state.get("smtp_dest", ""),
        "smtp_tls": state.get("smtp_tls", "starttls"),
        "smtp_pass": "••••••••" if state.get("smtp_pass") else ""
    }

@app.post("/api/config/telegram")
def save_tg_config(data: dict, token: str = Depends(get_current_user)):
    if "telegram_token" in data:
        tk = data["telegram_token"].strip()
        if tk and not tk.startswith("••••"): 
            state["telegram_token"] = tk; save_config("telegram_token", tk)
        elif tk == "": 
            state["telegram_token"] = ""; save_config("telegram_token", "")
    if "telegram_chat_id" in data:
        state["telegram_chat_id"] = data["telegram_chat_id"].strip(); save_config("telegram_chat_id", state["telegram_chat_id"])
    return {"ok": True}

@app.post("/api/config/telegram/test")
def test_tg(token: str = Depends(get_current_user)):
    threading.Thread(target=lambda: _send_telegram(t("sys_test_tg")), daemon=True).start()
    return {"ok": True}

@app.post("/api/config/email")
def save_email_config(data: dict, token: str = Depends(get_current_user)):
    for k in ["smtp_server", "smtp_port", "smtp_user", "smtp_dest", "smtp_tls"]:
        if k in data: 
            state[k] = data[k]; save_config(k, data[k])
    if "smtp_pass" in data:
        p = data["smtp_pass"].strip()
        if p and not p.startswith("••••"): 
            state["smtp_pass"] = p; save_config("smtp_pass", p)
        elif p == "": 
            state["smtp_pass"] = ""; save_config("smtp_pass", "")
    return {"ok": True}

@app.post("/api/config/email/test")
def test_email(token: str = Depends(get_current_user)):
    threading.Thread(target=lambda: _send_email(t("sys_test_em_sub"), t("sys_test_em_body")), daemon=True).start()
    return {"ok": True}


# === [ 5. API: LECTURAS VISUALES / FRONTEND ] ===

@app.get("/api/disks_summary")
def get_disks_summary(hours: int = 24, token: str = Depends(get_current_user)):
    sum_data = []
    cutoff = datetime.now() - timedelta(hours=hours)
    years = state.get("smart_life_years", 10)
    hours_per_pct = (years * 8760) / 100.0 if years > 0 else 876
    
    with db_read() as conn:
        for d_id, d in state["disks_data"].items():
            r = conn.execute("SELECT MIN(temp), MAX(temp), AVG(temp) FROM disk_history WHERE disk=? AND ts>?", (d_id, cutoff)).fetchone()
            
            # Si es NVMe / SSD, usamos su salud nativa. Si es HDD clásico, usamos desgaste de motor.
            if d.get('flash_health') is not None:
                life = d['flash_health']
            else:
                life = max(0, round(100 - (d.get('hours', 0) / hours_per_pct), 1))
            sum_data.append({
                "sn": d["name"], "current": d["temp"], "dev": d.get('deviation', 0.0), 
                "min24": round(r[0],1) if r[0] else "--", 
                "max24": round(r[1],1) if r[1] else "--", 
                "avg24": round(r[2],1) if r[2] else "--", 
                "life": life, "written": d.get('written', 0)
            })
    return sum_data

@app.get("/api/history")
def get_history(hours: int = 24, token: str = Depends(get_current_user)):
    """Sirve las matrices pre-cocinadas para que Chart.JS en el Frontend reaccione de inmediato"""
    cutoff = datetime.now() - timedelta(hours=hours)
    with db_read() as conn:
        data = conn.execute("SELECT ts, t_max, pwm FROM stats WHERE ts > ? ORDER BY ts ASC", (cutoff,)).fetchall()
        zdata = conn.execute("SELECT ts, read_mb, write_mb FROM zfs_io WHERE ts > ? ORDER BY ts ASC", (cutoff,)).fetchall()
        
        # Diezmo (Muestreo Dinámico): Evita matar navegadores viejos. Reduce a 1000 Puntos máximo.
        lbls = [str(r[0])[:19] for r in data[::max(1, len(data)//1000)]]
        zlbls = [str(r[0])[:19] for r in zdata[::max(1, len(zdata)//1000)]]
        return {
            "labels": lbls, 
            "temps": [r[1] for r in data[::max(1, len(data)//1000)]], 
            "pwms": [r[2] for r in data[::max(1, len(data)//1000)]], 
            "zfs_labels": zlbls, 
            "zfs_read": [r[1] for r in zdata[::max(1, len(zdata)//1000)]], 
            "zfs_write": [r[2] for r in zdata[::max(1, len(zdata)//1000)]]
        }

@app.get("/api/status")
def get_status(token: str = Depends(get_current_user)): 
    return {**state, "purge_remaining": max(0, int(state["purge_end"] - time.time())) if state["purge_active"] else 0}


# --- MOTOR STÁTICO FINAL (EL INDEX.HTML WEB GUI) ---
app.mount("/", StaticFiles(directory="static", html=True), name="static")

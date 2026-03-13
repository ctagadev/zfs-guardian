import os
import json
import shutil

LANG_DIR_RUNTIME = "data/lang"
LANG_DIR_SOURCE = "app/lang"

LANGUAGES = {}

# --- ESTADO GLOBAL (Diccionarios compartidos entre módulos) ---
# Extraer el estado (variables globales) a su propio módulo 'state' evita importaciones circulares en el futuro.
state = {
    "language": "", "mode": "aggressive", "failsafe_enabled": True, "failsafe_active": False,
    "boost_enabled": True, "boost_active": False, "boost_cooldown": 0, "boost_threshold": 100,
    "current_max": 0, "delta": 0, "systin": 25.0, "efficiency": 0,
    "io_read_mbs": 0, "io_write_mbs": 0, "active_disks_count": 0,
    "last_smart_pwm": 60, "disks_data": {}, "fans_data": {},
    "smart_life_years": 10, "telegram_token": "", "telegram_chat_id": "", "ambient_sensor_path": "",
    "smtp_server": "", "smtp_port": 587, "smtp_user": "", "smtp_pass": "", "smtp_dest": "", "smtp_tls": "starttls",
    "purge_active": False, "purge_end": 0, "calibrating": False, "calibrating_pwm": 0,
    "baseline": {"50": 1386, "75": 1944, "100": 2500}
}

last_io_sectors = {}
alerts_sent = {"overheat": False, "boost": False, "failsafe": False}

def init_langs():
    """Lee todos los archivos .json localizados en la carpeta de idiomas de Runtime (Data) y los expone en la API"""
    global LANGUAGES
    LANGUAGES.clear()
    
    if not os.path.exists(LANG_DIR_RUNTIME):
        os.makedirs(LANG_DIR_RUNTIME, exist_ok=True)
        print(f"[*] Directorio de idiomas creado en '{LANG_DIR_RUNTIME}'.")

    # 1. Cargamos TODOS los idiomas empaquetados en el Kernel (Container) y sacamos copias de plantilla (EN/ES)
    if os.path.exists(LANG_DIR_SOURCE):
        for f in os.listdir(LANG_DIR_SOURCE):
            if f.endswith(".json"):
                code = f.replace(".json", "")
                src = os.path.join(LANG_DIR_SOURCE, f)
                try:
                    with open(src, "r", encoding="utf-8") as file:
                        LANGUAGES[code] = json.load(file)
                except Exception as e:
                    print(f"Error cargando idioma de fábrica {f}: {e}")
                
                # Exportamos al disco físico solo las plantillas principales para no ensuciar
                if f in ["es.json", "en.json"]:
                    dst = os.path.join(LANG_DIR_RUNTIME, f)
                    if not os.path.exists(dst):
                        try: shutil.copy2(src, dst)
                        except: pass

    # 2. Cargamos los Custom (Sobrescribiendo o añadiendo nuevos desde /data/lang)
    if os.path.exists(LANG_DIR_RUNTIME):
        for f in os.listdir(LANG_DIR_RUNTIME):
            if f.endswith(".json"):
                code = f.replace(".json", "")
                try:
                    with open(os.path.join(LANG_DIR_RUNTIME, f), "r", encoding="utf-8") as file:
                        LANGUAGES[code] = json.load(file)
                except Exception as e:
                    print(f"Error cargando idioma custom del usuario {f}: {e}")

def t(key, **kwargs):
    """Función de traducción rápida utilizada por el Backend de Python"""
    lang = state.get("language")
    if not lang or lang not in LANGUAGES:
        lang = "en" if "en" in LANGUAGES else "es"
    msg = LANGUAGES.get(lang, {}).get(key, key)
    return msg.format(**kwargs) if kwargs else msg

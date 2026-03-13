import time
import threading
import subprocess
import json
import os
from datetime import datetime, timedelta

from app.state import state, t, alerts_sent
import app.state as app_state
from app.database import db_read, db_transaction
from app.hardware import read_io
from app.alerts import send_alert

# --- EL CEREBRO TÉRMICO Y CONTROL BUCLE (CORE LOGIC) ---
# Este loop asíncrono monitoriza Smart, Cargas de trabajo de ZFS y gestiona la curva de ventilación local.

def control_loop():
    iteration = 0
    while True:
        now = datetime.now()
        with db_read() as conn:
            active_disks = conn.execute("SELECT id, name FROM hw_disks WHERE is_active=1").fetchall()
            configured_fans = conn.execute("SELECT id, hwmon_path, pwm_num, name, role, manual_pct, hide_ui, max_rpm FROM hw_fans").fetchall()

        disk_paths = {d[0]: f"/dev/disk/by-id/{d[0]}" for d in active_disks}
        # 1) PREDICTIVO ZFS: Miramos antes que nadie si la carga I/O ha subido masivamente
        r_mbs, w_mbs, per_disk_io = read_io(disk_paths)
        total_io = r_mbs + w_mbs

        # 2) SENSOR BASE: Recuperar la temperatura puramente ambiental
        systin = 25.0
        if state["ambient_sensor_path"] and os.path.exists(state["ambient_sensor_path"]):
            try: systin = int(open(state["ambient_sensor_path"]).read().strip()) / 1000.0
            except: pass

        # 3) ANÁLISIS DE SMART (Temperaturas / Horas de Encendido / Terabytes Escritos)
        temps = {}
        for d_id, name in active_disks:
            try:
                # Usamos smartctl sin formato ruidoso a formato limpio JSON local. 'standby' evita despertar discos dormidos (Spin-Down)
                res = subprocess.run(['smartctl', '-j', '-n', 'standby', '-A', f"/dev/disk/by-id/{d_id}"], capture_output=True, text=True, timeout=5)
                data = json.loads(res.stdout)
                t_val = data.get('temperature', {}).get('current', 0)
                
                # Extracción Adaptativa: HDD Clásico (ATA) vs. Sólido (NVMe / SATA SSD)
                nvme_log = data.get('nvme_smart_health_information_log')
                if nvme_log:
                    h = nvme_log.get('power_on_hours', 0)
                    wr = round((nvme_log.get('data_units_written', 0) * 512000) / (1024**4), 2)
                    flash_health = 100 - nvme_log.get('percentage_used', 0)
                else:
                    h = sum([a['raw']['value'] for a in data.get('ata_smart_attributes', {}).get('table', []) if a['id']==9] + [0])
                    wr = sum([round((a['raw']['value']*512)/(1024**4),2) for a in data.get('ata_smart_attributes', {}).get('table', []) if a['id']==241] + [0])
                    
                    # Intentamos buscar atributos de desgaste flash (SATA SSDs)
                    ssds_life_attrs = [a for a in data.get('ata_smart_attributes', {}).get('table', []) if a['id'] in (231, 202, 177, 233)]
                    if ssds_life_attrs:
                        # La mayoría de marcas (Crucial, Kingston, Samsung) usan el valor normalizado ('value') de 0 a 100
                        flash_health = ssds_life_attrs[0].get('value', 100)
                    else:
                        flash_health = None
                
                if t_val > 0: 
                    d_io = per_disk_io.get(d_id, {"r": 0, "w": 0})
                    temps[d_id] = {"name": name, "temp": t_val, "hours": h, "written": wr, "deviation": 0.0, "r_mb": d_io["r"], "w_mb": d_io["w"], "flash_health": flash_health}
            except: pass
            
            # --- ALERTA: MUERTE SÚBITA O DESCONEXIÓN DE DISCO (LOST DISK) ---
            lost_k = f"lost_{d_id}"
            if d_id not in temps:
                if not alerts_sent.get(lost_k):
                    send_alert(t("sys_disk_lost_sub"), t("sys_disk_lost_sub"), t("sys_disk_lost_body", disk=name))
                    alerts_sent[lost_k] = True
            else: alerts_sent[lost_k] = False

        t_max, t_min, delta = 0, 0, 0
        smart_pwm = state.get("last_smart_pwm", 85) # Mantenemos inercia si fallan lecturas y el Fail-Safe está apagado
        state["failsafe_active"] = False

        # --- A. LÓGICA DE SUPERVIVENCIA EMERGENCIA ---
        # Si de repente todo el /dev desaparece o fallan los discos, forzamos un rescate ciego 80% (Permanente)
        if not temps and len(active_disks) > 0:
            state["failsafe_active"] = True
            smart_pwm = 204 # ~80% de 255
            if not alerts_sent.get("failsafe"):
                send_alert(t("sys_failsafe_sub"), t("sys_failsafe_sub"), t("sys_failsafe_body"))
                alerts_sent["failsafe"] = True
                
        elif temps:
            alerts_sent["failsafe"] = False
            
            # --- B. LÓGICA DE ALERTA TEMPRANA "DESVIACIÓN 48H" ---
            try:
                with db_read() as conn:
                    # Traemos la Media Ambiente histórica
                    avg_sys = conn.execute("SELECT AVG(systin) FROM stats WHERE ts > ?", (now - timedelta(hours=48),)).fetchone()
                    avg_sys = avg_sys[0] if avg_sys and avg_sys[0] else systin
                    
                    for d_id, d in temps.items():
                        # Y la comparamos con el propio historial del disco aislado. ¡Si uno vibra se calentará más!
                        avg_tmp = conn.execute("SELECT AVG(temp) FROM disk_history WHERE disk=? AND ts > ?", (d_id, now - timedelta(hours=48))).fetchone()
                        if avg_tmp and avg_tmp[0]: 
                            dev = round(d['temp'] - (avg_tmp[0] + (systin - avg_sys)), 1)
                            d['deviation'] = dev
                            
                            # --- ALERTA: ANOMALÍA TERMODINÁMICA (MOTOR ROZANDO O ASFIXIA) ---
                            anom_k = f"anom_{d_id}"
                            if dev >= 5.0 and not alerts_sent.get(anom_k):
                                send_alert(t("sys_anomaly_sub"), t("sys_anomaly_sub"), t("sys_anomaly_body", disk=d['name'], dev=dev))
                                alerts_sent[anom_k] = True
                            elif dev < 4.0: alerts_sent[anom_k] = False
            except: pass

            vals = [d["temp"] for d in temps.values()]
            t_max, t_min = max(vals), min(vals)
            delta = t_max - t_min

            # Evita avisos de spam y limita alarma Overheat a 1 aviso perenne.
            if t_max >= 45 and not alerts_sent.get("overheat"):
                send_alert(t("sys_overheat_sub", temp=t_max), t("sys_overheat_sub", temp=t_max), t("sys_overheat_body", temp=t_max))
                alerts_sent["overheat"] = True
            elif t_max < 42: 
                alerts_sent["overheat"] = False

            # --- C. ALGORITMO PID TÉRMICO HÍBRIDO ---
            target_t = t_min if state["mode"] == "aggressive_inverse" else t_max
            
            # La fórmula matricial simple: Si llegas a 45ºC = PÁNICO 100%
            calc = 255 if target_t >= 45 else (
                int(120 + (target_t-40)*27) if target_t >= 40 else (
                    # "BLOQUEO DE ESTABILIZACIÓN": Si venimos fuertes de rebote, frenamos la rampa descendente.
                    state["last_smart_pwm"] if state["last_smart_pwm"]>=120 and target_t>38 else (
                        85 if target_t>=35 else 60
                    )
                )
            )

            # Delta Soft mode compensa si hay asfixia en un rack cerrado (Hot-Spots). Multiplica el margen.
            if state["mode"] == "delta_soft": 
                smart_pwm = min(255, calc + (max(0, delta - 3) * 15))
            else: 
                smart_pwm = calc

            # --- D. ALGORITMO I/O "QUORUM BOOST" PREDICTIVO ---
            if state["boost_enabled"]:
                # Si una transferencia brutal activa el Boost Predictivo
                if total_io > state["boost_threshold"]:
                    # Subes las RPM de golpe para ganarles a la "Ley de Fourier" del Calor Metálico. (Adelántate 2 minutos)
                    state["boost_cooldown"] = time.time() + 120
                    if not state["boost_active"]:
                        state["boost_active"] = True
                        send_alert(t("sys_boost_sub", io=total_io), t("sys_boost_sub", io=total_io), t("sys_boost_body", io=total_io))
                elif state["boost_active"] and time.time() > state["boost_cooldown"]:
                    state["boost_active"] = False
                    send_alert(t("sys_boost_end_sub"), t("sys_boost_end_sub"), t("sys_boost_end_body"))

            # Consolidación final del impulso máximo (Predicción ZFS o Calor de Pánico)
            if state["boost_active"] or t_max >= 45: 
                smart_pwm = max(smart_pwm, 150 if t_max < 45 else 255)

        # Purga Manual / Extractor de Polvo temporal por GUI (60 Segundos al 100%)
        if state["purge_active"]:
            if time.time() < state["purge_end"]: smart_pwm = 255
            else: state["purge_active"] = False

        state["last_smart_pwm"] = smart_pwm
        
        # --- E. TRADUCCIÓN A SEÑAL ANALÓGICA / APLICACIÓN ---
        fan_status = {}
        for f_id, hwmon, p_num, name, role, m_pct, hide_ui, max_rpm in configured_fans:
            pwm_path, rpm_path, en_path = f"{hwmon}/pwm{p_num}", f"{hwmon}/fan{p_num}_input", f"{hwmon}/pwm{p_num}_enable"
            
            # Se activa "Modo Control" manual en el chip de placa base
            if role in ["smart", "manual"]:
                try: open(en_path, "w").write("1")
                except: pass

            target_pwm = 0
            if state["calibrating"]: target_pwm = state["calibrating_pwm"]
            elif state["purge_active"] or state["failsafe_active"]: 
                target_pwm = 204 if state["failsafe_active"] else 255
            elif role == "smart": 
                target_pwm = smart_pwm
            elif role == "manual": 
                target_pwm = int((m_pct/100)*255)

            if role in ["smart", "manual"]:
                try: open(pwm_path, "w").write(str(target_pwm))
                except: pass
                
            # Recuperamos información de Encoder Optico (Current RPM)
            rpm = 0
            try: rpm = int(open(rpm_path, "r").read())
            except: pass
            
            # --- ALERTA: ATASCO MECÁNICO (VENTILADOR MUERTO) ---
            jam_k, jam_c = f"jam_{f_id}", f"jam_c_{f_id}"
            if target_pwm > 100 and rpm == 0:
                alerts_sent[jam_c] = alerts_sent.get(jam_c, 0) + 1
                if alerts_sent[jam_c] >= 4 and not alerts_sent.get(jam_k): # Espera 20 segundos de inercia
                    send_alert(t("sys_fan_jam_sub"), t("sys_fan_jam_sub"), t("sys_fan_jam_body", fan=name))
                    alerts_sent[jam_k] = True
            else:
                alerts_sent[jam_c] = 0
                if rpm > 0: alerts_sent[jam_k] = False

            fan_status[f_id] = {
                "name": name, "role": role, "rpm": rpm, 
                "pct": round((target_pwm/255)*100) if role != "monitor" else "--", 
                "target_pwm": target_pwm, "hide_ui": bool(hide_ui), "max_rpm": max_rpm
            }

        # Eficiencia Térmica: Índice creado para ver si hace mucho ruido respecto a lo que enfría
        eff = round((t_max - systin) / (smart_pwm / 255.0), 2) if smart_pwm > 0 else 0
        state.update({"current_max": t_max, "delta": delta, "systin": systin, "efficiency": eff, "io_read_mbs": r_mbs, "io_write_mbs": w_mbs, "disks_data": temps, "fans_data": fan_status})

        if temps:
            with db_transaction() as conn:
                try:
                    conn.execute("INSERT INTO stats VALUES (?, ?, ?, ?, ?)", (now, t_max, smart_pwm, systin, eff))
                    conn.execute("INSERT INTO zfs_io VALUES (?, ?, ?)", (now, r_mbs, w_mbs))
                    for d_id, d in temps.items(): 
                        conn.execute("INSERT INTO disk_history VALUES (?, ?, ?)", (now, d_id, d['temp']))
                except: pass
                
                # Housekeeping: Poda la DB temporal (cada ~500 segundos) de métricas de más de 90 días
                iteration += 1
                if iteration >= 100:
                    conn.execute("DELETE FROM stats WHERE ts < ?", (now - timedelta(days=90),))
                    conn.execute("DELETE FROM zfs_io WHERE ts < ?", (now - timedelta(days=90),))
                    conn.execute("DELETE FROM disk_history WHERE ts < ?", (now - timedelta(days=90),))
                    iteration = 0
                    
        time.sleep(5)

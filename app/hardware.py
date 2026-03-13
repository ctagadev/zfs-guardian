import os
import time
import threading
from app.state import state, t
import app.state as app_state
from app.alerts import send_alert
from app.database import db_read, db_transaction

# --- MÓDULO DE INTERACCIÓN FÍSICA Y DETECCIÓN (EL HARDWARE) ---
# Toda la magia del S.O Linux se encapsula aquí. Desde /proc para IO hasta /sys/class para PWM.

def scan_hardware():
    """Analiza la máquina real mediante /dev/disk y /sys/class/hwmon sin necesidad de agentes externos"""
    disks, fans, temps = [], [], []

    # 1. Búsqueda exhaustiva de discos con identificación única (by-id en Linux)
    seen_realpath = set()
    if os.path.exists('/dev/disk/by-id/'):
        # Ordenamos para dar prioridad a los nombres más legibles (nvme- y ata-) frente a (wwn- o scsi-)
        # Así la deduplicación por hardware físico siempre se queda con el nombre comercial primero.
        archivos = os.listdir('/dev/disk/by-id/')
        archivos.sort(key=lambda x: (not x.startswith('nvme-'), not x.startswith('ata-'), x))

        for f in archivos:
            # Capturamos discos SATA (ata-), NVMe (nvme-), LUNs (wwn-, scsi-), ignorando particiones lógicas (-part)
            if (f.startswith('ata-') or f.startswith('nvme-') or f.startswith('wwn-') or f.startswith('scsi-')) and '-part' not in f: 
                full_path = f"/dev/disk/by-id/{f}"
                try:
                    # udev crea múltiples alias para el mismo disco (ej. nvme-eui... vs nvme-WDC...). 
                    # Resolvemos al nodo físico (/dev/nvme0n1 o /dev/sda) para evitar discos duplicados en la UI.
                    real_path = os.path.realpath(full_path)
                    if real_path not in seen_realpath:
                        seen_realpath.add(real_path)
                        disks.append({"id": f, "path": full_path})
                except Exception:
                    pass

    # 2. Exploración del subsistema HWMON para Placas Base y Controladoras IT Mode
    for i in range(15):
        base = f"/sys/class/hwmon/hwmon{i}"
        if os.path.exists(base):
            chip_name = open(f"{base}/name").read().strip() if os.path.exists(f"{base}/name") else f"hwmon{i}"
            
            # Buscando conectores "PWM" en cada hwmon (usualmente en chips ITE/Nuvoton)
            for j in range(1, 10):
                if os.path.exists(f"{base}/pwm{j}"): 
                    fans.append({"id": f"hwmon{i}_pwm{j}", "hwmon_path": base, "pwm_num": str(j), "chip": chip_name})
            
            # Leyendo sensores puramente térmicos ambientales (SYSTIN / CPUTIN, etc.)
            for j in range(1, 15):
                t_path = f"{base}/temp{j}_input"
                if os.path.exists(t_path):
                    try:
                        # Convertimos miliGrados a Celsius estándar
                        val = int(open(t_path).read().strip()) / 1000.0
                        label = open(f"{base}/temp{j}_label").read().strip() if os.path.exists(f"{base}/temp{j}_label") else f"Temp {j}"
                        temps.append({"path": t_path, "label": f"{chip_name} - {label}", "val": val})
                    except: pass
    return disks, fans, temps

def read_io(active_disk_paths):
    """
    Monitor de Operaciones ZFS en el Kernel.
    Calcula dinámicamente cuántos Megabytes se mueven en /proc/diskstats cada vez que se llama.
    """
    mapping = {os.path.realpath(p).split('/')[-1]: d_id for d_id, p in active_disk_paths.items() if os.path.exists(p)}
    current = {}
    
    try:
        # Aquí se encuentra el corazón de la monitorización Predictiva del I/O (Lectura ultra-ligera en memoria)
        for line in open("/proc/diskstats").readlines():
            parts = line.split()
            # Intercepta únicamente los discos que le interesan al Pool
            if parts[2] in mapping: 
                current[mapping[parts[2]]] = {'r': int(parts[5]), 'w': int(parts[9])}
    except: pass
    
    rmbs = wmbs = 0
    per_disk = {}
    # Compara contra la anterior captura de sectores leídos/escritos
    if app_state.last_io_sectors:
        for d_id, secs in current.items():
            prev = app_state.last_io_sectors.get(d_id, {'r': secs['r'], 'w': secs['w']})
            # Convertimos "Sectores de 512 bytes" en Megabytes
            r_mb = (max(0, secs['r'] - prev['r']) * 512) / 15728640
            w_mb = (max(0, secs['w'] - prev['w']) * 512) / 15728640
            rmbs += r_mb
            wmbs += w_mb
            per_disk[d_id] = {"r": round(r_mb, 2), "w": round(w_mb, 2)}
            
    # Guardamos estado global de RAM actual para la próxima iteración.
    app_state.last_io_sectors = current
    return round(rmbs, 2), round(wmbs, 2), per_disk

def run_calibration():
    """
    Laboratorio: Empuja mecánicamente los ventiladores controlables a 50%, 75% y 100%.
    Luego guarda la estabilización de RPM para crear la "Health Baseline" del Motor.
    """
    state["calibrating"] = True
    send_alert(t("sys_calib_start_sub"), t("sys_calib_start_sub"), t("sys_calib_start_body"))
    baseline = {}
    
    with db_read() as conn: 
        configured_fans = conn.execute("SELECT hwmon_path, pwm_num FROM hw_fans WHERE role IN ('smart', 'manual')").fetchall()
        
    for pct in range(0, 101, 10):
        pwm = int((pct / 100) * 255)
        state["calibrating_pwm"] = pwm
        
        # 1. Impulsa motores
        for hwmon, p_num in configured_fans:
            try: open(f"{hwmon}/pwm{p_num}", "w").write(str(pwm))
            except: pass
            
        # 2. Espera 20 Segundos (Inercia del Impulsor)
        time.sleep(20)
        rpm = 0
        
        # 3. Mide la punta (Máxima Estabilidad)
        for hwmon, p_num in configured_fans:
            try: rpm = max(rpm, int(open(f"{hwmon}/fan{p_num}_input", "r").read()))
            except: pass
        baseline[str(pct)] = rpm
        
    # Y lo almacena de forma persistente en BBDD
    with db_transaction() as conn:
        conn.execute("DELETE FROM fan_baseline")
        for p, r in baseline.items(): 
            conn.execute("INSERT INTO fan_baseline VALUES (?, ?)", (int(p), r))
            
    state["baseline"] = baseline
    state["calibrating"] = False

    msg_end = t("sys_calib_end", rpm100=baseline.get('100', 0))
    send_alert(msg_end, t("sys_calib_start_sub"), msg_end)

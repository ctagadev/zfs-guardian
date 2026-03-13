# 🛡️ ZFS Guardian

*🇬🇧 [English version here](readme.en.md)*

**El sistema definitivo de refrigeración inteligente y predictiva para servidores de almacenamiento y pools ZFS.**

En la mayoría de servidores y NAS caseros, las placas base controlan los ventiladores basándose en la temperatura de la CPU. Sin embargo, en un servidor de almacenamiento, la CPU puede estar al 5% de uso (fría) mientras los discos duros están realizando un *scrub* masivo de ZFS y literalmente quemándose.

**ZFS Guardian** toma el control total: escanea tu hardware, lee las temperaturas directamente del S.M.A.R.T. de los discos, monitoriza el tráfico I/O del sistema de archivos y ajusta dinámicamente los ventiladores PWM del chasis para mantener tus datos a salvo.

---

## ✨ Características Principales

### 🧠 Inteligencia Térmica y Algoritmos

* **Múltiples Algoritmos ZFS:** Selecciona entre el modo *Agresivo* (sigue al disco más caliente), *Inverso* (ideal para silencio con flujos de aire perfectos) o *Delta Soft* (híbrido).
* **Pre-enfriamiento Predictivo ZFS:** ZFS Guardian no espera a que los discos se calienten. Monitoriza el I/O global (MB/s). Si detecta transferencias masivas (>100 MB/s), acelera los ventiladores anticipadamente creando un colchón de aire frío antes de que suba la temperatura.
* **Inercia Térmica:** Los discos son bloques de metal que tardan en enfriarse. El sistema incluye bloqueos temporales para evitar "rebotes" y cambios bruscos de RPM en los ventiladores, alargando la vida de los motores.
* **Cálculo de Eficiencia:** Compara la temperatura ambiente (mediante un sensor de la placa base) con el esfuerzo del ventilador para avisarte si tus filtros de polvo están obstruidos.

### 🛠️ Hardware Modular y Dinámico

* **Escáner Automático:** Detecta automáticamente tus discos duros (`/dev/disk/by-id`) y todos los controladores PWM de tu placa base (`hwmon`).
* **Asignación de Roles:** Define qué ventiladores son *Inteligentes* (controlados por el algoritmo), cuáles son *Manuales* (fijos mediante un slider en la web) y cuáles ignorar.
* **Laboratorio de Calibración:** Pon a prueba tus ventiladores. El sistema fuerza progresivamente el motor de 10% en 10% hasta crear un perfil logarítmico de revoluciones en la BBDD, calculando en tiempo real la salud del motor mediante desgaste óptico.

### 🚨 Seguridad Activa y Notificaciones (Inteligencia Perimetral)

* **Alarma de Fricción Mecánica (Fan Jam):** Si ZFS Guardian inyecta un PWM de movimiento pero el sensor de RPM devuelve "0" por 20 segundos, detecta un bloqueo o cable atascado y dispara alarma crítica.
* **Anomalía Térmica Localizada (Desviación 48H):** Compara el calor de un disco consigo mismo usando los últimos 2 días de historial. Si un disco en su ranura sube de repente +5ºC respecto a su media compensada con la temperatura ambiental, te avisa por fricción o tapón de polvo mucho antes de llegar a los umbrales de sobrecalentamiento absolutos.
* **Detección de "Ghost Disk":** Si el SO o el cable SAS fallan silenciosamente, detecta los huecos en vacío dentro de su bucle general y notifica la pérdida.
* **Modo Vigilante (Fail-Safe Permanente):** Si se pierde por completo la matriz de discos, el daemon entra en pánico asumiendo el peor caso y bloquea permanentemente las turbinas PWM principales al 80% fijo de emergencia militar.
* **Autenticación en 2 Pasos (2FA):** Protege el acceso a la WebGUI integrándolo con Authy o Google Authenticator mediante TOTP.
* **Base de Datos Zero-Lag:** Utiliza SQLite en modo WAL (Write-Ahead Logging) permitiendo lecturas y escrituras ultrarrápidas y concurrentes sin bloqueos en la interfaz web.
* **Anonimización de UI:** Los tokens de Telegram y contraseñas SMTP se enmascaran en la WebGUI (`••••••••`) para evitar miradas indiscretas si compartes pantalla.

### 🌍 Internacionalización (i18n)

* **Soporte Multilingüe:** La app genera automáticamente archivos `.json` de idioma en el volumen de datos. Traducir la app a otro idioma es tan sencillo como duplicar el archivo `en.json`, renombrarlo a `fr.json` y traducir los textos. ¡La web actualizará los idiomas al vuelo sin recargar!

### 📊 Monitorización Visual

* **Gráficas en Tiempo Real:** Interfaz moderna con `Chart.js` que dibuja el histórico de temperaturas, RPMs y tráfico de lectura/escritura ZFS.
* **Salud S.M.A.R.T.:** Monitoriza la longevidad de tu matriz adaptándose a la tecnología física:
  * **NVMe:** Extrae nativamente su desgaste flash (*Percentage Used* / TBW).
  * **SATA SSD:** Busca e interpreta el ciclo de borrado según el fabricante (IDs `231`, `202`, `177`, `233`) para unidades Crucial, Kingston, Samsung, etc.
  * **HDD Mecánico:** Estima la salud mediante heurística comparando las horas de motor de giro continuo (*Power-On Hours*) contra tu regla de vida útil esperada.
---

## 🚀 Instalación (Docker)

**Por qué se requieren permisos elevados**

ZFS Guardian se ejecuta como un contenedor Docker, pero necesita acceso de bajo nivel al sistema para realizar la monitorización de hardware y el control de los ventiladores.

Por ello, se requieren los siguientes permisos:

`privileged: true`
Necesario para interactuar directamente con los dispositivos de almacenamiento a través de `smartctl` y leer datos S.M.A.R.T.
Esto permite que la aplicación acceda a la información de temperatura de los discos y otras métricas de hardware que no están disponibles con el aislamiento estándar de un contenedor.

`/sys/class/hwmon:rw`
Necesario para controlar los headers de ventiladores de la placa base mediante la interfaz `hwmon` de Linux.
La aplicación escribe directamente los valores PWM en los controladores de los ventiladores para ajustar dinámicamente la refrigeración.

Montar el directorio en solo lectura (`ro`) solo permitiría la monitorización pasiva y evitaría que ZFS Guardian controlara activamente la velocidad de los ventiladores.

### Opción A: Imagen Pre-compilada (Recomendado)

Si solo quieres usar la aplicación sin modificar el código fuente, crea una carpeta vacía, añade el siguiente `docker-compose.yml` y levántalo:

```yaml
services:
  zfs-guardian:
    image: ctagadev/zfs-guardian:latest
    container_name: zfs-guardian
    privileged: true
    restart: unless-stopped
    ports:
      - "48080:8000"
    volumes:
      - ./data:/app/data                        # Guarda la BD, configs e idiomas
      - /dev/disk/by-id:/dev/disk/by-id:ro      # Necesario para mapeo persistente ZFS
      - /sys/class/hwmon:/sys/class/hwmon:rw    # Necesario para inyectar voltaje PWM e i2c
    environment:
      - TZ=Europe/Madrid
```

Luego inicia el contenedor:
```bash
docker compose up -d
```

### Opción B: Construcción desde el Código Fuente (Desarrolladores)

Si prefieres compilar la aplicación tú mismo o modificar su código base, debes clonar el repositorio completo primero:

```bash
git clone https://github.com/ctagadev/zfs-guardian.git
cd zfs-guardian
```

Y luego utilizar el `docker-compose.yml` incluido en la raíz (el cual incluye la etiqueta `build: .`), ejecutando:
```bash
docker compose up -d --build
```

---

Accede a la interfaz web en: `http://TU_IP:48080`

---

## ⚙️ Primeros Pasos y Configuración

1. **Setup Inicial:** Al entrar por primera vez, inicia sesión con las credenciales por defecto (`admin` / `admin`). El sistema te pedirá inmediatamente que cambies y crees una contraseña fuerte (requiere mayúscula, minúscula, número y símbolo).
2. **Mapeo de Hardware:** Ve a la pestaña **Hardware**.
* Marca las casillas de los discos físicos que pertenecen a tu pool ZFS. (Ignora unidades de Caché/Sistema si no quieres que el Predictivo ZFS acelere el chasis por movimientos menores).
* Identifica tus ventiladores (usa el botón **🔊 TEST** que inyectará un ciclo de 15 segundos al 100% para que detectes acústicamente cuál es de la caja).
* Asígnales un nombre (ej. "Frontal Entrada") y un rol (*Inteligente*, *Manual* o *Ignorado*).
* Selecciona el sensor ambiental de tu placa base (normalmente `SYSTIN`).


3. **Guardar y Listo:** Al guardar, ZFS Guardian empezará a gestionar la refrigeración de tu servidor en el acto.

---

## 🔔 Notificaciones

Puedes configurar ZFS Guardian para que te avise en caso de sobrecalentamiento, activación del modo Fail-Safe o activaciones del modo Predictivo.

* **Telegram:** Solo necesitas el Token de un bot creado con *BotFather* y tu Chat ID.
* **Email (SMTP):** Soporta envío directo por correo (TLS, STARTTLS o texto plano).

---

## 🛠️ Stack Tecnológico

* **Backend:** Python 3 + FastAPI (Servidor asíncrono y threadpool).
* **Base de Datos:** SQLite3 (Modo WAL habilitado para cero bloqueos).
* **Frontend:** HTML5, CSS3, JavaScript puro (Vanilla JS), sin dependencias pesadas. Gráficas impulsadas por `Chart.js`.
* **Seguridad Frontend/Backend:** Tokens de sesión rotativos, Hashing SHA256 con Salt dinámico, integración PyOTP para 2FA.

---

## 🤝 Contribuir (Idiomas)

¿Quieres añadir tu idioma?

1. Ve a la carpeta mapeada en tu host: `./data/lang/`
2. Copia el archivo `en.json` y renómbralo con tu código de país (ej. `it.json`).
3. Abre el archivo, cambia la variable `"_name"` a tu idioma (ej. `"Italiano"`), la variable `"_flag"` a tu bandera (`"🇮🇹"`) y traduce los valores.
4. Reinicia la web y ¡tu idioma aparecerá en el menú desplegable automáticamente!
5. **(Opcional)** Abre un *Pull Request* en este repositorio con tu archivo `.json` para que lo añadamos de forma nativa a la app. ¡Gracias por colaborar!

---

## ⚠️ Disclaimer / Advertencia

*Este software interactúa directamente con los controladores PWM a bajo nivel del kernel de Linux (`/sys/class/hwmon`). Una mala configuración del hardware del host o de la BIOS podría resultar en ventiladores apagados. El creador de este software no se hace responsable de posibles daños por sobrecalentamiento en tu hardware. Activa siempre las protecciones de apagado por temperatura en la BIOS de tu placa base.*

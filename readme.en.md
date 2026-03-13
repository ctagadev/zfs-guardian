# 🛡️ ZFS Guardian

*🇪🇸 [Versión en español aquí](readme.md)*

**The ultimate smart and predictive cooling system for storage servers and ZFS pools.**

In most home servers and NAS environments, motherboards control fans based solely on CPU temperature. However, in a storage server, the CPU might idle at 5% (running cool) while the hard drives are performing a massive ZFS *scrub* and literally roasting.

**ZFS Guardian** takes total control: it scans your hardware, reads temperatures directly from the disks' S.M.A.R.T. data, monitors filesystem I/O traffic, and dynamically adjusts the chassis PWM fans to keep your data safe.

---

## ✨ Key Features

### 🧠 Thermal Intelligence & Algorithms

* **Multiple ZFS Algorithms:** Choose between *Aggressive* mode (follows the hottest drive), *Reverse* (ideal for silence under perfect airflow), or *Delta Soft* (hybrid).
* **Predictive ZFS Pre-cooling:** ZFS Guardian doesn't wait for your drives to get hot. It monitors global I/O (MB/s). If it detects massive transfers (>100 MB/s), it spins up the fans preemptively, creating a cold air cushion before temperatures rise.
* **Thermal Inertia:** Drives are metal blocks that take time to cool down. The system uses grace periods to prevent "bouncing" and sudden RPM changes, extending fan motor lifespan.
* **Efficiency Calculation:** Compares the ambient temperature (via a motherboard sensor) with fan effort to warn you if your dust filters are clogged.

### 🛠️ Modular & Dynamic Hardware

* **Auto-Scanner:** Automatically detects your hard drives (`/dev/disk/by-id`) and every PWM controller on your motherboard (`hwmon`).
* **Role Assignment:** Define which fans are *Smart* (algorithm-controlled), *Manual* (fixed via a slider on the web UI), or strictly ignored.
* **Calibration Lab:** Put your fans to the test. The system tests motors progressively in 10% steps to create a mathematically accurate logarithmic RPM profile in the database, allowing real-time estimation of bearing wear via optical feedback.

### 🚨 Active Security & Perimeter Intelligence

* **Mechanical Jam Alarm:** If ZFS Guardian injects movement PWM but the RPM sensor returns "0" for 20 seconds, it detects a physical jam or blocked cable and triggers a critical alarm.
* **Localized Thermal Anomaly (48H Deviation):** Compares a drive's heat against its own 48-hour history. If a specific drive suddenly spikes +5ºC compared to its compensated ambient average, it alerts you of bearing friction or dust blockages long before reaching absolute critical overheat limits.
* **Ghost Disk Detection:** If the OS or a SAS cable fails silently, it detects the empty voids in its main loop and notifies you of the loss.
* **Vigilante Mode (Permanent Fail-Safe):** If the entire disk array communication goes dark, the daemon panics assuming the worst-case scenario and permanently locks the main PWM turbines to a fixed 80% military emergency state.
* **Two-Factor Authentication (2FA):** Protect web access by integrating Authy or Google Authenticator via TOTP.
* **Zero-Lag Database:** Uses SQLite in WAL (Write-Ahead Logging) mode, enabling ultra-fast, concurrent reads and writes without locking the web interface.
* **UI Anonymization:** Telegram tokens and SMTP passwords are masked in the WebGUI (`••••••••`) to prevent prying eyes during screen sharing.

### 🌍 Internationalization (i18n)

* **Multilingual Support:** The app automatically copies language `.json` template files to the external data volume. Translating the app to a new language is as easy as duplicating `en.json`, renaming it to `fr.json`, and translating the strings. The web interface updates languages on the fly without reloading!

### 📊 Visual Monitoring

* **Real-time Charts:** Modern interface using `Chart.js` to draw historical temperatures, RPMs, and ZFS read/write I/O traffic.
* **S.M.A.R.T. Health:** Monitors the longevity of your array by adapting to its physical technology:
  * **NVMe:** Natively extracts the flash wear indicator (*Percentage Used* / TBW).
  * **SATA SSD:** Scans and interprets the erase cycle IDs depending on the vendor (IDs `231`, `202`, `177`, `233`) for Crucial, Kingston, Samsung, etc.
  * **Mechanical HDD:** Uses a heuristic algorithm estimating lifespan by comparing continuous motor rotation (*Power-On Hours*) against your custom expected lifespan rules.
---

## 🚀 Installation (Docker)

ZFS Guardian is designed to run as a Docker container. It requires low-level system access to perform its duties. Here is why it requires specific non-negotiable permissions:
* `privileged: true`: Necessary to interact directly with the hard drive controllers via `smartctl` commands (S.M.A.R.T. RAW I/O). Bypassing Kernel isolation allows the daemon to read the actual heat straight from the magnetic platters.
* `/sys/class/hwmon:rw`: Necessary to *write* and deploy the new voltages (PWM) to the physical fan motor controllers on the motherboard. (Using a read-only `ro` permission would turn the app into a passive monitor with no real cooling capabilities).

### Option A: Pre-built Image (Recommended)

If you just want to use the application without tinkering with the source code, simply create an empty folder, save the following `docker-compose.yml` file, and run it:

```yaml
services:
  zfs-guardian:
    image: your-github-user/zfs-guardian:latest # Adjust to your DockerHub/GHCR image
    container_name: zfs-guardian
    privileged: true
    ports:
      - "48082:8000"
    volumes:
      - ./data:/app/data                        # Stores DB, configs, and languages
      - /dev/disk/by-id:/dev/disk/by-id:ro      # Needed for persistent ZFS mapping
      - /sys/class/hwmon:/sys/class/hwmon:rw    # Needed to inject PWM voltage & read i2c
    restart: unless-stopped
```

Start the container:
```bash
docker compose up -d
```

### Option B: Build from Source (Developers)

If you prefer to compile the application yourself to mod it or read the source code, you must clone the repository first:

```bash
git clone https://github.com/your-username/zfs-guardian.git
cd zfs-guardian
```

Then, use the `docker-compose.yml` file located in the root directory (which contains the `build: .` tag) and run:
```bash
docker compose up -d --build
```

---

Access the web interface at: `http://YOUR_IP:48082`

---

## ⚙️ First Steps & Configuration

1. **Initial Setup:** Upon your first login, use the default credentials (`admin` / `admin`). The system will immediately prompt you to change it and create a strong password (requires uppercase, lowercase, number, and symbol).
2. **Hardware Mapping:** Go to the **Hardware** tab.
* Check the boxes for the physical drives that belong to your ZFS pool. (Ignore Cache/OS drives if you don't want the Predictive IO to spin up fans on minor OS writes).
* Identify your fans (use the **🔊 TEST** button to run a 15-second 100% burst so you can acoustically locate them in your chassis).
* Assign them a name (e.g. "Front Intake") and a role (*Smart*, *Manual*, or *Ignored*).
* Select your motherboard's ambient sensor (usually `SYSTIN`).

3. **Save and Done:** Once saved, ZFS Guardian will immediately take over your server's thermal management.

---

## 🔔 Notifications

You can configure ZFS Guardian to alert you on overheating, Fail-Safe activations, Predictive triggers, or hardware anomalies.

* **Telegram:** You only need a Bot Token (from *BotFather*) and your Chat ID.
* **Email (SMTP):** Supports direct delivery via TLS, STARTTLS, or plain text.

---

## 🛠️ Tech Stack

* **Backend:** Python 3 + FastAPI (Async Server & Threadpool processing).
* **Database:** SQLite3 (WAL mode enabled for zero blocking).
* **Frontend:** HTML5, CSS3, pure Vanilla JS - no heavy build frameworks. Charts powered by `Chart.js`.
* **Frontend/Backend Security:** Rolling session tokens, dynamic Salt SHA256 Hashing, PyOTP integration for 2FA.

---

## 🤝 Contributing (Languages)

Want to add your native language?

1. Go to your mapped host volume: `./data/lang/`
2. Copy the `en.json` template and rename it using your country code (e.g. `fr.json`).
3. Open it, change the `"_name"` variable to your language (e.g. `"Français"`), map the `"_flag"` variable (`"🇫🇷"`), and translate the values.
4. Restart or refresh the App, and your language will appear in the top-right menu instantly!
5. **(Optional)** Submit a *Pull Request* to this repository with your `.json` file so we can include it natively in the app. Thanks for your contribution!

---

## ⚠️ Disclaimer / Warning

*This software interacts directly with low-level PWM controllers in the Linux kernel (`/sys/class/hwmon`). Misconfiguration of host hardware or BIOS settings may result in fans stopping entirely. The creator is not responsible for any hardware damage caused by overheating. Always keep absolute thermal shutdown protections enabled in your motherboard's BIOS.*

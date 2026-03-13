// static/js/app.js
// --- Lógica Principal del Frontend (Fetch APIs y Core GUI) ---
// Todo este archivo esta diseñado para ser un SPA (Single Page Application) sin recargas.

// === 1. VARIABLES GLOBALES Y UTILIDADES API ===
let token = localStorage.getItem('tg_token'), temp_token = null, updateInterval;
let currentHw = { disks: [], fans: [], temps: [] };

async function apiCall(endpoint, method = 'GET', body = null) {
    const opts = { method, headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(endpoint, opts);
    if (res.status === 401) { logout(); throw new Error("Unauthorized"); }
    if (!res.ok) { 
        let errDetail = "Error"; 
        try { errDetail = (await res.json()).detail || errDetail; } catch(e){} 
        throw new Error(errDetail); 
    }
    return await res.json();
}

// === 2. GESTIÓN DE VISTAS Y ESTADO (GUI Utils) ===
function showView(v) { 
    document.querySelectorAll('.view').forEach(e => e.classList.remove('active')); 
    document.getElementById('view-'+v).classList.add('active'); 
    document.getElementById('header-controls').style.display = v === 'dashboard' ? 'flex' : 'none'; 
}
function openTab(evt, tab) { 
    document.querySelectorAll('.tab-content, .tab-btn').forEach(e => e.classList.remove('active')); 
    document.getElementById(tab).classList.add('active'); 
    evt.currentTarget.classList.add('active'); 
}
function showError(id, msg) { 
    const el = document.getElementById(id); 
    el.innerText = msg; 
    el.style.display = 'block'; 
}

// === 3. FLUJO DE AUTENTICACIÓN (Login, 2FA y Setup) ===
async function doLogin() {
    try {
        const res = await fetch('/api/login', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({
                username: document.getElementById('log-user').value, 
                password: document.getElementById('log-pass').value
            }) 
        });
        if (!res.ok) throw new Error("Credenciales incorrectas");
        const data = await res.json();
        
        if (data.status === "setup_required") { 
            document.getElementById('set-olduser').value = document.getElementById('log-user').value; 
            document.getElementById('set-oldpass').value = document.getElementById('log-pass').value; 
            showView('setup'); 
        } else if (data.status === "2fa_required") { 
            temp_token = data.temp_token; 
            showView('login-2fa'); 
        } else { 
            token = data.token; 
            localStorage.setItem('tg_token', token); 
            initDashboard(); 
        }
    } catch (e) { showError('log-err', e.message); }
}

async function verify2FALogin() {
    try {
        const res = await fetch('/api/login/2fa', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({temp_token: temp_token, code: document.getElementById('log-2fa-code').value}) 
        });
        if (!res.ok) throw new Error("Código incorrecto");
        token = (await res.json()).token; 
        localStorage.setItem('tg_token', token); 
        initDashboard();
    } catch (e) { showError('log-2fa-err', e.message); }
}

async function doSetup() {
    try {
        const res = await fetch('/api/setup', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({
                old_user: document.getElementById('set-olduser').value, 
                old_pass: document.getElementById('set-oldpass').value, 
                new_user: document.getElementById('set-user').value, 
                new_pass: document.getElementById('set-pass').value
            }) 
        });
        if (!res.ok) throw new Error((await res.json()).detail); 
        alert(t("js_setup_ok")); 
        logout();
    } catch(e) { showError('set-err', e.message); }
}

function logout() { 
    token = null; 
    localStorage.removeItem('tg_token'); 
    if(updateInterval) clearInterval(updateInterval); 
    showView('login'); 
}

// === 4. COMANDOS DE ACCIÓN DIRECTA ===
const apply = async (d, msg = null) => { 
    try { 
        await apiCall('/api/set', 'POST', d); 
        update(); 
        if(msg) setTimeout(()=>alert("✅ " + t("js_saved")), 50); 
    } catch(e) { 
        alert(t("js_error") + " " + e.message); 
    } 
};
async function startCalibrate() { if(confirm(t("js_calib_confirm"))) { await apiCall('/api/calibrate', 'POST'); update(); } }
async function startPurge() { if(confirm(t("js_purge_confirm"))) { await apiCall('/api/purge', 'POST'); update(); } }

// === 5. INICIALIZACIÓN DEL DASHBOARD E INTERNACIONALIZACIÓN ===
function initDashboard() {
    showView('dashboard');
    loadLanguages().then(() => { 
        apiCall('/api/status').then(s => { 
            if (!s.language && navigator.language) {
                let browserLang = navigator.language.split('-')[0];
                let options = Array.from(document.getElementById('lang-selector').options).map(o => o.value);
                
                if (options.includes(browserLang)) {
                    setLang(browserLang, true);
                } else if (browserLang !== 'en') {
                    setLang('en', true);
                }
            } else {
                setLang(s.language || 'en', false);
            }
        }); 
    });
    if(!updateInterval) updateInterval = setInterval(update, 5000);
    update();
}

const getTClass = (temp) => { if(temp === "--" || temp < 38) return "t-green"; return temp < 43 ? "t-orange" : "t-red"; };

function toggleBoostUI(enabled) {
    const inp = document.getElementById('inp-boost'); const btn = document.getElementById('btn-boost'); const txt = document.getElementById('txt-boost');
    inp.disabled = !enabled; btn.disabled = !enabled; 
    btn.style.opacity = enabled?'1':'0.3'; inp.style.opacity = enabled?'1':'0.3'; txt.style.opacity = enabled?'1':'0.3'; 
    btn.style.pointerEvents = enabled?'auto':'none';
}

async function applyFanManual(fid) {
    const sld = document.getElementById(`sld_${fid}`); const pct = parseInt(sld.value);
    document.getElementById(`lbl_${fid}`).innerText = pct; sld.dataset.lockedUntil = Date.now() + 8000;
    try { await apiCall('/api/set', 'POST', {fan_manual: {id: fid, pct: pct}}); } catch (e) { alert(t("js_error") + " " + e.message); }
}

function toggleHide(btn) {
    if(btn.dataset.hide === "true") { 
        btn.dataset.hide = "false"; btn.innerText = t("js_btn_vis"); btn.style.background = "#222"; btn.style.color = "#00e676"; 
    } else { 
        btn.dataset.hide = "true"; btn.innerText = t("js_btn_hid"); btn.style.background = "#333"; btn.style.color = "#888"; 
    }
}

// === 6. MOTOR DE REFRESCO PRINCIPAL (HEARTBEAT) ===
async function update() {
    if (document.hidden) return; // Ahorro de recursos al minimizar o cambiar pestaña
    try {
        const s = await apiCall('/api/status');
        const modeInfoEl = document.getElementById('mode-info');
        if(modeInfoEl) {
            modeInfoEl.innerHTML = t(s.mode === "aggressive" ? "algo_aggr_help" : (s.mode === "aggressive_inverse" ? "algo_inv_help" : "algo_soft_help")) || '';
        }
        document.getElementById('val-max').innerText = s.current_max + "ºC"; 
        document.getElementById('val-max').className = "temp " + getTClass(s.current_max);
        document.getElementById('val-delta').innerText = s.delta; 
        document.getElementById('val-systin').innerText = s.systin; 
        document.getElementById('val-eff').innerText = s.efficiency;

        document.getElementById('badge-failsafe').style.display = s.failsafe_active ? 'inline-block' : 'none';
        
        document.getElementById('badge-boost').style.display = s.boost_active ? 'inline-block' : 'none';
        if(document.activeElement.id !== 'inp-boost') document.getElementById('inp-boost').value = s.boost_threshold;
        if(document.activeElement.id !== 'chk-boost') { document.getElementById('chk-boost').checked = s.boost_enabled; toggleBoostUI(s.boost_enabled); }

        document.getElementById('val-read').innerText = s.io_read_mbs; 
        document.getElementById('val-write').innerText = s.io_write_mbs; 
        document.getElementById('val-total').innerText = (s.io_read_mbs + s.io_write_mbs).toFixed(2);
        
        document.querySelectorAll('.algo-grid button').forEach(b => b.classList.remove('active-mode'));
        if(document.getElementById('btn-'+s.mode)) document.getElementById('btn-'+s.mode).classList.add('active-mode');

        let fanHtml = "", mechHtml = "";
        let neededSliders = Object.keys(s.fans_data).filter(fid => s.fans_data[fid].role === 'manual');
        let sldBox = document.getElementById('manual-sliders-box');
        let currentSliders = Array.from(sldBox.querySelectorAll('input[type="range"]')).map(el => el.id.replace('sld_', ''));

        if (neededSliders.join(',') !== currentSliders.join(',')) {
            let sH = "";
            for(let fid of neededSliders) {
                let f = s.fans_data[fid];
                sH += `<div style="background:transparent; border:1px solid #333; border-radius:8px; padding:15px;"><div style="text-align:left; font-size:0.9em; color:#888; font-weight:bold;">${f.name}: <b id="lbl_${fid}" style="color:#fff;">${f.pct}</b>%</div><input type="range" min="20" max="100" id="sld_${fid}" style="width:100%; margin:10px 0;" oninput="document.getElementById('lbl_${fid}').innerText=this.value" onchange="applyFanManual('${fid}')"></div>`;
            }
            sldBox.innerHTML = sH || `<p style="color:#888; text-align:center; width:100%;">${t('no_manual')}</p>`;
        }

        for(let fid in s.fans_data) {
            const f = s.fans_data[fid];
            if(!f.hide_ui) {
                const icon = f.role === 'smart' ? '🧠' : (f.role === 'manual' ? '✋' : '👁️');
                fanHtml += `<div style="margin-bottom:10px;"><strong style="color:#fff">${icon} ${f.name}</strong><br><span style="color:#4fc3f7; font-family:monospace;">${f.rpm} RPM</span> <span style="color:#888;">(${f.pct}%)</span></div>`;
            }
            if (f.role === 'manual' && document.getElementById(`sld_${fid}`)) {
                const sld = document.getElementById(`sld_${fid}`);
                if (Date.now() > parseInt(sld.dataset.lockedUntil || 0) && document.activeElement !== sld) { 
                    sld.value = f.pct; 
                    document.getElementById(`lbl_${fid}`).innerText = f.pct; 
                }
            }
            if (f.role === 'smart' || f.role === 'manual') {
                let status = t("js_stat_noref");
                if (s.calibrating) status = t("js_stat_calib");
                else if (f.max_rpm > 0) {
                    let expected = 0;
                    let pct_f = (f.target_pwm / 255) * 100;
                    if (s.baseline && Object.keys(s.baseline).length > 2) {
                        let p1 = 0, r1 = 0, p2 = 100, r2 = s.baseline["100"] || f.max_rpm;
                        for (let bp = 10; bp <= 100; bp += 10) {
                            if (pct_f <= bp) {
                                p2 = bp; r2 = s.baseline[bp.toString()] || r2;
                                p1 = bp - 10; r1 = p1 === 0 ? 0 : (s.baseline[p1.toString()] || 0);
                                break;
                            }
                        }
                        let interpolated_rpm = r1 + ((pct_f - p1) / 10) * (r2 - r1);
                        let base_max = s.baseline["100"] || f.max_rpm;
                        expected = f.max_rpm * (base_max > 0 ? (interpolated_rpm / base_max) : (pct_f / 100));
                    } else {
                        expected = f.max_rpm * (pct_f / 100);
                    }
                    let health = expected > 0 ? (f.rpm / expected) * 100 : 0;
                    status = f.rpm == 0 ? t("js_stat_stop") : (health >= 85 && health <= 115 ? t("js_stat_opt") : t("js_stat_anom"));
                }
                mechHtml += `<tr><td><strong>${f.name}</strong> ${f.max_rpm ? ` <span style='color:#888; font-size:0.8em;'>(Max: ${f.max_rpm})</span>` : ''}</td><td>${f.pct}%</td><td style="color:#4fc3f7">${f.rpm} RPM</td><td>${status}</td></tr>`;
            }
        }

        fanHtml += `<button id="btn-purge" class="btn-purge" onclick="startPurge()">${t("btn_purge")}</button>`;
        document.getElementById('fans-status-box').innerHTML = `<h3 style="text-align: center; margin-top: 0;">${t("airflow")}</h3>${fanHtml}`;
        document.getElementById('mech-table').innerHTML = mechHtml || `<tr><td colspan="4" style="text-align:center; color:#888;">${t("no_fan")}</td></tr>`;

        // === C. TABLA ZFS I/O DESGLOSADA ===
        let zfsHtml = '';
        for (let did of Object.keys(s.disks_data || {})) {
            let d = s.disks_data[did];
            let r = d.r_mb || 0, w = d.w_mb || 0, total = r + w;
            zfsHtml += `<tr><td><strong>${d.name}</strong></td>
                <td style="color:#4fc3f7">${r.toFixed(1)} MB/s</td>
                <td style="color:#ff5252">${w.toFixed(1)} MB/s</td>
                <td style="color:#b388ff">${total.toFixed(1)} MB/s</td></tr>`;
        }
        document.getElementById('zfs-table').innerHTML = zfsHtml || `<tr><td colspan="4" style="text-align:center; color:#888;">${t("no_disk")}</td></tr>`;
        const btnP = document.getElementById('btn-purge'); 
        if(s.purge_active) { btnP.disabled=true; btnP.innerText=`${t("js_purg_act")} (${s.purge_remaining}s)`; }

        const tf = document.getElementById('timeframe').value;
        const disks = await apiCall(`/api/disks_summary?hours=${tf}`);
        document.getElementById('disk-table').innerHTML = disks.map(d => {
            const lCol = d.life > 75 ? '#00e676' : (d.life > 40 ? '#ffab40' : '#ff5252');
            return `<tr><td><strong>${d.sn}</strong></td><td class="${getTClass(d.current)}">${d.current}ºC</td><td style="color:${d.dev >= 3.0 ? '#ff5252' : '#888'}; font-weight:bold;">${d.dev > 0 ? '+'+d.dev : d.dev}ºC</td><td><span style="color:#4fc3f7">${d.min24}</span> - <span style="color:#ff5252">${d.max24}</span></td><td>${d.avg24}ºC</td><td><span style="color:${lCol}">${d.life}%</span><div class="life-bar"><div class="life-fill" style="width:${d.life}%; background:${lCol}"></div></div></td></tr>`;
        }).join('');

        const h = await apiCall(`/api/history?hours=${tf}`);
        const formatL = l => { 
            const d = new Date(l); 
            return tf > 24 ? d.toLocaleDateString([], {day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); 
        };
        if(!chartT && typeof initCharts === 'function') initCharts();
        if(chartT) {
            chartT.data.labels = h.labels.map(formatL); 
            chartT.data.datasets[0].data = h.temps; 
            chartT.data.datasets[1].data = h.pwms.map(p => (p/255)*100); 
            chartT.update();
        }
        if(chartZ) {
            chartZ.data.labels = h.zfs_labels.map(formatL); 
            chartZ.data.datasets[0].data = h.zfs_read; 
            chartZ.data.datasets[1].data = h.zfs_write; 
            chartZ.data.datasets[2].data = h.zfs_read.map((r, i) => r + h.zfs_write[i]); 
            chartZ.update();
        }
    } catch (e) {
        console.error("Update error: ", e);
    }
}

// === 7. GESTIÓN Y MAPEADO DE HARDWARE FISICO ===
async function loadHardware() {
    const hw = await apiCall('/api/hardware/scan'); currentHw = hw;
    document.getElementById('hw-disks-list').innerHTML = hw.disks.map((d, i) => `
        <div class="hw-row" style="padding: 10px; background: #141414; align-items:center;">
            <input type="checkbox" id="d_chk_${i}" ${d.is_active ? 'checked' : ''} style="transform: scale(1.5); margin: 0 15px;">
            <div style="flex:1; min-width:150px; display:flex; flex-direction:column;">
                <input type="text" id="d_name_${i}" value="${d.saved_name}" placeholder="Alias" style="border-bottom:none; border-bottom-left-radius:0; border-bottom-right-radius:0; padding:8px 10px;">
                <div style="background:#111; color:#888; font-size:0.75em; padding:4px 10px; border:1px solid #444; border-top:none; border-bottom-left-radius:6px; border-bottom-right-radius:6px; font-family:monospace; word-break: break-all;">${d.id}</div>
            </div>
        </div>`).join('') || `<p>${t('no_disk')}</p>`;

    document.getElementById('hw-fans-list').innerHTML = hw.fans.map((f, i) => `
        <div class="hw-row" style="padding: 10px; background: #141414; flex-wrap: wrap;">
            <button class="btn-test" style="margin:0; padding:8px 15px; border-width:1px;" onclick="identifyFan('${f.hwmon_path}', '${f.pwm_num}')">🔊 TEST</button>
            <div style="flex:1.5; min-width:120px; display:flex; flex-direction:column;">
                <input type="text" id="f_name_${i}" value="${f.saved_name}" placeholder="Alias" style="border-bottom:none; border-bottom-left-radius:0; border-bottom-right-radius:0; padding:8px 10px;">
                <div style="background:#111; color:#888; font-size:0.7em; padding:4px 10px; border:1px solid #444; border-top:none; border-bottom-left-radius:6px; border-bottom-right-radius:6px; font-family:monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${f.id}">${f.id}</div>
            </div>
            <select id="f_role_${i}" style="flex:1; min-width: 140px; margin:0; padding:8px 10px;"><option value="smart" ${f.role=='smart'?'selected':''}>🧠 Inteligente</option><option value="manual" ${f.role=='manual'?'selected':''}>✋ Manual</option><option value="monitor" ${f.role=='monitor'?'selected':''}>👁️ Ignorar</option></select>
            <input type="number" id="f_maxrpm_${i}" value="${f.max_rpm || ''}" placeholder="Max RPM" style="flex:1; min-width: 90px; margin:0; padding:8px 10px;">
            <button id="f_hide_${i}" data-hide="${f.hide_ui}" onclick="toggleHide(this)" style="margin:0; flex:0 0 auto; width:110px; background:${f.hide_ui?'#333':'#222'}; color:${f.hide_ui?'#888':'#00e676'}; border:1px solid #444; padding:8px 10px; border-radius:6px; cursor:pointer; font-weight:bold;">${f.hide_ui? t('js_btn_hid') : t('js_btn_vis')}</button>
        </div>`).join('') || `<p>${t('no_fan')}</p>`;

    document.getElementById('hw-smart-years').value = hw.smart_life_years || 10;
    let options = `<option value="">${t("hw_fixed25")}</option>`;
    hw.temps.forEach(temp => { options += `<option value="${temp.path}" ${hw.ambient_sensor === temp.path ? 'selected' : ''}>${temp.label} - ${t("hw_actual")}: ${temp.val}ºC</option>`; });
    document.getElementById('hw-ambient-select').innerHTML = options;
}

async function saveHardware() {
    try {
        const payload = { 
            disks: [], 
            fans: [], 
            ambient_sensor: document.getElementById('hw-ambient-select') ? document.getElementById('hw-ambient-select').value : "", 
            smart_life_years: document.getElementById('hw-smart-years') ? parseInt(document.getElementById('hw-smart-years').value) : 10 
        };
        if(currentHw.disks) currentHw.disks.forEach((d, i) => { 
            const n = document.getElementById(`d_name_${i}`); 
            const c = document.getElementById(`d_chk_${i}`); 
            if(n && c) payload.disks.push({ id: d.id, name: n.value, active: c.checked }); 
        });
        if(currentHw.fans) currentHw.fans.forEach((f, i) => { 
            const n = document.getElementById(`f_name_${i}`); 
            const r = document.getElementById(`f_role_${i}`); 
            const h = document.getElementById(`f_hide_${i}`); 
            const m = document.getElementById(`f_maxrpm_${i}`); 
            if(n && r && h && m) payload.fans.push({ 
                id: f.id, hwmon_path: f.hwmon_path, pwm_num: f.pwm_num, name: n.value, 
                role: r.value, hide_ui: h.dataset.hide === "true", max_rpm: parseInt(m.value) || 0 
            }); 
        });
        await apiCall('/api/hardware/save', 'POST', payload); 
        setTimeout(()=>alert("✅ " + t("js_saved")), 50); 
        update();
    } catch (e) { alert(t("js_error") + " " + e.message); }
}

async function identifyFan(hwmon, pwm) { 
    await apiCall('/api/hardware/identify', 'POST', {hwmon, pwm}); 
    alert("⚠️ TEST 100% (15s)..."); 
}

// Alerts Management
async function loadAlerts() {
    const a = await apiCall('/api/config/alerts');
    document.getElementById('tg-token').value = a.telegram_token || '';
    document.getElementById('tg-chatid').value = a.telegram_chat_id || '';
    document.getElementById('em-srv').value = a.smtp_server || '';
    document.getElementById('em-port').value = a.smtp_port || '';
    document.getElementById('em-usr').value = a.smtp_user || '';
    document.getElementById('em-dest').value = a.smtp_dest || '';
    document.getElementById('em-pass').value = a.smtp_pass || '';
    if(a.smtp_tls) document.getElementById('em-tls').value = a.smtp_tls;
}

async function saveTelegram() { 
    try { 
        await apiCall('/api/config/telegram', 'POST', {
            telegram_token: document.getElementById('tg-token').value, 
            telegram_chat_id: document.getElementById('tg-chatid').value
        }); 
        setTimeout(()=>alert("✅ " + t("js_saved")), 50); loadAlerts(); 
    } catch(e) { alert(t("js_error") + e.message); } 
}
async function testTelegram() { try{ await apiCall('/api/config/telegram/test', 'POST'); setTimeout(()=>alert(t("js_test_tg_ok")), 50); }catch(e){} }
async function saveSMTP() { 
    try { 
        await apiCall('/api/config/email', 'POST', { 
            smtp_server: document.getElementById('em-srv').value, 
            smtp_port: document.getElementById('em-port').value, 
            smtp_tls: document.getElementById('em-tls').value, 
            smtp_user: document.getElementById('em-usr').value, 
            smtp_dest: document.getElementById('em-dest').value, 
            smtp_pass: document.getElementById('em-pass').value 
        }); 
        setTimeout(()=>alert("✅ " + t("js_saved")), 50); loadAlerts(); 
    } catch(e) { alert(t("js_error") + e.message); } 
}
async function testSMTP() { try{ await apiCall('/api/config/email/test', 'POST'); setTimeout(()=>alert(t("js_test_tg_ok")), 50); }catch(e){} }

// === 8. GESTIÓN DE ALERTAS Y NOTIFICACIONES PUSH ===
async function loadSecurity() {
    const res = await apiCall('/api/2fa/status');
    document.getElementById('2fa-box').innerHTML = res.enabled 
        ? `<p style="color:#00e676; font-weight:bold;">✅ 2FA ON.</p><button class="btn-purge" style="width:auto; padding:10px 20px;" onclick="disable2FA()">Desactivar 2FA</button>` 
        : `<p style="color:#ffab40; font-weight:bold;">❌ 2FA OFF.</p><button class="btn-apply" style="width:auto; padding:10px 20px;" onclick="setup2FA()">Configurar 2FA</button>`;
}
async function changePassword() { 
    const c=document.getElementById('pw-curr').value, n1=document.getElementById('pw-new1').value, n2=document.getElementById('pw-new2').value; 
    if(!c||!n1) return alert("Rellena los campos."); 
    if(n1!==n2) return alert("Las contraseñas no coinciden."); 
    try { 
        await apiCall('/api/user/password', 'POST', {current_pass:c, new_pass:n1}); 
        alert("Contraseña cambiada. Vuelve a entrar."); logout(); 
    } catch(e) { alert(e.message); } 
}
async function setup2FA() { 
    const r = await apiCall('/api/2fa/generate', 'POST'); 
    document.getElementById('2fa-box').innerHTML = `
        <img src="data:image/png;base64,${r.qr_b64}" width="200" style="display:block; margin-bottom:10px; background:#fff; padding:10px; border-radius:8px;">
        <p style="font-family:monospace; color:#4fc3f7; font-size:1.2em;">${r.secret}</p>
        <div style="display:flex; gap:10px;">
            <input type="text" id="setup-2fa-code" placeholder="000000" class="auth-input" style="width:120px; text-align:center;">
            <button class="btn-apply" style="width:auto; margin:0;" onclick="confirm2FA()">Confirmar</button>
        </div>`; 
}
async function confirm2FA() { 
    try { 
        await apiCall('/api/2fa/enable', 'POST', {code: document.getElementById('setup-2fa-code').value}); 
        loadSecurity(); 
    } catch(e) { alert("Código incorrecto."); } 
}
async function disable2FA() { 
    if(confirm("¿Seguro que quieres quitar el 2FA?")) { 
        await apiCall('/api/2fa/disable', 'POST'); 
        loadSecurity(); 
    } 
}

// === 9. ARRANQUE EN TIEMPO DE EJECUCIÓN (BOOT) ===
document.addEventListener("DOMContentLoaded", () => {
    if(token) initDashboard(); else showView('login');
    document.addEventListener("visibilitychange", () => { if(!document.hidden && token) update(); });
});

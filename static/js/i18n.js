// static/js/i18n.js
// --- Motor de Idiomas y Traducción ---
let currentDict = {};
let currentLang = 'es';

async function loadLanguages() {
    try {
        const list = await apiCall('/api/lang/list');
        let html = '';
        list.forEach(l => { html += `<option value="${l.code}">${l.flag} ${l.name}</option>`; });
        document.getElementById('lang-selector').innerHTML = html;
    } catch(e){
        console.error("Error cargando idiomas", e);
    }
}

async function setLang(code, save = true) {
    try {
        currentLang = code;
        const selector = document.getElementById('lang-selector');
        if(selector && selector.value !== code) selector.value = code;
        currentDict = await apiCall('/api/lang/' + code);
        
        // Reemplazar textos en el DOM
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if(currentDict[key]) el.innerHTML = currentDict[key];
        });
        
        if(save && token) apiCall('/api/set', 'POST', {language: code});
        if(typeof update === 'function') update();
        if(document.getElementById('tab-hardware') && document.getElementById('tab-hardware').classList.contains('active') && typeof loadHardware === 'function') loadHardware();
    } catch(e){
        console.error("Error setting language", e);
    }
}

/** Obtiene una clave del diccionario cacheado en RAM */
function t(key) { 
    return currentDict[key] || key; 
}

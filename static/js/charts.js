// static/js/charts.js
// --- Gestor Visual de Gráficos (Chart.js) ---
let chartT, chartZ;

function initCharts() {
    const chartOpts = { 
        maintainAspectRatio: false, 
        scales: { 
            x: { grid: { display: false } }, 
            y: { type: 'linear', position: 'left', grid: { color: '#222' } } 
        }, 
        animation: false, 
        plugins: { legend: { display: true, position: 'bottom' } } 
    };
    
    // Gráfico de Temperatură vs Señal PWM
    chartT = new Chart(document.getElementById('chart-temp').getContext('2d'), { 
        type: 'line', 
        data: { 
            labels: [], 
            datasets: [
                { label: 'Temp Max (ºC)', data: [], borderColor: '#00e676', tension: 0.4, pointRadius: 0, yAxisID: 'y' }, 
                { label: 'PWM Medio (%)', data: [], borderColor: '#4fc3f7', borderDash: [5,5], pointRadius: 0, yAxisID: 'y1' }
            ]
        }, 
        options: { 
            ...chartOpts, 
            scales: { 
                ...chartOpts.scales, 
                y1: { type: 'linear', position: 'right', min: 0, max: 100, grid: { drawOnChartArea: false } } 
            } 
        } 
    });
    
    // Gráfico Predictivo ZFS (Lectura y Escritura combinadas)
    chartZ = new Chart(document.getElementById('chart-zfs').getContext('2d'), { 
        type: 'line', 
        data: { 
            labels: [], 
            datasets: [
                { label: 'Lectura', data: [], borderColor: '#4fc3f7', backgroundColor: 'rgba(79, 195, 247, 0.2)', fill: true, tension: 0.2, pointRadius: 0 }, 
                { label: 'Escritura', data: [], borderColor: '#ff5252', backgroundColor: 'rgba(255, 82, 82, 0.2)', fill: true, tension: 0.2, pointRadius: 0 }, 
                { label: 'Total', data: [], borderColor: '#b388ff', borderDash: [5,5], fill: false, tension: 0.2, pointRadius: 0 }
            ]
        }, 
        options: chartOpts 
    });
}

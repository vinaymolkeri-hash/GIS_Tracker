/* ============================================
   Land Safety Checker — Frontend Logic
   ============================================ */

const API_BASE = '';  // same origin

// ---------- State ----------
let map;
let marker;
let waterLayer;
let forestLayer;
let selectedLat = null;
let selectedLon = null;

// ---------- DOM ----------
const latInput       = document.getElementById('input-lat');
const lonInput       = document.getElementById('input-lon');
const btnAnalyze     = document.getElementById('btn-analyze');
const resultsPanel   = document.getElementById('results-panel');
const mapHint        = document.getElementById('map-hint');
const toggleWater    = document.getElementById('toggle-water');
const toggleForest   = document.getElementById('toggle-forest');
const locationInput  = document.getElementById('input-location');
const btnSearch      = document.getElementById('btn-search');
const resolvedNameEl = document.getElementById('resolved-name');

// ---------- Map Init ----------
function initMap() {
    map = L.map('map', {
        center: [9.87, 76.2],
        zoom: 12,
        zoomControl: true,
        attributionControl: false,
    });

    // Dark tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
    }).addTo(map);

    // Attribution (small)
    L.control.attribution({ prefix: false })
        .addAttribution('© <a href="https://carto.com/">CARTO</a>')
        .addTo(map);

    // Click handler
    map.on('click', (e) => {
        const { lat, lng } = e.latlng;
        setCoordinates(lat, lng);
    });

    // Load overlay layers
    loadLayers();
}

// ---------- Coordinate Handling ----------
function setCoordinates(lat, lon) {
    selectedLat = parseFloat(lat.toFixed(6));
    selectedLon = parseFloat(lon.toFixed(6));

    latInput.value = selectedLat;
    lonInput.value = selectedLon;

    placeMarker(selectedLat, selectedLon);

    // Hide hint
    if (mapHint) mapHint.classList.add('hidden');
}

function placeMarker(lat, lon) {
    if (marker) {
        map.removeLayer(marker);
    }

    const icon = L.divIcon({
        className: 'custom-marker',
        html: `<div class="marker-pulse"></div><div class="marker-pin"></div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 28],
        popupAnchor: [0, -30],
    });

    marker = L.marker([lat, lon], { icon })
        .addTo(map)
        .bindPopup(`<strong>Selected</strong><br>Lat: ${lat}<br>Lon: ${lon}`)
        .openPopup();
}

// ---------- GeoJSON Layers ----------
async function loadLayers() {
    try {
        const [waterRes, forestRes] = await Promise.all([
            fetch(`${API_BASE}/api/layers/water`),
            fetch(`${API_BASE}/api/layers/forest`),
        ]);

        const waterData  = await waterRes.json();
        const forestData = await forestRes.json();

        waterLayer = L.geoJSON(waterData, {
            style: () => ({
                color: 'hsl(217, 91%, 60%)',
                fillColor: 'hsl(217, 91%, 60%)',
                fillOpacity: 0.18,
                weight: 2,
                opacity: 0.7,
            }),
            onEachFeature: (feature, layer) => {
                if (feature.properties && feature.properties.name) {
                    layer.bindPopup(`<strong>${feature.properties.name}</strong><br>Type: ${feature.properties.type}`);
                }
            },
        }).addTo(map);

        forestLayer = L.geoJSON(forestData, {
            style: () => ({
                color: 'hsl(142, 71%, 45%)',
                fillColor: 'hsl(142, 71%, 45%)',
                fillOpacity: 0.15,
                weight: 2,
                opacity: 0.7,
            }),
            onEachFeature: (feature, layer) => {
                if (feature.properties && feature.properties.name) {
                    layer.bindPopup(`<strong>${feature.properties.name}</strong><br>Type: ${feature.properties.type}`);
                }
            },
        }).addTo(map);
    } catch (err) {
        console.error('Failed to load layers:', err);
    }
}

// ---------- Layer Toggles ----------
toggleWater.addEventListener('change', () => {
    if (toggleWater.checked) {
        waterLayer && map.addLayer(waterLayer);
    } else {
        waterLayer && map.removeLayer(waterLayer);
    }
});

toggleForest.addEventListener('change', () => {
    if (toggleForest.checked) {
        forestLayer && map.addLayer(forestLayer);
    } else {
        forestLayer && map.removeLayer(forestLayer);
    }
});

// ---------- Location Search ----------
btnSearch.addEventListener('click', () => searchLocation());

locationInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchLocation();
});

async function searchLocation() {
    const name = locationInput.value.trim();
    if (!name) {
        showError('Please enter a location name.');
        return;
    }

    // Loading state on search button
    btnSearch.classList.add('loading');
    btnSearch.disabled = true;
    btnAnalyze.classList.add('loading');
    btnAnalyze.disabled = true;
    clearError();
    hideResolvedName();

    try {
        const res = await fetch(`${API_BASE}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ location_name: name }),
        });

        const data = await res.json();

        if (!res.ok) {
            showError(data.error || 'Location not found.');
            return;
        }

        // Update map and coord fields with resolved coordinates
        const lat = data.lat;
        const lon = data.lon;
        selectedLat = lat;
        selectedLon = lon;
        latInput.value = lat;
        lonInput.value = lon;
        placeMarker(lat, lon);
        map.setView([lat, lon], 13);

        // Show resolved name
        if (data.resolved_name) {
            showResolvedName(data.resolved_name);
        }

        // Hide hint
        if (mapHint) mapHint.classList.add('hidden');

        renderResults(data);
    } catch (err) {
        console.error(err);
        showError('Search failed. Make sure the server is running.');
    } finally {
        btnSearch.classList.remove('loading');
        btnSearch.disabled = false;
        btnAnalyze.classList.remove('loading');
        btnAnalyze.disabled = false;
    }
}

function showResolvedName(name) {
    resolvedNameEl.textContent = `📍 ${name}`;
    resolvedNameEl.classList.remove('hidden');
}

function hideResolvedName() {
    resolvedNameEl.classList.add('hidden');
    resolvedNameEl.textContent = '';
}

// ---------- Analyze (lat/lon) ----------
btnAnalyze.addEventListener('click', async () => {
    const lat = parseFloat(latInput.value);
    const lon = parseFloat(lonInput.value);

    if (isNaN(lat) || isNaN(lon)) {
        showError('Please enter valid coordinates or click on the map.');
        return;
    }

    // Place marker if entered manually
    if (selectedLat !== lat || selectedLon !== lon) {
        selectedLat = lat;
        selectedLon = lon;
        placeMarker(lat, lon);
        map.setView([lat, lon], 14);
    }

    hideResolvedName();
    await runAnalysis(lat, lon);
});

async function runAnalysis(lat, lon) {
    // Loading state
    btnAnalyze.classList.add('loading');
    btnAnalyze.disabled = true;
    clearError();

    try {
        const res = await fetch(`${API_BASE}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat, lon }),
        });

        if (!res.ok) throw new Error(`API error: ${res.status}`);

        const data = await res.json();
        renderResults(data);
    } catch (err) {
        console.error(err);
        showError('Analysis failed. Make sure the server is running.');
    } finally {
        btnAnalyze.classList.remove('loading');
        btnAnalyze.disabled = false;
    }
}

// ---------- Render Results ----------
function renderResults(data) {
    const riskIcons = { HIGH: '🔴', MEDIUM: '🟡', LOW: '🟢' };
    const riskIcon = riskIcons[data.risk] || '⚪';

    // Calculate gauge percentage
    const minDist = Math.min(data.water_distance_m, data.forest_distance_m);
    const gaugePercent = Math.max(0, Math.min(100, 100 - (minDist / 50)));

    let gaugeColor;
    if (data.risk === 'HIGH') gaugeColor = 'hsl(0, 84%, 60%)';
    else if (data.risk === 'MEDIUM') gaugeColor = 'hsl(38, 92%, 50%)';
    else gaugeColor = 'hsl(142, 71%, 45%)';

    // ── Explainability: WHY this risk? ────────────────────────────────────
    let whyText = '';
    let ruleText = '';
    if (data.risk === 'HIGH') {
        if (data.water_risk === 'HIGH') {
            whyText = `This location lies <strong>inside a water body</strong>. Construction here would cause direct environmental damage and violates the Water (Prevention and Control of Pollution) Act.`;
            ruleText = 'Rule applied: <code>inside water body → HIGH</code>';
        } else if (data.forest_risk === 'HIGH') {
            whyText = `This location lies <strong>inside a forest or protected area</strong>. Construction here violates the Forest Conservation Act and environmental protection regulations.`;
            ruleText = 'Rule applied: <code>inside forest/protected zone → HIGH</code>';
        } else {
            whyText = `This location is within a <strong>restricted environmental zone</strong> detected via OpenStreetMap data.`;
            ruleText = 'Rule applied: <code>inside restricted zone → HIGH</code>';
        }
    } else if (data.risk === 'MEDIUM') {
        const nearDist = Math.min(data.water_distance_m, data.forest_distance_m);
        const nearType = data.water_distance_m < data.forest_distance_m ? 'water body' : 'forest zone';
        whyText = `This location is <strong>${nearDist} meters from a ${nearType}</strong> — within the 100-meter buffer zone. Development may face environmental restrictions and require EIA clearance.`;
        ruleText = 'Rule applied: <code>distance &lt; 100m → MEDIUM</code>';
    } else {
        whyText = `This location is <strong>more than 100 meters from all mapped water bodies and forest zones</strong>. No environmental zone violations detected.`;
        ruleText = 'Rule applied: <code>distance ≥ 100m → LOW</code>';
    }

    // Build flags HTML
    let flagsHtml = '<span style="color: var(--text-muted); font-size: 0.8rem;">None detected</span>';
    if (data.flags && data.flags.length > 0) {
        flagsHtml = `<ul class="flag-list">${data.flags.map(f => `<li>${f}</li>`).join('')}</ul>`;
    }

    resultsPanel.innerHTML = `
        <div class="risk-overview">
            <!-- Risk Badge -->
            <div class="risk-badge risk-${data.risk}" id="risk-badge">
                <span class="risk-badge-icon">${riskIcon}</span>
                <div class="risk-badge-text">
                    <div class="risk-badge-label">Overall Risk Level${data.resolved_name ? ' — ' + data.resolved_name.split(',')[0] : ''}</div>
                    <div class="risk-badge-value">${data.risk} RISK</div>
                </div>
            </div>

            <!-- WHY THIS RISK — Explainability Block -->
            <div class="why-block why-${data.risk}">
                <div class="why-title">📋 Why ${data.risk} Risk?</div>
                <p class="why-text">${whyText}</p>
                <div class="why-rule">${ruleText}</div>
            </div>

            <!-- Risk Gauge -->
            <div class="risk-gauge-container">
                <div class="risk-gauge">
                    <svg viewBox="0 0 160 90">
                        <path class="gauge-bg" d="M 15 80 A 65 65 0 0 1 145 80" />
                        <path class="gauge-fill" id="gauge-arc"
                              d="M 15 80 A 65 65 0 0 1 145 80"
                              stroke="${gaugeColor}"
                              style="stroke-dasharray: 204; stroke-dashoffset: 204;" />
                    </svg>
                    <div class="gauge-label">
                        <div class="gauge-value" style="color: ${gaugeColor}">${minDist}m</div>
                        <div class="gauge-unit">nearest zone</div>
                    </div>
                </div>
            </div>

            <!-- Detail Cards -->
            <div class="detail-cards">
                <div class="detail-card">
                    <div class="detail-card-header">
                        <span class="detail-card-icon">💧</span>
                        <span class="detail-card-title">Water Body Analysis</span>
                    </div>
                    <div class="detail-card-value">
                        <span class="risk-tag tag-${data.water_risk}">${data.water_risk}</span>
                        ${data.water_reason}
                    </div>
                </div>

                <div class="detail-card">
                    <div class="detail-card-header">
                        <span class="detail-card-icon">🌲</span>
                        <span class="detail-card-title">Forest Zone Analysis</span>
                    </div>
                    <div class="detail-card-value">
                        <span class="risk-tag tag-${data.forest_risk}">${data.forest_risk}</span>
                        ${data.forest_reason}
                    </div>
                </div>

                <div class="detail-card">
                    <div class="detail-card-header">
                        <span class="detail-card-icon">🚩</span>
                        <span class="detail-card-title">Environmental Flags</span>
                    </div>
                    <div class="detail-card-value">${flagsHtml}</div>
                </div>

                <div class="detail-card">
                    <div class="detail-card-header">
                        <span class="detail-card-icon">⚖️</span>
                        <span class="detail-card-title">Legal Risk</span>
                    </div>
                    <div class="detail-card-value">${data.legal_risk}</div>
                </div>

                <div class="detail-card">
                    <div class="detail-card-header">
                        <span class="detail-card-icon">✅</span>
                        <span class="detail-card-title">Recommendation</span>
                    </div>
                    <div class="detail-card-value" style="font-weight: 600;">${data.recommendation}</div>
                </div>
            </div>
        </div>
    `;

    // Animate gauge
    requestAnimationFrame(() => {
        const gaugeArc = document.getElementById('gauge-arc');
        if (gaugeArc) {
            const offset = 204 - (204 * gaugePercent / 100);
            gaugeArc.style.strokeDashoffset = offset;
        }
    });

    // Draw 100m buffer circle on map to visualize MEDIUM risk threshold
    drawBufferCircle(data.lat, data.lon, data.risk);
}

// ---------- Buffer Circle (100m radius) ----------
let bufferCircle = null;

function drawBufferCircle(lat, lon, risk) {
    // Remove previous circle
    if (bufferCircle) {
        map.removeLayer(bufferCircle);
        bufferCircle = null;
    }
    // Draw the 100m threshold circle
    const colors = { HIGH: '#ef4444', MEDIUM: '#f59e0b', LOW: '#22c55e' };
    const color = colors[risk] || '#888';
    bufferCircle = L.circle([lat, lon], {
        radius: 100,           // 100 meters — the MEDIUM risk threshold
        color: color,
        fillColor: color,
        fillOpacity: 0.08,
        weight: 2,
        dashArray: '6,4',
    }).addTo(map).bindTooltip('100m buffer zone (MEDIUM risk threshold)', {
        permanent: false,
        direction: 'top',
    });
}


// ---------- Error Handling ----------
function showError(msg) {
    clearError();
    const el = document.createElement('div');
    el.className = 'error-message';
    el.id = 'error-msg';
    el.textContent = msg;
    document.querySelector('.coord-panel').appendChild(el);
}

function clearError() {
    const existing = document.getElementById('error-msg');
    if (existing) existing.remove();
}

// ---------- Input Events ----------
latInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnAnalyze.click();
});

lonInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnAnalyze.click();
});

// ---------- Init ----------
document.addEventListener('DOMContentLoaded', initMap);

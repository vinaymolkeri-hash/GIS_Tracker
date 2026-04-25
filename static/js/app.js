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
const latInput = document.getElementById('input-lat');
const lonInput = document.getElementById('input-lon');
const btnAnalyze = document.getElementById('btn-analyze');
const resultsPanel = document.getElementById('results-panel');
const mapHint = document.getElementById('map-hint');
const toggleWater = document.getElementById('toggle-water');
const toggleForest = document.getElementById('toggle-forest');
const locationInput = document.getElementById('input-location');
const btnSearch = document.getElementById('btn-search');
const resolvedNameEl = document.getElementById('resolved-name');
const purposeInput = document.getElementById('input-purpose');

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function cleanLocationName(value) {
    const text = String(value ?? '')
        .replace(/\uFFFD/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    return text || 'Unknown Location';
}

function formatDistance(value) {
    if (value === 0) return '0 m';
    if (typeof value === 'number' && Number.isFinite(value)) return `${value} m`;
    return 'Not available';
}

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

        const waterData = await waterRes.json();
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
            body: JSON.stringify({ location_name: name, purpose: purposeInput.value }),
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
        if (data.location_name || data.resolved_name) {
            showResolvedName(data.location_name || data.resolved_name);
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
    resolvedNameEl.textContent = `📍 ${cleanLocationName(name)}`;
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
            body: JSON.stringify({ lat, lon, purpose: purposeInput.value }),
        });

        if (!res.ok) throw new Error(`API error: ${res.status}`);

        const data = await res.json();
        if (data.location_name || data.resolved_name) {
            showResolvedName(data.location_name || data.resolved_name);
        } else {
            hideResolvedName();
        }
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
    const riskColors = {
        HIGH: { bg: 'hsla(0,84%,60%,0.10)', border: 'hsl(0,84%,60%)', text: 'hsl(0,84%,65%)' },
        MEDIUM: { bg: 'hsla(38,92%,50%,0.10)', border: 'hsl(38,92%,50%)', text: 'hsl(38,92%,55%)' },
        LOW: { bg: 'hsla(142,71%,45%,0.10)', border: 'hsl(142,71%,45%)', text: 'hsl(142,71%,50%)' },
    };
    const icons = { HIGH: '🔴', MEDIUM: '🟡', LOW: '🟢' };
    const risk = data.risk;
    const col = riskColors[risk] || riskColors.LOW;

    // ── Distances ─────────────────────────────────────────────────
    const waterDistance = data.distance_to_water ?? data.water_distance_m ?? null;
    const forestDistance = data.distance_to_forest ?? data.forest_distance_m ?? null;
    const wDist = formatDistance(waterDistance);
    const fDist = formatDistance(forestDistance);

    // ── Location sub-heading ──────────────────────────────────────
    const locationName = cleanLocationName(data.location_name || data.resolved_name || 'Unknown Location');
    const locLabel = locationName !== 'Unknown Location'
        ? locationName
        : `${data.lat?.toFixed(4)}, ${data.lon?.toFixed(4)}`;

    // ── Purpose interpretation ────────────────────────────────────
    const purposeIcons = { residential: '🏠', farming: '🌾', commercial: '🏢' };
    const purposeLabel = data.purpose_label || '';
    const purposeRec = data.purpose_recommendation || '';
    const purposeIcon = purposeIcons[data.purpose] || '🏷️';
    const hasPurpose = !!data.purpose;
    const finalRecommendation = purposeRec || data.recommendation || 'No recommendation available.';

    // ── Structured explanation from backend ───────────────────────
    const triggeredFactors = (data.triggered_factors || []).length > 0
        ? data.triggered_factors
        : ['No water or forest zones detected within threshold distance'];
    const explanationReasons = data.explanation_reasons || [];
    const detailedExplanation = data.detailed_explanation || 'No explanation available.';

    resultsPanel.innerHTML = `
      <div class="report-card" style="
        background: ${col.bg};
        border: 1.5px solid ${col.border};
        border-radius: 12px;
        padding: 1.1rem 1.2rem;
        display: flex;
        flex-direction: column;
        gap: 0;
        animation: fadeInUp 0.3s ease;
      ">

        <!-- ① Risk Level -->
        <div class="report-section">
          <div class="report-row" style="align-items:center; gap:0.5rem; margin-bottom:0.25rem;">
            <span style="font-size:1.4rem;">${icons[risk]}</span>
            <div>
              <div class="report-label">Location</div>
              <div class="report-sub">${escapeHtml(locLabel)}</div>
            </div>
          </div>
        </div>

        <div class="report-divider"></div>

        <div class="report-section">
          <div class="report-row" style="align-items:center; gap:0.5rem; margin-bottom:0.25rem;">
            <span style="font-size:1.4rem;">⚠️</span>
            <div>
              <div class="report-label">Risk Level</div>
              <div class="report-value" style="color:${col.text}; font-size:1.3rem; font-weight:800; letter-spacing:0.04em;">
                ${escapeHtml(risk)}
              </div>
            </div>
          </div>
        </div>

        <div class="report-divider"></div>

        ${hasPurpose ? `
        <!-- ② Purpose Recommendation -->
        <div class="report-section purpose-result">
          <div class="report-label">Purpose: ${purposeIcon} ${escapeHtml(purposeLabel)}</div>
          <div class="purpose-rec-card purpose-rec-${risk.toLowerCase()}">
            <span class="purpose-rec-icon">${risk === 'HIGH' ? '⛔' : risk === 'MEDIUM' ? '⚠️' : '✅'}</span>
            <span class="purpose-rec-text">${escapeHtml(purposeRec)}</span>
          </div>
        </div>

        <div class="report-divider"></div>
        ` : ''}

        <!-- ③ Triggered Factors -->
        <div class="report-section">
          <div class="report-label">Triggered Factors</div>
          <ul class="report-list" style="border-left:2px solid ${col.border};">
            ${triggeredFactors.map(t => `<li>${escapeHtml(t)}</li>`).join('')}
          </ul>
        </div>

        <div class="report-divider"></div>

        <!-- ④ Detailed Explanation -->
        <div class="report-section">
          <div class="report-label">Detailed Explanation</div>
          <div class="explanation-block explanation-${risk.toLowerCase()}">
            <div class="explanation-text">${escapeHtml(detailedExplanation)}</div>
          </div>
          ${explanationReasons.length > 0 ? `
          <div class="explanation-reasons">
            ${explanationReasons.map(r => `
              <div class="explanation-reason-item">
                <span class="explanation-reason-bullet">›</span>
                <span>${escapeHtml(r)}</span>
              </div>
            `).join('')}
          </div>
          ` : ''}
        </div>

        <div class="report-divider"></div>

        <!-- ⑤ Distance -->
        <div class="report-section">
          <div class="report-label">Distances</div>
          <div class="report-dist-grid">
            <div class="dist-item">
              <span class="dist-icon">💧</span>
              <span class="dist-label">Water Distance</span>
              <span class="dist-val" style="color:${data.water_risk === 'HIGH' ? 'hsl(0,84%,65%)' : data.water_risk === 'MEDIUM' ? 'hsl(38,92%,55%)' : 'var(--text-secondary)'};">
                ${escapeHtml(wDist)}
              </span>
            </div>
            <div class="dist-item">
              <span class="dist-icon">🌲</span>
              <span class="dist-label">Forest Distance</span>
              <span class="dist-val" style="color:${data.forest_risk === 'HIGH' ? 'hsl(0,84%,65%)' : data.forest_risk === 'MEDIUM' ? 'hsl(38,92%,55%)' : 'var(--text-secondary)'};">
                ${escapeHtml(fDist)}
              </span>
            </div>
          </div>
        </div>

        <div class="report-divider"></div>

        <!-- ⑥ Recommendation -->
        <div class="report-section">
          <div class="report-label">Recommendation</div>
          <div class="report-rec" style="color:${col.text};">${escapeHtml(finalRecommendation)}</div>
        </div>

        <!-- ⑦ Legal -->
        <div class="report-legal">⚖️ Legal: ${escapeHtml(data.legal_risk || 'Not available')}</div>

      </div>
    `;

    // Draw 100m buffer circle on map
    drawBufferCircle(data.lat, data.lon, risk);
}

// ---------- Buffer Circle ----------
let bufferCircle = null;
function drawBufferCircle(lat, lon, risk) {
    if (bufferCircle) { map.removeLayer(bufferCircle); bufferCircle = null; }
    const colors = { HIGH: '#ef4444', MEDIUM: '#f59e0b', LOW: '#22c55e' };
    bufferCircle = L.circle([lat, lon], {
        radius: 100, color: colors[risk] || '#888',
        fillColor: colors[risk] || '#888', fillOpacity: 0.07,
        weight: 2, dashArray: '6,4',
    }).addTo(map).bindTooltip('100 m buffer zone', { permanent: false, direction: 'top' });
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
latInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') btnAnalyze.click(); });
lonInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') btnAnalyze.click(); });

// ---------- Init ----------
document.addEventListener('DOMContentLoaded', initMap);

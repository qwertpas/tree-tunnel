const map = L.map("map", { zoomControl: false, preferCanvas: true, zoomSnap: .25, zoomDelta: .5 });
L.control.zoom({ position: "topright" }).addTo(map);
map.attributionControl.setPrefix(false);
const streetTiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20, maxNativeZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);
const aerialTiles = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 20, maxNativeZoom: 19,
  attribution: 'Imagery &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics'
});
const status = document.getElementById("status");
const score = document.getElementById("score");
const search = document.getElementById("search");
const photos = L.layerGroup().addTo(map);
let streets;
let canopy;
let candidates;
let pinned;
let popupTimer;

function escape(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function read(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function style(feature) {
  const value = feature.properties.score;
  const aerial = map.hasLayer(aerialTiles);
  const color = aerial
    ? value >= .75 ? "#ffd166" : value >= .55 ? "#ffb454" : "#f59336"
    : value >= .75 ? "#176541" : value >= .55 ? "#3d875d" : "#78a77a";
  return { color, weight: aerial ? 5 : 4, opacity: aerial ? 1 : .88, lineCap: "round" };
}

function streetView(point) {
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${point.lat.toFixed(6)}%2C${point.lng.toFixed(6)}`;
}

function streetPopup(feature, point) {
  const p = feature.properties;
  return `<div class="street-popup"><strong>${escape(p.name)}</strong><div><span>${Math.round(p.length_m)} m</span><span>${Math.round(p.score * 100)}% road canopy</span>${p.access === "private" ? "<span>Private</span>" : ""}</div><a href="${escape(streetView(point))}" target="_blank" rel="noopener">Street View ↗</a></div>`;
}

function photoPopup(p) {
  const source = `<a href="${escape(p.source_url)}" target="_blank" rel="noopener">${escape(p.credit || p.source)}</a>`;
  const license = p.license_url ? `<a href="${escape(p.license_url)}" target="_blank" rel="noopener">${escape(p.license)}</a>` : escape(p.license);
  const rotation = p.rotation ?? 0;
  const image = `<a class="photo-frame${rotation % 180 ? " turned" : ""}" href="${escape(p.url)}" target="_blank" rel="noopener"><img style="transform:translate(-50%,-50%) rotate(${rotation}deg)" src="${escape(p.thumbnail)}" alt="${escape(p.title)}" loading="lazy"></a>`;
  const info = `<div class="photo-info"><strong>${escape(p.title)}</strong><div class="photo-class">${escape(p.classification)} · ${escape(p.context)}</div><span class="photo-date">${escape(p.date)}</span>${source}<div class="photo-license">${license}</div></div>`;
  return `<div class="photo-popup">${image}${info}</div>`;
}

function filter() {
  const threshold = Number(score.value) / 100;
  const query = search.value.trim().toLowerCase();
  document.getElementById("score-value").value = `≥ ${score.value}%`;
  streets.clearLayers();
  streets.addData(candidates.features.filter(feature => feature.properties.score >= threshold && feature.properties.name.toLowerCase().includes(query)));
  status.textContent = `${streets.getLayers().length.toLocaleString()} segments`;
  pinned = null;
}

function bindHover(layer) {
  layer.on("mouseover", () => {
    clearTimeout(popupTimer);
    if (!pinned) layer.openPopup();
  });
  layer.on("mouseout", () => {
    popupTimer = setTimeout(() => { if (pinned !== layer) layer.closePopup(); }, 180);
  });
  layer.on("popupclose", () => { layer.getPopup().options.autoPan = false; });
  layer.on("popupopen", () => {
    const panel = layer.getPopup().getElement();
    panel.onmouseenter = () => clearTimeout(popupTimer);
    panel.onmouseleave = () => { if (pinned !== layer) layer.closePopup(); };
  });
}

async function start() {
  const [config, lines, pictures] = await Promise.all([
    read("data/config.json"), read("data/candidates.geojson"), read("data/photos.geojson")
  ]);
  map.fitBounds(config.bounds, { padding: [20, 20] });
  candidates = lines;
  canopy = L.tileLayer(config.canopy_url, {
    opacity: .55, zIndex: 250, maxZoom: 20, maxNativeZoom: config.canopy_zoom,
    attribution: config.canopy_attribution
  });
  streets = L.geoJSON(null, {
    style,
    bubblingMouseEvents: false,
    onEachFeature(feature, layer) {
      const points = layer.getLatLngs();
      layer.bindPopup(streetPopup(feature, points[Math.floor(points.length / 2)]), { closeButton: false, autoPan: false });
      bindHover(layer);
      layer.on("click", event => {
        layer.setPopupContent(streetPopup(feature, event.latlng));
        window.open(streetView(event.latlng), "_blank", "noopener");
      });
      layer.on("mouseover", () => { layer.setStyle({ weight: 7, opacity: 1 }); layer.bringToFront(); });
      layer.on("mouseout", () => streets.resetStyle(layer));
    }
  }).addTo(map);
  const names = [...new Set(lines.features.map(feature => feature.properties.name))].sort();
  document.getElementById("streets").innerHTML = names.map(name => `<option value="${escape(name)}"></option>`).join("");
  const groups = [];
  for (const feature of pictures.features) {
    const point = L.latLng(feature.geometry.coordinates[1], feature.geometry.coordinates[0]);
    const group = groups.find(group => group.point.distanceTo(point) <= 12);
    if (group) group.items.push(feature.properties);
    else groups.push({ point, items: [feature.properties] });
  }
  for (const group of groups) {
    const marker = L.marker(group.point, {
      icon: L.divIcon({ className: `photo-dot${group.items.some(p => p.verified) ? " verified" : ""}`, iconSize: [11, 11], iconAnchor: [5.5, 5.5] }),
      title: group.items[0].title + (group.items.length > 1 ? ` · ${group.items.length} photos` : ""),
      riseOnHover: true
    }).bindPopup(`<div class="photo-list">${group.items.map(photoPopup).join("")}</div>`, { closeButton: false, autoPan: false, maxWidth: 280 }).addTo(photos);
    bindHover(marker);
    marker.on("click", () => {
      clearTimeout(popupTimer);
      pinned = marker;
      marker.openPopup();
      marker.getPopup().options.autoPan = true;
      marker.getPopup().options.autoPanPaddingTopLeft = [12, innerWidth <= 600 ? 184 : 12];
      marker.getPopup().options.autoPanPaddingBottomRight = [12, 12];
      marker.getPopup().update();
    });
  }
  filter();
  score.addEventListener("input", filter);
  search.addEventListener("input", filter);
  document.getElementById("controls").addEventListener("submit", event => {
    event.preventDefault();
    if (streets.getLayers().length) map.fitBounds(streets.getBounds(), { padding: [55, 55], maxZoom: 17 });
  });
  document.getElementById("canopy").addEventListener("change", event => {
    if (event.target.checked) canopy.addTo(map); else map.removeLayer(canopy);
  });
  document.getElementById("photos").addEventListener("change", event => {
    if (event.target.checked) photos.addTo(map); else map.removeLayer(photos);
  });
  document.getElementById("aerial").addEventListener("change", event => {
    if (event.target.checked) { map.removeLayer(streetTiles); aerialTiles.addTo(map); }
    else { map.removeLayer(aerialTiles); streetTiles.addTo(map); }
    streets.resetStyle();
  });
  map.on("popupclose", event => { if (pinned?.getPopup() === event.popup) pinned = null; });
  Object.assign(window, { map, candidates, pictures, streets, photos, canopy });
}

start().catch(error => {
  status.textContent = `Unable to load map: ${error.message}`;
  status.classList.add("error");
});

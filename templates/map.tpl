%include("header.tpl", title="Map", page="map", leaflet=True)
% import json
% colors = {'VFR': '#3ddc84', 'MVFR': '#4ea8ff', 'IFR': '#ff5a5a', 'LIFR': '#d77bff'}
% points = [{'code': s['code'], 'name': s['name'], 'cat': s['cat'], 'raw': s['raw'], 'lat': float(s['lat']), 'lon': float(s['lon']), 'color': colors.get(s['cat'], '#5b6b7e')} for s in stations if s['lat'] and s['lon']]
<section class="page-head">
    <div>
        <h1>Map</h1>
        <p>Click an airport to see its METAR.</p>
    </div>
    <div class="map-legend">
        % for c in ('VFR', 'MVFR', 'IFR', 'LIFR'):
        <span><span class="dot {{c.lower()}}"></span>{{c}}</span>
        % end
        <span><span class="dot"></span>No category</span>
    </div>
</section>

<div id="map" role="region" aria-label="Airport map"></div>

<script>
(function () {
    const map = L.map('map').setView({{config.data.geo.map.center}}, {{config.data.geo.map.zoom}});
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        className: 'tiles-dark',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    const points = {{!json.dumps(points).replace('</', '<\\/')}};
    points.forEach(function (p) {
        const popup = document.createElement('div');
        const title = document.createElement('b');
        title.textContent = p.code + (p.name ? ' · ' + p.name : '') + (p.cat ? ' · ' + p.cat : '');
        popup.appendChild(title);
        popup.appendChild(document.createElement('br'));
        popup.appendChild(document.createTextNode(p.raw || 'No METAR'));
        L.circleMarker([p.lat, p.lon], {
            radius: 8, weight: 2, color: '#0b1117', fillColor: p.color, fillOpacity: 1
        }).bindPopup(popup).addTo(map);
    });
})();
</script>

%include("footer.tpl")

// METARMap live map: mirrors the LEDs and the OLED screen of the physical map
(function () {
    'use strict';

    const settings = JSON.parse(document.getElementById('map-settings').textContent);
    const POLL_MS = 1000;
    const RADAR_REFRESH_MS = 5 * 60 * 1000;
    const FRAME_MS = 50;  // LED animation rate (20 fps is plenty for blink/pulse)

    const map = L.map('map', {zoomControl: true, attributionControl: true, zoomSnap: 0.25});

    // ---- backgrounds -------------------------------------------------------------------------
    const faaUrl = 'https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/' +
        settings.chart_service + '/MapServer/tile/{z}/{y}/{x}';
    const radarUrl = 'https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png';
    const chartName = settings.chart_label + (settings.chart_type === 'sectional' && settings.chart ? ' · ' + settings.chart : '');

    // radar tiles are cached by URL: each scan is a new layer with a new URL
    let radarAt = Date.now();
    function radarLayer() {
        return L.tileLayer(radarUrl + '?t=' + radarAt, {
            maxZoom: 16, maxNativeZoom: 12, opacity: 0.8, radar: true,
            attribution: 'Radar: NWS NEXRAD via <a href="https://mesonet.agron.iastate.edu/">Iowa Environmental Mesonet</a>'
        });
    }
    const backgrounds = {
        sectional: {
            label: settings.chart_type === 'sectional' ? 'Sectional' : settings.chart_type === 'terminal' ? 'Terminal' : 'IFR Low',
            // the FAA only has some zoom levels; Leaflet scales the nearest ones in between
            layers: [L.tileLayer(faaUrl, {
                maxZoom: 16, maxNativeZoom: 12, minNativeZoom: settings.chart_min_zoom, minZoom: settings.chart_min_zoom - 3,
                attribution: 'FAA ' + chartName
            })]
        },
        satellite: {
            label: 'Satellite',
            layers: [L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                maxZoom: 18,
                attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics'
            })]
        },
        radar: {
            label: 'Radar',
            layers: [L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 18, className: 'tiles-dark',
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            }), radarLayer()]
        }
    };

    let current = null;
    let radarInfo = null;
    function useBackground(id) {
        if (!backgrounds[id]) id = 'sectional';
        // every tile layer, including an old radar scan still waiting for the new one to load
        map.eachLayer(function (l) { if (l instanceof L.TileLayer) map.removeLayer(l); });
        current = id;
        if (id === 'radar' && radarStale()) refreshRadar();
        backgrounds[id].layers.forEach(function (l) { l.addTo(map); });
        try { localStorage.setItem('metarmap.background', id); } catch (e) { /* private mode */ }
        switcher.querySelectorAll('button').forEach(function (b) {
            b.setAttribute('aria-pressed', b.dataset.bg === id ? 'true' : 'false');
        });
        if (radarInfo) radarInfo.hidden = id !== 'radar';
    }

    // new scans while Radar is shown (and at once when it's picked again, or the screen wakes, after a while away).
    // The new scan goes on top of the old one, which is removed once it has loaded: the radar never blinks out.
    function radarStale() {
        return Date.now() - radarAt >= RADAR_REFRESH_MS;
    }
    function refreshRadar() {
        radarAt = Date.now();
        const layer = backgrounds.radar.layers[1] = radarLayer();
        if (radarInfo) radarInfo.querySelector('time').textContent = clock(new Date(radarAt));
        if (current !== 'radar') return;  // useBackground() adds it
        layer.once('load', function () {
            map.eachLayer(function (l) { if (l.options.radar && l !== layer) map.removeLayer(l); });
        });
        layer.addTo(map);
    }
    function checkRadar() {
        if (current === 'radar' && !document.hidden && radarStale()) refreshRadar();
    }
    setInterval(checkRadar, 30 * 1000);
    document.addEventListener('visibilitychange', checkRadar);

    function clock(d) {
        return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    let switcher;
    let trafficToggle, trafficNote;  // the live traffic checkbox and its status (see "live traffic" below)
    const BgControl = L.Control.extend({
        options: {position: 'topright'},
        onAdd: function () {
            const box = L.DomUtil.create('div', 'map-panel');
            switcher = L.DomUtil.create('div', 'seg-group map-switch', box);
            switcher.setAttribute('role', 'group');
            switcher.setAttribute('aria-label', 'Map background');
            Object.keys(backgrounds).forEach(function (id) {
                const b = L.DomUtil.create('button', 'seg', switcher);
                b.type = 'button';
                b.dataset.bg = id;
                b.textContent = backgrounds[id].label;
                L.DomEvent.on(b, 'click', function () { useBackground(id); });
            });
            radarInfo = L.DomUtil.create('div', 'map-note', box);
            radarInfo.innerHTML = '<span><b>NEXRAD base reflectivity</b> · <time></time> · updates every 5 min</span>' +
                '<span class="dbz"><span>dBZ 5</span><i></i><span>75</span></span>';
            radarInfo.querySelector('time').textContent = clock(new Date());
            radarInfo.hidden = true;
            const toggle = L.DomUtil.create('label', 'map-toggle', box);
            toggle.innerHTML = '<input type="checkbox"> Live traffic';
            trafficToggle = toggle.querySelector('input');
            trafficNote = L.DomUtil.create('div', 'map-note', box);
            trafficNote.hidden = true;
            L.DomEvent.disableClickPropagation(box);
            return box;
        }
    });
    new BgControl().addTo(map);

    let saved = null;
    try { saved = localStorage.getItem('metarmap.background'); } catch (e) { /* private mode */ }
    useBackground(saved || settings.background);

    // ---- legend: what the LEDs mean for the active visualizer (rendered by the server, shown on the map) -----------

    // starts closed; whether it's open is remembered in this browser
    const LEGEND_KEY = 'metarmap.legend';
    let legendBox;
    const LegendControl = L.Control.extend({
        options: {position: 'bottomleft'},
        onAdd: function () {
            const box = legendBox = L.DomUtil.create('details', 'map-key');
            L.DomUtil.create('summary', '', box);
            try { box.open = window.localStorage.getItem(LEGEND_KEY) === 'open'; } catch (e) { /* private window */ }
            box.addEventListener('toggle', function () {
                try { window.localStorage.setItem(LEGEND_KEY, box.open ? 'open' : 'closed'); } catch (e) { /* not remembered */ }
            });
            showLegend(document.querySelector('#legend-source .legend'));
            L.DomEvent.disableClickPropagation(box);
            L.DomEvent.disableScrollPropagation(box);
            return box;
        }
    });

    // `list` is the legend's <ul> (none for a visualizer without one)
    function showLegend(list) {
        const old = legendBox.querySelector('.legend');
        if (old) old.remove();
        legendBox.hidden = !list;
        if (!list) return;
        const title = document.querySelector('.vis-name b');
        legendBox.querySelector('summary').textContent = 'What the LEDs mean' + (title ? ' · ' + title.textContent : '');
        legendBox.append(list.cloneNode(true));
    }
    new LegendControl().addTo(map);

    // ---- the visualizer: the map follows it when it changes (the buttons, auto-rotate, Home Assistant) ---------
    const visName = document.querySelector('.vis-name');
    let shownVisualizer = visName ? +visName.dataset.active : null;
    let legendWanted = null;

    async function followVisualizer(vis) {
        if (vis.active === shownVisualizer || vis.active === legendWanted) return;
        legendWanted = vis.active;
        try {
            const res = await fetch('/map/legend', {cache: 'no-store'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const html = document.createElement('div');
            html.innerHTML = await res.text();
            if (legendWanted !== vis.active) return;  // changed again while this one loaded
            if (visName) visName.querySelector('b').textContent = vis.name;
            if (fullVisName) fullVisName.textContent = vis.name;
            showLegend(html.querySelector('.legend'));
            shownVisualizer = vis.active;
        } catch (err) {
            console.error('[map] legend failed', err);
        } finally {
            if (legendWanted === vis.active) legendWanted = null;  // try again on the next poll if it failed
        }
    }

    // ---- fullscreen: the browser's fullscreen, or the whole window where there's none (iPhone) ---------------
    const mapEl = document.getElementById('map');
    const canFullscreen = !!(mapEl.requestFullscreen || mapEl.webkitRequestFullscreen);
    function fullscreenElement() {
        return document.fullscreenElement || document.webkitFullscreenElement || null;
    }
    function isFull() {
        return fullscreenElement() === mapEl || mapEl.classList.contains('map-full');
    }
    let fullButton;
    function fullscreenChanged() {
        const full = isFull();
        fullButton.setAttribute('aria-pressed', full ? 'true' : 'false');
        fullButton.setAttribute('aria-label', full ? 'Exit fullscreen' : 'Fullscreen');
        fullButton.title = full ? 'Exit fullscreen (Esc)' : 'Fullscreen';
        document.body.classList.toggle('map-full-open', mapEl.classList.contains('map-full'));
        map.invalidateSize();
    }
    function toggleFullscreen() {
        if (fullscreenElement()) {
            (document.exitFullscreen || document.webkitExitFullscreen).call(document);
        } else if (mapEl.classList.contains('map-full')) {
            mapEl.classList.remove('map-full');
            fullscreenChanged();
        } else if (canFullscreen) {
            const request = mapEl.requestFullscreen || mapEl.webkitRequestFullscreen;
            Promise.resolve(request.call(mapEl)).catch(function () {
                mapEl.classList.add('map-full');  // refused (e.g. in a frame): fill the window instead
                fullscreenChanged();
            });
        } else {
            mapEl.classList.add('map-full');
            fullscreenChanged();
        }
    }
    document.addEventListener('fullscreenchange', fullscreenChanged);
    document.addEventListener('webkitfullscreenchange', fullscreenChanged);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && mapEl.classList.contains('map-full')) toggleFullscreen();
    });
    const FullscreenControl = L.Control.extend({
        options: {position: 'topleft'},
        onAdd: function () {
            const bar = L.DomUtil.create('div', 'leaflet-bar');
            const b = fullButton = L.DomUtil.create('a', 'map-fullscreen', bar);
            b.href = '#';
            b.setAttribute('role', 'button');
            b.innerHTML = '<svg class="enter" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>' +
                '<svg class="exit" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
            L.DomEvent.on(b, 'click', function (e) {
                L.DomEvent.preventDefault(e);
                toggleFullscreen();
            });
            L.DomEvent.disableClickPropagation(bar);
            return bar;
        }
    });
    new FullscreenControl().addTo(map);
    fullscreenChanged();

    // the page's visualizer buttons are outside the map, so fullscreen has its own (hidden otherwise, by CSS)
    const ARROWS = {
        previous: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>',
        next: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>'
    };
    let fullVisName = null;
    async function stepVisualizer(direction, button) {
        button.disabled = true;
        try {
            const res = await fetch('/visualizer/' + direction, {credentials: 'same-origin'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            // show the new one now, rather than at the next poll
            followVisualizer((await (await fetch('/api/live', {cache: 'no-store'})).json()).visualizer);
        } catch (err) {
            console.error('[map] visualizer ' + direction + ' failed', err);
        } finally {
            button.disabled = false;
        }
    }
    const VisualizerControl = L.Control.extend({
        options: {position: 'topright'},
        onAdd: function () {
            const box = L.DomUtil.create('div', 'map-vis');
            box.setAttribute('role', 'group');
            box.setAttribute('aria-label', 'Visualizer');
            const button = function (direction) {
                const b = L.DomUtil.create('button', 'btn icon', box);
                b.type = 'button';
                b.setAttribute('aria-label', (direction === 'next' ? 'Next' : 'Previous') + ' visualizer');
                b.innerHTML = ARROWS[direction];
                L.DomEvent.on(b, 'click', function () { stepVisualizer(direction, b); });
            };
            button('previous');
            const label = L.DomUtil.create('div', 'map-vis-name', box);
            label.innerHTML = '<span class="lbl">Visualizer</span><b></b>';
            fullVisName = label.querySelector('b');
            fullVisName.textContent = visName ? visName.querySelector('b').textContent : '';
            button('next');
            L.DomEvent.disableClickPropagation(box);
            return box;
        }
    });
    new VisualizerControl().addTo(map);

    // ---- OLED window -------------------------------------------------------------------------
    const ICONS = {
        wind: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M3 8h11a3 3 0 1 0-3-3"/><path d="M3 12h16a3 3 0 1 1-3 3"/><path d="M3 16h7"/></svg>',
        visibility: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6.5 19a4.5 4.5 0 0 1-.4-9 6 6 0 0 1 11.6 1.5A3.75 3.75 0 0 1 17.25 19z"/></svg>',
        pressure: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><circle cx="12" cy="13" r="9"/><path d="M12 13l4-4"/></svg>',
        temp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M10 14V5a2 2 0 1 1 4 0v9a4 4 0 1 1-4 0z"/></svg>',
        dewpoint: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.5S5 10.5 5 15a7 7 0 0 0 14 0c0-4.5-7-12.5-7-12.5z"/></svg>',
        date: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
        info: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2zm0-8h-2V7h2z"/></svg>'
    };
    let oled;
    const OledControl = L.Control.extend({
        options: {position: 'bottomright'},
        onAdd: function () {
            const box = L.DomUtil.create('div', 'oled');
            box.setAttribute('aria-label', 'OLED screen');
            box.innerHTML = '<div class="oled-screen" aria-live="off"></div><div class="oled-cap"><span>OLED · 128×64</span><span class="oled-status"></span></div>';
            L.DomEvent.disableClickPropagation(box);
            oled = box;
            return box;
        }
    });
    new OledControl().addTo(map);

    let lastScreenKey = '';
    function renderOled(display) {
        if (!display.enabled) {
            oled.hidden = true;
            return;
        }
        oled.hidden = false;
        const screen = display.screen;
        const key = JSON.stringify(screen) + display.on;
        if (key === lastScreenKey) return;
        lastScreenKey = key;
        const el = oled.querySelector('.oled-screen');
        el.textContent = '';
        if (!screen) {
            // turned off on the Home page, or between pages
            oled.querySelector('.oled-status').textContent = display.on === false ? 'off' : 'blank';
            return;
        }
        const add = function (cls, text) {
            const s = document.createElement('span');
            s.className = cls;
            s.textContent = text;
            el.appendChild(s);
            return s;
        };
        add('o-title' + (screen.virtual ? ' virtual' : ''), screen.title);
        add('o-badge', screen.badge || '');
        if (screen.icon && ICONS[screen.icon]) {
            add('o-ico o-ico-title', '').innerHTML = ICONS[screen.icon];
        }
        screen.lines.forEach(function (line, n) {
            add('o-line o-l' + n, line.text);
            if (line.icon && ICONS[line.icon]) {
                add('o-ico o-i' + n, '').innerHTML = ICONS[line.icon];
            }
        });
        oled.querySelector('.oled-status').textContent = screen.airport ?
            screen.airport + (screen.page ? ' · page ' + screen.page + '/2' : '') : 'message';
    }

    // ---- LEDs ------------------------------------------------------------------------------------
    const leds = {};          // pixel -> {marker, dot, data}
    let strip = null;
    let totalPixels = 1;
    let activeAirport = null;
    let lastLocateAt = null;
    let viewSet = false;

    // the popup's last tab (summary, raw or decoded), remembered in this browser
    const TAB_KEY = 'metarmap.popupTab';
    const TABS = [['summary', 'Summary'], ['raw', 'Raw'], ['decoded', 'Decoded']];
    function savedTab() {
        let tab = null;
        try { tab = window.localStorage.getItem(TAB_KEY); } catch (e) { /* private window */ }
        return TABS.some(function (t) { return t[0] === tab; }) ? tab : 'summary';
    }
    function saveTab(tab) {
        try { window.localStorage.setItem(TAB_KEY, tab); } catch (e) { /* private window: just don't remember */ }
    }

    function age(iso) {
        const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
        return minutes < 60 ? minutes + ' min ago' : Math.floor(minutes / 60) + ' h ' + (minutes % 60) + ' min ago';
    }

    // fills the Summary and Decoded tabs from /api/metar/<code>; resized() lets the popup grow to fit
    async function loadMetar(panels, code, resized) {
        panels.summary.textContent = panels.decoded.textContent = 'Loading…';
        try {
            const res = await fetch('/api/metar/' + encodeURIComponent(code), {credentials: 'same-origin'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const metar = await res.json();
            panels.summary.textContent = panels.decoded.textContent = '';
            if (!metar.decoded.length) {
                panels.summary.textContent = panels.decoded.textContent = 'Not reporting METAR data';
            } else {
                const ul = document.createElement('ul');
                ul.className = 'pop-summary';
                const item = function (text, cls) {
                    const li = document.createElement('li');
                    li.textContent = text;
                    if (cls) li.className = cls;
                    ul.appendChild(li);
                };
                metar.summary.forEach(function (line) { item(line); });
                if (metar.obsTime) item('Reported ' + age(metar.obsTime), 'age');
                panels.summary.appendChild(ul);

                const dl = document.createElement('dl');
                dl.className = 'pop-decoded';
                metar.decoded.forEach(function (line) {
                    const dt = document.createElement('dt');
                    dt.textContent = line.label;
                    const dd = document.createElement('dd');
                    dd.textContent = line.text + (line.label === 'Observed' && metar.obsTime ? ' · ' + age(metar.obsTime) : '');
                    dl.appendChild(dt);
                    dl.appendChild(dd);
                });
                panels.decoded.appendChild(dl);
            }
        } catch (err) {
            panels.summary.textContent = panels.decoded.textContent = 'Could not load the METAR (' + err.message + ')';
        }
        resized();
    }

    function popupFor(led, resized) {
        const box = document.createElement('div');
        const head = document.createElement('div');
        head.className = 'pop-head';
        const b = document.createElement('b');
        b.textContent = led.code + (led.name ? ' · ' + led.name : '');
        const pill = document.createElement('span');
        const cat = led.flightCategory;
        pill.className = 'pill' + (cat ? ' ' + cat.toLowerCase() : '');
        pill.textContent = cat || (led.raw ? 'No category' : 'No METAR');
        head.appendChild(b);
        if (led.mock) {  // dev_mode: a report typed on the Airports page, not a real one
            const mock = document.createElement('span');
            mock.className = 'badge-mock';
            mock.textContent = 'mock';
            mock.title = 'A mock METAR from the Airports page (dev_mode)';
            b.appendChild(mock);
        }
        head.appendChild(pill);
        box.appendChild(head);

        const panels = {};
        TABS.forEach(function (t) {
            panels[t[0]] = document.createElement('div');
            panels[t[0]].className = 'pop-raw';
        });
        panels.summary.className = 'pop-text';
        panels.raw.textContent = led.raw || 'Not reporting METAR data';
        let loaded = false;

        const tabs = document.createElement('div');
        tabs.className = 'pop-tabs';
        tabs.setAttribute('role', 'tablist');
        const buttons = {};
        const show = function (tab) {
            Object.keys(panels).forEach(function (name) {
                panels[name].hidden = name !== tab;
                buttons[name].setAttribute('aria-selected', name === tab ? 'true' : 'false');
            });
            if (tab !== 'raw' && !loaded) {
                loaded = true;
                loadMetar(panels, led.code, resized);
            }
            resized();
        };
        TABS.forEach(function (t) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'pop-tab';
            btn.setAttribute('role', 'tab');
            btn.textContent = t[1];
            btn.addEventListener('click', function () { saveTab(t[0]); show(t[0]); });
            buttons[t[0]] = btn;
            tabs.appendChild(btn);
        });
        box.appendChild(tabs);
        TABS.forEach(function (t) { box.appendChild(panels[t[0]]); });
        show(savedTab());
        return box;
    }

    function syncLeds(list) {
        list.forEach(function (led) {
            if (led.lat === null || led.lon === null) return;
            let entry = leds[led.pixel];
            if (!entry) {
                const icon = L.divIcon({
                    className: 'mled',
                    html: '<button type="button" class="mled-dot" aria-label="' + led.code + (led.virtual ? ' (virtual)' : '') + '"></button><span class="mled-code">' + led.code + '</span>',
                    iconSize: [0, 0]
                });
                const marker = L.marker([led.lat, led.lon], {icon: icon, keyboard: false}).addTo(map);
                // the element only exists once the map has a view; animate() looks it up
                entry = leds[led.pixel] = {marker: marker, dot: null, data: led, style: '', active: false, virtual: null};
                // content is built on each open (a content function would be rebuilt by every update())
                // pan clear of the zoom buttons and background switcher along the top of the map
                marker.bindPopup('', {className: 'led-popup', autoPanPaddingTopLeft: [10, 64]});
                marker.on('popupopen', function (e) {
                    const popup = e.popup;
                    popup.setContent(popupFor(entry.data, function () { if (popup.isOpen()) popup.update(); }));
                });
            }
            entry.data = led;
            totalPixels = Math.max(totalPixels, led.pixel + 1);
        });
    }

    function setView() {
        if (viewSet) return;
        const points = Object.values(leds).map(function (e) { return [e.data.lat, e.data.lon]; });
        const b = settings.chart_bounds;
        if (settings.view === 'chart' && b) {
            map.fitBounds([[b.south, b.west], [b.north, b.east]]);
        } else if (settings.view === 'custom' || !points.length) {
            map.setView(settings.center, settings.zoom);
        } else {
            map.fitBounds(points, {padding: [24, 24]});
        }
        viewSet = true;
    }

    // what one LED looks like at time t (seconds); mirrors the adafruit_led_animation effects
    function frame(look, pixel, t) {
        const c = look.colors || [];
        switch (look.effect) {
            case 'off':
                return null;
            case 'blink':  // a second color is shown instead of off
                return Math.floor(t / (look.period / 2)) % 2 === 0 ? {c: c[0], a: 1} : (c[1] ? {c: c[1], a: 1} : null);
            case 'pulse': {  // between full and look.low (0 = dark)
                const low = look.low || 0;
                return {c: c[0], a: low + (1 - low) * (0.5 - 0.5 * Math.cos(2 * Math.PI * t / look.period))};
            }
            case 'cycle':
                return {c: c[Math.floor(t / look.step) % c.length], a: 1};
            case 'rainbow':
                return {c: 'hsl(' + Math.round(((t / look.period) + pixel / totalPixels) % 1 * 360) + ' 100% 50%)', a: 1};
            case 'chase': {
                const width = look.size + look.spacing;
                const offset = Math.floor(t / look.step) % width;
                return ((pixel - offset) % width + width) % width < look.size ? {c: c[0], a: 1} : null;
            }
            default:
                return c.length ? {c: c[0], a: 1} : null;
        }
    }

    function animate() {
        const t = performance.now() / 1000;
        Object.keys(leds).forEach(function (pixel) {
            const e = leds[pixel];
            if (!e.dot) {
                const el = e.marker.getElement();
                if (!el) return;
                e.dot = el.querySelector('.mled-dot');
            }
            // an airport with no report is an open ring, unless a whole-strip effect (rainbow, chase) lights its LED;
            // a virtual airport has no LED on the strip: its own look says whether it joins in (rainbow) or not
            const noData = !strip && !e.data.raw;
            const f = noData ? null : frame(strip && !e.data.virtual ? strip : e.data.look, +pixel, t);
            const style = noData ? 'no-data' : f ? '--c:' + f.c + ';opacity:' + Math.max(0.08, f.a).toFixed(2) : '';
            if (style !== e.style) {
                e.dot.setAttribute('style', noData ? '' : style);
                e.dot.classList.toggle('off', !f && !noData);
                e.dot.classList.toggle('no-data', noData);
                e.dot.parentElement.classList.toggle('no-data', noData);
                e.style = style;
            }
            const virtual = !!e.data.virtual;  // a dashed circle: on the web map only, no LED
            if (virtual !== e.virtual) {
                e.dot.parentElement.classList.toggle('virtual', virtual);
                e.virtual = virtual;
            }
            const active = e.data.code === activeAirport;
            if (active !== e.active) {
                e.dot.classList.toggle('active', active);
                e.active = active;
            }
        });
    }

    function pulse(pixel) {
        const e = leds[pixel];
        if (!e || !e.dot) return;
        e.dot.classList.remove('locate');
        void e.dot.offsetWidth;  // restart the animation
        e.dot.classList.add('locate');
    }

    // ---- live traffic: aircraft from adsb.fi, through the map (/api/traffic); ticked on in this browser -----------
    // Between updates every aircraft glides along its track at its ground speed. Clicking one opens its details and
    // follows it (the map keeps it centered and draws its trail) until the popup closes or the map is dragged.
    const TRAFFIC_KEY = 'metarmap.traffic';
    const GLIDE_MS = 250;
    const MAX_GLIDE_S = 60;  // no further than this past its last report
    const TRAIL_POINTS = 720;
    const TRAFFIC_CREDIT = 'Traffic: <a href="https://adsb.fi/" target="_blank" rel="noopener">adsb.fi</a>';
    // an aircraft's shape by its kind (from its ADS-B category and type, see metarmap.traffic); its size is in the CSS
    const JET = '<path d="M12 1.5c.8 0 1.3.9 1.3 2v5.4l7.9 4.7v2.1l-7.9-2.5v5l2.3 1.7v1.8L12 20.6l-3.6 1.1v-1.8l2.3-1.7v-5l-7.9 2.5v-2.1l7.9-4.7V3.5c0-1.1.5-2 1.3-2z"/>';
    const TWIN = '<ellipse cx="16.6" cy="12.2" rx=".9" ry="1.7"/><ellipse cx="7.4" cy="12.2" rx=".9" ry="1.7"/>';
    const FOUR = '<ellipse cx="15.6" cy="11.8" rx=".8" ry="1.5"/><ellipse cx="18.8" cy="13.3" rx=".8" ry="1.5"/>' +
        '<ellipse cx="8.4" cy="11.8" rx=".8" ry="1.5"/><ellipse cx="5.2" cy="13.3" rx=".8" ry="1.5"/>';
    const SHAPES = {
        light: '<path d="M10.8 4.5C10.8 3 11.3 2 12 2s1.2 1 1.2 2.5v4h8.8c.3 0 .5.2.5.5v2c0 .3-.2.5-.5.5h-8.8V18h3c.3 0 .5.2.5.5v1.4c0 .3-.2.5-.5.5h-3l-.5 1.6h-1.4l-.5-1.6h-3c-.3 0-.5-.2-.5-.5v-1.4c0-.3.2-.5.5-.5h3v-6.5H2c-.3 0-.5-.2-.5-.5V9c0-.3.2-.5.5-.5h8.8z"/><rect x="9.6" y="1" width="4.8" height=".9" rx=".45"/>',
        small: JET,
        large: JET + TWIN,
        heavy: JET + TWIN,
        super: JET + FOUR,
        unknown: JET,
        helicopter: '<circle cx="12" cy="10" r="9" fill-opacity=".18"/><ellipse cx="12" cy="10.5" rx="2.8" ry="4.3"/>' +
            '<rect x="11.4" y="14" width="1.2" height="7.5" rx=".6"/><rect x="9.6" y="19.8" width="4.8" height="1.1" rx=".5"/>' +
            '<path d="M5.6 3.6l12.8 12.8M18.4 3.6L5.6 16.4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
        glider: '<ellipse cx="12" cy="4.6" rx="1" ry="2"/><rect x="11.4" y="3.5" width="1.2" height="17.5" rx=".6"/>' +
            '<rect x=".5" y="8.6" width="23" height="1.5" rx=".75"/><rect x="8.5" y="19" width="7" height="1.2" rx=".6"/>',
        balloon: '<circle cx="12" cy="9" r="6.5"/><rect x="10.3" y="18.5" width="3.4" height="2.8" rx=".5"/>' +
            '<path d="M7.2 12.6l3.4 5.9M16.8 12.6l-3.4 5.9" stroke="currentColor" stroke-width=".9"/>',
        drone: '<path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="1.8"/><rect x="9.8" y="9.8" width="4.4" height="4.4" rx="1"/>' +
            '<circle cx="6" cy="6" r="2.6" fill-opacity=".6"/><circle cx="18" cy="6" r="2.6" fill-opacity=".6"/>' +
            '<circle cx="6" cy="18" r="2.6" fill-opacity=".6"/><circle cx="18" cy="18" r="2.6" fill-opacity=".6"/>',
        vehicle: '<rect x="7" y="4" width="10" height="16" rx="2.5"/><rect x="8.5" y="6" width="7" height="3" rx="1" fill="#000" fill-opacity=".35"/>'
    };
    const KIND_LABELS = {light: 'Light (under 15,500 lb)', small: 'Small or fast (15,500–75,000 lb, or military)',
        large: 'Large (75,000–300,000 lb)', heavy: 'Heavy (over 300,000 lb)', super: 'Super heavy (A380, 747, An-124…)',
        helicopter: 'Helicopter', glider: 'Glider', balloon: 'Balloon or airship', drone: 'Drone', vehicle: 'Ground vehicle'};

    function kindOf(a) {
        return SHAPES[a.kind] ? a.kind : 'unknown';
    }

    function shapeSvg(kind) {
        return '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' + SHAPES[kind] + '</svg>';
    }
    const EMERGENCY_SQUAWKS = {'7500': 'Hijack', '7600': 'Radio failure', '7700': 'Emergency'};
    const aircraft = {};  // hex -> {marker, data, el, track, pop}
    let trafficOn = false;
    let trafficTimer = null;
    let trafficAsking = false;  // a request to /api/traffic is in flight
    let glideTimer = null;
    let trafficInterval = 5;
    let serverSkew = 0;  // this browser's clock minus the map's
    let followed = null;  // {hex, points, trail}

    function serverNow() {
        return Date.now() / 1000 - serverSkew;
    }

    // where an aircraft is now: its last report moved along its track at its ground speed
    function glide(a) {
        if (!a.gs || a.track === null) return [a.lat, a.lon];
        const nm = a.gs * Math.min(MAX_GLIDE_S, Math.max(0, serverNow() - a.at)) / 3600;
        const rad = a.track * Math.PI / 180;
        return [a.lat + nm * Math.cos(rad) / 60, a.lon + nm * Math.sin(rad) / (60 * Math.cos(a.lat * Math.PI / 180))];
    }

    function callsign(a) {
        return a.flight || a.reg || a.hex.toUpperCase();
    }

    function emergencyOf(a) {
        return EMERGENCY_SQUAWKS[a.squawk] || (a.emergency ? a.emergency.replace(/^\w/, function (c) { return c.toUpperCase(); }) : null);
    }

    function feet(n) {
        return Math.round(n).toLocaleString() + ' ft';
    }

    // the popup: built once, its values refreshed by fillPopup()
    function aircraftPopup(entry) {
        const box = document.createElement('div');
        box.innerHTML = '<div class="pop-head"><b></b><span class="pill"></span></div><dl class="pop-decoded"></dl>' +
            '<a class="ac-link" target="_blank" rel="noopener"></a>';
        entry.pop = {box: box, title: box.querySelector('b'), pill: box.querySelector('.pill'), dl: box.querySelector('dl'),
            link: box.querySelector('a')};
        fillPopup(entry);
        return box;
    }

    function fillPopup(entry) {
        const p = entry.pop;
        if (!p) return;
        const a = entry.data;
        p.title.textContent = callsign(a);
        const emergency = emergencyOf(a);
        p.pill.className = 'pill' + (emergency ? ' ac-emergency' : '');
        p.pill.textContent = emergency || (a.ground ? 'Ground' : a.alt !== null ? feet(a.alt) : '');
        p.pill.hidden = !p.pill.textContent;
        const vrate = a.vrate && Math.abs(a.vrate) >= 100 ? (a.vrate > 0 ? ' ↑ ' : ' ↓ ') + Math.abs(Math.round(a.vrate)).toLocaleString() + ' ft/min' : '';
        const rows = [
            ['Aircraft', [a.desc, a.type && a.desc ? '(' + a.type + ')' : a.type].filter(Boolean).join(' ')],
            ['Class', KIND_LABELS[kindOf(a)]],
            ['Operator', a.operator],
            ['Registration', a.reg],
            ['Callsign', a.flight],
            ['Altitude', a.ground ? 'On the ground' : a.alt !== null ? feet(a.alt) + vrate : null],
            ['Speed', a.gs !== null ? Math.round(a.gs) + ' kt' : null],
            ['Track', a.track !== null ? String(Math.round(a.track) % 360).padStart(3, '0') + '°' : null],
            ['Squawk', a.squawk ? a.squawk + (emergency ? ' · ' + emergency : '') : null],
            ['ICAO', a.hex.toUpperCase()],
            ['Position', Math.max(0, Math.round(serverNow() - a.at)) + ' s old']
        ];
        p.dl.textContent = '';
        rows.forEach(function (r) {
            if (!r[1]) return;
            const dt = document.createElement('dt');
            dt.textContent = r[0];
            const dd = document.createElement('dd');
            dd.textContent = r[1];
            p.dl.appendChild(dt);
            p.dl.appendChild(dd);
        });
        p.link.href = 'https://globe.adsb.fi/?icao=' + encodeURIComponent(a.hex);
        p.link.textContent = 'Open on globe.adsb.fi';
    }

    function follow(hex) {
        unfollow();
        const entry = aircraft[hex];
        if (!entry) return;
        const here = glide(entry.data);
        followed = {hex: hex, points: [[entry.data.lat, entry.data.lon]], at: entry.data.at,
            trail: L.polyline([here], {color: '#f5b544', weight: 2, opacity: 0.85, interactive: false}).addTo(map)};
        entry.marker.setZIndexOffset(1000);
        styleAircraft(entry);
        map.panTo(here);
    }

    function unfollow() {
        if (!followed) return;
        const entry = aircraft[followed.hex];
        map.removeLayer(followed.trail);
        followed = null;
        if (entry) {
            entry.marker.setZIndexOffset(-1000);
            styleAircraft(entry);
        }
    }
    map.on('dragstart', unfollow);  // looking somewhere else; the popup stays open

    // the plane's color and heading (the element only exists once the map has a view)
    function styleAircraft(entry) {
        const el = entry.el || (entry.el = entry.marker.getElement());
        if (!el) return;
        const a = entry.data;
        el.classList.toggle('ground', a.ground);
        el.classList.toggle('emergency', !!emergencyOf(a));
        el.classList.toggle('followed', !!followed && followed.hex === a.hex);
        el.querySelector('.ac-code').textContent = callsign(a);
        const kind = kindOf(a);
        if (kind !== entry.kind) {  // e.g. its type arrived after its first report
            if (entry.kind) el.classList.remove('k-' + entry.kind);
            el.classList.add('k-' + kind);
            el.querySelector('.ac-plane').innerHTML = shapeSvg(kind);
            entry.kind = kind;
        }
        if (a.track !== entry.track) {
            el.querySelector('.ac-plane').style.setProperty('--track', (a.track || 0) + 'deg');
            entry.track = a.track;
        }
    }

    function syncAircraft(list) {
        const seen = {};
        list.forEach(function (a) {
            seen[a.hex] = true;
            let entry = aircraft[a.hex];
            if (!entry) {
                const icon = L.divIcon({
                    className: 'ac',
                    // styleAircraft() puts in the shape for its kind
                    html: '<button type="button" class="ac-plane" aria-label="Aircraft ' + callsign(a).replace(/[^\w-]/g, '') + '"></button><span class="ac-code"></span>',
                    iconSize: [0, 0]
                });
                // under the airports, so the LEDs stay easy to click
                const marker = L.marker([a.lat, a.lon], {icon: icon, keyboard: false, zIndexOffset: -1000}).addTo(map);
                entry = aircraft[a.hex] = {marker: marker, data: a, el: null, track: undefined, kind: null, pop: null};
                marker.bindPopup('', {className: 'led-popup', autoPanPaddingTopLeft: [10, 64]});
                marker.on('popupopen', function (e) {
                    e.popup.setContent(aircraftPopup(entry));
                    follow(a.hex);
                });
                marker.on('popupclose', function () {
                    entry.pop = null;
                    if (followed && followed.hex === a.hex) unfollow();
                });
            }
            entry.data = a;
            if (followed && followed.hex === a.hex && a.at !== followed.at) {
                followed.points.push([a.lat, a.lon]);
                if (followed.points.length > TRAIL_POINTS) followed.points.shift();
                followed.at = a.at;
            }
            styleAircraft(entry);
            if (entry.pop) {
                fillPopup(entry);
                entry.marker.getPopup().update();  // its size may have changed
            }
        });
        Object.keys(aircraft).forEach(function (hex) {
            if (seen[hex]) return;
            const entry = aircraft[hex];
            if (followed && followed.hex === hex) unfollow();
            entry.marker.closePopup();
            map.removeLayer(entry.marker);
            delete aircraft[hex];
        });
        moveAircraft();
    }

    function moveAircraft() {
        Object.keys(aircraft).forEach(function (hex) {
            const entry = aircraft[hex];
            if (!entry.el) styleAircraft(entry);
            entry.marker.setLatLng(glide(entry.data));
        });
        if (followed && aircraft[followed.hex]) {
            const here = aircraft[followed.hex].marker.getLatLng();
            followed.trail.setLatLngs(followed.points.concat([here]));
            map.panTo(here, {animate: false});
        }
    }

    function trafficStatus(t) {
        const count = t.aircraft.length;
        let text;
        if (t.error) {
            text = 'Live traffic: ' + t.error + (t.fetched ? ' · last update ' + clock(new Date((t.fetched + serverSkew) * 1000)) : '');
        } else if (t.fetched === null) {
            text = 'Live traffic: loading…';
        } else {
            text = count + ' aircraft within ' + t.radius + ' NM · every ' + t.interval + ' s';
        }
        trafficNote.textContent = text;
        trafficNote.hidden = false;
    }

    async function pollTraffic() {
        if (trafficAsking) return;  // the one in flight schedules the next
        trafficTimer = null;
        if (!trafficOn) return;
        if (!document.hidden) {
            trafficAsking = true;
            try {
                const res = await fetch('/api/traffic', {cache: 'no-store'});
                if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
                const t = await res.json();
                if (!trafficOn) return;  // ticked off while it loaded (finally still clears trafficAsking)
                serverSkew = Date.now() / 1000 - t.now;
                trafficInterval = Math.max(1, t.interval || trafficInterval);
                syncAircraft(t.aircraft);
                trafficStatus(t);
            } catch (err) {
                console.error('[map] traffic failed', err);
                trafficNote.textContent = 'Live traffic: the map can\'t be reached';
                trafficNote.hidden = !trafficOn;
            } finally {
                trafficAsking = false;
            }
        }
        if (trafficOn && !trafficTimer) trafficTimer = setTimeout(pollTraffic, trafficInterval * 1000);
    }

    function showTraffic(on) {
        trafficOn = on;
        trafficToggle.checked = on;
        try { localStorage.setItem(TRAFFIC_KEY, on ? 'on' : 'off'); } catch (e) { /* private mode */ }
        clearTimeout(trafficTimer);
        clearInterval(glideTimer);
        trafficTimer = glideTimer = null;
        if (on) {
            map.attributionControl.addAttribution(TRAFFIC_CREDIT);
            trafficNote.textContent = 'Live traffic: loading…';
            trafficNote.hidden = false;
            glideTimer = setInterval(moveAircraft, GLIDE_MS);
            pollTraffic();
        } else {
            map.attributionControl.removeAttribution(TRAFFIC_CREDIT);
            trafficNote.hidden = true;
            unfollow();
            syncAircraft([]);
        }
    }
    trafficToggle.addEventListener('change', function () { showTraffic(trafficToggle.checked); });
    document.addEventListener('visibilitychange', function () {
        if (trafficOn && !document.hidden) {
            clearTimeout(trafficTimer);
            pollTraffic();
        }
    });
    try { if (localStorage.getItem(TRAFFIC_KEY) === 'on') showTraffic(true); } catch (e) { /* private mode */ }

    async function poll() {
        try {
            const res = await fetch('/api/live', {cache: 'no-store'});
            const live = await res.json();
            syncLeds(live.leds);
            strip = live.strip;
            followVisualizer(live.visualizer);
            setView();
            const screen = live.display.screen;
            activeAirport = screen && screen.airport;
            renderOled(live.display);
            const loc = live.locate;
            if (loc && loc.at !== lastLocateAt) {
                // only replay pulses that happened since the page opened
                if (lastLocateAt !== null || live.now - loc.at < 2) pulse(loc.pixel);
                lastLocateAt = loc.at;
            } else if (!loc && lastLocateAt === null) {
                lastLocateAt = 0;
            }
        } catch (err) {
            console.error('[map] poll failed', err && err.stack || err);
            if (oled) oled.querySelector('.oled-status').textContent = 'offline';
        } finally {
            setTimeout(poll, POLL_MS);
        }
    }

    poll();
    setInterval(animate, FRAME_MS);
})();

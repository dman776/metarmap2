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

    const radarOverlay = L.tileLayer(radarUrl + '?t=' + Date.now(), {
        maxZoom: 16, maxNativeZoom: 12, opacity: 0.8,
        attribution: 'Radar: NWS NEXRAD via <a href="https://mesonet.agron.iastate.edu/">Iowa Environmental Mesonet</a>'
    });
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
            }), radarOverlay]
        }
    };

    let current = null;
    let radarInfo = null;
    function useBackground(id) {
        if (!backgrounds[id]) id = 'sectional';
        if (current) backgrounds[current].layers.forEach(function (l) { map.removeLayer(l); });
        backgrounds[id].layers.forEach(function (l) { l.addTo(map); });
        current = id;
        try { localStorage.setItem('metarmap.background', id); } catch (e) { /* private mode */ }
        switcher.querySelectorAll('button').forEach(function (b) {
            b.setAttribute('aria-pressed', b.dataset.bg === id ? 'true' : 'false');
        });
        if (radarInfo) radarInfo.hidden = id !== 'radar';
    }

    // radar tiles are cached by URL; bump it so new scans appear
    setInterval(function () {
        radarOverlay.setUrl(radarUrl + '?t=' + Date.now());
        if (radarInfo) radarInfo.querySelector('time').textContent = clock(new Date());
    }, RADAR_REFRESH_MS);

    function clock(d) {
        return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    let switcher;
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
            radarInfo.innerHTML = '<b>NEXRAD base reflectivity</b> · <time></time> · updates every 5 min' +
                '<span class="dbz"><span>dBZ 5</span><i></i><span>75</span></span>';
            radarInfo.querySelector('time').textContent = clock(new Date());
            radarInfo.hidden = true;
            L.DomEvent.disableClickPropagation(box);
            return box;
        }
    });
    new BgControl().addTo(map);

    let saved = null;
    try { saved = localStorage.getItem('metarmap.background'); } catch (e) { /* private mode */ }
    useBackground(saved || settings.background);

    // ---- legend: what the LEDs mean for the active visualizer (rendered by the server, shown on the map) -----------

    const LegendControl = L.Control.extend({
        options: {position: 'bottomleft'},
        onAdd: function () {
            const source = document.querySelector('#legend-source .legend');
            const box = L.DomUtil.create('details', 'map-key');
            if (!source) {
                box.hidden = true;
                return box;
            }
            const title = document.querySelector('.vis-name b');
            const summary = L.DomUtil.create('summary', '', box);
            summary.textContent = 'What the LEDs mean' + (title ? ' · ' + title.textContent : '');
            box.append(source.cloneNode(true));
            // open on a wide screen; on a phone it would cover the map
            box.open = window.matchMedia('(min-width: 900px)').matches;
            L.DomEvent.disableClickPropagation(box);
            L.DomEvent.disableScrollPropagation(box);
            return box;
        }
    });
    new LegendControl().addTo(map);

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
        const key = JSON.stringify(screen);
        if (key === lastScreenKey) return;
        lastScreenKey = key;
        const el = oled.querySelector('.oled-screen');
        el.textContent = '';
        if (!screen) {
            oled.querySelector('.oled-status').textContent = 'blank';
            return;
        }
        const add = function (cls, text) {
            const s = document.createElement('span');
            s.className = cls;
            s.textContent = text;
            el.appendChild(s);
            return s;
        };
        add('o-title', screen.title);
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

    // the popup's last tab (raw or decoded), remembered in this browser
    const TAB_KEY = 'metarmap.popupTab';
    function savedTab() {
        try { return window.localStorage.getItem(TAB_KEY) === 'decoded' ? 'decoded' : 'raw'; } catch (e) { return 'raw'; }
    }
    function saveTab(tab) {
        try { window.localStorage.setItem(TAB_KEY, tab); } catch (e) { /* private window: just don't remember */ }
    }

    function age(iso) {
        const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
        return minutes < 60 ? minutes + ' min ago' : Math.floor(minutes / 60) + ' h ' + (minutes % 60) + ' min ago';
    }

    // fills the Decoded tab from /api/metar/<code>; resized() lets the popup grow to fit
    async function loadDecoded(panel, code, resized) {
        panel.textContent = 'Loading…';
        try {
            const res = await fetch('/api/metar/' + encodeURIComponent(code), {credentials: 'same-origin'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const metar = await res.json();
            panel.textContent = '';
            if (!metar.decoded.length) {
                panel.textContent = 'Not reporting METAR data';
            } else {
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
                panel.appendChild(dl);
            }
        } catch (err) {
            panel.textContent = 'Could not load the decoded METAR (' + err.message + ')';
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
        head.appendChild(pill);
        box.appendChild(head);

        const raw = document.createElement('div');
        raw.className = 'pop-raw';
        raw.textContent = led.raw || 'Not reporting METAR data';
        const decoded = document.createElement('div');
        decoded.className = 'pop-raw';
        const panels = {raw: raw, decoded: decoded};
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
            if (tab === 'decoded' && !loaded) {
                loaded = true;
                loadDecoded(decoded, led.code, resized);
            }
            resized();
        };
        [['raw', 'Raw'], ['decoded', 'Decoded']].forEach(function (t) {
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
        box.appendChild(raw);
        box.appendChild(decoded);
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
                    html: '<button type="button" class="mled-dot" aria-label="' + led.code + '"></button><span class="mled-code">' + led.code + '</span>',
                    iconSize: [0, 0]
                });
                const marker = L.marker([led.lat, led.lon], {icon: icon, keyboard: false}).addTo(map);
                // the element only exists once the map has a view; animate() looks it up
                entry = leds[led.pixel] = {marker: marker, dot: null, data: led, style: '', active: false};
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
            case 'blink':
                return Math.floor(t / (look.period / 2)) % 2 === 0 ? {c: c[0], a: 1} : null;
            case 'pulse':
                return {c: c[0], a: 0.5 - 0.5 * Math.cos(2 * Math.PI * t / look.period)};
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
            // an airport with no report is an open ring, unless a whole-strip effect (rainbow, chase) lights its LED
            const noData = !strip && !e.data.raw;
            const f = noData ? null : frame(strip || e.data.look, +pixel, t);
            const style = noData ? 'no-data' : f ? '--c:' + f.c + ';opacity:' + Math.max(0.08, f.a).toFixed(2) : '';
            if (style !== e.style) {
                e.dot.setAttribute('style', noData ? '' : style);
                e.dot.classList.toggle('off', !f && !noData);
                e.dot.classList.toggle('no-data', noData);
                e.dot.parentElement.classList.toggle('no-data', noData);
                e.style = style;
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

    async function poll() {
        try {
            const res = await fetch('/api/live', {cache: 'no-store'});
            const live = await res.json();
            syncLeds(live.leds);
            strip = live.strip;
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

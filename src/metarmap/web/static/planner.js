// MetarMap2 Web: Config > Plan a new chart. The form, the job's progress and the Map and Board views of the plan.
(function () {
    'use strict';

    const root = document.getElementById('planner');
    if (!root) return;

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const MM_IN = 25.4;
    const POLL_MS = 1500;
    const LABEL_ZOOM = 8;  // the Map shows the airport codes from this zoom up, or always when there are few pixels
    const FEW_PIXELS = 40;
    const ZOOMS = [1, 1.5, 2, 3, 4, 6];

    const $ = function (id) { return document.getElementById(id); };
    const boards = JSON.parse(root.dataset.boards || '{}');  // chart -> [height / width, height note]
    const fields = {
        chart: $('pl-chart'), source: $('pl-source'), codes: $('pl-codes'), target: $('pl-target'),
        number: $('pl-number'), strings: $('pl-strings'), coverage: $('pl-coverage'), fresh: $('pl-fresh'), width: $('pl-width'),
        height: $('pl-height'), pitch: $('pl-pitch'), gap: $('pl-gap'), move: $('pl-move'), len: $('pl-len'),
        tol: $('pl-tol'), sizes: $('pl-sizes'), corner: $('pl-corner'), bright: $('pl-bright'),
        ma5: $('pl-ma5'), ma12: $('pl-ma12'),
    };
    const form = $('planner-form');
    const goButton = $('pl-go');
    const cancelButton = $('pl-cancel');
    const errorBox = $('pl-error');
    let polling = null;
    let pollGen = 0;  // each polling chain has its own number; stopPolling() makes the one in flight stale
    let heightTouched = false;
    let stringsTouched = false;  // the user typed a number of strings: stop following the default
    let zoom = 0;
    let board = null;  // the last result's board, for the Board view's size
    let lastResult = null;
    let jobRunning = false;
    const currentCodes = Array.prototype.map.call($('pl-keep').querySelectorAll('input'), function (b) { return b.value; });
    const unlocated = Array.prototype.filter.call($('pl-keep').querySelectorAll('input'), function (b) { return b.dataset.unlocated; })
        .map(function (b) { return b.value; });
    const names = {};  // airport code -> name, for the must-keep tooltips: the current airports, then each result's
    Array.prototype.forEach.call($('pl-keep').querySelectorAll('label'), function (l) {
        if (l.dataset.code && l.title) names[l.dataset.code] = l.title;
    });

    // ---- small helpers ----------------------------------------------------------------------------------------

    function el(tag, attrs, text) {
        const node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function svg(tag, attrs, text) {
        const node = document.createElementNS(SVG_NS, tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function add(parent, children) {
        children.forEach(function (c) { if (c) parent.appendChild(c); });
        return parent;
    }

    // a length in both units: 120 mm / 4.7 in
    function len(mm) {
        return Math.round(mm) + ' mm / ' + (mm / MM_IN).toFixed(1) + ' in';
    }

    function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many || one + 's'); }

    function showError(text) {
        errorBox.textContent = text || '';
        errorBox.hidden = !text;
    }

    // ---- the form ---------------------------------------------------------------------------------------------

    function sourceCodes() {
        if (fields.source.value === 'paste') {
            const found = [];
            fields.codes.value.toUpperCase().split(/[\s,;]+/).forEach(function (c) {
                if (c && found.indexOf(c) < 0) found.push(c);
            });
            return found;
        }
        return currentCodes;
    }

    function keptNow() {
        return Array.prototype.filter.call($('pl-keep').querySelectorAll('input'), function (b) { return b.checked; })
            .map(function (b) { return b.value; });
    }

    // the must-keep ticks follow the source: the current airports (ticked when recommending, unless start fresh), or
    // the pasted codes
    function buildKeep(ticked) {
        const box = $('pl-keep');
        const codes = sourceCodes();
        const keep = {};
        (ticked || keptNow()).forEach(function (c) { keep[c] = true; });
        while (box.firstChild) box.removeChild(box.firstChild);
        codes.forEach(function (code) {
            const label = el('label', {'class': 'keep', 'data-code': code});
            if (names[code]) label.setAttribute('title', names[code]);
            const input = el('input', {type: 'checkbox', value: code});
            input.checked = !!keep[code];
            if (unlocated.indexOf(code) >= 0 && fields.source.value === 'current') input.dataset.unlocated = '1';
            add(label, [input, document.createTextNode(' '), el('span', {'class': 'mono'}, code)]);
            box.appendChild(label);
        });
        $('pl-keep-set').hidden = !codes.length;
        const bad = $('pl-unlocated');
        const missing = fields.source.value === 'current' ? unlocated : [];
        bad.hidden = !missing.length;
        bad.textContent = missing.length
            ? 'No known position for ' + missing.join(', ') + ': the plan looks them up and leaves out any it still cannot find.'
            : '';
        stringsChanged();
    }

    // the strings the airports you keep already fill; the box starts there, and the help says so
    function stringsNeeded() {
        const per = Math.max(1, parseInt(fields.len.value, 10) || 50);
        return Math.max(1, Math.ceil(keptNow().length / per));
    }

    function stringsChanged() {
        const kept = keptNow().length;
        const per = Math.max(1, parseInt(fields.len.value, 10) || 50);
        const needed = stringsNeeded();
        if (!stringsTouched) fields.strings.value = needed;
        const asked = parseInt(fields.strings.value, 10);
        $('pl-strings-help').textContent = (kept
            ? 'The ' + plural(kept, 'airport') + ' you keep fill ' + plural(needed, 'string') + ' of ' + per + ' pixels.'
            : 'No airports are kept, so one string of ' + per + ' pixels is the least.')
            + (asked > needed ? ' ' + plural(asked * per, 'airport') + ' in all.' : ' Raise the number to add more airports.');
    }

    function sourceChanged() {
        const recommended = fields.source.value === 'recommended';
        buildKeep(recommended && !fields.fresh.checked ? currentCodes : []);
    }

    function boardChanged() {
        const info = boards[fields.chart.value];  // [height / width, the note for this chart's shape]
        if (!info) return;
        if (!heightTouched) fields.height.value = (parseFloat(fields.width.value || 0) * info[0]).toFixed(1).replace(/\.0$/, '');
        $('pl-height-note').textContent = info[1];
    }

    function readForm() {
        const target = fields.target.value === 'number' ? parseInt(fields.number.value, 10) : fields.target.value;
        return {
            chart: fields.chart.value,
            source: fields.source.value,
            codes: fields.source.value === 'paste' ? sourceCodes() : [],
            must_keep: keptNow(),
            start_fresh: fields.fresh.checked,
            target: target,
            strings: target === 'strings' ? parseInt(fields.strings.value, 10) : null,
            coverage: parseFloat(fields.coverage.value),
            width_in: parseFloat(fields.width.value),
            height_in: fields.height.value.trim() === '' ? null : parseFloat(fields.height.value),
            pitch: parseFloat(fields.pitch.value),
            min_gap: parseFloat(fields.gap.value),
            max_move: parseFloat(fields.move.value),
            string_len: parseInt(fields.len.value, 10),
            tolerance: parseFloat(fields.tol.value),
            suggest_sizes: fields.sizes.checked,
            start_corner: fields.corner.value || null,
            brightness: parseFloat(fields.bright.value),
            ma_white_5v: parseFloat(fields.ma5.value),
            ma_white_12v: parseFloat(fields.ma12.value),
        };
    }

    // a reloaded page shows what the running (or last) plan was asked
    function restoreForm(p) {
        if (!p) return;
        fields.chart.value = p.chart;
        fields.source.value = p.source;
        fields.codes.value = (p.codes || []).join(' ');
        fields.fresh.checked = !!p.start_fresh;
        fields.target.value = typeof p.target === 'number' ? 'number' : p.target;
        if (typeof p.target === 'number') fields.number.value = p.target;
        if (p.strings) { fields.strings.value = p.strings; stringsTouched = true; }
        fields.coverage.value = p.coverage;
        $('pl-coverage-val').textContent = p.coverage;
        fields.width.value = p.width_in;
        if (p.height_in) { fields.height.value = p.height_in; heightTouched = true; }
        fields.pitch.value = p.pitch;
        fields.gap.value = p.min_gap;
        fields.move.value = p.max_move;
        fields.len.value = p.string_len;
        fields.tol.value = p.tolerance;
        fields.sizes.checked = !!p.suggest_sizes;
        fields.corner.value = p.start_corner || '';
        fields.bright.value = p.brightness;
        fields.ma5.value = p.ma_white_5v;
        fields.ma12.value = p.ma_white_12v;
        ['source', 'target'].forEach(function (k) { fields[k].dispatchEvent(new Event('change')); });
        buildKeep(p.must_keep || []);
        boardChanged();
    }

    fields.chart.addEventListener('change', boardChanged);
    fields.width.addEventListener('input', boardChanged);
    fields.height.addEventListener('input', function () { heightTouched = fields.height.value.trim() !== ''; });
    fields.source.addEventListener('change', sourceChanged);
    fields.fresh.addEventListener('change', sourceChanged);
    fields.strings.addEventListener('input', function () { stringsTouched = fields.strings.value.trim() !== ''; stringsChanged(); });
    fields.len.addEventListener('input', stringsChanged);
    $('pl-keep').addEventListener('change', stringsChanged);
    fields.codes.addEventListener('input', function () { buildKeep(); });
    fields.coverage.addEventListener('input', function () { $('pl-coverage-val').textContent = fields.coverage.value; });
    boardChanged();
    sourceChanged();

    // ---- the job ----------------------------------------------------------------------------------------------

    async function send(url, method, body) {
        const res = await fetch(url, {
            method: method,
            credentials: 'same-origin',
            headers: body ? {'Content-Type': 'application/json'} : {},
            body: body ? JSON.stringify(body) : undefined,
        });
        let data = null;
        try { data = await res.json(); } catch (e) { /* not JSON: an error page */ }
        return {status: res.status, data: data};
    }

    function setRunning(running) {
        jobRunning = running;
        if (running) resetApply();
        applyChanged();
        goButton.disabled = running;
        cancelButton.hidden = !running;
        $('pl-progress').hidden = !running;
    }

    function showProgress(job) {
        const bar = $('pl-bar');
        if (job.fraction === null || job.fraction === undefined) bar.removeAttribute('value');
        else bar.value = job.fraction;
        const secs = job.elapsed || 0;
        const label = $('pl-label');
        const text = job.label || 'Working';
        if (label.textContent !== text) label.textContent = text;  // a live region: only a new label is read out
        $('pl-elapsed').textContent = '(' + Math.floor(secs / 60) + ':' + ('0' + (secs % 60)).slice(-2) + ')';
    }

    function finished(job) {
        stopPolling();
        setRunning(false);
        if (job.ok && job.result) {
            showError('');
            renderResult(job.result);
        } else if (job.cancelled) {
            showError('Cancelled.');
        } else {
            showError(job.error || 'The plan did not finish.');
        }
    }

    function stopPolling() {
        pollGen += 1;
        if (polling) clearTimeout(polling);
        polling = null;
    }

    function pollSoon(ms) {
        const gen = pollGen;
        polling = setTimeout(function () { poll(gen); }, ms);
    }

    async function poll(gen) {
        polling = null;
        let reply;
        try {
            reply = await send('/config/planner/progress', 'GET');
        } catch (e) {
            if (gen !== pollGen) return;
            showProgress({label: 'Waiting for the Chart to answer', fraction: null});
            pollSoon(POLL_MS * 2);
            return;
        }
        if (gen !== pollGen) return;  // another chain took over while this answer was on its way
        const job = reply.data;
        if (!job) {
            showError('The Chart answered with ' + reply.status + '.');
            setRunning(false);
            return;
        }
        if (job.done) {
            finished(job);
        } else {
            setRunning(true);
            showProgress(job);
            pollSoon(POLL_MS);
        }
    }

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        showError('');
        goButton.disabled = true;
        try {
            const reply = await send('/config/planner/plan', 'POST', readForm());
            if (reply.status === 202 || reply.status === 409) {
                if (reply.status === 409) showError('A plan is already running (maybe from another browser); showing it.');
                $('pl-result').hidden = true;
                resetApply();
                setRunning(true);
                showProgress(reply.data);
                stopPolling();
                pollSoon(POLL_MS);
            } else {
                showError((reply.data && reply.data.error) || 'The Chart answered with ' + reply.status + '.');
                goButton.disabled = false;
            }
        } catch (err) {
            showError('Could not reach the Chart: ' + err);
            goButton.disabled = false;
        }
    });

    cancelButton.addEventListener('click', async function () {
        cancelButton.disabled = true;
        try { await send('/config/planner/cancel', 'POST'); } catch (e) { /* the poll shows what happened */ }
        cancelButton.disabled = false;
    });

    // ---- the result -------------------------------------------------------------------------------------------

    function renderResult(r) {
        const sheet = r.sheet;
        board = sheet.board;
        $('pl-result').hidden = false;
        Object.keys(r.names || {}).forEach(function (code) { if (r.names[code]) names[code] = r.names[code]; });

        const problems = sheet.problems;
        const summary = $('pl-summary');
        while (summary.firstChild) summary.removeChild(summary.firstChild);
        const text = el('div');
        text.appendChild(el('strong', null, r.message + '. '));
        text.appendChild(document.createTextNode(problems.ok
            ? 'No extensions and nothing crowded.'
            : plural(sheet.shopping.extensions, 'extension') + ' and ' + plural(problems.crowded.length, 'crowded cluster') + '.'));
        r.notes.forEach(function (n) { text.appendChild(el('div', {'class': 'muted'}, n)); });
        r.left_out.forEach(function (l) { text.appendChild(el('div', {'class': 'muted'}, 'Left out ' + l.code + ': ' + l.reason + '.')); });
        summary.appendChild(text);

        lastResult = r;
        resetApply();
        applyChanged();
        // the lists and the snippet first: they need no Leaflet, so a map that cannot start leaves them on screen
        drawLists(r);
        $('pl-snippet').value = snippet(r.airports);
        showView(view, true);
        $('pl-result').scrollIntoView({block: 'start'});
    }

    function snippet(list) {
        return '[\n' + list.map(function (a) {
            return '  {"code": ' + JSON.stringify(a.code) + ', "name": ' + JSON.stringify(a.name) + ', "display": ' + (a.display ? 'true' : 'false') + '}';
        }).join(',\n') + '\n]';
    }

    // ---- the Map view: Leaflet, like the Map page ---------------------------------------------------------------

    const KEYS = {background: 'metarmap.planner.background', opacity: 'metarmap.planner.opacity', view: 'metarmap.planner.view'};
    const COLORS = {ok: '#3ddc84', slack: '#f5b544', extension: '#ff5a5a', join: '#4ea8ff', moved: '#d77bff'};
    const BACKGROUNDS = ['none', 'sectional', 'satellite', 'street'];
    const BG_NAMES = {sectional: 'sectional', satellite: 'satellite imagery', street: 'street map'};
    const MOVED_MM = 1;  // a pixel moved further than this gets a line to its true place, and the popup says it moved
    const NO_MAP = 'The map needs Leaflet from unpkg.com, which could not be loaded: showing the Board view.';
    let mapFailed = typeof L === 'undefined';  // Leaflet comes from the internet: a Chart without it still plans
    let lmap = null;
    let planLayer = null;
    let bgLayer = null;
    let mapPending = null;  // a result waiting for the Map to be on screen: Leaflet cannot lay out a hidden map
    let view = load(KEYS.view) === 'board' ? 'board' : 'map';
    let background = BACKGROUNDS.indexOf(load(KEYS.background)) >= 0 ? load(KEYS.background) : 'none';
    let opacity = Math.min(Math.max(parseInt(load(KEYS.opacity), 10) || 100, 10), 100);

    // the browser may refuse storage (private mode): the page works without it
    function load(key) {
        try { return localStorage.getItem(key); } catch (e) { return null; }
    }

    function save(key, value) {
        try { localStorage.setItem(key, String(value)); } catch (e) { /* private mode */ }
    }

    // the backgrounds as on the Map page (static/map.js, "backgrounds"): the same tile servers and zoom limits
    function makeBackground(id) {
        if (id === 'sectional') {
            return L.tileLayer('https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Sectional/MapServer/tile/{z}/{y}/{x}', {
                maxZoom: 16, maxNativeZoom: 12, minNativeZoom: 8, minZoom: 5, attribution: 'FAA VFR Sectional'
            });
        }
        if (id === 'satellite') {
            return L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                maxZoom: 18, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics'
            });
        }
        if (id === 'street') {
            return L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            });
        }
        return null;
    }

    function ensureMap() {
        if (lmap) return;
        const m = L.map('pl-leaflet', {zoomControl: true, attributionControl: true, zoomSnap: 0.25, minZoom: 2, maxZoom: 18});
        m.setView([39, -98], 4);
        planLayer = L.layerGroup().addTo(m);
        m.on('zoomend', function () { updateCodes(); updateHint(); });
        lmap = m;
        applyBackground();
    }

    // true when the Map can be drawn; when Leaflet is missing or fails to start, the Board view takes over
    function mapReady() {
        if (mapFailed) return false;
        if (lmap) return true;
        try {
            ensureMap();
            return true;
        } catch (e) {
            mapFailed = true;
            lmap = null;
            planLayer = null;
            bgLayer = null;
            return false;
        }
    }

    function noMap() {
        $('pl-map-note').textContent = NO_MAP;
        $('pl-map-note').hidden = false;
        const mapButton = $('pl-view').querySelector('button[data-view="map"]');
        mapButton.disabled = true;
        Array.prototype.forEach.call($('pl-bg').querySelectorAll('button'), function (b) { b.disabled = true; });
        $('pl-opacity').disabled = true;
    }

    // the FAA tiles start at zoom 8 and Leaflet scales them down, but not below the layer's minZoom: say so, never
    // change the user's zoom
    function updateHint() {
        const hint = $('pl-bg-hint');
        let text = '';
        if (lmap && bgLayer && bgLayer.options.minZoom > lmap.getZoom()) {
            text = 'Zoom in to see the ' + BG_NAMES[background] + ': it shows from zoom ' + bgLayer.options.minZoom + '.';
        }
        if (hint.textContent !== text) hint.textContent = text;  // a status region: only a change is announced
        hint.hidden = !text;
    }

    function applyBackground() {
        if (!lmap) return;
        if (bgLayer) lmap.removeLayer(bgLayer);
        bgLayer = makeBackground(background);
        if (bgLayer) {
            bgLayer.setOpacity(opacity / 100);
            bgLayer.addTo(lmap);  // the tile pane sits under the plan's layers, so the plan stays readable
        }
        Array.prototype.forEach.call($('pl-bg').querySelectorAll('button'), function (b) {
            b.setAttribute('aria-pressed', b.dataset.bg === background ? 'true' : 'false');
        });
        $('pl-opacity').disabled = background === 'none';
        $('pl-opacity').value = opacity;
        $('pl-opacity-val').textContent = opacity + '%';
        updateHint();
    }

    // airport codes beside the pixels: from zoom LABEL_ZOOM up, or always for a small plan
    function updateCodes() {
        if (!lmap) return;
        const few = !lastResult || lastResult.sheet.pixels.length < FEW_PIXELS;
        $('pl-leaflet').classList.toggle('pl-codes', few || lmap.getZoom() >= LABEL_ZOOM);
    }

    // a label on the map (a cut, a join cable, START): built from an element, so its text can never be taken as html;
    // it sits under the pins (a negative z offset) so a pin's number is never covered
    function tag(latlng, text, cls) {
        const span = document.createElement('span');
        span.className = 'pl-tag ' + cls;
        span.textContent = text;
        return L.marker(latlng, {
            interactive: false, keyboard: false, zIndexOffset: -1000,
            icon: L.divIcon({className: 'pl-tag-box', iconSize: [0, 0], html: span})
        });
    }

    // a longitude past 180 (the Western Aleutians are kept continuous for the map) shown as people write it
    function wrapLon(lon) {
        let x = lon;
        while (x > 180) x -= 360;
        while (x < -180) x += 360;
        return x;
    }

    function popupFor(p) {
        const box = el('div', {'class': 'pl-pop'});
        if (p.skipped) {
            box.appendChild(el('div', {'class': 'pop-head'}, 'Hidden pixel ' + p.number));
            box.appendChild(el('div', {'class': 'pl-pop-row'}, 'String ' + p.string + ', position ' + p.position + '. Not lit; it only holds the wire.'));
            return box;
        }
        box.appendChild(el('div', {'class': 'pop-head'}, p.code + ' · pixel ' + p.number));
        if (names[p.code]) box.appendChild(el('div', {'class': 'pl-pop-row'}, names[p.code]));
        box.appendChild(el('div', {'class': 'pl-pop-row'}, 'String ' + p.string + ', position ' + p.position));
        box.appendChild(el('div', {'class': 'pl-pop-row'}, p.moved_mm > MOVED_MM
            ? 'Moved ' + len(p.moved_mm) + ' from its true place'
            : 'On its true place'));
        if (p.orig_lat !== null && p.orig_lat !== undefined) {
            box.appendChild(el('div', {'class': 'pl-pop-row muted'}, 'True position ' + p.orig_lat.toFixed(4) + ', ' + wrapLon(p.orig_lon).toFixed(4)));
        }
        return box;
    }

    function drawPlan(r) {
        const sheet = r.sheet, px = sheet.pixels, chart = r.chart;
        planLayer.clearLayers();
        const at = function (p) { return [p.lat, p.lon]; };
        const placed = px.filter(function (p) { return typeof p.lat === 'number' && typeof p.lon === 'number'; });
        if (chart.outline && chart.outline.length) {
            L.polygon(chart.outline, {color: '#93a4b8', weight: 1.5, opacity: 0.8, dashArray: '6 6', fill: false, interactive: false}).addTo(planLayer);
        }

        placed.forEach(function (p) {  // a moved pixel's line to its true place
            if (p.skipped || !(p.moved_mm > MOVED_MM) || typeof p.orig_lat !== 'number') return;
            L.polyline([[p.orig_lat, p.orig_lon], at(p)], {color: COLORS.moved, weight: 1.5, dashArray: '3 4', interactive: false}).addTo(planLayer);
            L.circleMarker([p.orig_lat, p.orig_lon], {radius: 3, color: COLORS.moved, weight: 1, fillColor: COLORS.moved, fillOpacity: 1, interactive: false}).addTo(planLayer);
        });

        sheet.route.forEach(function (leg) {
            const a = px[leg.from_index], b = px[leg.to_index];
            if (!a || !b || typeof a.lat !== 'number' || typeof b.lat !== 'number') return;
            const join = leg.kind === 'join';
            L.polyline([at(a), at(b)], {
                color: join ? COLORS.join : COLORS[leg.status] || COLORS.ok, weight: leg.status === 'extension' ? 4 : 3,
                dashArray: join ? '8 6' : null, interactive: false
            }).addTo(planLayer);
            const middle = [(a.lat + b.lat) / 2, (a.lon + b.lon) / 2];
            if (leg.status === 'extension') tag(middle, '+' + len(leg.extension_mm), 'ext').addTo(planLayer);
            else if (join) tag(middle, 'join cable ' + len(leg.length_mm), 'join').addTo(planLayer);
        });

        placed.forEach(function (p) {
            const pin = document.createElement('div');
            pin.appendChild(el('span', {'class': 'pl-n'}, p.skipped ? '' : String(p.number)));
            if (!p.skipped) pin.appendChild(el('span', {'class': 'pl-c'}, p.code));
            const icon = L.divIcon({
                className: 'pl-pin' + (p.skipped ? ' skipped' : ''), iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -11],
                html: pin
            });
            L.marker(at(p), {
                icon: icon, title: p.skipped ? 'Hidden pixel ' + p.number : p.code + ', pixel ' + p.number,
                keyboard: placed.length <= 60  // a thousand tab stops would trap a keyboard user
            }).bindPopup(popupFor(p), {className: 'led-popup pl-popup', maxWidth: 300}).addTo(planLayer);
        });

        if (placed.length && px[0] && typeof px[0].lat === 'number') tag(at(px[0]), 'START', 'start').addTo(planLayer);
        updateCodes();

        const bounds = chart.bounds;
        if (bounds) lmap.fitBounds([[bounds.south, bounds.west], [bounds.north, bounds.east]], {padding: [24, 24], maxZoom: 14, animate: false});
        else if (placed.length) lmap.fitBounds(L.latLngBounds(placed.map(at)), {padding: [24, 24], maxZoom: 14, animate: false});
        updateCodes();
        updateHint();
    }

    // show the Map or the Board; a result drawn while the Map was hidden is drawn when it comes back; with no Leaflet
    // the Board is all there is
    function showView(which, fresh) {
        if (which === 'map' && !mapReady()) {
            which = 'board';
            noMap();
        }
        view = which;
        const onMap = which === 'map';
        $('pl-map').hidden = !onMap;
        $('pl-board').hidden = onMap;
        Array.prototype.forEach.call($('pl-view').querySelectorAll('button'), function (b) {
            b.setAttribute('aria-pressed', b.dataset.view === which ? 'true' : 'false');
        });
        if (lastResult) {
            if (fresh) {
                drawBoard(lastResult);
                mapPending = lastResult;
            }
            drawLegend(lastResult);  // its last line says what the map area looks like in this view
        }
        if (onMap) {
            lmap.invalidateSize();
            if (mapPending) { const r = mapPending; mapPending = null; drawPlan(r); }
        } else {
            sizeMap();
        }
    }

    $('pl-view').addEventListener('click', function (e) {
        const btn = e.target.closest('button[data-view]');
        if (!btn) return;
        save(KEYS.view, btn.dataset.view);
        showView(btn.dataset.view, false);
    });
    $('pl-bg').addEventListener('click', function (e) {
        const btn = e.target.closest('button[data-bg]');
        if (!btn) return;
        background = btn.dataset.bg;
        save(KEYS.background, background);
        applyBackground();
    });
    $('pl-opacity').addEventListener('input', function () {
        opacity = parseInt($('pl-opacity').value, 10) || 100;
        $('pl-opacity-val').textContent = opacity + '%';
        if (bgLayer) bgLayer.setOpacity(opacity / 100);
        save(KEYS.opacity, opacity);
    });
    Array.prototype.forEach.call($('pl-view').querySelectorAll('button'), function (b) {
        b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false');
    });
    Array.prototype.forEach.call($('pl-bg').querySelectorAll('button'), function (b) {
        b.setAttribute('aria-pressed', b.dataset.bg === background ? 'true' : 'false');
    });
    $('pl-opacity').value = opacity;
    $('pl-opacity-val').textContent = opacity + '%';
    $('pl-opacity').disabled = background === 'none';
    if (mapFailed) noMap();  // Leaflet did not load: the Map button and the Background controls are off from the start

    function mid(a, b) { return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}; }

    // the Board view: the board's own drawing, in millimetres
    function drawBoard(r) {
        const sheet = r.sheet;
        const W = sheet.board.width_mm, H = sheet.board.height_mm;
        const m = r.chart.margins;
        const pad = Math.max(W, H) * 0.03;
        board.pad = pad;
        const rad = Math.min(Math.max(sheet.settings.min_gap_mm * 0.42, 3), 8.5);
        const font = rad * 0.95;
        const root = svg('svg', {viewBox: [-pad, -pad, W + 2 * pad, H + 2 * pad].join(' '), role: 'img',
            'aria-label': 'Build map of ' + sheet.pixels.length + ' pixels on a ' + len(W).split(' / ')[1] + ' wide board', 'class': 'pm'});
        root.appendChild(svg('rect', {x: 0, y: 0, width: W, height: H, 'class': 'pm-board'}));
        root.appendChild(svg('rect', {
            x: W * m.left, y: H * m.top, width: W * (1 - m.left - m.right), height: H * (1 - m.top - m.bottom), 'class': 'pm-area'}));
        const px = sheet.pixels;

        px.forEach(function (p) {  // a moved pixel's line to its true place
            if (p.skipped || !p.moved_mm || p.orig_x === null) return;
            root.appendChild(svg('line', {x1: p.x, y1: p.y, x2: p.orig_x, y2: p.orig_y, 'class': 'pm-moved'}));
            root.appendChild(svg('circle', {cx: p.orig_x, cy: p.orig_y, r: rad * 0.25, 'class': 'pm-true'}));
        });

        const labels = [];
        sheet.route.forEach(function (leg) {
            const a = px[leg.from_index], b = px[leg.to_index];
            const cls = leg.kind === 'join' ? 'join' : leg.status;
            root.appendChild(svg('line', {x1: a.x, y1: a.y, x2: b.x, y2: b.y, 'class': 'pm-wire ' + cls}));
            const c = mid(a, b);
            if (leg.status === 'extension') {
                const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
                const nx = -dy / d * rad * 0.9, ny = dx / d * rad * 0.9;  // a tick across the wire: where to cut
                root.appendChild(svg('line', {x1: c.x - nx, y1: c.y - ny, x2: c.x + nx, y2: c.y + ny, 'class': 'pm-cut'}));
                labels.push({x: c.x, y: c.y - rad * 1.3, text: '+' + len(leg.extension_mm), cls: 'ext'});
            } else if (leg.kind === 'join') {
                labels.push({x: c.x, y: c.y - rad * 0.6, text: 'join cable ' + len(leg.length_mm), cls: 'join'});
            }
        });

        px.forEach(function (p) {
            const g = svg('g', {'class': 'pm-pixel' + (p.skipped ? ' skipped' : '')});
            g.appendChild(svg('title', null, p.skipped ? 'Hidden pixel ' + p.number
                : 'Pixel ' + p.number + ': ' + p.code + ' (string ' + p.string + ', position ' + p.position + ')'
                    + (p.moved_mm ? ', moved ' + len(p.moved_mm) : '')));
            g.appendChild(svg('circle', {cx: p.x, cy: p.y, r: rad, 'class': 'pm-dot'}));
            if (!p.skipped) {
                g.appendChild(svg('text', {x: p.x, y: p.y + font * 0.35, 'font-size': font, 'text-anchor': 'middle', 'class': 'pm-num'}, String(p.number)));
                g.appendChild(svg('text', {x: p.x, y: p.y + rad + font * 1.05, 'font-size': font * 0.9, 'text-anchor': 'middle', 'class': 'pm-code'}, p.code));
            }
            root.appendChild(g);
        });

        labels.forEach(function (l) {
            root.appendChild(svg('text', {x: l.x, y: l.y, 'font-size': font * 0.9, 'text-anchor': 'middle', 'class': 'pm-label ' + l.cls}, l.text));
        });

        if (sheet.start) {
            const s = sheet.start, k = rad * 1.9;
            const g = svg('g', {'class': 'pm-start'});
            g.appendChild(svg('path', {d: 'M' + (s.x - k) + ',' + (s.y - k * 1.6) + 'l' + k * 2 + ',0l' + (-k) + ',' + k * 1.1 + 'z'}));
            g.appendChild(svg('text', {x: s.x, y: s.y - k * 1.75, 'font-size': font, 'text-anchor': 'middle'}, 'START'));
            root.appendChild(g);
        }

        const holder = $('pl-board-svg');
        while (holder.firstChild) holder.removeChild(holder.firstChild);
        holder.appendChild(root);
        zoom = 0;
        sizeMap();
    }

    function sizeMap() {
        const holder = $('pl-board-svg');
        const node = holder.firstChild;
        if (!node || !board) return;
        const aspect = (board.height_mm + 2 * board.pad) / (board.width_mm + 2 * board.pad);
        let width = holder.clientWidth * ZOOMS[zoom];
        if (zoom === 0) {  // Fit: the whole board in view, so a tall board on a wide screen is not cut off
            const room = Math.max(window.innerHeight * 0.8 - 24, 240);
            width = Math.min(width, room / aspect);
        }
        node.setAttribute('width', Math.round(width));
        node.setAttribute('height', Math.round(width * aspect));
    }

    $('pl-board').addEventListener('click', function (e) {
        const btn = e.target.closest('[data-zoom]');
        if (!btn) return;
        const way = btn.dataset.zoom;
        zoom = way === 'fit' ? 0 : Math.min(Math.max(zoom + (way === 'in' ? 1 : -1), 0), ZOOMS.length - 1);
        sizeMap();
    });
    window.addEventListener('resize', function () {
        sizeMap();
        if (lmap && view === 'map') lmap.invalidateSize();  // Leaflet does not see a changed layout by itself
    });

    function drawLegend(r) {
        const list = $('pl-legend');
        while (list.firstChild) list.removeChild(list.firstChild);
        const mark = function (cls, dashed) {
            const s = svg('svg', {width: 28, height: 10, viewBox: '0 0 28 10', 'aria-hidden': 'true'});
            s.appendChild(svg('line', {x1: 1, y1: 5, x2: 27, y2: 5, 'class': 'pm-wire ' + cls}));
            return s;
        };
        const ring = function (cls) {
            const s = svg('svg', {width: 18, height: 18, viewBox: '0 0 18 18', 'aria-hidden': 'true'});
            s.appendChild(svg('circle', {cx: 9, cy: 9, r: 6, 'class': 'pm-dot ' + cls, 'stroke-width': 1.5}));
            return s;
        };
        [
            [mark('ok'), 'Wire fits'],
            [mark('slack'), 'Slack: a lot of wire to hide'],
            [mark('extension'), 'Needs an extension (the length is on it)'],
            [mark('join'), 'Free join between strings: use a join cable'],
            [ring(''), 'Pixel, with its LED number and airport'],
            [ring('hollow'), 'Skipped (hidden) pixel'],
            [mark('moved'), 'Moved from the airport\'s true place'],
        ].forEach(function (pair) {
            const li = el('li');
            add(li, [pair[0], el('span', null, pair[1])]);
            list.appendChild(li);
        });
        const where = view === 'board' ? 'the shaded area is the map' : 'inside the dashed outline is the map';
        const chart = el('li', {'class': 'muted'}, r.chart.name + ' chart: ' + where + ', the rest its margins.');
        list.appendChild(chart);
    }

    // ---- the lists --------------------------------------------------------------------------------------------

    function card(title) {
        const c = el('div', {'class': 'card pl-gen'});
        c.appendChild(add(el('div', {'class': 'card-head'}), [el('h2', null, title)]));
        const body = el('div', {'class': 'pl-body'});
        c.appendChild(body);
        return {card: c, body: body};
    }

    function kv(body, rows) {
        const dl = el('dl', {'class': 'pl-kv'});
        rows.forEach(function (row) {
            add(dl, [el('dt', null, row[0]), el('dd', null, row[1])]);
        });
        body.appendChild(dl);
    }

    function items(body, texts, empty) {
        if (!texts.length) { body.appendChild(el('p', {'class': 'muted'}, empty)); return; }
        const ul = el('ul', {'class': 'pl-list'});
        texts.forEach(function (t) { ul.appendChild(el('li', null, t)); });
        body.appendChild(ul);
    }

    function drawLists(r) {
        const out = $('pl-lists');
        Array.prototype.slice.call(out.querySelectorAll('.pl-gen')).forEach(function (old) { out.removeChild(old); });
        const sheet = r.sheet, shop = sheet.shopping, pw = sheet.power, prob = sheet.problems;
        const last = $('pl-snippet-card');  // the generated cards go before the config snippet
        const stack = function (c) { out.insertBefore(c.card, last); };

        let c = card('Shopping list');
        kv(c.body, [
            ['Pixels', shop.pixels + ' (' + plural(shop.airports, 'airport') + (shop.skipped ? ', ' + shop.skipped + ' hidden' : '') + ')'],
            ['Strings', plural(shop.strings, 'string') + ' of ' + sheet.settings.string_len + (shop.spare_pixels ? ', with ' + plural(shop.spare_pixels, 'spare pixel') + ' at the end' : '')],
            ['Extensions', shop.extensions ? plural(shop.extensions, 'extension') + ', ' + len(shop.extension_wire_mm) + ' of wire, ' + plural(shop.splices, 'splice') : 'none'],
            ['Join cables', shop.joins ? plural(shop.joins, 'cable') + ', ' + len(shop.join_cable_mm) + ' in all' : 'none'],
            ['Slack gaps', String(shop.slack_gaps)],
            ['Moved pixels', String(shop.moved)],
        ]);
        stack(c);

        c = card('Cut list');
        items(c.body, r.sheet.cuts.map(function (cut) {
            return 'String ' + cut.string + ': ' + cut.how.replace(/splice in [\d.]+ mm/, 'splice in ' + len(cut.extension_mm)) + ' (gap ' + len(cut.length_mm) + ').';
        }), 'Nothing to cut: every wire fits.');
        stack(c);

        c = card('Joins between strings');
        items(c.body, sheet.joins.map(function (j) {
            return 'String ' + j.string_a + ' to ' + j.string_b + ': a join cable of ' + len(j.length_mm) + ' (pixel ' + (j.between[0] + 1) + ' to ' + (j.between[1] + 1) + ').';
        }), 'One string: no joins.');
        stack(c);

        c = card('Power');
        kv(c.body, [
            ['Voltage', pw.voltage + ' V'],
            ['Estimated current', pw.estimated_amps + ' A at brightness ' + pw.brightness + ' (' + pw.ma_per_pixel + ' mA a pixel at full white)'],
            ['Supply', pw.supply_amps + ' A (' + pw.supply_watts + ' W), with ' + Math.round((pw.margin - 1) * 100) + '% to spare'],
            ['Power feeds', plural(pw.feed_points.length, 'feed') + ' at pixel ' + pw.feed_points.map(function (i) { return i + 1; }).join(', ')],
        ]);
        c.body.appendChild(el('p', null, pw.reason));
        items(c.body, pw.notes, '');
        stack(c);

        c = card('Problems');
        const why = [];
        prob.drops.forEach(function (d) {
            why.push(d.code + ' is too close to ' + d.crowding + ': the two cannot be spaced apart within the maximum move. Drop ' + d.code + ', or use a bigger board.');
        });
        prob.crowded.forEach(function (cl) {
            why.push(cl.join(', ') + ' are too close together to space out at the minimum spacing.');
        });
        prob.clipped.forEach(function (code) { why.push(code + ' began off the board and was put on its edge.'); });
        if (prob.skips_wanted) why.push(prob.skips_note + ' Skipped pixels need Chart support, a later change.');
        items(c.body, why, 'Nothing crowded and nothing dropped.');
        stack(c);

        if (r.sizes) {
            c = card('Board sizes to try');
            const cur = r.sizes.current;
            c.body.appendChild(el('p', {'class': 'muted'}, 'Yours, ' + cur.width_in + ' x ' + cur.height_in + ' in: ' + plural(cur.extensions, 'extension') + ', ' + plural(cur.crowded, 'crowded cluster') + '.'));
            items(c.body, r.sizes.best.map(function (s) {
                return s.width_in + ' x ' + s.height_in + ' in: ' + plural(s.extensions, 'extension') + ', ' + plural(s.crowded, 'crowded cluster') + (s.drops ? ', ' + plural(s.drops, 'drop') : '') + '.';
            }), 'No sizes tried.');
            c.body.appendChild(el('p', {'class': 'muted'}, 'Widths from 90% to 115% of yours, keeping its shape. Set the width and height above and plan again to try one.'));
            stack(c);
        }
    }


    // ---- apply the plan to this Chart --------------------------------------------------------------------------

    const LONG_LIST = 12;  // a list of codes longer than this is collapsed
    const applyBtn = $('pl-apply-btn');
    const applyPanel = $('pl-apply-panel');
    const applyGo = $('pl-apply-go');
    const applyWired = $('pl-apply-wired');
    const undoBtn = $('pl-undo-btn');
    const undoPanel = $('pl-undo-panel');
    let applyToken = null;
    let applyBusy = false;  // a request is on its way
    let applyUnchanged = false;  // the preview says the Chart already has this plan: nothing to apply
    let undoInfo = null;

    function say(text, bad) {  // the one polite status line: set only when something happened
        const box = $('pl-apply-status');
        box.textContent = text || '';
        box.className = 'pl-pad' + (bad ? ' bad' : '');
    }

    function sayUndo(text, bad) {  // the Undo card's own polite status line
        const box = $('pl-undo-status');
        box.textContent = text || '';
        box.className = 'pl-pad' + (bad ? ' bad' : '');
    }

    function applyChanged() {
        applyBtn.disabled = jobRunning || applyBusy || !lastResult || !applyPanel.hidden;
        applyGo.disabled = jobRunning || applyBusy || applyUnchanged || !applyWired.checked || !applyToken;
        undoBtn.disabled = jobRunning || applyBusy || !undoPanel.hidden;
    }

    // close the confirmation and the success message (the standing Undo card is left alone): a new plan starts clean
    function resetApply() {
        applyToken = null;
        applyUnchanged = false;
        applyPanel.hidden = true;
        $('pl-apply-done').hidden = true;
        applyWired.checked = false;
        say('');
        applyChanged();
    }

    function closePanel(panel, back) {
        panel.hidden = true;
        applyToken = null;
        applyChanged();
        if (back && !back.disabled) back.focus();
    }

    function changeWords(s) {
        const parts = [];
        parts.push(s.moved + (s.moved === 1 ? ' airport moves' : ' airports move'));
        parts.push(s.added.length + (s.added.length === 1 ? ' is added' : ' are added'));
        parts.push(s.became_virtual.length + (s.became_virtual.length === 1 ? ' becomes virtual' : ' become virtual'));
        if (s.promoted && s.promoted.length) parts.push(s.promoted.length + (s.promoted.length === 1 ? ' virtual airport gets a pixel' : ' virtual airports get pixels'));
        const a = s.led_count.from;
        const b = s.led_count.to;
        parts.push(a === b ? 'the pixel count stays at ' + a : 'the pixel count goes from ' + a + ' to ' + b);
        return parts.join(', ');
    }

    function codeList(parent, title, codes) {
        if (!codes || !codes.length) return;
        const label = title + ' (' + codes.length + ')';
        const text = codes.join(', ');
        if (codes.length > LONG_LIST) {
            const d = el('details');
            d.appendChild(el('summary', null, label));
            d.appendChild(el('div', {'class': 'mono'}, text));
            parent.appendChild(d);
        } else {
            const p = el('p', {'style': 'margin: 0 0 8px'});
            p.appendChild(document.createTextNode(label + ': '));
            p.appendChild(el('span', {'class': 'mono'}, text));
            parent.appendChild(p);
        }
    }

    function showPreview(s, backup) {
        applyUnchanged = !!s.unchanged && !s.over_limit;
        const box = $('pl-apply-lists');
        while (box.firstChild) box.removeChild(box.firstChild);
        // with nothing to apply there is no warning, no backup and no wiring box to tick: just the answer
        $('pl-apply-warning').hidden = applyUnchanged;
        $('pl-apply-backup-line').hidden = applyUnchanged;
        $('pl-apply-wired-line').hidden = applyUnchanged;
        if (applyUnchanged) {
            $('pl-apply-head').textContent = 'Nothing to apply: the Chart already has this plan.';
            applyWired.checked = false;
            applyWired.disabled = true;
            applyPanel.hidden = false;
            applyChanged();
            $('pl-apply-head').focus();
            return;
        }
        $('pl-apply-head').textContent = 'Apply this plan to this Chart? ' + changeWords(s);
        codeList(box, 'Added', s.added);
        codeList(box, 'Become virtual airports', s.became_virtual);
        codeList(box, 'Virtual airports that get a pixel', s.promoted);
        if (s.blank_leds) box.appendChild(el('p', {'style': 'margin: 0 0 8px'}, plural(s.blank_leds, 'pixel') + ' will have no airport.'));
        $('pl-apply-warning').textContent = s.over_limit
            ? 'This plan has more airports than the Chart takes, so it cannot be applied.'
            : s.wiring_note || 'The strip must be wired in the plan\'s order.';
        $('pl-apply-backup').textContent = backup || '';
        applyWired.checked = false;
        applyWired.disabled = !!s.over_limit;
        applyPanel.hidden = false;
        applyChanged();
        $('pl-apply-head').focus();
    }

    function errorText(reply, fallback) {
        return (reply.data && reply.data.error) || fallback || 'The Chart answered with ' + reply.status + '.';
    }

    async function preview(again) {
        applyBusy = true;
        applyChanged();
        say('Checking what the plan would change...');
        try {
            const reply = await send('/config/planner/apply/preview', 'GET');
            const d = reply.data;
            if (reply.status === 200 && d && d.ok) {
                applyToken = d.token;
                $('pl-apply-done').hidden = true;
                applyBusy = false;
                say(again ? 'The plan or the config changed since you looked: check the new numbers.' : '');
                showPreview(d.summary, d.backup);
            } else {
                applyBusy = false;
                applyToken = null;
                applyPanel.hidden = true;
                say(errorText(reply), true);
            }
        } catch (e) {
            applyBusy = false;
            applyPanel.hidden = true;
            say('Could not reach the Chart: ' + e, true);
        }
        applyBusy = false;
        applyChanged();
    }

    applyBtn.addEventListener('click', function () { preview(false); });
    applyWired.addEventListener('change', applyChanged);
    $('pl-apply-cancel').addEventListener('click', function () { say(''); closePanel(applyPanel, applyBtn); });

    function whatChanged(s) {
        return s ? changeWords(s).replace(/^./, function (c) { return c.toUpperCase(); }) + '.' : '';
    }

    function showDone(text, restart) {
        $('pl-apply-done-text').textContent = text;
        $('pl-apply-restart').hidden = !restart;
        $('pl-apply-done').hidden = false;
        say(restart ? 'Done. Restart the Chart to use the new pixel count.' : 'Done.');
    }

    applyGo.addEventListener('click', async function () {
        if (!applyToken || !applyWired.checked) return;
        applyBusy = true;
        applyChanged();
        say('Applying...');
        try {
            const reply = await send('/config/planner/apply', 'POST', {token: applyToken});
            const d = reply.data;
            applyBusy = false;
            if (reply.status === 200 && d && d.ok) {
                closePanel(applyPanel);
                $('pl-undo-done').hidden = true;
                sayUndo('');
                showDone('Applied. ' + whatChanged(d.summary) + ' The backup is ' + d.backup + '.', d.restart_needed);
                await loadUndo();
                applyBtn.focus();
            } else if (reply.status === 409 && d && d.reason === 'stale') {
                await preview(true);
            } else if (reply.status === 409 && d && d.reason === 'unchanged') {
                await preview(false);  // the panel then says there is nothing to apply
            } else if (reply.status === 409 && d && d.reason === 'running') {
                closePanel(applyPanel, applyBtn);
                say(errorText(reply, 'A plan is running: wait for it to finish.'), true);
            } else {
                say(errorText(reply), true);
            }
        } catch (e) {
            say('Could not reach the Chart: ' + e, true);
        }
        applyBusy = false;
        applyChanged();
    });

    async function loadUndo() {
        let info = null;
        try {
            const reply = await send('/config/planner/apply/status', 'GET');
            info = reply.status === 200 && reply.data ? reply.data.undo : null;
        } catch (e) { /* no undo shown */ }
        undoInfo = info && info.available ? info : null;
        // the card stays while its done message (and the Restart now button) is showing
        $('pl-undo-card').hidden = !undoInfo && $('pl-undo-done').hidden;
        $('pl-undo-btn').parentNode.hidden = !undoInfo;
        if (undoInfo) {
            let when = undoInfo.made_at || '';
            const t = new Date(when);
            if (when && !isNaN(t.getTime())) when = t.toLocaleString();
            $('pl-undo-text').textContent = 'Last applied ' + when + ' (backup ' + undoInfo.backup + ')';
        } else {
            undoPanel.hidden = true;
        }
        applyChanged();
    }

    function showUndoDone(text, restart) {
        $('pl-undo-done-text').textContent = text;
        $('pl-undo-restart').hidden = !restart;
        $('pl-undo-done').hidden = false;
        sayUndo(restart ? 'Done. Restart the Chart to use the restored pixel count.' : 'Done.');
    }

    undoBtn.addEventListener('click', function () {
        undoPanel.hidden = false;
        $('pl-undo-done').hidden = true;
        sayUndo('');
        applyChanged();
        $('pl-undo-head').focus();
    });
    $('pl-undo-cancel').addEventListener('click', function () { closePanel(undoPanel, undoBtn); });
    $('pl-undo-go').addEventListener('click', async function () {
        if (!undoInfo || !undoInfo.backup) {
            undoPanel.hidden = true;
            sayUndo('There is nothing to undo.', true);
            await loadUndo();
            return;
        }
        applyBusy = true;
        applyChanged();
        sayUndo('Restoring from the backup...');
        try {
            // the server wants the backup's name (from apply/status), so an Undo it did not offer is refused
            const reply = await send('/config/planner/undo', 'POST', {backup: undoInfo.backup});
            const d = reply.data;
            applyBusy = false;
            if (reply.status === 200 && d && d.ok) {
                const r = d.restored || {};
                undoPanel.hidden = true;
                applyPanel.hidden = true;
                applyToken = null;
                $('pl-apply-done').hidden = true;
                say('');
                showUndoDone('Undone. Restored ' + plural(r.airports, 'airport') + ', ' + plural(r.led_count, 'pixel') + ' and ' + plural(r.virtual_count, 'virtual airport') + ' from the backup.', d.restart_needed);
                await loadUndo();
                if (!applyBtn.disabled) applyBtn.focus();
            } else {
                undoPanel.hidden = true;
                sayUndo(errorText(reply), true);
                await loadUndo();
            }
        } catch (e) {
            sayUndo('Could not reach the Chart: ' + e, true);
        }
        applyBusy = false;
        applyChanged();
    });

    loadUndo();  // the standing card shows on every load, with or without a plan on the page

    applyChanged();

    // ---- copy -------------------------------------------------------------------------------------------------

    $('pl-copy').addEventListener('click', async function () {
        const box = $('pl-snippet');
        const done = function () {
            $('pl-copy').textContent = 'Copied';
            setTimeout(function () { $('pl-copy').textContent = 'Copy'; }, 1500);
        };
        try {
            await navigator.clipboard.writeText(box.value);
            done();
        } catch (e) {  // older Safari, or a page that is not https
            box.focus();
            box.select();
            box.setSelectionRange(0, box.value.length);
            try { if (document.execCommand('copy')) done(); } catch (err) { /* selected: press copy by hand */ }
        }
    });

    // a reloaded page picks up the running plan, or shows the last one
    (async function resume() {
        try {
            const reply = await send('/config/planner/progress', 'GET');
            const job = reply.data;
            if (!job || job.idle) return;
            restoreForm(job.params);
            if (job.done) finished(job); else { stopPolling(); poll(pollGen); }
        } catch (e) { /* the form still works */ }
    })();
})();

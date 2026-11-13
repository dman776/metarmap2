// MetarMap2 Web: Config > Plan a new chart. The form, the job's progress and the build map.
(function () {
    'use strict';

    const root = document.getElementById('planner');
    if (!root) return;

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const MM_IN = 25.4;
    const POLL_MS = 1500;
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
    let board = null;  // the last result's board, for the map's size
    let sectionalHolder = null;  // the SVG group the sectional's image is put in
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

        drawMap(r);
        drawLists(r);
        $('pl-snippet').value = snippet(r.airports);
        $('pl-result').scrollIntoView({block: 'start'});
    }

    function snippet(list) {
        return '[\n' + list.map(function (a) {
            return '  {"code": ' + JSON.stringify(a.code) + ', "name": ' + JSON.stringify(a.name) + ', "display": ' + (a.display ? 'true' : 'false') + '}';
        }).join(',\n') + '\n]';
    }

    function mid(a, b) { return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}; }

    function drawMap(r) {
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
        sectionalHolder = svg('g', {'class': 'pm-sectional-holder'});  // the sectional goes here: under the plan, over the area
        root.appendChild(sectionalHolder);
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

        const holder = $('pl-map');
        while (holder.firstChild) holder.removeChild(holder.firstChild);
        holder.appendChild(root);
        zoom = 0;
        sizeMap();
        drawLegend(r);
        sectionalNewResult(r);
    }

    function sizeMap() {
        const holder = $('pl-map');
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

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-zoom]');
        if (!btn) return;
        const way = btn.dataset.zoom;
        zoom = way === 'fit' ? 0 : Math.min(Math.max(zoom + (way === 'in' ? 1 : -1), 0), ZOOMS.length - 1);
        sizeMap();
    });
    window.addEventListener('resize', sizeMap);
    $('pl-print').addEventListener('click', function () { window.print(); });

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
        const chart = el('li', {'class': 'muted'}, r.chart.name + ' chart: the shaded area is the map, the rest its margins.');
        list.appendChild(chart);
    }

    // ---- the sectional chart under the plan ---------------------------------------------------------------------
    // The FAA sectional tiles (Web Mercator) are resampled onto the plan's map area with the lat/lon grid the plan
    // sends, tile by tile as each loads, into one canvas of the area, which is shown as an image under the route.

    const TILE_URL = 'https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Sectional/MapServer/tile/{z}/{y}/{x}';
    const TILE_MIN_ZOOM = 8, TILE_MAX_ZOOM = 10;
    const TILE_BIG = 300;       // tiles above which the size note shows, and a sectional stays at zoom 9
    const TILE_KB = 46;
    const IN_FLIGHT = 6;
    const REFRESH_MS = 700;
    const AREA_COLOR = [20, 33, 45];  // the map area's fill (#14212d): what shows where a tile is missing
    const KEY_SHOW = 'metarmap.planner.sectional';
    const KEY_OPACITY = 'metarmap.planner.sectionalOpacity';
    const sect = {
        box: $('pl-sect'), range: $('pl-sect-op'), val: $('pl-sect-op-val'), note: $('pl-sect-note'),
        progress: $('pl-sect-progress'), status: $('pl-sect-status'),
        chart: null,   // the current result's chart (grid, usable, bounds)
        plan: null,    // {z, outW, outH, tiles: n}, worked out once a result is in
        run: 0,        // each load has a number; cancelling makes the one in flight stale
        active: null,  // the running load's state
        image: null,
    };

    function store(key, value) {
        try { window.localStorage.setItem(key, value); } catch (e) { /* storage blocked or full: the page works without it */ }
    }

    function stored(key) {
        try { return window.localStorage.getItem(key); } catch (e) { return null; }
    }

    function mercX(lon, z) { return (lon + 180) / 360 * 256 * Math.pow(2, z); }

    function mercY(lat, z) {
        const s = Math.sin(Math.max(-85.05, Math.min(85.05, lat)) * Math.PI / 180);
        return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * 256 * Math.pow(2, z);
    }

    // lat and lon at fractions (fx, fy) across and down the map area, bilinear on the grid's corners
    function gridAt(grid, fx, fy) {
        const gx = Math.min(Math.max(fx, 0), 1) * (grid.cols - 1), gy = Math.min(Math.max(fy, 0), 1) * (grid.rows - 1);
        const i = Math.min(Math.floor(gx), grid.cols - 2), j = Math.min(Math.floor(gy), grid.rows - 2);
        const tx = gx - i, ty = gy - j;
        const mix = function (t) {
            return (t[j][i] * (1 - tx) + t[j][i + 1] * tx) * (1 - ty) + (t[j + 1][i] * (1 - tx) + t[j + 1][i + 1] * tx) * ty;
        };
        return {lat: mix(grid.lat), lon: mix(grid.lon)};
    }

    function gridOk(c) {
        const g = c && c.grid, u = c && c.usable;
        if (!g || !u || !g.lat || !g.lon || !(g.cols >= 2) || !(g.rows >= 2) || !(u.w > 0) || !(u.h > 0)) return false;
        if (g.lat.length !== g.rows || g.lon.length !== g.rows) return false;
        for (let j = 0; j < g.rows; j++) if (g.lat[j].length !== g.cols || g.lon[j].length !== g.cols) return false;
        return true;
    }

    // the distinct tiles the area touches at zoom z, found on a coarse sample of the output (a tile is 256 px: a step of
    // 8 px of the output cannot skip one, apart from a sliver at a corner)
    function tilesFor(c, z, outW, outH) {
        const seen = {}, list = [], n = Math.pow(2, z);
        const stepX = Math.max(1, Math.round(outW / 200)), stepY = Math.max(1, Math.round(outH / 140));
        for (let y = 0; y <= outH; y += stepY) {
            for (let x = 0; x <= outW; x += stepX) {
                const at = gridAt(c.grid, x / outW, y / outH);
                const tx = Math.floor(mercX(at.lon, z) / 256), ty = Math.floor(mercY(at.lat, z) / 256);
                if (tx < 0 || ty < 0 || tx >= n || ty >= n) continue;
                const key = tx + ',' + ty;
                if (!seen[key]) { seen[key] = true; list.push([tx, ty]); }
            }
        }
        return list;
    }

    // the canvas size and the tile zoom: the smallest zoom (8 to 10) with about as many tile pixels across the area as the
    // canvas has; a sectional stays at 9 if zoom 10 would need more than TILE_BIG tiles
    function planSectional(c) {
        const small = window.innerWidth <= 640;
        const outW = small ? 900 : 1600;
        const outH = Math.max(2, Math.round(outW * c.usable.h / c.usable.w));
        const b = c.bounds || {};
        let span = null;
        const lons = c.grid.lon;
        let west = Infinity, east = -Infinity;
        lons.forEach(function (row) { row.forEach(function (v) { west = Math.min(west, v); east = Math.max(east, v); }); });
        if (isFinite(b.west) && isFinite(b.east)) { west = Math.min(west, b.west); east = Math.max(east, b.east); }
        let z = TILE_MAX_ZOOM;
        for (let t = TILE_MIN_ZOOM; t <= TILE_MAX_ZOOM; t++) {
            span = (mercX(east, t) - mercX(west, t));
            if (span >= outW * 0.9) { z = t; break; }
        }
        let tiles = tilesFor(c, z, outW, outH);
        if (z === TILE_MAX_ZOOM && c.kind !== 'wall' && tiles.length > TILE_BIG) {
            z = TILE_MAX_ZOOM - 1;
            tiles = tilesFor(c, z, outW, outH);
        }
        return {z: z, outW: outW, outH: outH, count: tiles.length};
    }

    function setNote(text) {
        sect.note.textContent = text || '';
        sect.note.hidden = !text;
    }

    function setStatus(text, progress) {  // the polite status is only for what happens (done, trouble); the count is a visible aside
        sect.progress.textContent = progress || '';
        sect.progress.hidden = !progress;
        if (sect.status.textContent !== (text || '')) sect.status.textContent = text || '';
        sect.status.hidden = !text;
    }

    function setCredit(on) {
        const list = $('pl-legend');
        const old = list.querySelector('.pm-credit');
        if (old) list.removeChild(old);
        if (on) list.appendChild(el('li', {'class': 'pm-credit muted'}, 'Chart under the plan: FAA VFR Sectional'));
    }

    function removeImage() {
        if (sect.image && sect.image.parentNode) sect.image.parentNode.removeChild(sect.image);
        sect.image = null;
        setCredit(false);
    }

    function stopSectional() {
        sect.run += 1;
        const a = sect.active;
        sect.active = null;
        if (a) {
            a.loading.forEach(function (img) { img.onload = img.onerror = null; img.src = ''; });
            a.canvas = a.out = a.order = a.starts = null;
            if (a.timer) clearTimeout(a.timer);
        }
    }

    function applyOpacity() {
        const pct = Math.min(100, Math.max(10, parseInt(sect.range.value, 10) || 60));
        sect.val.textContent = pct + '%';
        if (sect.image) sect.image.setAttribute('opacity', pct / 100);
    }

    function enableSectional(on) {
        sect.box.disabled = !on;
        sect.range.disabled = !on;
    }

    // a new result (or none): stop any load, forget the old image and work out the new area
    function sectionalNewResult(r) {
        stopSectional();
        removeImage();
        setStatus('', '');
        setNote('');
        sect.chart = null;
        sect.plan = null;
        const c = r && r.chart;
        if (!gridOk(c)) {
            enableSectional(false);
            setNote(c ? 'The sectional chart is not available for this plan.' : '');
            return;
        }
        sect.chart = c;
        sect.plan = planSectional(c);
        enableSectional(true);
        const n = sect.plan.count;
        if (n > TILE_BIG) {
            const rounded = Math.round(n / 10) * 10;
            setNote((c.kind === 'wall' ? 'The whole US' : 'This chart') + ' is about ' + rounded.toLocaleString('en-US') + ' tiles, about '
                + Math.round(rounded * TILE_KB / 1000) + ' MB; they load as you watch and your browser keeps them for an hour.');
        }
        if (sect.box.checked) startSectional();
    }

    function startSectional() {
        stopSectional();
        removeImage();
        const c = sect.chart, plan = sect.plan;
        if (!c || !plan || !sectionalHolder) return;
        const run = sect.run;
        const a = {c: c, plan: plan, loading: [], done: 0, failed: 0, total: 0, queue: [], dirty: false, last: 0, timer: null, broken: false};
        sect.active = a;
        try {
            a.canvas = document.createElement('canvas');
            a.canvas.width = plan.outW;
            a.canvas.height = plan.outH;
            a.ctx = a.canvas.getContext('2d');
            a.out = a.ctx.createImageData(plan.outW, plan.outH);
        } catch (e) {
            sectionalFail('The chart could not be drawn: this browser would not make the canvas.');
            return;
        }
        const d = a.out.data;
        for (let k = 0; k < d.length; k += 4) { d[k] = AREA_COLOR[0]; d[k + 1] = AREA_COLOR[1]; d[k + 2] = AREA_COLOR[2]; d[k + 3] = 255; }

        // each output pixel's tile, then the pixels grouped by tile (a counting sort), so a tile is filled when it arrives
        const z = plan.z, n = Math.pow(2, z), W = plan.outW, H = plan.outH;
        const ids = {}, tiles = [];
        const key = new Int32Array(W * H);
        for (let y = 0; y < H; y++) {
            for (let x = 0; x < W; x++) {
                const at = gridAt(c.grid, (x + 0.5) / W, (y + 0.5) / H);
                const tx = Math.floor(mercX(at.lon, z) / 256), ty = Math.floor(mercY(at.lat, z) / 256);
                let k = -1;
                if (tx >= 0 && ty >= 0 && tx < n && ty < n) {
                    const name = tx + ',' + ty;
                    k = ids[name];
                    if (k === undefined) { k = tiles.length; ids[name] = k; tiles.push({x: tx, y: ty, count: 0}); }
                    tiles[k].count += 1;
                }
                key[y * W + x] = k;
            }
        }
        a.tiles = tiles;
        a.starts = new Uint32Array(tiles.length + 1);
        tiles.forEach(function (t, k) { a.starts[k + 1] = a.starts[k] + t.count; });
        const fill = a.starts.slice(0, tiles.length);
        a.order = new Uint32Array(a.starts[tiles.length]);
        for (let p = 0; p < key.length; p++) if (key[p] >= 0) a.order[fill[key[p]]++] = p;
        a.total = tiles.length;
        a.queue = tiles.map(function (t, k) { return k; });
        setStatus('', 'Loading chart tiles: 0 of ' + a.total);
        sectionalPump(run);
    }

    function sectionalFail(text) {
        stopSectional();
        removeImage();
        setStatus(text, '');
    }

    function sectionalPump(run) {
        const a = sect.active;
        if (!a || run !== sect.run) return;
        while (a.loading.length < IN_FLIGHT && a.queue.length) loadTile(run, a, a.queue.shift());
        if (!a.loading.length && !a.queue.length) sectionalDone(run);
    }

    function loadTile(run, a, k) {
        const t = a.tiles[k];
        const img = new Image();
        a.loading.push(img);
        const settle = function (ok) {
            if (run !== sect.run || sect.active !== a) return;
            const at = a.loading.indexOf(img);
            if (at >= 0) a.loading.splice(at, 1);
            img.onload = img.onerror = null;
            if (ok) {
                try {
                    paintTile(a, k, img);
                } catch (e) {  // a canvas the page may not read (the tiles came without CORS), or no memory
                    sectionalFail('The chart could not be read.');
                    return;
                }
            } else {
                a.failed += 1;
            }
            a.done += 1;
            setStatus('', 'Loading chart tiles: ' + a.done + ' of ' + a.total);
            refreshSoon(run, a);
            sectionalPump(run);
        };
        img.onload = function () { settle(true); };
        img.onerror = function () { settle(false); };
        img.crossOrigin = 'anonymous';
        img.src = TILE_URL.replace('{z}', a.plan.z).replace('{y}', t.y).replace('{x}', t.x);
    }

    // decode one tile into a 256 px canvas and write the output pixels that fall on it (bilinear within the tile)
    let tileCanvas = null;
    function paintTile(a, k, img) {
        const t = a.tiles[k], size = img.naturalWidth || 256;
        if (!tileCanvas) tileCanvas = document.createElement('canvas');
        tileCanvas.width = tileCanvas.height = size;
        const tctx = tileCanvas.getContext('2d');
        tctx.drawImage(img, 0, 0, size, size);
        const src = tctx.getImageData(0, 0, size, size).data;  // throws on a tainted canvas
        const z = a.plan.z, W = a.plan.outW, H = a.plan.outH, scale = size / 256, out = a.out.data, max = size - 1;
        const x0 = t.x * 256, y0 = t.y * 256;
        for (let q = a.starts[k]; q < a.starts[k + 1]; q++) {
            const p = a.order[q], px = p % W, py = (p - px) / W;
            const at = gridAt(a.c.grid, (px + 0.5) / W, (py + 0.5) / H);
            const u = Math.min(Math.max((mercX(at.lon, z) - x0) * scale - 0.5, 0), max);
            const v = Math.min(Math.max((mercY(at.lat, z) - y0) * scale - 0.5, 0), max);
            const iu = Math.min(Math.floor(u), max - 1), iv = Math.min(Math.floor(v), max - 1);
            const fu = u - iu, fv = v - iv;
            const s0 = (iv * size + iu) * 4, s1 = s0 + size * 4;
            const o = p * 4;
            for (let ch = 0; ch < 3; ch++) {
                out[o + ch] = (src[s0 + ch] * (1 - fu) + src[s0 + 4 + ch] * fu) * (1 - fv) + (src[s1 + ch] * (1 - fu) + src[s1 + 4 + ch] * fu) * fv;
            }
            // a transparent tile pixel shows the area's colour
            const alpha = src[s0 + 3] / 255;
            if (alpha < 1) for (let ch = 0; ch < 3; ch++) out[o + ch] = out[o + ch] * alpha + AREA_COLOR[ch] * (1 - alpha);
        }
        a.dirty = true;
    }

    function refreshSoon(run, a) {
        if (a.timer || !a.dirty) return;
        const wait = Math.max(0, REFRESH_MS - (Date.now() - a.last));
        a.timer = setTimeout(function () { a.timer = null; if (run === sect.run && sect.active === a) showCanvas(a); }, wait);
    }

    function showCanvas(a) {
        if (!a.dirty && sect.image) return;
        a.dirty = false;
        a.last = Date.now();
        let url;
        try {
            a.ctx.putImageData(a.out, 0, 0);
            url = a.canvas.toDataURL('image/jpeg', 0.85);
        } catch (e) {
            sectionalFail('The chart could not be read.');
            return;
        }
        if (!sect.image) {
            const u = sect.chart.usable;
            sect.image = svg('image', {x: u.x, y: u.y, width: u.w, height: u.h, preserveAspectRatio: 'none', 'class': 'pm-sectional'});
            sectionalHolder.appendChild(sect.image);
            applyOpacity();
            setCredit(true);
        }
        sect.image.setAttribute('href', url);
        sect.image.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', url);  // Safari 12 reads only this one
    }

    function sectionalDone(run) {
        const a = sect.active;
        if (!a || run !== sect.run) return;
        if (a.timer) { clearTimeout(a.timer); a.timer = null; }
        showCanvas(a);
        if (sect.active !== a) return;  // showCanvas found the canvas unreadable
        a.dirty = false;
        setStatus(a.failed
            ? plural(a.failed, 'chart tile') + ' could not be loaded.'
            : 'The chart is loaded.', '');
        a.canvas = a.out = a.order = a.starts = null;  // the picture is in the page now; let the memory go
    }

    sect.box.addEventListener('change', function () {
        store(KEY_SHOW, sect.box.checked ? '1' : '0');
        if (sect.box.checked) {
            startSectional();
        } else {
            stopSectional();
            removeImage();
            setStatus('', '');
        }
    });
    sect.range.addEventListener('input', function () {
        applyOpacity();
        store(KEY_OPACITY, sect.range.value);
    });
    (function restoreSectional() {
        const op = parseInt(stored(KEY_OPACITY), 10);
        if (op >= 10 && op <= 100) sect.range.value = op;
        sect.box.checked = stored(KEY_SHOW) === '1';
        applyOpacity();
    })();

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

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

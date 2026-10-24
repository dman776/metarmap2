// METARMap web UI helpers
(function () {
    'use strict';

    async function call(url) {
        const res = await fetch(url, {credentials: 'same-origin'});
        if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
        return res.text();
    }

    function busy(btn, on) {
        if (!btn) return;
        btn.disabled = on;
        btn.setAttribute('aria-busy', on ? 'true' : 'false');
    }

    // <button data-call="/url" data-then="reload|home|none" data-confirm="Are you sure?">
    document.addEventListener('click', async function (e) {
        const btn = e.target.closest('[data-call]');
        if (!btn) return;
        e.preventDefault();
        if (btn.dataset.confirm && !window.confirm(btn.dataset.confirm)) return;
        busy(btn, true);
        try {
            const text = await call(btn.dataset.call);
            const then = btn.dataset.then || 'reload';
            if (then === 'dialog') {
                showOutput(btn.dataset.title || 'Output', text);
            } else if (then === 'home') {
                window.location.href = '/';
            } else if (then === 'reload') {
                window.location.reload();
            }
        } catch (err) {
            // restart drops the connection before it answers
            if (btn.dataset.then !== 'none') showOutput('Error', String(err));
        } finally {
            busy(btn, false);
        }
    });

    // output dialog (update log, errors)
    function showOutput(title, text) {
        const dlg = document.getElementById('output');
        if (!dlg) return;
        dlg.querySelector('h2').textContent = title;
        dlg.querySelector('.body').textContent = text.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '');
        dlg.showModal();
    }
    window.metarmapOutput = showOutput;

    // range inputs with a live label: <input type=range data-label="id" data-format="pct|sec">
    document.querySelectorAll('input[type=range][data-label]').forEach(function (r) {
        const out = document.getElementById(r.dataset.label);
        const fmt = function (v) {
            return r.dataset.format === 'pct' ? Math.round(v * 100) + '%' : v + ' s';
        };
        r.addEventListener('input', function () { if (out) out.textContent = fmt(r.value); });
    });

    // "last METAR fetch" age, kept current while the page is open
    const fetched = document.querySelector('[data-fetched]');
    if (fetched && fetched.dataset.fetched) {
        const at = parseInt(fetched.dataset.fetched, 10) * 1000;
        const ago = fetched.querySelector('.ago');
        const tick = function () {
            const min = Math.max(0, Math.floor((Date.now() - at) / 60000));
            ago.textContent = '· ' + (min < 1 ? 'just now' : min === 1 ? '1 min ago' : min + ' min ago') +
                (min >= 20 ? ' · may be stale' : '');
            fetched.classList.toggle('stale', min >= 20);
        };
        tick();
        setInterval(tick, 30000);
    }

    // brightness slider
    const brt = document.getElementById('brightness');
    if (brt) {
        brt.addEventListener('change', function () { call('/brightness/' + brt.value); });
    }

    // config settings: <input data-key="a.b" data-restart> / <select data-key>
    document.querySelectorAll('[data-key]').forEach(function (el) {
        el.addEventListener('change', async function () {
            const value = el.type === 'checkbox' ? el.checked : el.value;
            try {
                await call('/config/edit/' + el.dataset.key + '/' + encodeURIComponent(value));
                if (el.hasAttribute('data-restart')) {
                    const banner = document.getElementById('restart-banner');
                    if (banner) banner.hidden = false;
                }
            } catch (err) {
                showOutput('Could not save', String(err));
            }
        });
    });

    // map center: two inputs saved together as [lat, lon]
    document.querySelectorAll('[data-center]').forEach(function (el) {
        el.addEventListener('change', function () {
            const v = Array.from(document.querySelectorAll('[data-center]')).map(function (i) { return parseFloat(i.value); });
            if (v.some(isNaN)) return;
            call('/config/edit/geo.map.center/' + encodeURIComponent(JSON.stringify(v)))
                .catch(function (err) { showOutput('Could not save', String(err)); });
        });
    });

    // airports: code edits and OLED display toggles
    document.querySelectorAll('[data-airport]').forEach(function (el) {
        el.addEventListener('change', function () {
            const code = el.dataset.airport;
            if (el.type === 'checkbox') {
                call('/config/airports/edit/prop/' + code + '/display/' + el.checked);
            } else if (el.value && el.value.toUpperCase() !== code) {
                window.location.href = '/config/airports/edit/' + code + '/' + el.value.toUpperCase();
            }
        });
    });

    // METAR list: category filter + search
    const rows = document.querySelectorAll('[data-station]');
    if (rows.length) {
        let cat = 'all';
        const search = document.getElementById('station-search');
        const apply = function () {
            const q = search ? search.value.trim().toUpperCase() : '';
            rows.forEach(function (row) {
                const okCat = cat === 'all' || row.dataset.cat === cat;
                const okQ = !q || row.dataset.station.indexOf(q) !== -1;
                row.hidden = !(okCat && okQ);
            });
        };
        document.querySelectorAll('[data-filter]').forEach(function (b) {
            b.addEventListener('click', function () {
                cat = b.dataset.filter;
                document.querySelectorAll('[data-filter]').forEach(function (o) {
                    o.setAttribute('aria-pressed', o === b ? 'true' : 'false');
                });
                apply();
            });
        });
        if (search) search.addEventListener('input', apply);
    }
})();

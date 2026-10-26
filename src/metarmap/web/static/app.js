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

    // <button data-call="/url" data-then="reload|home|dialog|restart|none" data-confirm="Are you sure?">
    document.addEventListener('click', async function (e) {
        const btn = e.target.closest('[data-call]');
        if (!btn) return;
        e.preventDefault();
        if (btn.dataset.confirm && !window.confirm(btn.dataset.confirm)) return;
        if (btn.dataset.then === 'restart') {
            restartMap(btn.dataset.call);
            return;
        }
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

    // ---- restart: close any popup, wait, then reload once the map answers again ------------------------------

    const RESTART_WAIT_S = 5;
    const RESTART_POLL_MS = 3000;
    const RESTART_GIVE_UP_S = 90;  // after the wait; then reload anyway

    async function mapIsUp() {
        const ctrl = new AbortController();
        const timer = setTimeout(function () { ctrl.abort(); }, 2500);
        try {
            const res = await fetch('/api/status', {cache: 'no-store', signal: ctrl.signal});
            return res.ok;
        } catch (err) {
            return false;
        } finally {
            clearTimeout(timer);
        }
    }

    function restartMap(url) {
        document.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
        // the map restarts before it can answer, so don't wait for a response
        fetch(url, {credentials: 'same-origin'}).catch(function () {});

        const overlay = document.createElement('div');
        overlay.className = 'restarting';
        overlay.setAttribute('role', 'status');
        const card = document.createElement('div');
        card.className = 'card restarting-card';
        const title = document.createElement('h2');
        title.textContent = 'Restarting the map';
        const label = document.createElement('p');
        const bar = document.createElement('progress');
        bar.className = 'update-bar';
        bar.max = RESTART_WAIT_S;
        bar.value = 0;
        card.append(title, label, bar);
        overlay.append(card);
        document.body.append(overlay);

        let left = RESTART_WAIT_S;
        const tick = function () {
            label.textContent = 'Reloading this page in ' + left + ' s';
            bar.value = RESTART_WAIT_S - left;
        };
        tick();
        const countdown = setInterval(async function () {
            left -= 1;
            if (left > 0) {
                tick();
                return;
            }
            clearInterval(countdown);
            bar.removeAttribute('value');  // indeterminate while waiting
            label.textContent = 'Waiting for the map to come back…';
            const giveUp = Date.now() + RESTART_GIVE_UP_S * 1000;
            while (Date.now() < giveUp && !(await mapIsUp())) {
                await new Promise(function (resolve) { setTimeout(resolve, RESTART_POLL_MS); });
            }
            window.location.reload();
        }, 1000);
    }

    // ---- update: a progress bar instead of git's output ----------------------------------------------------------

    async function runUpdate(btn) {
        const dlg = document.getElementById('update-dialog');
        if (!dlg) return;
        const label = dlg.querySelector('.update-label');
        const bar = dlg.querySelector('.update-bar');
        const errors = dlg.querySelector('.update-errors');
        const restart = dlg.querySelector('.update-restart');
        label.textContent = 'Starting';
        bar.value = 0;
        errors.hidden = true;
        restart.hidden = true;
        dlg.showModal();
        busy(btn, true);
        try {
            let res = await fetch('/update/start', {method: 'POST', credentials: 'same-origin'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            let job = await res.json();
            while (!job.done) {
                bar.value = job.fraction;
                label.textContent = job.label + '…';
                await new Promise(function (resolve) { setTimeout(resolve, 500); });
                res = await fetch('/update/progress', {cache: 'no-store', credentials: 'same-origin'});
                if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
                job = await res.json();
            }
            bar.value = 1;
            if (job.ok) {
                label.textContent = job.changed ? 'Update installed. Restart the map to start using it.'
                    : 'Already up to date.';
                restart.hidden = !job.changed;
            } else {
                label.textContent = 'Update failed.';
                errors.textContent = (job.errors || []).join('\n');
                errors.hidden = !errors.textContent;
            }
        } catch (err) {
            label.textContent = 'Update failed.';
            errors.textContent = String(err);
            errors.hidden = false;
        } finally {
            busy(btn, false);
        }
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-update]');
        if (!btn) return;
        e.preventDefault();
        runUpdate(btn);
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

    // OLED display switch on the Home page
    const oledOn = document.getElementById('oled-on');
    if (oledOn) {
        oledOn.addEventListener('change', async function () {
            try {
                await call('/display/' + (oledOn.checked ? 'on' : 'off'));
            } catch (err) {
                oledOn.checked = !oledOn.checked;
                showOutput('Could not change the display', String(err));
            }
        });
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

    // Config > Visualizer: the unticked visualizers are saved as a list of names (visualizer.auto_rotate.skip)
    const rotateBoxes = document.querySelectorAll('[data-rotate]');
    rotateBoxes.forEach(function (box) {
        box.addEventListener('change', async function () {
            const left = Array.from(rotateBoxes).filter(function (b) { return !b.checked; })
                .map(function (b) { return b.dataset.rotate; });
            try {
                await call('/config/edit/visualizer.auto_rotate.skip/' + encodeURIComponent(JSON.stringify(left)));
            } catch (err) {
                box.checked = !box.checked;
                showOutput('Could not save', String(err));
            }
        });
    });

    // POSTs JSON (passwords never go in a URL); an error's message is bottle's <pre> text
    async function postJSON(url, data) {
        const res = await fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
        });
        const text = await res.text();
        if (!res.ok) {
            const pre = /<pre>([\s\S]*?)<\/pre>/i.exec(text);
            throw new Error(pre ? pre[1].replace(/&#039;|&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&') : res.status + ' ' + res.statusText);
        }
        return JSON.parse(text);
    }

    // Config > Access: <form data-form="/url" data-then="login|wifi">
    document.querySelectorAll('form[data-form]').forEach(function (form) {
        form.addEventListener('submit', async function (e) {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(form).entries());
            const button = form.querySelector('[type=submit]');
            if (form.dataset.then === 'login') {
                if (data.password !== data.confirm) {
                    showOutput('Passwords don’t match', 'Type the same new password in both boxes.');
                    return;
                }
                delete data.confirm;
            } else if (form.dataset.then === 'wifi') {
                const current = button.dataset.current;
                if (!window.confirm('Switch the map to the Wi-Fi network "' + data.ssid + '"?\n\nThis device must join that network too to reach the map.'
                        + (current ? ' If the map can’t connect, it goes back to "' + current + '".' : ''))) return;
            }
            busy(button, true);
            try {
                const result = await postJSON(form.dataset.form, data);
                if (form.dataset.then === 'login') {
                    showOutput('Login saved', 'Web UI user: ' + result.user + '\nPi password: ' + result.linux_password
                        + '\n\nYour browser will ask you to log in again with the new details.');
                    form.querySelectorAll('input[type=password]').forEach(function (i) { i.value = ''; });
                } else {
                    showOutput('Switching Wi-Fi', 'In ' + result.delay + ' seconds the map switches to "' + result.ssid + '".\n\n'
                        + 'Join this device to "' + result.ssid + '", then open http://' + window.location.host + '/ again.'
                        + (result.current ? '\nIf the map can’t connect, it goes back to "' + result.current + '".' : ''));
                }
            } catch (err) {
                showOutput('Not saved', err.message);
            } finally {
                busy(button, false);
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

    // airports: each LED's code, name and OLED switch ("-" clears a code or name)
    document.querySelectorAll('[data-led]').forEach(function (el) {
        el.addEventListener('change', async function () {
            const field = el.dataset.field;
            let value = el.type === 'checkbox' ? el.checked : el.value.trim();
            if (field === 'code') value = value.toUpperCase();
            try {
                // "-" stands for an empty code or name; a switch's false is sent as it is
                await call('/config/airports/' + el.dataset.led + '/' + field + '/' + encodeURIComponent(value === '' ? '-' : value));
                // a new code changes the row (OLED switch, map data)
                if (field === 'code') window.location.reload();
            } catch (err) {
                showOutput('Could not save', String(err));
            }
        });
    });

    // airports: number of LEDs; lowering it removes the airports on the last LEDs
    const ledCount = document.querySelector('[data-led-count]');
    if (ledCount) {
        ledCount.addEventListener('change', async function () {
            const n = parseInt(ledCount.value, 10);
            const was = parseInt(ledCount.dataset.ledCount, 10);
            if (!(n >= 1) || n === was) return;
            const removed = Array.from(document.querySelectorAll('[data-row]'))
                .filter(function (row) { return parseInt(row.dataset.row, 10) >= n && row.dataset.code; })
                .map(function (row) { return row.dataset.code; });
            if (removed.length && !window.confirm('Remove ' + removed.join(', ') + ' from the map?')) {
                ledCount.value = was;
                return;
            }
            try {
                await call('/config/edit/led.count/' + n);
                window.location.reload();
            } catch (err) {
                showOutput('Could not save', String(err));
            }
        });
    }

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

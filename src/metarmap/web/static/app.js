// MetarMap2 web UI helpers
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

    const RESTART_WAIT_S = 10;
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

    // version: a release picked on Config (older ones too); none: what the update channel says.
    // New code that installed restarts the map at once, so it's running.
    const UPDATE_RESTART_MS = 1500;  // long enough to read what was installed
    async function runUpdate(btn, version) {
        const dlg = document.getElementById('update-dialog');
        if (!dlg) return;
        const label = dlg.querySelector('.update-label');
        const bar = dlg.querySelector('.update-bar');
        const errors = dlg.querySelector('.update-errors');
        label.textContent = 'Starting';
        bar.value = 0;
        errors.hidden = true;
        dlg.showModal();
        busy(btn, true);
        try {
            let res = await fetch('/update/start', version ? {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({version: version})
            } : {method: 'POST', credentials: 'same-origin'});
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
                label.textContent = job.changed
                    ? (job.message || 'Update installed') + '. Restarting the map…'
                    : (job.message || 'Already up to date') + '.';
                if (job.changed) {
                    setTimeout(function () { restartMap('/restart'); }, UPDATE_RESTART_MS);
                }
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

    // Config > Software: install the release picked in the list, older ones too
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-install-release]');
        if (!btn) return;
        e.preventDefault();
        const pick = document.getElementById('release-pick');
        const option = pick && pick.selectedOptions[0];
        if (!option) return;
        if (option.dataset.older === 'true' && !window.confirm('Go back to ' + option.value + '? Your settings are '
                + 'kept; settings that only newer versions have are ignored by it.')) return;
        runUpdate(btn, option.value);
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

    // ---- an ATIS to read along (/api/atis/<code>/lines): each line the FAA's text, then how it's said. While the
    // audio plays, the line being said is lit and kept in view. The voice doesn't say when it reaches a line, so it's
    // worked out from how long each line's words are: close, not exact. remote.js uses it too (window.metarmapTranscript)
    const transcript = {
        render: function (list, lines) {
            list.textContent = '';
            lines.forEach(function (line) {
                const li = document.createElement('li');
                const raw = document.createElement('span');
                raw.className = 'tx-raw';
                raw.textContent = line.raw;
                const said = document.createElement('span');
                said.className = 'tx-said';
                said.textContent = line.said;
                if (line.raw) li.appendChild(raw);
                li.appendChild(said);
                list.appendChild(li);
            });
            list.hidden = !lines.length;
        },
        // lights the line being said while `audio` plays; returns a function that stops following it
        follow: function (list, audio, lines) {
            const weights = lines.map(function (line) { return line.said.length + 12; });  // + a pause between lines
            const total = weights.reduce(function (a, b) { return a + b; }, 0) || 1;
            let lit = -1;
            const light = function (i) {
                if (i === lit) return;
                const items = list.children;
                if (items[lit]) items[lit].classList.remove('current');
                lit = i;
                if (items[i]) {
                    items[i].classList.add('current');
                    items[i].scrollIntoView({block: 'nearest', behavior: 'smooth'});
                }
            };
            const update = function () {
                if (!audio.duration || !isFinite(audio.duration)) return;
                const at = audio.currentTime / audio.duration * total;
                let sum = 0;
                for (let i = 0; i < weights.length; i++) {
                    sum += weights[i];
                    if (at < sum) { light(i); return; }
                }
                light(weights.length - 1);
            };
            const done = function () { light(-1); };
            audio.addEventListener('timeupdate', update);
            audio.addEventListener('ended', done);
            return function () {
                audio.removeEventListener('timeupdate', update);
                audio.removeEventListener('ended', done);
                light(-1);
            };
        },
        // runs show() once `audio` starts playing (now, if it has): the words wait for the sound, which can take
        // half a minute to be made; returns a function that cancels the wait
        whenPlaying: function (audio, show) {
            if (!audio.paused && audio.currentTime > 0) {
                show();
                return function () {};
            }
            const once = function () {
                audio.removeEventListener('playing', once);
                show();
            };
            audio.addEventListener('playing', once);
            return function () { audio.removeEventListener('playing', once); };
        },
        lines: async function (code) {
            const res = await fetch('/api/atis/' + encodeURIComponent(code) + '/lines', {cache: 'no-store'});
            if (!res.ok) throw new Error((await res.text()).trim() || res.status + ' ' + res.statusText);
            return (await res.json()).lines;
        },
    };
    window.metarmapTranscript = transcript;

    // range inputs with a live label: <input type=range data-label="id" data-format="pct|sec|x">
    document.querySelectorAll('input[type=range][data-label]').forEach(function (r) {
        const out = document.getElementById(r.dataset.label);
        const fmt = function (v) {
            if (r.dataset.format === 'pct') return Math.round(v * 100) + '%';
            return r.dataset.format === 'x' ? v + '×' : v + ' s';  // x: a speed, 1.25×
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

    // Home's Fetch METARs: a ring and m:ss counting down to the next fetch (the map's, or a retry's), from
    // /api/live's fetch. Once the fetch has come (fetch.fetched is newer than this page's), the page reloads.
    const fetchRing = document.getElementById('fetch-ring');
    if (fetchRing) {
        const POLL_MS = 15000;
        const DUE_POLL_MS = 2000;  // after the countdown ends, until the fetch has come
        const ringLeft = document.getElementById('fetch-ring-left');
        const ringTime = document.getElementById('fetch-time');
        const icon = document.querySelector('.fetch-icon');
        const pageFetched = fetched && fetched.dataset.fetched ? parseInt(fetched.dataset.fetched, 10) : null;
        let fetchAt = null;  // when the next fetch comes, in this browser's time (ms)
        let fetchSeconds = 0;
        let timer = null;

        const showRing = function (on) {
            // the attribute: an <svg> has no .hidden property
            fetchRing.toggleAttribute('hidden', !on);
            icon.toggleAttribute('hidden', on);
            if (!on) ringTime.textContent = '';
        };
        const tickFetch = function () {
            if (fetchAt === null) return;
            const left = Math.max(0, Math.ceil((fetchAt - Date.now()) / 1000));
            ringTime.textContent = Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0');
            const part = fetchSeconds > 0 ? Math.min(100, 100 * left / fetchSeconds) : 0;
            ringLeft.setAttribute('stroke-dasharray', part.toFixed(1) + ' 100');
            if (left === 0 && timer !== null && !timer.due) {  // due: look often until the fetch has come
                clearTimeout(timer.id);
                timer = {id: setTimeout(pollFetch, DUE_POLL_MS), due: true};
            }
        };
        const pollFetch = async function () {
            let due = false;
            try {
                const res = await fetch('/api/live', {cache: 'no-store'});
                if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
                const live = await res.json();
                const f = live.fetch;
                if (f && f.fetched !== null && (pageFetched === null || f.fetched > pageFetched + 1)) {
                    window.location.reload();  // new METARs: show them
                    return;
                }
                if (!f || f.next === null) {
                    fetchAt = null;
                } else {
                    const at = Date.now() + Math.max(0, f.next - live.now) * 1000;
                    if (fetchAt === null || Math.abs(at - fetchAt) > 1500) fetchAt = at;  // no jump with each poll
                    fetchSeconds = f.seconds || 0;
                    due = f.next <= live.now;
                }
                showRing(fetchAt !== null);
            } catch (err) {
                console.error('[home] fetch countdown failed', err);
            }
            timer = {id: setTimeout(pollFetch, due ? DUE_POLL_MS : POLL_MS), due: due};
            tickFetch();
        };
        pollFetch();
        setInterval(tickFetch, 250);
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
            let value = el.type === 'checkbox' ? el.checked : el.value;
            if (value === '' && el.dataset.empty) value = el.dataset.empty;  // a URL can't end in nothing: "-" is empty
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

    // Config > System > Spoken weather: Test plays an airport's report here, or says why it can't
    const speechTest = document.getElementById('speech-test');
    if (speechTest) {
        const result = document.getElementById('speech-test-result');
        const idle = result.textContent;
        let player = null;
        speechTest.addEventListener('click', async function () {
            if (player) player.pause();
            const url = '/api/speak/' + encodeURIComponent(speechTest.dataset.code) + '.audio';
            busy(speechTest, true);
            const engine = document.getElementById('speech-engine');
            result.textContent = engine && engine.value === 'kokoro' ? 'Asking Kokoro...' : 'Asking Home Assistant...';
            result.classList.remove('bad');
            try {
                const res = await fetch(url, {cache: 'no-store'});
                if (!res.ok) throw new Error((await res.text()).trim() || res.status + ' ' + res.statusText);
                player = new Audio(URL.createObjectURL(await res.blob()));
                player.addEventListener('ended', function () { result.textContent = idle; });
                await player.play();
                result.textContent = 'Playing...';
            } catch (err) {
                result.textContent = err.name === 'NotAllowedError' ? 'The browser blocked sound: press Play again' : String(err.message || err);
                result.classList.add('bad');
            } finally {
                busy(speechTest, false);
            }
        });
    }

    // Config tabs: #physical, #visualizers, ... show one panel; the address keeps the tab, and the last one is
    // remembered for the next visit. Airports is its own page (/config/airports).
    const panels = document.querySelectorAll('[data-panel]');
    if (panels.length) {
        const TAB_KEY = 'metarmap.config.tab';
        const keys = Array.from(panels).map(function (p) { return p.dataset.panel; });
        const showTab = function (key) {
            if (key === 'airports') {
                location.replace('/config/airports');
                return;
            }
            if (keys.indexOf(key) < 0) key = keys[0];
            panels.forEach(function (p) { p.hidden = p.dataset.panel !== key; });
            document.querySelectorAll('.tab[data-tab]').forEach(function (tab) {
                if (tab.dataset.tab === key) {
                    tab.setAttribute('aria-current', 'page');
                    tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                } else {
                    tab.removeAttribute('aria-current');
                }
            });
            try { localStorage.setItem(TAB_KEY, key); } catch (e) { /* private mode: not remembered */ }
        };
        let remembered = null;
        try { remembered = localStorage.getItem(TAB_KEY); } catch (e) { /* private mode */ }
        window.addEventListener('hashchange', function () { showTab(location.hash.slice(1)); });
        showTab(location.hash.slice(1) || remembered);
    }

    // Config: settings nested under another, <div class="sub" data-when="control-id" [data-when-value="v" |
    // data-when-filled]>, show while its switch is on (or its select has that value, or its text box has something).
    // The page is drawn with them already shown or hidden.
    document.querySelectorAll('[data-when]').forEach(function (group) {
        const control = document.getElementById(group.dataset.when);
        if (!control) return;
        const update = function () {
            if ('whenFilled' in group.dataset) group.hidden = !control.value.trim();  // a text box that has something
            else group.hidden = 'whenValue' in group.dataset ? control.value !== group.dataset.whenValue : !control.checked;
        };
        control.addEventListener('change', update);
    });

    // Config > Visualizer: the unticked visualizers are saved as a list of ids (visualizer.auto_rotate.skip)
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

    // airports (dev_mode): a mock METAR in place of the airport's real one; empty goes back to the real one
    document.querySelectorAll('[data-mock]').forEach(function (el) {
        el.addEventListener('change', async function () {
            try {
                await postJSON('/config/airports/mock', {pixel: +el.dataset.mock, metar: el.value.trim()});
                window.location.reload();  // the row's MOCK tag
            } catch (err) {
                showOutput('Could not save the mock METAR', String(err));
            }
        });
    });

    // airports: number of LEDs (led.count) and of virtual airports after them (led.virtual_count);
    // lowering one removes the airports on its last rows: data-first is the row its airports start at
    document.querySelectorAll('[data-led-count]').forEach(function (input) {
        input.addEventListener('change', async function () {
            const n = parseInt(input.value, 10);
            const was = parseInt(input.dataset.ledCount, 10);
            const first = parseInt(input.dataset.first, 10);
            if (!(n >= parseInt(input.min, 10)) || n === was) return;
            const removed = Array.from(document.querySelectorAll('[data-row]'))
                .filter(function (row) {
                    const pixel = parseInt(row.dataset.row, 10);
                    return pixel >= first + n && pixel < first + was && row.dataset.code;
                })
                .map(function (row) { return row.dataset.code; });
            if (removed.length && !window.confirm('Remove ' + removed.join(', ') + ' from the map?')) {
                input.value = was;
                return;
            }
            try {
                await call('/config/edit/' + input.dataset.countKey + '/' + n);
                window.location.reload();
            } catch (err) {
                input.value = was;
                showOutput('Could not save', String(err));
            }
        });
    });

    // METARs page: AWOS plays an airport's report here (/api/speak/<code>.audio, from the speech server), and ATIS
    // its real ATIS (/api/atis/<code>.audio). Another button switches to it; the one playing again stops. The sound
    // starts in the press itself (a phone only lets a page play sound in answer to a touch); if it can't play, the
    // map says why.
    const awosAudio = document.getElementById('awos-audio');
    if (awosAudio) {
        let playing = null;  // the button whose report is playing (or loading)
        // an ATIS shows its words to read along, in a panel at the bottom; × closes it (and stops it)
        const sheet = document.getElementById('atis-sheet');
        let unfollow = function () {};
        const closeSheet = function () {
            unfollow();
            if (sheet) sheet.hidden = true;
        };
        const openSheet = async function (btn) {
            if (!sheet) return;
            const code = btn.dataset.atis;
            sheet.querySelector('h2').textContent = code + ' ATIS';
            const list = sheet.querySelector('.tx');
            try {
                const lines = await transcript.lines(code);  // fetched while the audio is made...
                if (playing !== btn) return;
                unfollow = transcript.whenPlaying(awosAudio, function () {  // ...shown once it plays
                    if (playing !== btn) return;
                    transcript.render(list, lines);
                    sheet.hidden = false;
                    unfollow = transcript.follow(list, awosAudio, lines);
                });
            } catch (e) { /* the audio says why it can't */ }
        };
        if (sheet) sheet.querySelector('.tx-close').addEventListener('click', function () { stop(); closeSheet(); });
        const reset = function () {
            if (!playing) return;
            playing.setAttribute('aria-pressed', 'false');
            playing.classList.remove('loading');
            playing = null;
        };
        const stop = function () {
            awosAudio.pause();
            awosAudio.removeAttribute('src');
            awosAudio.load();
            reset();
        };
        const isAtis = function (btn) { return 'atis' in btn.dataset; };
        const codeOf = function (btn) { return isAtis(btn) ? btn.dataset.atis : btn.dataset.awos; };
        const urlOf = function (btn) {
            return (isAtis(btn) ? '/api/atis/' : '/api/speak/') + encodeURIComponent(codeOf(btn)) + '.audio';
        };
        const failed = async function (btn, err) {
            const what = isAtis(btn) ? 'ATIS' : 'AWOS';
            let why = 'It could not be played.';
            try {
                const res = await fetch(urlOf(btn), {cache: 'no-store'});
                if (!res.ok) why = (await res.text()).trim() || why;
                else if (err && err.name === 'NotAllowedError') why = 'The browser blocked sound: press ' + what + ' again.';
            } catch (e) {
                why = "Can't reach the map.";
            }
            if (playing !== btn) return;  // switched or stopped meanwhile
            stop();
            showOutput(codeOf(btn) + (isAtis(btn) ? ': no ATIS' : ': no spoken weather'), why);
        };
        document.querySelectorAll('[data-awos], [data-atis]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (playing === btn) {
                    stop();
                    return;
                }
                reset();
                closeSheet();
                playing = btn;
                btn.setAttribute('aria-pressed', 'true');
                btn.classList.add('loading');
                awosAudio.src = urlOf(btn);
                if (isAtis(btn)) openSheet(btn);
                const started = awosAudio.play();
                if (started) started.catch(function (err) {
                    if (err.name !== 'AbortError' && playing === btn) failed(btn, err);
                });
            });
        });
        awosAudio.addEventListener('playing', function () { if (playing) playing.classList.remove('loading'); });
        awosAudio.addEventListener('ended', stop);
        awosAudio.addEventListener('error', function () {
            if (playing && awosAudio.getAttribute('src')) failed(playing, awosAudio.error);
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
    // ---- the Pronunciation page: the tunings (rows of: the FAA's text, say it as, airport), Save sends the whole
    // list; a suggested word adds a row for it; Try it shows and plays an airport's ATIS as saved
    const tunings = document.getElementById('tunings');
    if (tunings) {
        const rows = document.getElementById('tn-rows');
        const empty = document.getElementById('tn-empty');
        const status = document.getElementById('tn-status');
        const codes = tunings.dataset.codes ? tunings.dataset.codes.split(' ') : [];
        const showEmpty = function () { empty.hidden = rows.children.length > 0; };
        const wire = function (row) {
            row.querySelector('.tn-remove').addEventListener('click', function () {
                row.remove();
                showEmpty();
                status.textContent = 'Not saved yet.';
            });
            row.querySelectorAll('input, select').forEach(function (el) {
                el.addEventListener('input', function () { status.textContent = 'Not saved yet.'; });
            });
        };
        const addRow = function (text) {
            const row = document.createElement('div');
            row.className = 'tn-row trow';
            row.innerHTML = '<input type="text" class="tn-text" aria-label="The FAA writes" autocapitalize="characters" spellcheck="false" maxlength="40">' +
                '<input type="text" class="tn-say" aria-label="Say it as" maxlength="120">' +
                '<select class="tn-airport" aria-label="Airport"><option value="">Every airport</option></select>' +
                '<button class="btn icon tn-remove" type="button" aria-label="Remove"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>';
            const select = row.querySelector('select');
            codes.forEach(function (c) {
                const o = document.createElement('option');
                o.value = o.textContent = c;
                select.appendChild(o);
            });
            row.querySelector('.tn-text').value = text || '';
            rows.appendChild(row);
            wire(row);
            showEmpty();
            row.querySelector(text ? '.tn-say' : '.tn-text').focus();
            status.textContent = 'Not saved yet.';
        };
        Array.from(rows.children).forEach(wire);
        document.getElementById('tn-add').addEventListener('click', function () { addRow(''); });
        document.querySelectorAll('[data-suggest]').forEach(function (chip) {
            chip.addEventListener('click', function () {
                addRow(chip.dataset.suggest);
                chip.remove();
            });
        });
        const save = document.getElementById('tn-save');
        save.addEventListener('click', async function () {
            const list = Array.from(rows.children).map(function (row) {
                return {
                    text: row.querySelector('.tn-text').value,
                    say: row.querySelector('.tn-say').value,
                    airport: row.querySelector('.tn-airport').value,
                };
            }).filter(function (t) { return t.text.trim() || t.say.trim(); });  // a row left empty is dropped
            busy(save, true);
            try {
                const res = await fetch('/config/tunings', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tunings: list}),
                });
                const text = await res.text();
                if (!res.ok) throw new Error(text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || res.statusText);
                const saved = JSON.parse(text).tunings;
                status.textContent = 'Saved ' + saved.length + (saved.length === 1 ? ' tuning.' : ' tunings.');
                rows.querySelectorAll('.tn-text').forEach(function (input, i) {  // as saved: in capitals
                    if (saved[i]) input.value = saved[i].text;
                });
                if (shown) show();
            } catch (err) {
                showOutput('Could not save', String(err.message || err));
            } finally {
                busy(save, false);
            }
        });

        const pick = document.getElementById('tn-airport');
        const list = document.getElementById('tn-transcript');
        const audio = document.getElementById('tn-audio');
        const play = document.getElementById('tn-play');
        let shown = false, lines = [], unfollow = function () {};
        const show = async function () {
            try {
                lines = await transcript.lines(pick.value);
                shown = true;
            } catch (err) {  // said in place of the lines: the page shows it on opening, unasked
                lines = [{raw: '', said: "Couldn't get " + pick.value + "'s ATIS: " + String(err.message || err)}];
            }
            transcript.render(list, lines);
        };
        // Play's three looks: idle (Play), getting (glowing: the ATIS is fetched and read, which can take half a
        // minute), playing (Stop: press it to stop)
        const playLabel = play && play.querySelector('.tn-play-label');
        const playState = function (state) {
            play.setAttribute('aria-pressed', state === 'idle' ? 'false' : 'true');
            play.classList.toggle('loading', state === 'getting');
            playLabel.textContent = state === 'getting' ? 'Getting the ATIS...' : state === 'playing' ? 'Stop' : 'Play';
            play.title = state === 'idle' ? '' : 'Press to stop';
        };
        const stopPlaying = function () {
            unfollow();
            unfollow = function () {};
            audio.pause();
            audio.removeAttribute('src');
            audio.load();
            playState('idle');
        };
        if (pick) {
            document.getElementById('tn-show').addEventListener('click', function () { stopPlaying(); show(); });
            pick.addEventListener('change', function () { stopPlaying(); show(); });
            play.addEventListener('click', async function () {
                if (play.getAttribute('aria-pressed') === 'true') { stopPlaying(); return; }
                playState('getting');
                audio.src = '/api/atis/' + encodeURIComponent(pick.value) + '.audio';
                const started = audio.play();  // in the press: a phone only plays sound in answer to a touch
                await show();
                unfollow();
                unfollow = transcript.follow(list, audio, lines);
                if (started) started.catch(async function (err) {
                    if (err.name === 'AbortError') return;
                    let why = String(err.message || err);
                    try {
                        const res = await fetch(audio.src, {cache: 'no-store'});
                        if (!res.ok) why = (await res.text()).trim() || why;
                    } catch (e) { /* as it is */ }
                    stopPlaying();
                    showOutput(pick.value + ': no ATIS', why);
                });
            });
            audio.addEventListener('playing', function () { playState('playing'); });
            audio.addEventListener('ended', function () { playState('idle'); });
            show();
        }
    }
})();

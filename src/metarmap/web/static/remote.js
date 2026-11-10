// MetarMap2 remote: the Remote page's tabs, and keeping it in step with the map, whoever changes it (another remote,
// auto-rotate, Home Assistant). The buttons themselves are app.js's data-call buttons.
(function () {
    'use strict';

    // opened at http://user:password@map/remote (an old bookmark): browsers refuse fetch() from a page whose address
    // has a login in it, so go to the same page without it
    const here = new URL(document.URL);  // location.href leaves the login out
    if (here.username || here.password) {
        here.username = here.password = '';
        window.location.replace(here.href);
        return;
    }

    // the page fills the window: an older iPad's Safari has no dvh, and its 100vh reaches under the toolbars
    function fitHeight() {
        document.documentElement.style.setProperty('--kiosk-h', window.innerHeight + 'px');
    }
    fitHeight();
    window.addEventListener('resize', fitHeight);
    function fitSoon() {  // again once Safari has finished rotating, or going in or out of fullscreen
        fitHeight();
        setTimeout(fitHeight, 300);
        setTimeout(fitHeight, 1000);
    }
    window.addEventListener('orientationchange', fitSoon);
    document.addEventListener('fullscreenchange', fitSoon);
    document.addEventListener('webkitfullscreenchange', fitSoon);

    const LIVE_MS = 1000;
    const STATUS_MS = 60 * 1000;
    const HOLD_MS = 3000;  // after a touch, a control keeps what the user set while the map catches up
    const TAB_KEY = 'metarmap.remote.tab';
    const MODE_KEY = 'metarmap.remote.mode';
    // the Info tab's modes, and the old tabs' names: #locator and #awos (a kiosk's address, a remembered tab)
    const MODES = ['locate', 'awos', 'atis'];
    const OLD_TABS = {locator: 'locate', awos: 'awos', atis: 'atis'};

    const page = document.querySelector('.remote');
    const host = document.querySelector('.r-host');
    const visName = document.getElementById('r-vis-name');
    const visDesc = document.getElementById('r-vis-desc');
    const chips = Array.from(document.querySelectorAll('[data-vis]'));
    const legend = document.getElementById('r-legend');
    const paused = document.getElementById('r-paused');
    const grid = document.querySelector('.r-grid');
    const brt = document.getElementById('brightness');
    const brtLabel = document.getElementById('brt_label');
    const oled = document.getElementById('oled-on');
    const info = document.getElementById('info');
    const tiles = {};  // the Info tab's airports, by LED
    document.querySelectorAll('#info .r-apt').forEach(function (t) { tiles[t.dataset.pixel] = t; });
    const modeChips = Array.from(document.querySelectorAll('.r-modes [data-mode]'));
    const noAtis = document.getElementById('r-no-atis');
    let mode = 'locate';
    let quiet = function () {};  // stops what the Info tab is reading (set below, with the speech)

    // ---- the Map tab: map.js, loaded when the tab first opens, then told the map's size each time it opens -----
    const mapEl = document.getElementById('map');
    let mapLoaded = false;

    function openMap() {
        if (mapLoaded) {
            window.dispatchEvent(new Event('resize'));  // Leaflet re-measures the map on a window resize
            return;
        }
        mapLoaded = true;
        const script = document.createElement('script');
        script.src = mapEl.dataset.script;
        document.body.appendChild(script);
    }

    // ---- tabs: #locator in the address opens that one (for a kiosk), else the one last used in this browser ------
    const tabs = Array.from(document.querySelectorAll('[data-tab]'));

    function showTab(name, keep) {
        if (OLD_TABS[name]) {  // #locator, #awos, #atis: the Info tab in that mode
            setMode(OLD_TABS[name], keep);
            name = 'info';
        }
        const tab = tabs.find(function (t) { return t.dataset.tab === name; }) || tabs[0];
        if (tab.dataset.tab !== 'info') quiet();  // the reading is for the one looking
        if (tab.dataset.tab !== 'map') document.dispatchEvent(new Event('metarmap:quiet'));  // and the map popup's
        tabs.forEach(function (t) {
            const on = t === tab;
            t.setAttribute('aria-selected', on ? 'true' : 'false');
            t.tabIndex = on ? 0 : -1;
            document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
        });
        if (tab.dataset.tab === 'map') openMap();
        if (keep) {
            try { window.localStorage.setItem(TAB_KEY, tab.dataset.tab); } catch (e) { /* private window */ }
        }
        return tab;
    }

    tabs.forEach(function (t, i) {
        t.addEventListener('click', function () { showTab(t.dataset.tab, true); });
        t.addEventListener('keydown', function (e) {  // arrow keys move between tabs
            const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
            if (!step) return;
            showTab(tabs[(i + step + tabs.length) % tabs.length].dataset.tab, true).focus();
        });
    });
    // ---- Info: what a press on an airport does. Locate pulses its LED (app.js's data-call); AWOS and ATIS read it
    // aloud here (below). ATIS shows only the airports with a digital ATIS (/api/live's leds[].atis)
    const LABELS = {locate: 'Locate ', awos: 'Hear the weather at ', atis: 'Hear the ATIS at '};

    function setMode(next, keep) {
        const chip = modeChips.find(function (c) { return c.dataset.mode === next; });
        next = chip || next === 'locate' ? next : 'locate';  // AWOS or ATIS off: Locate
        if (next !== mode) quiet();
        mode = next;
        info.dataset.mode = mode;
        modeChips.forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.mode === mode ? 'true' : 'false'); });
        Object.keys(tiles).forEach(function (pixel) {
            const tile = tiles[pixel];
            if (mode === 'locate') tile.dataset.call = '/locate/' + pixel;
            else delete tile.dataset.call;  // a press reads it aloud instead
            tile.setAttribute('aria-label', LABELS[mode] + tile.dataset.station);
        });
        showNoAtis();
        if (keep) {
            try { window.localStorage.setItem(MODE_KEY, mode); } catch (e) { /* private window */ }
        }
    }

    function showNoAtis() {
        if (!noAtis) return;
        noAtis.hidden = mode !== 'atis' || Object.keys(tiles).some(function (p) { return tiles[p].dataset.atis === 'true'; });
    }

    modeChips.forEach(function (c) {
        c.addEventListener('click', function () { setMode(c.dataset.mode, true); });
    });

    let saved = null, savedMode = null;
    try {
        saved = window.localStorage.getItem(TAB_KEY);
        savedMode = window.localStorage.getItem(MODE_KEY);
    } catch (e) { /* private window */ }
    setMode(MODES.indexOf(savedMode) >= 0 ? savedMode : 'locate', false);
    showTab(window.location.hash.slice(1) || saved, false);
    window.addEventListener('hashchange', function () { showTab(window.location.hash.slice(1), false); });

    // ---- the visualizer ----------------------------------------------------------------------------------------
    let shown = +(chips.find(function (c) { return c.getAttribute('aria-pressed') === 'true'; }) || {dataset: {vis: -1}}).dataset.vis;
    let loading = null;

    function showVisualizer(index) {
        const chip = chips[index];
        chips.forEach(function (c) { c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'); });
        if (!chip) return;
        visName.textContent = chip.dataset.name;
        visDesc.textContent = chip.dataset.desc;
        const exclusive = chip.dataset.exclusive === 'true';
        paused.hidden = !exclusive;
        paused.textContent = 'Locate is paused by ' + chip.dataset.name;
        grid.classList.toggle('paused', exclusive);
    }

    async function followVisualizer(index) {
        if (index === shown || index === loading) return;
        loading = index;
        showVisualizer(index);
        try {
            const res = await fetch('/map/legend', {cache: 'no-store'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const html = await res.text();
            if (loading !== index) return;  // changed again while this one loaded
            legend.innerHTML = html;
            shown = index;
        } catch (err) {
            console.error('[remote] legend failed', err);
        } finally {
            if (loading === index) loading = null;  // try again on the next poll if it failed
        }
    }

    // a picked visualizer shows at once, not at the next poll
    chips.forEach(function (c) {
        c.addEventListener('click', function () { showVisualizer(+c.dataset.vis); });
    });

    // ---- auto-rotate: the switch (saved), and a countdown to the next visualizer ------------------------------
    const rotate = document.getElementById('auto-rotate');
    const clock = document.getElementById('r-clock');
    const clockLeft = document.getElementById('r-clock-left');
    const clockText = document.getElementById('r-clock-text');
    let rotateTouched = 0;
    let rotateAt = null;  // when the next visualizer comes, in this browser's time (ms)
    let rotateSeconds = 0;

    rotate.addEventListener('change', async function () {
        rotateTouched = Date.now();
        try {
            const res = await fetch('/visualizer/auto_rotate/' + (rotate.checked ? 'on' : 'off'), {cache: 'no-store'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            rotateTouched = 0;
            poll();  // the new countdown now, not at the next poll
        } catch (err) {
            console.error('[remote] auto-rotate failed', err);
        }
    });

    function showRotation(r, now) {
        if (Date.now() - rotateTouched < HOLD_MS) return;
        rotate.checked = r.enabled;
        rotateSeconds = r.seconds;
        if (!r.enabled || r.next === null) {
            rotateAt = null;
        } else {
            const at = Date.now() + Math.max(0, r.next - now) * 1000;
            if (rotateAt === null || Math.abs(at - rotateAt) > 1500) rotateAt = at;  // not jumping with each poll's delay
        }
        clock.hidden = rotateAt === null;
        tick();
    }

    function tick() {
        if (rotateAt === null) return;
        const left = Math.max(0, Math.ceil((rotateAt - Date.now()) / 1000));
        clockText.textContent = Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0');
        const part = rotateSeconds > 0 ? Math.min(100, 100 * left / rotateSeconds) : 0;
        clockLeft.setAttribute('stroke-dasharray', part.toFixed(1) + ' 100');
    }
    setInterval(tick, 250);

    // ---- brightness and the OLED switch: the map's, unless the user just changed them -------------------------
    let brtTouched = 0;
    let oledTouched = 0;
    if (brt) {
        ['input', 'change', 'pointerdown'].forEach(function (ev) {
            brt.addEventListener(ev, function () { brtTouched = Date.now(); });
        });
    }
    if (oled) oled.addEventListener('change', function () { oledTouched = Date.now(); });

    function showBrightness(level) {
        if (!brt || Date.now() - brtTouched < HOLD_MS || +brt.value === level) return;
        brt.value = level;
        brtLabel.textContent = Math.round(level * 100) + '%';
    }

    function showOled(display) {
        if (!oled || Date.now() - oledTouched < HOLD_MS) return;
        oled.checked = display.on;
    }

    // ---- airports: flight category colors, and a flash where the last locate pulsed -----------------------------
    let lastLocate = null;

    function showAirports(leds, locate, now) {
        leds.forEach(function (led) {
            const cat = /^(VFR|MVFR|IFR|LIFR)$/.test(led.flightCategory || '') ? led.flightCategory : 'none';
            const tile = tiles[led.pixel];
            if (!tile) return;
            if (tile.dataset.cat !== cat) {
                tile.dataset.cat = cat;
                tile.querySelector('.dot').className = 'dot ' + cat.toLowerCase();
            }
            if (led.atis !== undefined) tile.dataset.atis = led.atis ? 'true' : 'false';
        });
        showNoAtis();
        if (locate && locate.at !== lastLocate) {
            const fresh = lastLocate !== null || now - locate.at < 2;  // not one from before the page loaded
            lastLocate = locate.at;
            const tile = tiles[locate.pixel];
            if (fresh && tile) {
                tile.classList.remove('locating');
                void tile.offsetWidth;  // restart the animation
                tile.classList.add('locating');
            }
        }
    }

    // ---- polling -----------------------------------------------------------------------------------------------
    function online(ok) {
        host.classList.toggle('offline', !ok);
        page.classList.toggle('offline', !ok);
    }

    // visualizer.legend_in_use_only: the legend lists only the entries the LEDs show now (/api/live's legendInUse);
    // the others stay in the page, hidden, so they come back when an LED shows them. Not while the legend on screen
    // is still the previous visualizer's.
    function filterLegend(list, vis, shownIndex) {
        if (!list || vis.active !== shownIndex) return;
        const used = vis.legendInUseOnly && vis.legendInUse && vis.legendInUse.length ? vis.legendInUse : null;
        const rows = list.querySelectorAll('li[data-key]');
        for (let i = 0; i < rows.length; i++) {
            rows[i].hidden = used !== null && used.indexOf(rows[i].dataset.key) < 0;
        }
    }

    // which of a stepping visualizer's steps is on now (/api/live's visualizer.step: {labels, index}, or null)
    function markStep(root, step) {
        const items = root.querySelectorAll('.steps li');
        for (let i = 0; i < items.length; i++) items[i].classList.toggle('on', !!step && i === step.index);
    }

    async function poll() {
        try {
            const res = await fetch('/api/live', {cache: 'no-store'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const live = await res.json();
            online(true);
            followVisualizer(live.visualizer.active);
            filterLegend(legend.querySelector('.legend'), live.visualizer, shown);
            if (live.visualizer.active === shown) markStep(legend, live.visualizer.step);
            showRotation(live.visualizer.autoRotate, live.now);
            showBrightness(live.brightness);
            showOled(live.display);
            showAirports(live.leds, live.locate, live.now);
        } catch (err) {
            console.error('[remote] poll failed', err);
            online(false);
        }
    }

    // a map that came back with another version (updated and restarted) gets this page again: new templates
    async function pollVersion() {
        try {
            const res = await fetch('/api/status', {cache: 'no-store'});
            if (res.ok && (await res.json()).version !== page.dataset.version) window.location.reload();
        } catch (err) { /* poll() shows that the map can't be reached */ }
    }

    poll();
    setInterval(poll, LIVE_MS);
    setInterval(pollVersion, STATUS_MS);
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) { poll(); pollVersion(); }
    });

    // ---- AWOS and ATIS: an airport's METAR (/api/speak/<code>.audio) or real ATIS (/api/atis/<code>.audio) read
    // aloud by the map's speech server. A press plays it here, in the browser; another airport switches to it; the
    // one playing again (or Stop) stops. The audio is started in the press itself: a phone only lets a page play
    // sound in answer to a touch.
    const audio = document.getElementById('r-speak-audio');
    if (audio) {
        const bar = document.getElementById('r-speak-bar');
        const codeEl = document.getElementById('r-speak-code');
        const textEl = document.getElementById('r-speak-text');
        const stopBtn = document.getElementById('r-speak-stop');
        const idleText = textEl.textContent;
        let current = null;  // the button being read
        let base = '/api/speak/';  // and where its words come from: /api/speak/ (AWOS) or /api/atis/ (ATIS)
        let words = null;  // its text, once it's come
        const said = document.getElementById('r-transcript');  // an ATIS's lines, to read along
        let unfollow = function () {};
        function clearTranscript() {
            unfollow();
            unfollow = function () {};
            if (said) said.hidden = true;
        }
        const IDLE = {awos: 'Press an airport to hear its weather', atis: 'Press an airport to hear its ATIS'};

        function mark(btn, state) {  // state: 'loading', 'speaking' or null
            btn.classList.toggle('loading', state === 'loading');
            btn.classList.toggle('speaking', state === 'speaking');
            btn.setAttribute('aria-pressed', state ? 'true' : 'false');
        }
        function showBar(code, text, state) {
            codeEl.textContent = code || '';
            textEl.textContent = text;
            bar.dataset.state = state || '';
            stopBtn.hidden = !code || state === 'error';
        }
        function stop(message) {
            audio.pause();
            audio.removeAttribute('src');
            audio.load();  // drops what was loading
            if (current) mark(current, null);
            const code = current && current.dataset.speak;
            current = null;
            words = null;
            if (message) showBar(code, message, 'error');
            else showBar('', IDLE[mode] || idleText, '');
        }
        quiet = function () {
            clearTranscript();
            if (current) stop();
            else showBar('', IDLE[mode] || idleText, '');
        };
        quiet();
        // from: {line, lines}, to start at that line of the ATIS
        function speak(btn, from) {
            if (mode === 'locate') return;  // app.js's data-call locates it
            const code = btn.dataset.speak;
            if (current === btn) {
                stop();
                return;
            }
            if (current) mark(current, null);
            document.dispatchEvent(new CustomEvent('metarmap:speaking', {detail: 'info'}));  // the map popup's stops
            current = btn;
            base = mode === 'atis' ? '/api/atis/' : '/api/speak/';
            words = null;
            mark(btn, 'loading');
            showBar(code, mode === 'atis' ? 'Getting the ATIS...' : 'Getting the weather...', 'loading');
            audio.src = base + encodeURIComponent(code) + '.audio';
            const playing = audio.play();
            if (from) window.metarmapTranscript.seek(audio, from.lines, from.line);
            if (playing) playing.catch(function (err) {
                if (err.name !== 'AbortError' && current === btn) failed(btn, err);  // Abort: switched or stopped
            });
            clearTranscript();
            if (mode === 'atis' && said && window.metarmapTranscript) {
                // the ATIS line by line below the airports; the bar says which one it is
                const t = window.metarmapTranscript;
                t.lines(code).then(function (lines) {  // fetched while the audio is made, shown once it plays
                    if (current !== btn) return;
                    words = lines.length ? lines[0].said : null;
                    unfollow = t.whenPlaying(audio, function () {
                        if (current !== btn) return;
                        t.render(said, lines, false, function (i) {
                            if (current === btn) t.seek(audio, lines, i);
                            else speak(btn, {line: i, lines: lines});  // it has ended; the words are still there
                        });
                        unfollow = t.follow(said, audio, lines);
                        if (btn.classList.contains('speaking')) showBar(code, words || 'Speaking...', 'speaking');
                    });
                }).catch(function () { /* the audio says it all */ });
                return;
            }
            fetch(base + encodeURIComponent(code), {cache: 'no-store'})
                .then(function (res) { return res.ok ? res.text() : null; })
                .then(function (text) {
                    if (current !== btn || !text) return;
                    words = text;
                    if (btn.classList.contains('speaking')) showBar(code, words, 'speaking');
                })
                .catch(function () { /* the audio says it all */ });
        }
        // why it didn't play: the map says it in words (no server, the server or atis.info couldn't be reached)
        async function failed(btn, err) {
            let why = 'Could not play it';
            try {
                const res = await fetch(base + encodeURIComponent(btn.dataset.speak) + '.audio', {cache: 'no-store'});
                if (!res.ok) why = (await res.text()).trim() || why;
                else if (err && err.name === 'NotAllowedError') why = 'The browser blocked sound: press again';
            } catch (e) {
                why = "Can't reach the Chart";
            }
            if (current === btn) stop(why);
        }
        audio.addEventListener('playing', function () {
            if (!current) return;
            mark(current, 'speaking');
            showBar(current.dataset.speak, words || 'Speaking...', 'speaking');
        });
        audio.addEventListener('ended', function () { stop(); });
        audio.addEventListener('error', function () {
            if (current && audio.getAttribute('src')) failed(current, audio.error);
        });
        document.querySelectorAll('[data-speak]').forEach(function (btn) {
            btn.addEventListener('click', function () { speak(btn); });
        });
        stopBtn.addEventListener('click', function () { stop(); });
        // the map popup's Listen started: one voice at a time
        document.addEventListener('metarmap:speaking', function (e) { if (e.detail !== 'info' && current) stop(); });
        // the page hidden (another tab or mode: quiet(), above): quiet, as the reading is for the one looking
        document.addEventListener('visibilitychange', function () { if (document.hidden && current) stop(); });
    }

    // ---- fullscreen: the browser's own; on an iPhone (none) add the page to the Home Screen instead -------------
    const full = document.querySelector('.r-full');
    const root = document.documentElement;
    const request = root.requestFullscreen || root.webkitRequestFullscreen;
    const standalone = window.navigator.standalone || window.matchMedia('(display-mode: standalone)').matches ||
        window.matchMedia('(display-mode: fullscreen)').matches;
    function fullscreenElement() {
        return document.fullscreenElement || document.webkitFullscreenElement || null;
    }
    function fullscreenChanged() {
        const on = !!fullscreenElement();
        page.classList.toggle('fullscreen', on);
        full.setAttribute('aria-pressed', on ? 'true' : 'false');
        full.setAttribute('aria-label', on ? 'Exit fullscreen' : 'Fullscreen');
    }
    if (request && !standalone) {
        full.hidden = false;
        full.addEventListener('click', function () {
            if (fullscreenElement()) {
                (document.exitFullscreen || document.webkitExitFullscreen).call(document);
            } else {
                Promise.resolve(request.call(root)).catch(function (err) { console.error('[remote] fullscreen', err); });
            }
        });
        document.addEventListener('fullscreenchange', fullscreenChanged);
        document.addEventListener('webkitfullscreenchange', fullscreenChanged);
    }
})();

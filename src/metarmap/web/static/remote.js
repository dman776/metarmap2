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
    const tiles = {};  // the Locator's, by LED
    document.querySelectorAll('#locator .r-apt').forEach(function (t) { tiles[t.dataset.pixel] = t; });
    const speakTiles = {};  // the AWOS tab's, by LED
    document.querySelectorAll('#awos .r-apt').forEach(function (t) { speakTiles[t.dataset.pixel] = t; });

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
        const tab = tabs.find(function (t) { return t.dataset.tab === name; }) || tabs[0];
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
    let saved = null;
    try { saved = window.localStorage.getItem(TAB_KEY); } catch (e) { /* private window */ }
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
            [tiles[led.pixel], speakTiles[led.pixel]].forEach(function (tile) {
                if (tile && tile.dataset.cat !== cat) {
                    tile.dataset.cat = cat;
                    tile.querySelector('.dot').className = 'dot ' + cat.toLowerCase();
                }
            });
        });
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

    async function poll() {
        try {
            const res = await fetch('/api/live', {cache: 'no-store'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const live = await res.json();
            online(true);
            followVisualizer(live.visualizer.active);
            filterLegend(legend.querySelector('.legend'), live.visualizer, shown);
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

    // ---- AWOS: an airport's METAR read aloud (/api/speak/<code>.audio, made by Home Assistant's Piper) ------------
    // A press plays it here, in the browser; another airport switches to it; the one playing again (or Stop) stops.
    // The audio is started in the press itself: a phone only lets a page play sound in answer to a touch.
    const audio = document.getElementById('r-speak-audio');
    if (audio) {
        const bar = document.getElementById('r-speak-bar');
        const codeEl = document.getElementById('r-speak-code');
        const textEl = document.getElementById('r-speak-text');
        const stopBtn = document.getElementById('r-speak-stop');
        const idleText = textEl.textContent;
        let current = null;  // the button being read
        let words = null;  // its text, once it's come

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
            else showBar('', idleText, '');
        }
        function speak(btn) {
            const code = btn.dataset.speak;
            if (current === btn) {
                stop();
                return;
            }
            if (current) mark(current, null);
            current = btn;
            words = null;
            mark(btn, 'loading');
            showBar(code, 'Getting the weather...', 'loading');
            audio.src = '/api/speak/' + encodeURIComponent(code) + '.audio';
            const playing = audio.play();
            if (playing) playing.catch(function (err) {
                if (err.name !== 'AbortError' && current === btn) failed(btn, err);  // Abort: switched or stopped
            });
            fetch('/api/speak/' + encodeURIComponent(code), {cache: 'no-store'})
                .then(function (res) { return res.ok ? res.text() : null; })
                .then(function (text) {
                    if (current !== btn || !text) return;
                    words = text;
                    if (btn.classList.contains('speaking')) showBar(code, words, 'speaking');
                })
                .catch(function () { /* the audio says it all */ });
        }
        // why it didn't play: the map says it in words (no server, or Home Assistant's Piper couldn't be reached)
        async function failed(btn, err) {
            let why = 'Could not play it';
            try {
                const res = await fetch('/api/speak/' + encodeURIComponent(btn.dataset.speak) + '.audio', {cache: 'no-store'});
                if (!res.ok) why = (await res.text()).trim() || why;
                else if (err && err.name === 'NotAllowedError') why = 'The browser blocked sound: press again';
            } catch (e) {
                why = "Can't reach the map";
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
        // the tab left (or the page hidden): quiet, as the reading is for the one looking
        tabs.forEach(function (t) {
            t.addEventListener('click', function () { if (t.dataset.tab !== 'awos' && current) stop(); });
        });
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

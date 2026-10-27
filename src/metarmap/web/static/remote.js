// METARMap remote: the Remote page's tabs, and keeping it in step with the map, whoever changes it (another remote,
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
    const tiles = {};
    document.querySelectorAll('.r-apt').forEach(function (t) { tiles[t.dataset.pixel] = t; });

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
            const tile = tiles[led.pixel];
            if (!tile) return;
            const cat = /^(VFR|MVFR|IFR|LIFR)$/.test(led.flightCategory || '') ? led.flightCategory : 'none';
            if (tile.dataset.cat !== cat) {
                tile.dataset.cat = cat;
                tile.querySelector('.dot').className = 'dot ' + cat.toLowerCase();
            }
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

    async function poll() {
        try {
            const res = await fetch('/api/live', {cache: 'no-store'});
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const live = await res.json();
            online(true);
            followVisualizer(live.visualizer.active);
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

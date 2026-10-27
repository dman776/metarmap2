%include("header.tpl", title="Remote", page="remote", kiosk=True, leaflet=True)
% import json
<div class="remote" data-version="{{version}}">
    <header class="r-bar">
        <svg class="r-brand" width="22" height="22" viewBox="0 0 24 24" aria-label="METARMap" role="img"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" fill="none" stroke="#f5b544" stroke-width="1.8" stroke-linejoin="round"/></svg>
        <div class="r-tabs" role="tablist" aria-label="Remote">
            <button class="r-tab" type="button" role="tab" id="tab-visualizer" aria-controls="visualizer" aria-selected="true" data-tab="visualizer">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="6" cy="12" r="2.5"/><circle cx="12" cy="6" r="2.5"/><circle cx="18" cy="12" r="2.5"/><circle cx="12" cy="18" r="2.5"/></svg>
                <span>Visualizer</span>
            </button>
            <button class="r-tab" type="button" role="tab" id="tab-map" aria-controls="r-map" aria-selected="false" data-tab="map">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/></svg>
                <span>Map</span>
            </button>
            <button class="r-tab" type="button" role="tab" id="tab-locator" aria-controls="locator" aria-selected="false" data-tab="locator">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>
                <span>Locator</span>
            </button>
            <button class="r-tab" type="button" role="tab" id="tab-config" aria-controls="config" aria-selected="false" data-tab="config">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>
                <span>Config</span>
            </button>
        </div>
        <span class="host r-host" role="status" title="{{myIP}} · v{{version}}"><span>{{myIP}}</span></span>
        <button class="btn icon r-full" type="button" aria-label="Fullscreen" aria-pressed="false" hidden>
            <svg class="enter" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>
            <svg class="exit" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>
        </button>
    </header>

    <section class="r-panel r-vis" id="visualizer" role="tabpanel" aria-labelledby="tab-visualizer">
        <div class="r-vis-pick">
            <div class="vis-head">
                <button class="btn icon" type="button" aria-label="Previous visualizer" data-call="/visualizer/previous" data-then="none">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>
                </button>
                <div class="r-vis-text">
                    <div class="name" id="r-vis-name">{{active['name']}}</div>
                    <div class="desc" id="r-vis-desc">{{active['description']}}</div>
                </div>
                <button class="btn icon" type="button" aria-label="Next visualizer" data-call="/visualizer/next" data-then="none">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
                </button>
            </div>
            <div class="chip-row r-chips" role="group" aria-label="Choose a visualizer">
                % for i, v in enumerate(visualizers):
                <button class="chip" type="button" aria-pressed="{{'true' if i == active['index'] else 'false'}}" data-call="/visualizer/{{i}}" data-then="none"
                        data-vis="{{i}}" data-name="{{v['name']}}" data-desc="{{v['description']}}" data-exclusive="{{'true' if v['exclusive'] else 'false'}}">{{v['name']}}</button>
                % end
            </div>
        </div>
        <div class="r-legend" id="r-legend">
            %include("legend.tpl", legend=active['legend'])
        </div>
    </section>

    <!-- the Map page's map; remote.js loads map.js the first time the tab opens (Leaflet can't lay out a hidden map) -->
    <section class="r-panel r-map" id="r-map" role="tabpanel" aria-labelledby="tab-map" hidden>
        <div id="map" class="live-map" role="region" aria-label="Map of airport LEDs" data-script="/static/map.js?v={{assets}}"></div>
        <div id="legend-source" hidden>
            %include("legend.tpl", legend=active['legend'])
        </div>
        <script id="map-settings" type="application/json">{{!json.dumps(settings).replace('</', '<\\/')}}</script>
    </section>

    <section class="r-panel r-air" id="locator" role="tabpanel" aria-labelledby="tab-locator" hidden>
        <div class="r-air-head">
            <span class="badge warn" id="r-paused"{{!'' if active['exclusive'] else ' hidden'}}>Locate is paused by {{active['name']}}</span>
            % if len(stations) > 12:
            <label class="search r-search">
                <span class="sr-only">Search airports</span>
                <input id="station-search" type="search" placeholder="Search airports" autocomplete="off" autocapitalize="characters">
            </label>
            % end
        </div>
        <div class="r-grid{{' paused' if active['exclusive'] else ''}}">
            % for s in stations:
            % cat = s['cat'] if s['cat'] in cats else 'none'
            <button class="r-apt{{' virtual' if s['virtual'] else ''}}" type="button" data-call="/locate/{{s['pixel']}}" data-then="none"
                    data-station="{{s['code']}}" data-cat="{{cat}}" data-pixel="{{s['pixel']}}" aria-label="Locate {{s['code']}}" title="{{s['name'] or s['code']}}">
                <span class="dot {{cat.lower()}}"></span>
                <b>{{s['code']}}</b>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>
            </button>
            % end
        </div>
    </section>

    <section class="r-panel r-ctl" id="config" role="tabpanel" aria-labelledby="tab-config" hidden>
        <div class="card r-set">
            <div class="set-inline">
                <label class="lbl" for="brightness">LED brightness</label>
                <span class="big" id="brt_label">{{int(round(brightness * 100))}}%</span>
            </div>
            <input id="brightness" type="range" min="0" max="1" step="0.01" value="{{brightness}}" data-label="brt_label" data-format="pct">
            <p class="muted">Until the next sunrise, sunset, dawn or dusk, which set it again.</p>
        </div>
        % if oled_on is not None:
        <div class="card r-set">
            <div class="set-inline">
                <label class="lbl" for="oled-on">OLED display</label>
                <input id="oled-on" class="switch" type="checkbox"{{!' checked' if oled_on else ''}}>
            </div>
            <p class="muted">Back on when the map restarts.</p>
        </div>
        % end
    </section>
</div>

<script src="/static/remote.js?v={{assets}}"></script>

%include("footer.tpl", kiosk=True)

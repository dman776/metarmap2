%include("header.tpl", title="Cockpit", page="remote", kiosk=True, leaflet=True)
% import json
% from metarmap.web import icons
{{!icons.sprite()}}
<div class="remote" data-version="{{version}}">
    <header class="r-bar">
        <svg class="r-brand" width="22" height="22" viewBox="0 0 24 24" aria-label="MetarMap2" role="img"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" fill="none" stroke="#f5b544" stroke-width="1.8" stroke-linejoin="round"/></svg>
        <span class="r-brand-name">Cockpit</span>
        <div class="r-tabs" role="tablist" aria-label="Cockpit">
            <button class="r-tab" type="button" role="tab" id="tab-visualizer" aria-controls="visualizer" aria-selected="true" data-tab="visualizer">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="6" cy="12" r="2.5"/><circle cx="12" cy="6" r="2.5"/><circle cx="18" cy="12" r="2.5"/><circle cx="12" cy="18" r="2.5"/></svg>
                <span>Visualizer</span>
            </button>
            <button class="r-tab" type="button" role="tab" id="tab-map" aria-controls="r-map" aria-selected="false" data-tab="map">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/></svg>
                <span>Map</span>
            </button>
            <button class="r-tab" type="button" role="tab" id="tab-info" aria-controls="info" aria-selected="false" data-tab="info">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>
                <span>Info</span>
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
                <button class="chip{{' skipped' if v['skipped'] else ''}}" type="button" aria-pressed="{{'true' if v['id'] == active['id'] else 'false'}}" data-call="/visualizer/{{v['id']}}" data-then="none"
                        data-vis="{{i}}" data-id="{{v['id']}}" data-name="{{v['name']}}" data-desc="{{v['description']}}" data-exclusive="{{'true' if v['exclusive'] else 'false'}}">{{!icons.use(v['icon'])}}{{v['name']}}<span class="skip-badge" aria-hidden="true">skip</span></button>
                % end
            </div>
            <!-- press and hold a visualizer to leave it out of auto-rotate, or put it back (remote.js) -->
            <div class="r-toast" id="r-toast" role="status" aria-live="polite" hidden></div>
        </div>
        <div class="r-legend" id="r-legend">
            %include("legend.tpl", legend=active['legend'], filtered=active['filtered'], step=active['step'])
        </div>
        <!-- the controls, under the legend (it scrolls on its own); spaced with margins: Safari before 14.1 has no flex gap -->
        <div class="r-foot">
            <div class="r-foot-item r-rotate">
                <label class="lbl" for="auto-rotate">Auto-rotate</label>
                <input id="auto-rotate" class="switch" type="checkbox"{{!' checked' if auto_rotate else ''}}>
                <span class="r-clock" id="r-clock" role="timer" aria-label="Next visualizer" hidden>
                    <svg width="26" height="26" viewBox="0 0 36 36" aria-hidden="true"><circle class="track" cx="18" cy="18" r="15"/><circle class="left" id="r-clock-left" cx="18" cy="18" r="15" pathLength="100" stroke-dasharray="100 100"/></svg>
                    <span id="r-clock-text"></span>
                </span>
            </div>
            <div class="r-foot-item r-brt" title="Until the next sunrise, sunset, dawn or dusk, which set it again">
                <label class="lbl" for="brightness">Pixel brightness</label>
                <input id="brightness" type="range" min="0" max="1" step="0.01" value="{{brightness}}" data-label="brt_label" data-format="pct">
                <span class="r-val" id="brt_label">{{int(round(brightness * 100))}}%</span>
            </div>
            % if oled_on is not None:
            <div class="r-foot-item" title="Back on when the Chart restarts">
                <label class="lbl" for="oled-on">Micro</label>
                <input id="oled-on" class="switch" type="checkbox"{{!' checked' if oled_on else ''}}>
            </div>
            % end
        </div>
    </section>

    <!-- the Map page's map; remote.js loads map.js the first time the tab opens (Leaflet can't lay out a hidden map) -->
    <section class="r-panel r-map" id="r-map" role="tabpanel" aria-labelledby="tab-map" hidden>
        <div id="map" class="live-map" role="region" aria-label="Map of airport pixels" data-script="/static/map.js?v={{assets}}"></div>
        <div id="legend-source" hidden>
            %include("legend.tpl", legend=active['legend'], filtered=active['filtered'], step=active['step'])
        </div>
        <script id="map-settings" type="application/json">{{!json.dumps(settings).replace('</', '<\\/')}}</script>
    </section>

    <!-- Info: the airports, and what a press does (Locate, AWOS, ATIS). #locator, #awos and #atis open a mode -->
    <section class="r-panel r-air" id="info" role="tabpanel" aria-labelledby="tab-info" data-mode="locate" hidden>
        <div class="r-air-head">
            % if speech:
            <div class="r-modes" role="group" aria-label="What a press does">
                <button class="chip" type="button" data-mode="locate" aria-pressed="true">Locate</button>
                <button class="chip" type="button" data-mode="awos" aria-pressed="false">AWOS</button>
                % if atis:
                <button class="chip" type="button" data-mode="atis" aria-pressed="false">ATIS</button>
                % end
            </div>
            % end
            <span class="badge warn" id="r-paused"{{!'' if active['exclusive'] else ' hidden'}}>Locate is paused by {{active['name']}}</span>
            % if len(stations) > 12:
            <label class="search r-search">
                <span class="sr-only">Search airports</span>
                <input id="station-search" type="search" placeholder="Search airports" autocomplete="off" autocapitalize="characters">
            </label>
            % end
        </div>
        % if speech:
        <!-- what's being read: the airport, then its words as they're spoken; Stop -->
        <div class="r-speak-bar" id="r-speak-bar" role="status" aria-live="polite">
            <span class="r-speak-code" id="r-speak-code"></span>
            <span class="r-speak-text" id="r-speak-text">Press an airport to hear its weather</span>
            <button class="btn" type="button" id="r-speak-stop" hidden>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
                Stop
            </button>
        </div>
        <audio id="r-speak-audio" preload="none"></audio>
        <p class="muted r-no-atis" id="r-no-atis" hidden>No airport on this Chart has a digital ATIS. Only about 75 large US airports publish one.</p>
        % end
        <div class="r-grid{{' paused' if active['exclusive'] else ''}}">
            % for s in stations:
            % cat = s['cat'] if s['cat'] in cats else 'none'
            <button class="r-apt{{' virtual' if s['virtual'] else ''}}" type="button" data-call="/locate/{{s['pixel']}}" data-then="none"
                    data-station="{{s['code']}}" data-speak="{{s['code']}}" data-atis="{{'true' if s['code'] in with_atis else 'false'}}"
                    data-cat="{{cat}}" data-pixel="{{s['pixel']}}" aria-label="Locate {{s['code']}}" title="{{s['name'] or s['code']}}">
                <span class="dot {{cat.lower()}}"></span>
                <b>{{s['code']}}</b>
                <svg class="i-locate" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>
                <svg class="i-speak" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>
            </button>
            % end
        </div>
        % if atis:
        <!-- ATIS: the one being read, line by line (the FAA's text, then how it's said), the line being said lit -->
        <ol class="tx r-transcript" id="r-transcript" aria-label="The ATIS, line by line" hidden></ol>
        % end
    </section>
</div>

<script src="/static/remote.js?v={{assets}}"></script>

%include("footer.tpl", kiosk=True)

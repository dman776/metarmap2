%include("header.tpl", title="Map", page="map", leaflet=True)
% import json
<section class="page-head">
    <div>
        <h1>Map</h1>
        <p>Live mirror of the LEDs and the OLED screen. Click an LED for its weather.</p>
    </div>
    <div class="vis-switch">
        <button class="btn icon" type="button" aria-label="Previous visualizer" data-call="/visualizer/previous" data-then="none">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>
        </button>
        <div class="vis-name" data-active="{{active['index']}}"><span class="lbl">Visualizer</span><b>{{active['name']}}</b></div>
        <button class="btn icon" type="button" aria-label="Next visualizer" data-call="/visualizer/next" data-then="none">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
        </button>
    </div>
</section>

<div id="map" class="live-map" role="region" aria-label="Map of airport LEDs"></div>

<div id="legend-source" hidden>
    %include("legend.tpl", legend=active['legend'])
</div>

<p class="muted" style="margin: 0; font-size: 13px">LEDs are drawn at full brightness. The map itself is at {{int(round(brightness * 100))}}% right now. A white ring marks the airport on the OLED screen.</p>

<script id="map-settings" type="application/json">{{!json.dumps(settings).replace('</', '<\\/')}}</script>
<script src="/static/map.js?v={{assets}}"></script>

%include("footer.tpl")

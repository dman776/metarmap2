%include("header.tpl", title="Map", page="map", leaflet=True)
% import json
% from metarmap.web import icons
{{!icons.sprite()}}
<section class="page-head">
    <div>
        <h1>Map</h1>
        <p>Live mirror of the Chart and the Micro. Click an airport for its weather.</p>
    </div>
    <div class="vis-switch">
        <button class="btn icon" type="button" aria-label="Previous visualizer" data-call="/visualizer/previous" data-then="none">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>
        </button>
        <div class="vis-name" data-active="{{active['index']}}" data-icon="{{active['icon']}}" data-id="{{active['id']}}">
            <button class="vis-pick" type="button" aria-haspopup="true" aria-expanded="false" aria-label="Choose a visualizer"><span class="lbl">Visualizer</span><b>{{active['name']}}</b><svg class="caret" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>
        </div>
        <button class="btn icon" type="button" aria-label="Next visualizer" data-call="/visualizer/next" data-then="none">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
        </button>
    </div>
</section>

<div id="map" class="live-map" role="region" aria-label="Map of airport pixels"></div>

<!-- every visualizer, for the pick lists under the visualizer's name (map.js builds them from this) -->
<ul id="vis-choices" hidden>
    % for v in visualizers:
    <li data-id="{{v['id']}}" data-name="{{v['name']}}" data-icon="{{v['icon']}}" data-skipped="{{'true' if v['skipped'] else 'false'}}"></li>
    % end
</ul>

<div id="legend-source" hidden>
    %include("legend.tpl", legend=active['legend'], filtered=active['filtered'], step=active['step'])
</div>

<p class="muted" style="margin: 0; font-size: 13px">LEDs are drawn at full brightness. The map itself is at {{int(round(brightness * 100))}}% right now. A white ring marks the airport on the OLED screen.</p>

<script id="map-settings" type="application/json">{{!json.dumps(settings).replace('</', '<\\/')}}</script>
<script src="/static/map.js?v={{assets}}"></script>

%include("footer.tpl")

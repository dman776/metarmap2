%include("header.tpl", title="Plan a new chart", page="config")
<section class="page-head">
    <div>
        <h1>Plan a new chart</h1>
        <p>Lay the airports out on a board: where each pixel goes, the wire to cut and the power to buy. This only plans; nothing here changes the Chart.</p>
    </div>
    <a class="btn" href="/config/airports">Back to Airports</a>
</section>

%include("config_tabs.tpl", active="airports", own_page=True)

<div class="planner" id="planner" data-boards="{{boards}}">
<form class="planner-form" id="planner-form" autocomplete="off" novalidate>
    <section class="card settings">
        <h2>1. Which chart</h2>
        <div class="set">
            <div>
                <label class="t" for="pl-chart">Chart printed on the board</label>
                <div class="d">A sectional, or the US Wall Planning chart for the whole country. Starts with the sectional the Web map uses.</div>
            </div>
            <select id="pl-chart" name="chart">
                % for c in charts:
                <option value="{{c['name']}}"{{!' selected' if c['name'] == chart else ''}}>{{c['name'] + (' (whole US)' if c['kind'] == 'wall' else '')}}</option>
                % end
            </select>
        </div>
    </section>

    <section class="card settings">
        <h2>2. Which airports</h2>
        <div class="set">
            <div>
                <label class="t" for="pl-source">Airports</label>
                <div class="d">Your current airports, a list you paste, or airports picked for you from the METAR stations on the chart (fetched from aviationweather.gov; a national chart takes about ten minutes).</div>
            </div>
            <select id="pl-source" name="source">
                <option value="current" selected>My current airports</option>
                <option value="paste">Paste a list of codes</option>
                <option value="recommended">Recommended</option>
            </select>
        </div>
        <div class="sub" data-when="pl-source" data-when-value="paste" hidden>
            <div class="set">
                <div>
                    <label class="t" for="pl-codes">Airport codes</label>
                    <div class="d">Separated by spaces, commas or lines, for example KHOU KIAH KDWH.</div>
                </div>
                <textarea id="pl-codes" name="codes" rows="3" spellcheck="false" autocapitalize="characters"></textarea>
            </div>
        </div>
        <div class="sub" data-when="pl-source" data-when-value="recommended" hidden>
            <div class="set">
                <div>
                    <label class="t" for="pl-target">How many</label>
                    <div class="d">Strings are bought whole, so a number of strings fills each one with airports. The Chart takes at most 1000 pixels.</div>
                </div>
                <select id="pl-target" name="target">
                    <option value="strings" selected>A number of strings</option>
                    <option value="number">A number of airports</option>
                    <option value="max">As many as fit</option>
                </select>
            </div>
            <div class="sub" data-when="pl-target" data-when-value="strings">
                <div class="set">
                    <div>
                        <label class="t" for="pl-strings">Strings</label>
                        <div class="d" id="pl-strings-help">The airports you keep fill one string. Raise the number to add more airports.</div>
                    </div>
                    <input id="pl-strings" class="num" type="number" inputmode="numeric" min="1" step="1" value="1">
                </div>
            </div>
            <div class="sub" data-when="pl-target" data-when-value="number" hidden>
                <div class="set">
                    <label class="t" for="pl-number">Airports</label>
                    <input id="pl-number" class="num" type="number" inputmode="numeric" min="1" step="1" value="50">
                </div>
            </div>
            <div class="set">
                <div>
                    <label class="t" for="pl-coverage">Even coverage</label>
                    <div class="d">0 takes the most important airports first; 1 spreads them over the whole chart.</div>
                </div>
                <div class="range"><input id="pl-coverage" type="range" min="0" max="1" step="0.05" value="0"><span class="val mono" id="pl-coverage-val">0</span></div>
            </div>
            <div class="set">
                <div>
                    <label class="t" for="pl-fresh">Start fresh</label>
                    <div class="d">Off: your current airports start ticked below (must keep); untick any you do not need. On: none starts ticked.</div>
                </div>
                <input id="pl-fresh" class="switch" type="checkbox">
            </div>
        </div>
        <div class="set" id="pl-keep-set">
            <div>
                <span class="t">Must keep</span>
                <div class="d" id="pl-keep-note">Airports ticked here are never dropped, and the plan keeps them where they are as far as it can.</div>
                <div class="d bad" id="pl-unlocated" hidden></div>
            </div>
            <div class="keep-list" id="pl-keep" role="group" aria-label="Must keep">
                % for a in current:
                <label class="keep" data-code="{{a['code']}}" title="{{a['name']}}"><input type="checkbox" value="{{a['code']}}"{{!' data-unlocated="1"' if not a['located'] else ''}}> <span class="mono">{{a['code']}}</span></label>
                % end
            </div>
        </div>
    </section>

    <section class="card settings">
        <h2>3. Board size</h2>
        <div class="set">
            <div>
                <label class="t" for="pl-width">Width</label>
                <div class="d">The whole printed board, in inches. The chart's margins are taken off for you.</div>
            </div>
            <span class="with-unit"><input id="pl-width" class="num" type="number" inputmode="decimal" min="1" step="0.1" value="32"> <span class="muted">in</span></span>
        </div>
        <div class="set">
            <div>
                <label class="t" for="pl-height">Height</label>
                <div class="d" id="pl-height-note">{{height_note}}</div>
            </div>
            <span class="with-unit"><input id="pl-height" class="num" type="number" inputmode="decimal" min="1" step="0.1" value="{{height}}"> <span class="muted">in</span></span>
        </div>
    </section>

    <section class="card settings">
        <h2>4. Pixels and wire</h2>
        <div class="set">
            <div><label class="t" for="pl-pitch">Pitch</label><div class="d">The wire between two pixels on a string, 20 to 1000 mm.</div></div>
            <span class="with-unit"><input id="pl-pitch" class="num" type="number" inputmode="decimal" min="20" max="1000" step="1" value="80"> <span class="muted">mm</span></span>
        </div>
        <div class="set">
            <div><label class="t" for="pl-gap">Minimum spacing</label><div class="d">The closest two pixels can sit, up to 25 mm.</div></div>
            <span class="with-unit"><input id="pl-gap" class="num" type="number" inputmode="decimal" min="0" max="25" step="1" value="18"> <span class="muted">mm</span></span>
        </div>
        <div class="set">
            <div><label class="t" for="pl-move">Maximum move</label><div class="d">The furthest a pixel may sit from its airport's true place, up to 25 mm.</div></div>
            <span class="with-unit"><input id="pl-move" class="num" type="number" inputmode="decimal" min="0" max="25" step="1" value="18"> <span class="muted">mm</span></span>
        </div>
        <div class="set">
            <div><label class="t" for="pl-len">String length</label><div class="d">Pixels in one string, 10 or more. A join between strings costs no cut.</div></div>
            <span class="with-unit"><input id="pl-len" class="num" type="number" inputmode="numeric" min="10" max="1000" step="1" value="50"> <span class="muted">pixels</span></span>
        </div>
        <div class="set">
            <div><label class="t" for="pl-tol">Tolerance</label><div class="d">A gap this much longer than the pitch still fits without an extension.</div></div>
            <span class="with-unit"><input id="pl-tol" class="num" type="number" inputmode="decimal" min="0" step="1" value="5"> <span class="muted">%</span></span>
        </div>
    </section>

    <section class="card settings">
        <h2>5. Options and power</h2>
        <div class="set">
            <div><label class="t" for="pl-sizes">Suggest a nearby board size</label><div class="d">Tries widths from 90% to 115% of yours, keeping its shape, and lists the best three. Adds a little time.</div></div>
            <input id="pl-sizes" class="switch" type="checkbox" checked>
        </div>
        <div class="set">
            <div><label class="t" for="pl-skips">Allow skipped pixels</label><div class="d">{{skips_note}} The plan still tells you how many hidden pixels would remove the extensions left.</div></div>
            <input id="pl-skips" class="switch" type="checkbox" disabled>
        </div>
        <div class="set">
            <div><label class="t" for="pl-corner">Start near this corner</label><div class="d">The first pixel is the one nearest it, where the power and the Pi go.</div></div>
            <select id="pl-corner">
                <option value="" selected>Anywhere</option>
                <option value="tl">Top left</option>
                <option value="tr">Top right</option>
                <option value="bl">Bottom left</option>
                <option value="br">Bottom right</option>
            </select>
        </div>
        <div class="set">
            <div><label class="t" for="pl-bright">Brightness</label><div class="d">For the power estimate: the Chart's normal brightness, 0 to 1.</div></div>
            <input id="pl-bright" class="num" type="number" inputmode="decimal" min="0" max="1" step="0.05" value="{{brightness}}">
        </div>
        <div class="set">
            <div><label class="t" for="pl-ma5">Current per pixel, 5 V</label><div class="d">At full white. Check the strings you buy.</div></div>
            <span class="with-unit"><input id="pl-ma5" class="num" type="number" inputmode="decimal" min="1" step="1" value="60"> <span class="muted">mA</span></span>
        </div>
        <div class="set">
            <div><label class="t" for="pl-ma12">Current per pixel, 12 V</label><div class="d">At full white. Check the strings you buy.</div></div>
            <span class="with-unit"><input id="pl-ma12" class="num" type="number" inputmode="decimal" min="1" step="1" value="25"> <span class="muted">mA</span></span>
        </div>
    </section>

    <div class="planner-actions">
        <button class="btn primary" type="submit" id="pl-go">Plan the chart</button>
        <button class="btn danger" type="button" id="pl-cancel" hidden>Cancel</button>
    </div>
    <p class="d bad" id="pl-error" role="alert" hidden></p>
</form>

<section class="card pad" id="pl-progress" hidden>
    <h2 id="pl-progress-title">Planning</h2>
    <p class="update-label"><span id="pl-label" role="status">Starting</span> <span class="muted" id="pl-elapsed" aria-hidden="true"></span></p>
    <progress class="update-bar" id="pl-bar" max="1" aria-labelledby="pl-progress-title"></progress>
    <p class="muted" id="pl-note">You can leave this page and come back: the plan keeps running. A national chart's airport fetch takes about ten minutes on a Pi.</p>
</section>

<section id="pl-result" hidden>
    <div class="banner" id="pl-summary" role="status"></div>
    <div class="planner-grid">
        <div class="card map-card">
            <div class="card-head">
                <h2>Build map</h2>
                <div class="chip-row no-print">
                    <button class="chip sm" type="button" data-zoom="out" aria-label="Zoom out">&minus;</button>
                    <button class="chip sm" type="button" data-zoom="fit">Fit</button>
                    <button class="chip sm" type="button" data-zoom="in" aria-label="Zoom in">+</button>
                    <button class="chip sm" type="button" id="pl-print">Print</button>
                </div>
            </div>
            <div class="pm-scroll" id="pl-map"></div>
            <ul class="pm-legend" id="pl-legend"></ul>
        </div>
        <div class="planner-side" id="pl-lists">
            <div class="card no-print" id="pl-snippet-card">
                <div class="card-head">
                    <h2>config.json airports</h2>
                    <button class="btn sm" type="button" id="pl-copy">Copy</button>
                </div>
                <p class="muted pl-pad">These are the airports in the new pixel order, the same shape as <span class="mono">airports</span> in <span class="mono">config.json</span>. Virtual airports are not in it, so if you have any, pasting this over <span class="mono">airports</span> drops them and <span class="mono">led.count</span> may need changing. Applying them to the Chart comes in a later change.</p>
                <textarea class="snippet mono" id="pl-snippet" readonly rows="8" aria-label="config.json airports"></textarea>
            </div>
        </div>
    </div>
</section>
</div>
<script src="/static/planner.js?v={{assets}}"></script>
%include("footer.tpl")

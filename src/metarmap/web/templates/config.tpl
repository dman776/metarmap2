%include("header.tpl", title="Config", page="config")
% def switch(key, val, label, desc='', restart=False, ident=None):
%   ident = ident or key.replace('.', '-')
<div class="set">
    <div>
        <label class="t" for="{{ident}}">{{label}}
            % if restart:
            <span class="rs">Restart</span>
            % end
        </label>
        % if desc:
        <div class="d">{{desc}}</div>
        % end
    </div>
    <input id="{{ident}}" class="switch" type="checkbox" data-key="{{key}}"{{!' checked' if val else ''}}{{!' data-restart' if restart else ''}}>
</div>
% end
% def slider(key, val, label, desc='', lo=0, hi=1, step=0.01, fmt='pct', restart=False):
%   ident = key.replace('.', '-')
<div class="set">
    <div>
        <label class="t" for="{{ident}}">{{label}}
            % if restart:
            <span class="rs">Restart</span>
            % end
        </label>
        % if desc:
        <div class="d">{{desc}}</div>
        % end
    </div>
    <div class="range">
        <input id="{{ident}}" type="range" min="{{lo}}" max="{{hi}}" step="{{step}}" value="{{val}}" data-key="{{key}}" data-label="{{ident}}-val" data-format="{{fmt}}"{{!' data-restart' if restart else ''}}>
        <span class="val" id="{{ident}}-val">{{'%d%%' % round(val * 100) if fmt == 'pct' else '%g s' % val}}</span>
    </div>
</div>
% end

<section class="page-head">
    <div>
        <h1>Configuration</h1>
        <p>Changes save as you make them.</p>
    </div>
    <nav class="subnav" aria-label="Config sections">
        <a class="chip" href="/config" aria-current="page" style="border-color: var(--accent); color: var(--accent)">Settings</a>
        <a class="chip" href="/config/airports">Airports</a>
    </nav>
</section>

<section class="banner" id="restart-banner" role="status" hidden>
    <span>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f5b544" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>
        Some changes take effect after the map restarts.
    </span>
    <button class="btn primary" type="button" data-call="/restart" data-then="restart">Restart now</button>
</section>

<div class="split">
    <div class="main">
        <section class="card settings">
            <h2>Visualizer</h2>
            <div class="set">
                <div>
                    <label class="t" for="visualizer-active">Default visualizer</label>
                    <div class="d">Shown when the map starts.</div>
                </div>
                <select id="visualizer-active" data-key="visualizer.active">
                    % for i, name in enumerate(visualizers):
                    <option value="{{i}}"{{!' selected' if i == d.visualizer.active else ''}}>{{name}}</option>
                    % end
                </select>
            </div>
            % switch('lightning.animation', d.lightning.animation, 'Lightning animation', 'Flash airports that report lightning.')
            % switch('visualizer.auto_rotate.enabled', d.visualizer.auto_rotate.enabled, 'Auto-rotate visualizers', 'Cycle through the visualizers on a timer.')
            % slider('visualizer.auto_rotate.delay_seconds', d.visualizer.auto_rotate.delay_seconds, 'Auto-rotate delay', 'Time on each visualizer.', lo=10, hi=600, step=10, fmt='sec')
        </section>

        <section class="card settings">
            <h2>Display screen</h2>
            % switch('display_screen.enabled', d.display_screen.enabled, 'Enabled', 'Show airport details on the OLED screen.')
            % switch('display_screen.locate_active', d.display_screen.locate_active, 'Highlight active airport', 'Pulse the LED of the airport on screen.')
            % slider('display_screen.delay', d.display_screen.delay, 'Delay per airport', lo=0, hi=30, step=1, fmt='sec')
        </section>

        % m = map_settings
        <section class="card settings">
            <h2>Map page</h2>
            <div class="set">
                <div><label class="t" for="map-bg">Default background</label><div class="d">Viewers can still switch on the Map page.</div></div>
                <select id="map-bg" data-key="geo.map.background">
                    % for value, label in (('sectional', 'FAA chart'), ('satellite', 'Satellite'), ('radar', 'Radar')):
                    <option value="{{value}}"{{!' selected' if m['background'] == value else ''}}>{{label}}</option>
                    % end
                </select>
            </div>
            <div class="set">
                <div><label class="t" for="map-type">Chart type</label><div class="d">Charts update with each FAA edition.</div></div>
                <select id="map-type" data-key="geo.map.chart_type">
                    % for value, (service, label, min_zoom) in chart_types.items():
                    <option value="{{value}}"{{!' selected' if m['chart_type'] == value else ''}}>{{label}}</option>
                    % end
                </select>
            </div>
            <div class="set">
                <div><label class="t" for="map-chart">Sectional chart</label><div class="d">The chart printed on your map.</div></div>
                <select id="map-chart" data-key="geo.map.chart">
                    % for c in sectionals:
                    <option{{!' selected' if m['chart'] == c['name'] else ''}}>{{c['name']}}</option>
                    % end
                </select>
            </div>
            <div class="set" style="align-items: flex-start">
                <div><div class="t" id="map-view">Starting view</div><div class="d">Where the Map page opens.</div></div>
                <div role="radiogroup" aria-labelledby="map-view" class="radios">
                    % for value, label in (('airports', 'Fit to my airports'), ('chart', 'Whole sectional chart'), ('custom', 'Custom center and zoom')):
                    <label><input type="radio" name="map-view" value="{{value}}" data-key="geo.map.view"{{!' checked' if m['view'] == value else ''}}>{{label}}</label>
                    % end
                    <div class="coords">
                        <label>Latitude<input type="text" inputmode="decimal" value="{{m['center'][0]}}" data-center="0"></label>
                        <label>Longitude<input type="text" inputmode="decimal" value="{{m['center'][1]}}" data-center="1"></label>
                        <label>Zoom<input type="text" inputmode="numeric" value="{{m['zoom']}}" data-key="geo.map.zoom"></label>
                    </div>
                </div>
            </div>
        </section>
    </div>

    <div class="side">
        <section class="card settings" id="access">
            <h2>Access</h2>
            <form class="set access" data-form="/config/login" data-then="login" autocomplete="off">
                <div>
                    <div class="t">Web UI login</div>
                    <div class="d">For the Config pages.{{!' The Pi&#39;s <b>%s</b> login gets the same password.' % linux_user if linux_user else ''}}</div>
                </div>
                <label>User name<input type="text" name="user" value="{{d.web_server.user}}" autocapitalize="none" spellcheck="false" required></label>
                <label>New password<input type="password" name="password" autocomplete="new-password" placeholder="Unchanged"></label>
                <label>Confirm password<input type="password" name="confirm" autocomplete="new-password"></label>
                <button class="btn primary" type="submit">Save login</button>
            </form>
            <form class="set access" data-form="/config/wifi" data-then="wifi" autocomplete="off">
                <div>
                    <div class="t">Wi-Fi</div>
                    % if wifi:
                    <div class="d">Now on <b>{{wifi}}</b>. If the Pi can't join the new network, it goes back to this one.</div>
                    % else:
                    <div class="d">If the Pi can't join the new network, it goes back to the one it's on now.</div>
                    % end
                </div>
                <label>Network name<input type="text" name="ssid" maxlength="32" autocapitalize="none" spellcheck="false" required></label>
                <label>Password<input type="password" name="password" autocomplete="new-password" placeholder="Empty for an open network"></label>
                <button class="btn" type="submit" data-current="{{wifi or ''}}">Switch network</button>
            </form>
        </section>

        <section class="card settings">
            <h2>LED pixels</h2>
            % switch('led.inittest', d.led.inittest, 'Test pattern on startup', restart=True)
            % switch('led.dim_on_refresh', d.led.dim_on_refresh, 'Dim while updating', 'The LEDs dim for a moment while new METARs download.')
            % slider('led.brightness.normal', d.led.brightness.normal, 'Daytime brightness', 'Sunrise to sunset.', restart=True)
            % slider('led.brightness.dimmed', d.led.brightness.dimmed, 'Dawn / dusk brightness', 'Dawn to sunrise, sunset to dusk.', restart=True)
            % slider('led.brightness.off', d.led.brightness.off, 'Night brightness', 'Dusk to dawn.', restart=True)
            <p class="muted" style="margin: 0; padding: 0 24px 18px; font-size: 13px">Brightness levels load at midnight or when the map restarts.</p>
        </section>
    </div>
</div>

%include("footer.tpl")

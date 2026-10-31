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
</section>

<section class="banner" id="restart-banner" role="status" hidden>
    <span>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f5b544" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>
        Some changes take effect after the map restarts.
    </span>
    <button class="btn primary" type="button" data-call="/restart" data-then="restart">Restart now</button>
</section>

%include("config_tabs.tpl", active="physical")

<div class="tab-panel" id="panel-physical" data-panel="physical">
    <section class="card settings">
        <h2>LED pixels</h2>
        <div class="set">
            <div>
                <label class="t" for="led-pin">Data pin <span class="rs">Restart</span></label>
                <div class="d">The Pi GPIO pin wired to the strip's data line.</div>
            </div>
            <select id="led-pin" data-key="led.pin" data-restart>
                % for pin in led_pins:
                <option value="{{pin}}"{{!' selected' if pin == d.led.pin else ''}}>GPIO {{pin}}</option>
                % end
                % if d.led.pin not in led_pins:
                <option value="{{d.led.pin}}" selected disabled>GPIO {{d.led.pin}} (not supported)</option>
                % end
            </select>
        </div>
        <div class="set">
            <div>
                <label class="t" for="led-order">Color order <span class="rs">Restart</span></label>
                <div class="d">Change it if red and green are swapped on the LEDs.</div>
            </div>
            <select id="led-order" data-key="led.order" data-restart>
                % for order in led_orders:
                <option value="{{order}}"{{!' selected' if order == d.led.order else ''}}>{{order}}</option>
                % end
                % if d.led.order not in led_orders:
                <option value="{{d.led.order}}" selected disabled>{{d.led.order}}</option>
                % end
            </select>
        </div>
        % switch('led.inittest', d.led.inittest, 'Test pattern on startup', 'A rainbow along the strip when the map starts. Turning it on runs it once now.')
        % switch('led.dim_on_refresh', d.led.dim_on_refresh, 'Dim while updating', 'The LEDs fade down for a moment while new METARs download.')
        % slider('led.brightness.normal', d.led.brightness.normal, 'Daytime brightness', 'Sunrise to sunset.')
        % slider('led.brightness.dimmed', d.led.brightness.dimmed, 'Dawn / dusk brightness', 'Dawn to sunrise, sunset to dusk.')
        % slider('led.brightness.off', d.led.brightness.off, 'Night brightness', 'Dusk to dawn.')
        <p class="muted" style="margin: 0; padding: 0 24px 18px; font-size: 13px">The level in use now changes right away; the others take over at their time of day.</p>
    </section>

    <section class="card settings">
        <h2>OLED screen</h2>
        % switch('display_screen.enabled', d.display_screen.enabled, 'Enabled', 'Show airport details on the OLED screen.')
        % switch('display_screen.locate_active', d.display_screen.locate_active, 'Highlight active airport', 'Pulse the LED of the airport on screen.')
        % slider('display_screen.delay', d.display_screen.delay, 'Delay per airport', lo=0, hi=30, step=1, fmt='sec')
    </section>
</div>

<div class="tab-panel" id="panel-visualizers" data-panel="visualizers" hidden>
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
        % switch('lightning.animation', d.lightning.animation, 'Lightning animation', 'Two quick yellow flashes on airports with lightning or a thunderstorm, in every weather visualizer.')
        % switch('visualizer.auto_rotate.enabled', d.visualizer.auto_rotate.enabled, 'Auto-rotate visualizers', 'Cycle through the visualizers on a timer.')
        % slider('visualizer.auto_rotate.delay_seconds', d.visualizer.auto_rotate.delay_seconds, 'Auto-rotate delay', 'Time on each visualizer.', lo=10, hi=600, step=10, fmt='sec')
        <div class="set">
            <div>
                <span class="t" id="rotate-label">Visualizers in auto-rotate</span>
                <div class="d">Untick the ones to leave out.
                    % left_out = [v['name'] for v in rotation if v['exclusive']]
                    {{' and '.join(filter(None, [', '.join(left_out[:-1]), left_out[-1]])) if left_out else ''}} {{'is' if len(left_out) == 1 else 'are'}} always left out: {{'it uses' if len(left_out) == 1 else 'they use'}} the whole strip. The buttons still show every visualizer.</div>
            </div>
            <div class="rotate-list" role="group" aria-labelledby="rotate-label">
                % for v in rotation:
                %   if not v['exclusive']:
                <label><input type="checkbox" data-rotate="{{v['name']}}"{{!' checked' if v['shown'] else ''}}> {{v['name']}}</label>
                %   end
                % end
            </div>
        </div>
    </section>
</div>

<div class="tab-panel" id="panel-map" data-panel="map" hidden>
    % m = map_settings
    <section class="card settings">
        <h2>Virtual map</h2>
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

    <section class="card settings">
        <h2>Live traffic</h2>
        <p class="muted" style="margin: 0; padding: 0 24px 6px; font-size: 13px">Aircraft around your airports from <a href="https://adsb.fi/" target="_blank" rel="noopener">adsb.fi</a>, shown when a viewer ticks Live traffic on the Map page. The map only asks adsb.fi while a page shows it.</p>
        % slider('geo.map.traffic_seconds', d.geo.map.traffic_seconds, 'Update every', 'How often the map asks adsb.fi. %d seconds at least: adsb.fi allows one request a second.' % traffic_seconds[0], lo=traffic_seconds[0], hi=traffic_seconds[1], step=1, fmt='sec')
        % switch('geo.map.traffic_ground', d.geo.map.traffic_ground, 'Ground traffic', 'Also show aircraft on the ground (parked and taxiing).')
    </section>
</div>

<div class="tab-panel" id="panel-system" data-panel="system" hidden>
    % release = get('release')
    % if release:
    <section class="card settings" id="updates">
        <h2>Software</h2>
        <div class="set">
            <div>
                <span class="t">Running v{{version}}</span>
                <div class="d">
                    % if release['error']:
                    Couldn't check GitHub: {{release['error']}}
                    % elif release['checked'] is None:
                    Not checked for updates yet.
                    % elif release['available'] and release['channel'] == 'latest':
                    A newer commit is on GitHub ({{release['available']}}).
                    % elif release['available'] and release['channel'] == 'branch':
                    A newer commit is on {{release['branch']}} ({{release['available']}}).
                    % elif release['channel'] == 'branch' and release['branch'] not in release['branches']:
                    % if release['branch']:
                    There's no branch {{release['branch']}} on GitHub.
                    % else:
                    Pick a branch to update from.
                    % end
                    % elif release['available']:
                    {{release['available']}} is available.
                    % elif not release['releases'] and release['channel'] == 'releases':
                    There are no releases on GitHub yet.
                    % else:
                    Up to date.
                    % end
                    % build = release['build']
                    % if build:
                    % if build['pill']:
                    {{build['pill']}}.
                    % end
                    Commit
                    % if build['url']:
                    <a class="mono" href="{{build['url']}}" target="_blank" rel="noopener">{{build['commit']}}</a>.
                    % else:
                    <span class="mono">{{build['commit']}}</span>.
                    % end
                    % end
                </div>
            </div>
            <button class="btn" type="button" data-call="/update/check">Check now</button>
        </div>
        <div class="set">
            <div>
                <label class="t" for="update-channel">Update to</label>
                <div class="d">Releases: the newest release. Latest commit: the newest code on GitHub, released or not, for testing.{{' Branch: the newest commit of a branch on GitHub (dev_mode).' if release['dev_mode'] else ''}}</div>
            </div>
            <select id="update-channel" data-key="update.channel">
                % channels = (('releases', 'Releases'), ('latest', 'Latest commit')) + ((('branch', 'Branch'),) if release['dev_mode'] else ())
                % for value, label in channels:
                <option value="{{value}}"{{!' selected' if release['channel'] == value else ''}}>{{label}}</option>
                % end
            </select>
        </div>
        % if release['dev_mode']:
        % branches = release['branches'] + ([release['branch']] if release['branch'] and release['branch'] not in release['branches'] else [])
        <div class="set" id="update-branch-row"{{!'' if release['channel'] == 'branch' else ' hidden'}}>
            <div>
                <label class="t" for="update-branch">Branch</label>
                <div class="d">Branches on GitHub. Push a new one, then Check now to see it here.</div>
            </div>
            <select id="update-branch" data-key="update.branch">
                % if not release['branch']:
                <option value="" selected disabled>Pick a branch</option>
                % end
                % for b in branches:
                <option value="{{b}}"{{!' selected' if b == release['branch'] else ''}}>{{b}}{{'' if b in release['branches'] else ' (not on GitHub)'}}</option>
                % end
            </select>
        </div>
        % end
        % if release['releases']:
        <div class="set">
            <div>
                <label class="t" for="release-pick">Install a release</label>
                <div class="d">Any release, older ones too. Your settings are kept.</div>
            </div>
            <div class="release-pick">
                <select id="release-pick">
                    % for r in release['releases']:
                    <option value="{{r['tag']}}"{{!' data-older="true"' if r['older'] else ''}}{{!' selected' if r['running'] else ''}}>{{r['tag']}}{{' (running)' if r['running'] else ''}}</option>
                    % end
                </select>
                <button class="btn" type="button" data-install-release>Install</button>
            </div>
        </div>
        % end
    </section>
    % end

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
</div>

%include("footer.tpl")

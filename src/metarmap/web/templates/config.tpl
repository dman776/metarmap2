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
        <span class="val" id="{{ident}}-val">{{'%d%%' % round(val * 100) if fmt == 'pct' else ('%g×' % val if fmt == 'x' else '%g s' % val)}}</span>
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
        % switch('led.inittest', d.led.inittest, 'Startup sequence', 'Play a sequence when the map starts, and when quiet hours end. When they begin, the same sequence takes the map dark. Turning it on plays it once now.')
        <div class="sub" data-when="led-inittest"{{!'' if d.led.inittest else ' hidden'}}>
        <div class="set">
            <div>
                <label class="t" for="led-init-sequence">Sequence</label>
                <div class="d">Comet runs a rainbow along the strip. The others fade the map in to the visualizer, from where each airport is. Changing it plays it once now.</div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center">
                <select id="led-init-sequence" data-key="led.init_sequence">
                    % for value, name in init_sequences.items():
                    <option value="{{value}}"{{!' selected' if value == d.led.init_sequence else ''}}>{{name}}</option>
                    % end
                </select>
                <button class="btn" type="button" data-call="/led/init_sequence/play" data-then="none">Play now</button>
            </div>
        </div>
        <div class="sub" data-when="led-init-sequence" data-when-value="sweep"{{!'' if d.led.init_sequence == 'sweep' else ' hidden'}}>
        <div class="set">
            <div>
                <label class="t" for="led-init-sweep-from">Sweep direction</label>
                <div class="d">Where Sweep starts on the map.</div>
            </div>
            <select id="led-init-sweep-from" data-key="led.init_sweep_from">
                % for side, name in sweep_sides.items():
                <option value="{{side}}"{{!' selected' if side == d.led.init_sweep_from else ''}}>{{name}}</option>
                % end
            </select>
        </div>
        </div>
        </div>
        % switch('led.dim_on_refresh', d.led.dim_on_refresh, 'Dim while updating', 'The LEDs fade down for a moment while new METARs download.')
        <div class="set subhead">
            <div>
                <div class="t">Brightness</div>
                <div class="d">The level in use now changes right away; the others take over at their time of day.</div>
            </div>
        </div>
        <div class="sub">
        % slider('led.brightness.normal', d.led.brightness.normal, 'Daytime', 'Sunrise to sunset.')
        % slider('led.brightness.dimmed', d.led.brightness.dimmed, 'Dawn / dusk', 'Dawn to sunrise, sunset to dusk.')
        % slider('led.brightness.off', d.led.brightness.off, 'Night', 'Dusk to dawn.')
        </div>
        % switch('led.quiet_hours.enabled', d.led.quiet_hours.enabled, 'Quiet hours', 'Force physical LED brightness to 0% between two times, regardless of sunrise or sunset. The OLED screen is blank then too.')
        <div class="sub" data-when="led-quiet_hours-enabled"{{!'' if d.led.quiet_hours.enabled else ' hidden'}}>
        <div class="set">
            <div><label class="t" for="quiet-hours-start">Start quiet hours</label><div class="d">Local Raspberry Pi time.</div></div>
            <input id="quiet-hours-start" type="time" value="{{d.led.quiet_hours.start}}" data-key="led.quiet_hours.start" step="60">
        </div>
        <div class="set">
            <div><label class="t" for="quiet-hours-end">End quiet hours</label><div class="d">Local Raspberry Pi time. Returns to the scheduled brightness. The interval can cross midnight.</div></div>
            <input id="quiet-hours-end" type="time" value="{{d.led.quiet_hours.end}}" data-key="led.quiet_hours.end" step="60">
        </div>
        </div>
    </section>

    <section class="card settings">
        <h2>OLED screen</h2>
        % switch('display_screen.enabled', d.display_screen.enabled, 'Enabled', 'Show airport details on the OLED screen.')
        <div class="sub" data-when="display_screen-enabled"{{!'' if d.display_screen.enabled else ' hidden'}}>
        % switch('display_screen.locate_active', d.display_screen.locate_active, 'Highlight active airport', 'Pulse the LED of the airport on screen.')
        % slider('display_screen.delay', d.display_screen.delay, 'Delay per airport', lo=0, hi=30, step=1, fmt='sec')
        </div>
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
                % for v in visualizers:
                <option value="{{v['id']}}"{{!' selected' if v['id'] == d.visualizer.active else ''}}>{{v['name']}}</option>
                % end
            </select>
        </div>
        % switch('visualizer.missing_data_blink', d.visualizer.missing_data_blink, 'Missing data blink', 'Slow red blink on an airport whose report lacks what the visualizer shows, such as no flight category, visibility or sky condition. Off leaves its LED dark.')
        % switch('visualizer.estimated_category_breathing', d.visualizer.estimated_category_breathing, 'Estimated flight category breathing', 'Estimated flight categories breathe slowly. Off shows them in a steady color, like a reported one (the OLED still shows VFR*).')
        % switch('visualizer.legend_in_use_only', d.visualizer.legend_in_use_only, 'Only show legend items in use', 'The legends on Home, Map and Remote list only what the LEDs are showing now, e.g. just VFR and MVFR. Off lists everything the visualizer can show.')
        % switch('lightning.animation', d.lightning.animation, 'Lightning animation', 'Two quick flashes on airports with lightning or a thunderstorm, in every weather visualizer.')
        <div class="sub" data-when="lightning-animation"{{!'' if d.lightning.animation else ' hidden'}}>
        <div class="set">
            <div>
                <label class="t" for="lightning-color">Lightning color</label>
                <div class="d">The color of the flashes, on the LEDs and the Map page.</div>
            </div>
            <select id="lightning-color" data-key="lightning.color">
                % for color in lightning_colors:
                <option value="{{color}}"{{!' selected' if color == d.lightning.color else ''}}>{{color.title()}}</option>
                % end
                % if d.lightning.color not in lightning_colors:
                <option value="{{d.lightning.color}}" selected disabled>{{d.lightning.color}}</option>
                % end
            </select>
        </div>
        </div>
        <div class="set">
            <div>
                <label class="t" for="tfr-nearby">TFR nearby distance</label>
                <div class="d">The TFR visualizer also shows a TFR this close to an airport, dimmed.</div>
            </div>
            <select id="tfr-nearby" data-key="tfr.nearby_nm">
                % choices = [(0, 'Inside only'), (5, '5 NM'), (10, '10 NM'), (15, '15 NM'), (20, '20 NM'), (30, '30 NM'), (50, '50 NM')]
                % for value, label in choices:
                <option value="{{value}}"{{!' selected' if value == d.tfr.nearby_nm else ''}}>{{label}}</option>
                % end
                % if d.tfr.nearby_nm not in [c[0] for c in choices]:
                <option value="{{d.tfr.nearby_nm}}" selected>{{'%g NM' % d.tfr.nearby_nm}}</option>
                % end
            </select>
        </div>
        % switch('visualizer.auto_rotate.enabled', d.visualizer.auto_rotate.enabled, 'Auto-rotate visualizers', 'Cycle through the visualizers on a timer. Picking one by hand shows it for the whole delay before the next change.')
        <div class="sub" data-when="visualizer-auto_rotate-enabled"{{!'' if d.visualizer.auto_rotate.enabled else ' hidden'}}>
        % slider('visualizer.auto_rotate.delay_seconds', d.visualizer.auto_rotate.delay_seconds, 'Auto-rotate delay', 'Time on each visualizer.', lo=10, hi=600, step=10, fmt='sec')
        % switch('visualizer.auto_rotate.skip_dark', d.visualizer.auto_rotate.skip_dark, 'Skip visualizers with nothing to show', 'Leave out a visualizer while every LED would be off with it, e.g. Precipitation on a dry day. A red "METAR not available" blink counts as something to show.')
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
                <label><input type="checkbox" data-rotate="{{v['id']}}"{{!' checked' if v['shown'] else ''}}> {{v['name']}}</label>
                %   end
                % end
            </div>
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
        <div class="sub" data-when="update-channel" data-when-value="branch" id="update-branch-row"{{!'' if release['channel'] == 'branch' else ' hidden'}}>
        <div class="set">
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

    <section class="card settings" id="speech">
        <h2>Spoken weather</h2>
        <p class="muted" style="margin: 0; padding: 0 24px 6px; font-size: 13px">Airports' METARs read aloud, as an AWOS reads them: the Remote page's Info tab, and <code>/api/speak/&lt;code&gt;.audio</code>. A speech server on another computer reads them; the map keeps each one until the next METAR.</p>
        % s = d.speech
        % switch('speech.enabled', s.enabled, 'Enable speech', 'Read METARs aloud: AWOS buttons on the METARs page and an AWOS mode on the Remote page\'s Info tab.')
        <div class="sub" data-when="speech-enabled"{{!'' if s.enabled else ' hidden'}}>
        <div class="set">
            <div><label class="t" for="speech-engine">Speech server</label><div class="d">Piper in Home Assistant, or a Kokoro server (Kokoro-FastAPI).</div></div>
            <select id="speech-engine" data-key="speech.engine">
                <option value="wyoming"{{!' selected' if s.engine == 'wyoming' else ''}}>Home Assistant (Piper)</option>
                <option value="kokoro"{{!' selected' if s.engine == 'kokoro' else ''}}>Kokoro</option>
            </select>
        </div>

        <div class="sub" data-when="speech-engine" data-when-value="wyoming"{{!'' if s.engine == 'wyoming' else ' hidden'}}>
        <div class="set">
            <div><label class="t" for="speech-host">Home Assistant</label><div class="d">Its address, e.g. 192.168.0.14. It needs the <b>Piper</b> add-on, with its port set to 10200 in the add-on's <b>Configuration &gt; Network</b>. Empty: no spoken weather.</div></div>
            <input id="speech-host" type="text" value="{{s.wyoming_host}}" data-key="speech.wyoming_host" data-empty="-" placeholder="Not set" autocapitalize="none" spellcheck="false">
        </div>
        <div class="set">
            <div><label class="t" for="speech-port">Port</label><div class="d">The Piper add-on's: 10200 unless you changed it.</div></div>
            <input id="speech-port" type="text" inputmode="numeric" value="{{s.wyoming_port}}" data-key="speech.wyoming_port" style="width: 110px">
        </div>
        <div class="set">
            <div><label class="t" for="speech-voice">Voice</label><div class="d">A Piper voice. Empty: the add-on's own. Home Assistant downloads a new one the first time, so its first report takes longer.</div></div>
            <input id="speech-voice" type="text" list="speech-voices" value="{{s.wyoming_voice}}" data-key="speech.wyoming_voice" data-empty="-" placeholder="The add-on's own" autocapitalize="none" spellcheck="false">
            <datalist id="speech-voices">
                % for voice in speech_voices:
                <option value="{{voice}}"></option>
                % end
            </datalist>
        </div>
        </div>

        <div class="sub" data-when="speech-engine" data-when-value="kokoro"{{!'' if s.engine == 'kokoro' else ' hidden'}}>
        <div class="set">
            <div><label class="t" for="speech-kokoro-url">Kokoro server</label><div class="d">Its address and port, e.g. http://192.168.0.164:8880. Empty: no spoken weather.</div></div>
            <input id="speech-kokoro-url" type="text" value="{{s.kokoro_url}}" data-key="speech.kokoro_url" data-empty="-" placeholder="Not set" autocapitalize="none" spellcheck="false">
        </div>
        <div class="set">
            <div><label class="t" for="speech-kokoro-voice">Voice</label><div class="d">A Kokoro voice: af_ and am_ are American (female, male), bf_ and bm_ British.</div></div>
            <input id="speech-kokoro-voice" type="text" list="kokoro-voices" value="{{s.kokoro_voice}}" data-key="speech.kokoro_voice" autocapitalize="none" spellcheck="false">
            <datalist id="kokoro-voices">
                % for voice in kokoro_voices:
                <option value="{{voice}}"></option>
                % end
            </datalist>
        </div>
        % slider('speech.kokoro_speed', s.kokoro_speed, 'Speed', 'How fast it reads: 1 is normal.', lo=0.5, hi=2, step=0.05, fmt='x')
        </div>

        <div class="set">
            <div><div class="t">Pronunciation</div><div class="d">Airport names, local names, fixes and the FAA's odd spellings said your way, in the AWOS and the ATIS{{!' (%d set)' % len(s.tunings) if s.tunings else ''}}.</div></div>
            <a class="btn" href="/config/pronunciation">Pronunciation</a>
        </div>

        % switch('speech.atis', s.atis, 'Spoken ATIS', 'The real ATIS too, for airports that publish a digital one (about 75 large US airports), from atis.info, an unofficial service. Only asked when you play one.')

        % if first_airport:
        <div class="set">
            <div><div class="t">Test</div><div class="d" id="speech-test-result">Plays {{first_airport}}'s weather here.</div></div>
            <button class="btn" type="button" id="speech-test" data-code="{{first_airport}}">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>
                Play
            </button>
        </div>
        % end
        </div>
    </section>

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

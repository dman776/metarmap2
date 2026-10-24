%include("header.tpl", title="Config", page="config")
% d = config.data
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
    <button class="btn primary" type="button" data-call="/restart" data-then="none">Restart now</button>
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
                    % for i, v in enumerate(config.renderer.visualizers):
                    <option value="{{i}}"{{!' selected' if i == d.visualizer.active else ''}}>{{v.name}}</option>
                    % end
                </select>
            </div>
            % switch('lightning.animation', d.lightning.animation, 'Lightning animation', 'Flash airports that report lightning.')
            % switch('visualizer.auto_rotate.enabled', d.visualizer.auto_rotate.enabled, 'Auto-rotate visualizers', 'Cycle through the visualizers on a timer.', restart=True)
            % slider('visualizer.auto_rotate.delay_seconds', d.visualizer.auto_rotate.delay_seconds, 'Auto-rotate delay', 'Time on each visualizer.', lo=10, hi=600, step=10, fmt='sec', restart=True)
        </section>

        <section class="card settings">
            <h2>Display screen</h2>
            % switch('display_screen.enabled', d.display_screen.enabled, 'Enabled', 'Show airport details on the OLED screen.', restart=True)
            % switch('display_screen.locate_active', d.display_screen.locate_active, 'Highlight active airport', 'Pulse the LED of the airport on screen.')
            % slider('display_screen.delay', d.display_screen.delay, 'Delay per airport', lo=0, hi=30, step=1, fmt='sec')
        </section>
    </div>

    <div class="side">
        <section class="card settings">
            <h2>LED pixels</h2>
            % switch('led.inittest', d.led.inittest, 'Test pattern on startup', restart=True)
            % slider('led.brightness.normal', d.led.brightness.normal, 'Daytime brightness', 'Sunrise to sunset.', restart=True)
            % slider('led.brightness.dimmed', d.led.brightness.dimmed, 'Dawn / dusk brightness', 'Dawn to sunrise, sunset to dusk.', restart=True)
            % slider('led.brightness.off', d.led.brightness.off, 'Night brightness', 'Dusk to dawn.', restart=True)
            <p class="muted" style="margin: 0; padding: 0 24px 18px; font-size: 13px">Brightness levels load at midnight or when the map restarts.</p>
        </section>
    </div>
</div>

%include("footer.tpl")

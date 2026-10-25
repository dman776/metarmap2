%include("header.tpl", title="Airports", page="config")
<section class="page-head">
    <div>
        <h1>Airports</h1>
        <p>{{count}} LEDs, one airport each, in the order they're wired. Changes save right away.</p>
    </div>
    <nav class="subnav" aria-label="Config sections">
        <a class="chip" href="/config">Settings</a>
        <a class="chip" href="/config/airports" aria-current="page" style="border-color: var(--accent); color: var(--accent)">Airports</a>
    </nav>
</section>

<section class="banner" id="restart-banner" role="status"{{!'' if count != strip_leds else ' hidden'}}>
    <span>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f5b544" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>
        The strip is running {{strip_leds}} LEDs; the new number takes effect after the map restarts.
    </span>
    <button class="btn primary" type="button" data-call="/restart" data-then="restart">Restart now</button>
</section>

<section class="card settings">
    <div class="set" style="border-top: 0">
        <div>
            <label class="t" for="led-count">Number of LEDs</label>
            <div class="d">New LEDs are added at the end with no airport. Lowering it removes the airports on the last LEDs.</div>
        </div>
        <input id="led-count" class="led-count" type="number" inputmode="numeric" min="1" max="{{max_leds}}" value="{{count}}" data-led-count="{{count}}">
    </div>
</section>

<section class="card">
    <div class="ap-row trow head" style="border-top: 0"><span>LED</span><span>ICAO</span><span class="ap-name">Name</span><span>OLED</span><span class="ap-move">Move</span></div>
    % for led in leds:
    % n = led['pixel'] + 1
    <div class="ap-row{{'' if led['on_strip'] else ' off-strip'}}" data-row="{{led['pixel']}}" data-code="{{led['code']}}">
        <span class="mono muted">{{n}}{{!'' if led['on_strip'] else '<span class="tag">not on the strip</span>'}}</span>
        <input class="code" type="text" value="{{led['code']}}" maxlength="4" spellcheck="false" placeholder="—" aria-label="Airport for LED {{n}}" data-led="{{led['pixel']}}" data-field="code">
        <input class="ap-name" type="text" value="{{led['name']}}" maxlength="40" placeholder="Name" aria-label="Name for LED {{n}}" data-led="{{led['pixel']}}" data-field="name">
        <input class="switch" type="checkbox" aria-label="Show LED {{n}} on the OLED display" data-led="{{led['pixel']}}" data-field="display"{{!' checked' if led['display'] else ''}}{{!'' if led['code'] else ' disabled'}}>
        <span class="ap-move">
            <button class="btn icon sm" type="button" aria-label="Move LED {{n}} up" data-call="/config/airports/move/{{led['pixel']}}/{{led['pixel'] - 1}}"{{!' disabled' if led['pixel'] == 0 else ''}}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m6 15 6-6 6 6"/></svg>
            </button>
            <button class="btn icon sm" type="button" aria-label="Move LED {{n}} down" data-call="/config/airports/move/{{led['pixel']}}/{{led['pixel'] + 1}}"{{!' disabled' if led['pixel'] == len(leds) - 1 else ''}}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
            </button>
        </span>
    </div>
    % end
</section>

%include("footer.tpl")

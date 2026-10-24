%include("header.tpl", title="Airports", page="config")
<section class="page-head">
    <div>
        <h1>Airports</h1>
        <p>{{len(stations)}} airports, one per LED. Edit an ICAO code to move a station; changes save right away.</p>
    </div>
    <nav class="subnav" aria-label="Config sections">
        <a class="chip" href="/config">Settings</a>
        <a class="chip" href="/config/airports" aria-current="page" style="border-color: var(--accent); color: var(--accent)">Airports</a>
    </nav>
</section>

<section class="card">
    <div class="ap-row trow head" style="border-top: 0"><span>LED</span><span>ICAO</span><span class="ap-name">Name</span><span>OLED</span></div>
    % for s in stations:
    <div class="ap-row">
        <span class="mono muted">{{s['pixel'] + 1}}</span>
        <input type="text" value="{{s['code']}}" maxlength="4" spellcheck="false" aria-label="Airport for LED {{s['pixel'] + 1}}" data-airport="{{s['code']}}">
        <span class="ap-name muted">{{s['name']}}</span>
        <input class="switch" type="checkbox" aria-label="Show {{s['code']}} on the OLED display" data-airport="{{s['code']}}"{{!' checked' if s['display'] else ''}}>
    </div>
    % end
</section>

%include("footer.tpl")

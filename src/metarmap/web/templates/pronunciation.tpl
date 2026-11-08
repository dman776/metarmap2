%include("header.tpl", title="Pronunciation", page="config")
<section class="page-head">
    <div>
        <h1>Configuration</h1>
        <p>Pronunciation for the spoken ATIS and AWOS. Save keeps the list.</p>
    </div>
</section>

%include("config_tabs.tpl", active="system", own_page=True)

<p class="tab-intro"><a href="/config#system">Spoken weather</a> › Pronunciation. The map writes out the FAA's contractions itself ("DEPG RY 15L" is "departing runway one five left"). Here you tell it how to say the rest: a fix or a local name ("MNSTR" as "monster"), a typo in the FAA's text ("GRO UND" as "ground"), or a word you'd like said another way ("RNAV" as "are nav"). Each is matched as whole words, in any case, in every airport's ATIS and AWOS or in one airport's (its name too), before the map's own rules, and is said just as you write it.</p>

% if not atis_on:
<section class="banner" role="status">
    <span>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f5b544" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>
        Spoken ATIS is off (or spoken weather has no server). The list is kept; turn it on in Spoken weather to hear it.
    </span>
    <a class="btn" href="/config#system">Spoken weather</a>
</section>
% end

<section class="card" id="tunings" data-codes="{{' '.join(codes)}}">
    <div class="card-head">
        <h2>Said another way</h2>
        <span class="tn-actions">
            <button class="btn" type="button" id="tn-add">Add</button>
            <button class="btn primary" type="button" id="tn-save">Save</button>
        </span>
    </div>
    <div class="tn-row trow head"><span>The FAA writes</span><span>Say it as</span><span>Airport</span><span></span><span></span></div>
    <div id="tn-rows">
        % for t in tunings:
        <div class="tn-row trow">
            <input type="text" class="tn-text" value="{{t.text}}" aria-label="The FAA writes" autocapitalize="characters" spellcheck="false" maxlength="40">
            <input type="text" class="tn-say" value="{{t.say}}" aria-label="Say it as" maxlength="120">
            <select class="tn-airport" aria-label="Airport">
                <option value=""{{!' selected' if not t.airport else ''}}>Every airport</option>
                % for c in sorted(set(codes) | ({t.airport} if t.airport else set())):
                <option value="{{c}}"{{!' selected' if c == t.airport else ''}}>{{c}}</option>
                % end
            </select>
            <button class="btn icon tn-play tn-hear" type="button" aria-label="Hear it" aria-pressed="false" title="Hear it as written, before saving">
                <svg class="i-play" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>
                <svg class="i-stop" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
            </button>
            <button class="btn icon tn-remove" type="button" aria-label="Remove">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
            </button>
        </div>
        % end
    </div>
    <p class="tn-empty muted" id="tn-empty"{{!' hidden' if tunings else ''}}>None yet: Add one, or press a word below.</p>
    <p class="tn-status muted" id="tn-status" role="status"></p>
    <p class="muted tn-hint">Press the speaker beside a row to hear its "say it as" now, saved or not, and tweak the spelling until it sounds right.</p>
    <audio id="tn-hear-audio" preload="none"></audio>
</section>

<section class="card">
    <div class="card-head">
        <h2>Read as written</h2>
        <span class="muted">In the ATIS on your map now, the map didn't know these: it reads them as written (spelled, in capitals). Press one to tune it.</span>
    </div>
    <div class="tn-suggest">
        % if problem:
        <span class="muted">Couldn't get the ATIS: {{problem}}</span>
        % elif not with_atis:
        <span class="muted">No airport on the map has a digital ATIS{{'' if atis_on else ' to look at while spoken ATIS is off'}}.</span>
        % elif not suggestions:
        <span class="muted">None: the map knows every word in its airports' ATIS now.</span>
        % end
        % for word, where in suggestions.items():
        <button class="chip" type="button" data-suggest="{{word}}" title="In {{', '.join(where)}}">{{word}}</button>
        % end
    </div>
</section>

% if with_atis:
<section class="card" id="tn-try">
    <div class="card-head">
        <h2>Try it</h2>
        <span class="tn-actions">
            <label class="sr-only" for="tn-airport">Airport</label>
            <select id="tn-airport">
                % for c in with_atis:
                <option value="{{c}}">{{c}}</option>
                % end
            </select>
            <button class="btn" type="button" id="tn-show">Show</button>
            <!-- Play; glows while the map gets the ATIS and the speech server reads it; then Stop -->
            <button class="btn tn-play" type="button" id="tn-play" aria-pressed="false">
                <svg class="i-play" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>
                <svg class="i-stop" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
                <span class="tn-play-label">Play</span>
            </button>
        </span>
    </div>
    <p class="muted tn-hint">The ATIS as saved: Save first to hear a change. Each line is the FAA's text, then how it's said.</p>
    <ol class="tx" id="tn-transcript"></ol>
    <audio id="tn-audio" preload="none"></audio>
</section>
% end

%include("footer.tpl")

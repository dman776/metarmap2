%include("header.tpl", title="Debug")
% num, vis = renderer.visualizer
% looks = renderer.looks
<section class="page-head">
    <div>
        <h1>Debug</h1>
        <p>Active visualizer: {{vis.name}} · METARs fetched {{metars.lastFetchTime or 'never'}}</p>
    </div>
    <button class="btn" type="button" data-call="/fetch">Fetch</button>
</section>

<section class="card">
    <div class="card-head"><h2>LED looks</h2><span class="mono muted">{{len(looks) if looks else 'whole strip'}}</span></div>
    <pre class="dump">
% if renderer.strip_look is not None:
strip: {{renderer.strip_look}}
% end
% for i, (code, look) in enumerate(zip(metars.data, looks)):
{{i}} {{code}}: {{look}}
% end
</pre>
</section>

%include("footer.tpl")

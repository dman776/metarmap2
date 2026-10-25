%include("header.tpl", title="Debug")
<section class="page-head">
    <div>
        <h1>Debug</h1>
        <p>Active visualizer: {{active['name']}} · METARs fetched {{fetched or 'never'}}</p>
    </div>
    <button class="btn" type="button" data-call="/fetch">Fetch</button>
</section>

<section class="card">
    <div class="card-head"><h2>LED looks</h2><span class="mono muted">{{len(looks) if looks else 'whole strip'}}</span></div>
    <pre class="dump">
% if strip_look is not None:
strip: {{strip_look}}
% end
% for i, (code, look) in rows:
{{i}} {{code}}: {{look}}
% end
</pre>
</section>

%include("footer.tpl")

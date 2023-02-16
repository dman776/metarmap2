%include("header.tpl",title="METAR List")
<div class="py-5 text-center">
    <h2>Control</h2>
</div>

<div class="row">
    <a class="btn btn-primary" href="/" role="button">Control</a>&nbsp;
    <a class="btn btn-primary" href="/metars" role="button">Metars</a>&nbsp;
    <a class="btn btn-primary" href="/visualizer/previous" role="button">Prev Visualizer</a>&nbsp;
    <a class="btn btn-primary" href="/visualizer/next" role="button">Next Visualizer</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/1" role="button">Brightness 100%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.5" role="button">Brightness 50%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.1" role="button">Brightness 10%</a>&nbsp;
    <a class="btn btn-primary" href="/fetch" role="button">Fetch</a>&nbsp;
    <a class="btn btn-primary" href="/debug" role="button">Debug</a>&nbsp;
    <a class="btn btn-primary" href="/raw" role="button">Raw Metars</a>&nbsp;
</div>
<div class="row">
    Current Visualizer: {{renderer.visualizer[1]}}
</div>
%include("footer.tpl")

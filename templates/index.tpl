%include("header.tpl",title="METARMap")

<div class="py-5 text-center">
    <h2>Home</h2>
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/metars';">Metars</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/raw';" role="button">Raw Metars</button>&nbsp;
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/previous';">&lt;</button>&nbsp;
    <button class="btn btn-primary" disabled>Visualizer</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/next';">&gt;</button>
</div>
<div class="row"><b>{{renderer.visualizer[1].name}}</b></div>
<div class="row">{{!renderer.visualizer[1].description}}</div>
<hr />
<div class="row">
    <label for="brightness" class="form-label">Brightness</label>&nbsp;
    <input type="range" class="form-range" min="0" max="1" step="0.01" id="brightness" onChange="fetch('/brightness/' + this.value);" value="{{renderer.pixels().brightness}}" />
</div>
<hr />
%include("footer.tpl")

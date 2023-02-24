%include("header.tpl",title="METARMap")

<div class="py-5 text-center">
    <h2>Home</h2>
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/metars';">Metars</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/raw';" role="button">Raw Metars</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/config';" role="button">Config</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="fetch('/restart');" role="button">Restart</button>&nbsp;
</div>
<hr />
<div class="row">
    <label for="brightness" class="form-label">Brightness</label>&nbsp;
    <input type="range" class="form-range" min="0" max="1" step="0.01" id="brightness" onChange="fetch('/brightness/' + this.value);" value="{{renderer.pixels().brightness}}" />
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/previous';">&lt;</button>&nbsp;
    <div class="dropdown">
      <button class="btn btn-secondary dropdown-toggle" type="button" id="dropdownMenuButton" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
        Visualizer
      </button>
      <div class="dropdown-menu" aria-labelledby="dropdownMenuButton">
        %for i in range(0, len(renderer.visualizers)):
            <a class="dropdown-item" onClick="window.location='/visualizer/{{i}}'">{{renderer.visualizers[i].name}}</a>
        %end
      </div>
    </div>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/next';">&gt;</button>
</div>
<div class="row"><b>{{renderer.visualizer[1].name}}</b></div>
<div class="row">{{!renderer.visualizer[1].description}}</div>
<hr />
%include("footer.tpl")

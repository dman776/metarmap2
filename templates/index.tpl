%include("header.tpl",title="METARMap")
<script>
    async function fetch_output(url, destdiv, modalTitleDiv, title) {
        e = document.getElementById(destdiv);
        e.innerHTML = "Processing..."
        mtd = document.getElementById(modalTitleDiv);
        mtd.innerHTML = title
        let result;
        const res = await fetch(url);
        result = await res.text();
        e.innerHTML = result;
        return;
    }

</script>
<div class="py-5 text-center">
<h2>Home</h2>
</div>
<hr/>
<div class="row">
<div class="col-sm">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/metars';">Metars</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/raw';" role="button">Raw Metars</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/map';" role="button">Map</button>
</div>
</div>
        &nbsp;
<div class="row">
<div class="col-sm">
    <button type="button" class="btn btn-secondary" onClick="window.location='/config';" role="button">Config</button>&nbsp;
    <button type="button" class="btn btn-secondary"
            onClick="fetch_output('/update', 'modalBody', 'outputModalTitle', 'Update');" role="button"
            data-toggle="modal" data-target="#outputModal">Update
    </button>&nbsp;
    <button type="button" class="btn btn-secondary" onClick="fetch('/restart');" role="button">Restart</button>&nbsp;
</div>
</div>
<hr/>
<div class="row">
<div class="col-sm">
    <label for="brightness" class="form-label">Brightness</label>&nbsp;
    <input type="range" class="form-range" min="0" max="1" step="0.01" id="brightness"
           onChange="fetch('/brightness/' + this.value);document.getElementById('brt_label').innerText=Math.round(this.value*100) + '%';"
           value="{{renderer.pixels().brightness}}"/>
    <label id="brt_label">{{round(renderer.pixels().brightness * 100)}}%</label>
</div>
</div>
<hr/>
<div class="row">
<div class="col-sm">
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/previous';">&lt;</button>
    <span class="dropdown">
            <button class="btn btn-secondary dropdown-toggle" type="button" id="dropdownMenuButton"
                    data-toggle="dropdown"
                    aria-haspopup="true" aria-expanded="false">
                Visualizer
            </button>
            <div class="dropdown-menu" aria-labelledby="dropdownMenuButton">
                %for i in range(0, len(renderer.visualizers)):
                <a class="dropdown-item"
                   onClick="window.location='/visualizer/{{i}}'">{{renderer.visualizers[i].name}}</a>
                %end
            </div>
        </span>
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/next';">&gt;</button>
</div>
</div>
<div class="row">
<div class="col-sm">
    <b>{{renderer.visualizer[1].name}}</b>
</div>
</div>
<div class="row">
<div class="col-sm">
    {{!renderer.visualizer[1].description}}
</div>
</div>&nbsp;
<div class="row">
<div class="col-sm">
    This visualizer will {{"not" if renderer.visualizer[1].exclusive else ""}} allow other functions to interrupt the
    map.
</div>
</div>&nbsp;
<hr/>
        <!-- Modal -->
<div class="modal fade" id="outputModal" tabindex="-1" role="dialog" aria-labelledby="outputModalTitle"
     aria-hidden="true">
<div class="modal-dialog modal-dialog-scrollable" role="document">
    <div class="modal-content">
        <div class="modal-header">
            <h5 class="modal-title" id="outputModalTitle"></h5>
            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                <span aria-hidden="true">&times;</span>
            </button>
        </div>
        <div class="modal-body" id="modalBody"></div>
        <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
            <button type="button" class="btn btn-primary" onClick="fetch('/restart');" data-dismiss="modal"
                    role="button">Restart
            </button>
        </div>
    </div>
</div>
</div>

        %include("footer.tpl")

%include("header.tpl",title="METAR List")
<div class="py-5 text-center">
    <h2>CONFIG</h2>
</div>

<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<div class="row">
    <div class="form-check">
        <input class="form-check-input" type="checkbox" value="{{renderer.config.data.display_screen.locate_active}}" id="defaultCheck1">
        <label class="form-check-label" for="defaultCheck1">
            Display Highlight Active Airport
        </label>
    </div>
</div>
%include("footer.tpl")

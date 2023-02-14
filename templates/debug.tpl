%include("header.tpl",title="DEBUG")
<div class="py-5 text-center">
    <h2>DEBUG</h2>
</div>

<div class="row">
  <a class="btn btn-primary" href="/fetch" role="button">Fetch</a>&nbsp;
</div>

<div class="row">
	<div class="col-md-12 order-md-1">
        <h4>{{metars.lastFetchTime}}</h4>
        <ul class="list-group">
    	    %for e in renderer.visualizer().__effect__:
            <li class="list-group-item d-flex align-items-center">{{e}}</li>
            %end
    	</ul>
	</div>
</div>
%include("footer.tpl")

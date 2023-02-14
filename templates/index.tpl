%include("header.tpl",title="METAR List")
<div class="py-5 text-center">
    <h2>METARS</h2>
</div>

<div class="row">
    <a class="btn btn-primary" href="/fetch" role="button">Fetch</a>&nbsp;
    <a class="btn btn-primary" href="/debug" role="button">Debug</a>&nbsp;
</div>

<div class="row">
	<div class="col-md-12 order-md-1">
        <h4>{{metars.lastFetchTime}}</h4>
        <ul class="list-group">
            % i = 0
    	    %for m in metars.data:
          <li class="list-group-item d-flex align-items-center\\
                %if len(metars.data[m].keys() > 0):
                    %if metars.data[m]['flightCategory']=='VFR':
                        list-group-item-success">
                    %elif metars.data[m]['flightCategory']=='MVFR':
                        list-group-item-primary">
                    %elif metars.data[m]['flightCategory'] == 'IFR':
                        list-group-item-danger">
                    %elif metars.data[m]['flightCategory'] == 'LIFR':
                        list-group-item-info">
                    %end
                    <div class="col-1"><a class="badge badge-primary" href="/locate/{{i}}" role="button">Locate</a></div>
                    <div class="col-1">{{m}}</div>
                    <div class="col-1"></div>
                    <div class="col-1">{{metars.data[m]['flightCategory']}}</div>
                    <div class="col-6">{{metars.data[m]['raw']}}</div>
                    <div class="col-2">{{metars.data[m]['obsTime']}}</div>
                %else
                    ">
                    <div class="col-1"><a class="badge badge-primary" href="/locate/{{i}}" role="button">Locate</a></div>
                    <div class="col-1">{{m}}</div>
                    <div class="col-1"></div>
                    <div class="col-1">-</div>
                    <div class="col-6">-</div>
                    <div class="col-2">-</div>
                %end
          </li>
            % i+=1
            %end
    	</ul>
	</div>
</div>
%include("footer.tpl")

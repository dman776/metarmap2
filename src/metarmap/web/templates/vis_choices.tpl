<!-- every visualizer, for the pick lists under the visualizer's name (map.js builds them from this); data-* is the active one -->
<ul id="vis-choices" data-active="{{active['index']}}" data-active-id="{{active['id']}}" data-active-name="{{active['name']}}" hidden>
    % for v in visualizers:
    <li data-id="{{v['id']}}" data-name="{{v['name']}}" data-icon="{{v['icon']}}" data-skipped="{{'true' if v['skipped'] else 'false'}}"></li>
    % end
</ul>

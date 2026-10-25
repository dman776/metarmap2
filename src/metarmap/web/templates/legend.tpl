% if legend:
<div style="display: flex; flex-direction: column; gap: 10px">
    <div class="lbl">What the LEDs mean</div>
    <ul class="legend">
        % for item in legend:
        %   colors = item['colors']
        %   style = ''
        %   if len(colors) > 1 and item['effect'] not in ('flash', 'alternate'):
        %     style = '--c: {0}; background: linear-gradient(90deg, {1})'.format(colors[0], ', '.join(colors))
        %   elif colors:
        %     style = '--c: {0}; --c2: {1}'.format(colors[0], colors[-1])
        %   end
        %   if item['period']:
        %     style += '; --period: {0}s'.format(item['period'])
        %   end
        %   if item.get('low'):
        %     style += '; --low: {0}'.format(item['low'])
        %   end
        %   classes = 'led ' + item['effect'] + (' grad' if len(colors) > 1 and item['effect'] not in ('flash', 'alternate') else '')
        <li><span class="{{classes}}" style="{{style}}" aria-hidden="true"></span><div><b>{{item['label']}}</b><span class="m">{{item['detail']}}</span></div></li>
        % end
    </ul>
</div>
% end

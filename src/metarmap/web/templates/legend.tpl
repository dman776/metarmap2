% if legend:
<div style="display: flex; flex-direction: column; gap: 10px">
    <div class="lbl">What the pixels mean</div>
    % if defined('step') and step:
    <ol class="steps" aria-label="Forecast step">
        % for n, label in enumerate(step['labels']):
        <li{{!' class="on"' if n == step['index'] else ''}}>{{label}}</li>
        % end
    </ol>
    % end
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
        %   hide = defined('filtered') and filtered and not item.get('inUse', True)
        <li data-key="{{item['key']}}"{{!' hidden' if hide else ''}}><span class="{{classes}}" style="{{style}}" aria-hidden="true"></span><div><b>{{item['label']}}</b><span class="m">{{item['detail']}}</span></div></li>
        % end
    </ul>
</div>
% end

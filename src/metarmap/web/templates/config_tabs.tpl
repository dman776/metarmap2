% # the Config tab bar. On /config the tabs switch panels in the page (app.js); Airports is its own page
% on_airports = active == 'airports'
% release = get('release')
<nav class="tabs" aria-label="Config sections">
    % for key, label in (('physical', 'Physical display'), ('visualizers', 'Visualizers'), ('airports', 'Airports'), ('map', 'Virtual map'), ('system', 'System')):
    %   href = '/config/airports' if key == 'airports' else ('/config#' if on_airports else '#') + key
    <a class="tab" href="{{href}}" data-tab="{{key}}"{{!' aria-current="page"' if key == active else ''}}>{{label}}
        % if key == 'system' and release and release['badge']:
        <span class="tab-dot" title="{{release['badge']}}"></span>
        % end
    </a>
    % end
</nav>

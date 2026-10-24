% import datetime
        </main>
        <footer class="foot">
            &copy; {{datetime.date.today().year}} Darryl Quinn · <a href="http://metarmap.local">metarmap.local</a> · Version {{config.app_version}}
        </footer>
        <dialog id="output" aria-labelledby="output-title">
            <div class="card-head"><h2 id="output-title">Output</h2></div>
            <div class="body"></div>
            <form method="dialog" class="foot-actions">
                <button class="btn" type="submit">Close</button>
                <button class="btn primary" type="button" data-call="/restart" data-then="none" data-confirm="Restart the map now?">Restart</button>
            </form>
        </dialog>
        <script src="/static/app.js?v={{config.app_version}}"></script>
    </body>
</html>

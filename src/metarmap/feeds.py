"""
Fetching the map's weather feeds on their schedule, and trying again when one fails.

Feeds holds what the fetches share: the METARs, advisories, TFRs, FAA status and TAFs; the lock that lets one METAR
fetch run at a time; and the retry state. App builds one (App.__post_init__) and calls it; it never imports
metarmap.app.
"""

import logging
import threading
import time
from typing import List, Optional

import schedule

from metarmap.advisories import Advisories
from metarmap.config import Config
from metarmap.delays import Delays
from metarmap.forecast import Forecasts
from metarmap.metar import Reports
from metarmap.renderer import Renderer
from metarmap.tfr import Tfrs

log = logging.getLogger(__name__)

METAR_MINUTES = 10  # how often METARs are fetched
RETRY_SECONDS = 60  # after a failed fetch or lookup (e.g. aviationweather.gov answering 502), how soon to try again
FETCH_WAIT_SECONDS = 20  # GET /fetch waits at most this long for a fetch under way to finish (else 503)
UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}  # a schedule job's unit, in seconds


class Feeds:
    def __init__(
        self,
        config: Config,
        metars: Reports,
        renderer: Renderer,
        scheduler: schedule.Scheduler,
        advisories: Optional[Advisories] = None,
        tfrs: Optional[Tfrs] = None,
        delays: Optional[Delays] = None,
        forecasts: Optional[Forecasts] = None,
    ):
        self.config = config
        self.metars = metars
        self.renderer = renderer
        self.scheduler = scheduler
        self.advisories = advisories
        self.tfrs = tfrs
        self.delays = delays
        self.forecasts = forecasts
        # held while a METAR fetch runs (start_fetch): one at a time, so they don't fade the LEDs over each other
        self.fetching = threading.Lock()
        # set when an airport code changed: its METAR is fetched now, or right after the fetch under way (refetch_soon)
        self.refetch_due = threading.Event()
        self._retrying = set()  # the feeds retry_feeds() has said it is trying again, so it says so once
        # retry_soon() runs on the scheduler's thread and the startup lookup's
        self._retry_lock = threading.Lock()

    # ---- scheduling ------------------------------------------------------------------------------------------

    def schedule_fetch(self):
        """
        The regular fetch every METAR_MINUTES, the wait starting now: at startup, and after a fetch by hand (/fetch),
        so the next one is a whole interval later instead of maybe a minute.
        """
        self.scheduler.clear("fetch")
        self.scheduler.every(METAR_MINUTES).minutes.do(self.update_data).tag("fetch")

    def next_fetch(self) -> dict:
        """
        When METARs are next fetched (Unix time; None if nothing is scheduled) and that job's interval in seconds: the
        regular fetch, or a retry after a failed one if that comes first. With when they were last fetched, for the
        Home page's countdown.
        """
        jobs = [j for tag in ("fetch", "retry") for j in self.scheduler.get_jobs(tag) if j.next_run is not None]
        soonest = min(jobs, key=lambda j: j.next_run, default=None)
        fetched = self.metars.lastFetchTime
        return {
            "next": soonest.next_run.timestamp() if soonest else None,  # schedule's times are the map's local time
            "seconds": soonest.interval * UNIT_SECONDS[soonest.unit] if soonest else None,
            "fetched": fetched.timestamp() if fetched else None,
        }

    def start_retry_job(self):
        """At startup: the retry of the advisories, TFRs and FAA status that ends itself once all have loaded."""
        self.scheduler.every(RETRY_SECONDS).seconds.do(self.retry_feeds).tag("retry_feeds")

    def start(self):
        """At startup: every feed in the background, so a slow aviationweather.gov or FAA doesn't hold up the map."""
        # the LEDs show them when they come (the first TFR list has a few dozen details to fetch)
        self.fetch_advisories_soon()
        self.fetch_tfrs()
        self.fetch_delays()
        self.fetch_forecasts()
        self.locate_soon()
        self.start_retry_job()

    # ---- fetching METARs in the background -------------------------------------------------------------------

    def airport_codes_changed(self):
        """
        A new airport code: its name now (looked up if need be), so the Airports page shows it when it reloads; its
        METAR in the background.
        """
        unnamed = {a.code for a in self.config.airports if a.code and not a.name}
        self.config.fill_names({code: self.metars.name_for(code) for code in unnamed})
        self.refetch_soon()
        self.fetch_forecasts()  # fetches only if the airports differ from the last TAF fetch's

    def refetch_soon(self) -> Optional[threading.Thread]:
        """
        An airport changed: only the METARs (not the advisories and TFRs that update_data() also fetches), in the
        background; right after the fetch under way if there is one, which may have asked for the old airports.
        """
        self.refetch_due.set()  # first: a fetch letting go of the lock now still sees it (_run_fetch)
        return self.start_fetch(
            self.fetch_metars_only, "METAR fetch", busy="an airport changed: its METAR comes after the fetch under way"
        )

    def refetch_metars(self) -> bool:
        """
        GET /fetch: the METARs now, back when they're in (the web thread waits, not the LEDs). A fetch under way is
        waited for first, up to FETCH_WAIT_SECONDS. Returns False if it was still running then (nothing fetched).
        Raises what the fetch raised (logged already, `fetching` let go), for /fetch to answer 500.
        """
        if not self.fetching.acquire(timeout=FETCH_WAIT_SECONDS):
            log.warning(
                f"fetch by hand: a METAR fetch has been under way for over {FETCH_WAIT_SECONDS} s; not fetching"
            )
            return False
        error = self._run_fetch(self.fetch_metars_only, "METAR fetch")
        if error is not None:
            raise error
        return True

    def fetch_metars_only(self):
        self.fetch_reports()
        self.renderer.update_data(self.metars)  # a forecast goes on at the step it's on
        self.fill_names()

    def start_fetch(self, job, what, busy) -> Optional[threading.Thread]:
        """
        Runs job() in a thread holding `fetching`, so the LEDs keep going while aviationweather.gov answers (it has
        taken 20 s), and one at a time: two at once would fade the LEDs over each other and could leave them half dim.
        Returns the thread (tests join it), or None with `busy` logged when a fetch is under way: this one is skipped.
        """
        if not self.fetching.acquire(blocking=False):
            log.info(busy)  # at most every RETRY_SECONDS (a retry), so no flood
            return None
        thread = threading.Thread(target=self._run_fetch, args=(job, what), name="metars", daemon=True)
        try:
            thread.start()
        except Exception:
            self.fetching.release()  # no thread to let go of it
            raise
        return thread

    def _run_fetch(self, job, what) -> Optional[Exception]:
        """
        job(), `fetching` already held; lets go of it however the job ends. Then the METAR of a new airport. Returns
        what the job raised, logged (a thread's caller doesn't look: the schedule goes on), or None.
        """
        error = None
        try:
            job()
            if self.needs_retry():
                self.retry_soon()
            else:
                self.stop_retrying()  # at once, not at the retry's next turn (the Home page counts down to it)
        except Exception as e:
            log.exception(f"{what} failed: {e}")  # the next regular fetch or retry tries again
            error = e
        finally:
            self.fetching.release()
        if self.refetch_due.is_set():  # an airport changed while this ran, and its fetch was put off
            self.refetch_soon()
        return error

    def fetch_reports(self):
        """The METARs (with the G-AIRMET hazards). Only in a fetch holding `fetching`. Returns whether they came."""
        self.refetch_due.clear()  # this fetch asks for the airports as they are now
        with self.renderer.dimmed():  # off the main loop: the LEDs dim (led.dim_on_refresh) but keep animating
            return self.metars.fetch()

    # ---- the regular fetch -----------------------------------------------------------------------------------

    def update_data(self) -> Optional[threading.Thread]:
        """
        The regular fetch, every METAR_MINUTES, all in the background. Returns the thread fetching the advisories and
        METARs, or None if the last fetch is still under way: this one is skipped.
        """
        self.fetch_tfrs()
        self.fetch_delays()
        self.fetch_forecasts()
        return self.start_fetch(
            self.fetch_all, "METAR fetch", busy="regular METAR fetch skipped: the last one is still under way"
        )

    def fetch_all(self):
        """update_data()'s thread: the advisories, then the METARs (they pick up the advisories), then the LEDs."""
        self.fetch_advisories()
        self.fetch_metars_only()

    def fetch_advisories(self):
        """New G-AIRMETs and SIGMETs; the METARs pick them up when next processed. Keeps the old ones if it fails."""
        if self.advisories is not None and self.advisories.fetch():
            self.metars.apply_mocks()  # reapplied now, in case the METAR fetch after this fails

    def fetch_advisories_soon(self):
        """At startup: the G-AIRMETs and SIGMETs in the background; the LEDs show them when they come."""

        def fetch():
            started = time.monotonic()
            if self.advisories.fetch():
                log.info(f"advisories fetched in {time.monotonic() - started:.1f}s")
                self.show_areas()

        if self.advisories is not None:
            threading.Thread(target=fetch, name="advisories", daemon=True).start()

    def locate_soon(self):
        """
        At startup: where the airports without a report are, and the names, in the background (aviationweather.gov's
        station lookup has taken 20 s and answered 504). Only the Map page's positions and the empty names need it,
        not the LEDs. A failed lookup is retried like any other (retry_soon).
        """

        def locate():
            started = time.monotonic()
            ok = self.metars.locate()
            log.info(f"stations looked up in {time.monotonic() - started:.1f}s" + ("" if ok else " (failed)"))
            self.fill_names()
            if ok:
                self.show_areas()  # an airport's position places it in the advisory and TFR areas
            else:
                self.retry_soon()

        threading.Thread(target=locate, name="stations", daemon=True).start()

    def fetch_tfrs(self):
        """Fetches the TFRs in the background; the LEDs show them when it's done."""
        if self.tfrs is not None:
            self.tfrs.fetch_soon(then=self.show_areas)

    def fetch_delays(self):
        """
        Fetches the FAA airport status in the background; the LEDs show it when it's done, if it changed (it's
        fetched every few minutes, and usually hasn't).
        """
        if self.delays is not None:
            self.delays.fetch_soon(then=self.show_areas)

    def fetch_forecasts(self, force=False):
        """The TAFs in the background (not more often than they change); the LEDs show them when they come."""
        if self.forecasts is not None:
            codes = [a.code for a in self.config.airports if a.code]
            self.forecasts.fetch_soon(codes, then=self.show_areas, force=force)

    def show_areas(self):
        """
        The reports again, with the advisory and TFR areas each airport is in (or near) and its FAA status, on the
        LEDs.
        """
        self.metars.apply_mocks()  # adds them to each report
        self.renderer.update_data(self.metars)

    def fill_names(self):
        """Airports with an empty name get the name the station lookup found (saved to config.json)."""
        filled = self.config.fill_names(self.metars.station_names())
        if filled:
            log.info(f"filled in the names of {filled} airports")

    # ---- trying again ----------------------------------------------------------------------------------------

    def needs_retry(self):
        """Whether the METAR fetch, or the lookup of where airports without a report are, failed."""
        return self.metars.last_fetch_ok is False or self.metars.locate_failed

    def feeds_waiting(self) -> List[str]:
        """The advisories, TFR and FAA status feeds that have never loaded: their airports breathe dimly until then."""
        feeds = (
            ("advisories", self.advisories is not None and self.advisories.waiting()),
            ("TFR", self.tfrs is not None and self.tfrs.fetched is None),
            ("FAA status", self.delays is not None and self.delays.fetched is None),
        )
        return [name for name, waiting in feeds if waiting]

    def retry_feeds(self):
        """
        Every RETRY_SECONDS until the advisories, TFRs and FAA status have each loaded once: asks again the ones
        whose last try failed (one still under way is left to finish), instead of leaving their airports breathing
        dimly until the next regular fetch, up to METAR_MINUTES away. Each fetch is in the background, so the LEDs
        don't wait for it.
        """
        waiting = self.feeds_waiting()
        if not waiting:
            self._retrying.clear()
            return schedule.CancelJob
        for name, failed, fetch in (
            ("advisories", "advisories" in waiting and self.advisories.failed(), self.fetch_advisories_soon),
            ("TFR", "TFR" in waiting and self.tfrs.error is not None, self.fetch_tfrs),
            ("FAA status", "FAA status" in waiting and self.delays.error is not None, self.fetch_delays),
        ):
            if failed:
                # said once per feed, not every minute for as long as the network is down
                (log.debug if name in self._retrying else log.info)(
                    f"{name}: trying again every {RETRY_SECONDS} s until it loads"
                )
                self._retrying.add(name)
                fetch()

    def retry_soon(self):
        """Tries again every RETRY_SECONDS until it works, instead of waiting for the next regular fetch."""
        with self._retry_lock:  # the startup lookup's thread and the scheduler's thread can both get here
            if not self.scheduler.get_jobs("retry"):
                what = "METAR fetch" if self.metars.last_fetch_ok is False else "airport position lookup"
                log.warning(f"{what} failed; trying again every {RETRY_SECONDS} s until it works")
                self.scheduler.every(RETRY_SECONDS).seconds.do(self.retry_fetch).tag("retry")

    def stop_retrying(self):
        with self._retry_lock:
            self.scheduler.clear("retry")

    def retry_fetch(self):
        """The retry job: redoes what failed in the background, so a failing aviationweather.gov leaves the LEDs be."""
        if not self.needs_retry():
            return schedule.CancelJob
        self.start_fetch(self.redo_failed, "METAR retry", busy="METAR retry skipped: a fetch is under way")

    def redo_failed(self):
        """The fetch (which also does the lookup), or only the lookup."""
        if self.metars.last_fetch_ok is False:
            if self.fetch_reports():
                self.renderer.update_data(self.metars)
        elif self.metars.locate_failed:
            self.metars.locate()
        self.fill_names()

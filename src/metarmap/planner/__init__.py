"""
The Chart Planner (B90): lays out the airports on a board so a pixel string needs the fewest cuts or extensions.

projection  lat/lon on a chart to millimetres on the board (charts, margins, board size)
layout      declutter, order, split into strings, skipped pixels, size search, drop and recommend suggestions
airports    live airport data (aviationweather.gov) for the candidates and their ranking
"""

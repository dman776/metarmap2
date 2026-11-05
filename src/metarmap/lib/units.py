"""Unit conversions."""


def celsius_to_fahrenheit(celsius):
    """Degrees Fahrenheit from Celsius; 0 for None (a report without a temperature)."""
    if celsius is None:
        return 0
    return celsius * 9.0 / 5.0 + 32.0

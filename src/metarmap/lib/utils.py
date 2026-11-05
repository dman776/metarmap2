"""Small helpers: Celsius to Fahrenheit, and a ping."""

import subprocess


def celsius_to_fahrenheit(temperature_celsius: float):
    """
    Converts a temperature in celsius to fahrenheit.
    Args:
        temperature_celsius (float): A temperature in C
    Returns:
        [type]: The temperature converted to F
    """
    if temperature_celsius is None:
        return 0

    return (temperature_celsius * (9.0 / 5.0)) + 32.0


def is_pingable(site="www.aviationweather.gov"):
    return subprocess.run(["ping", "-c", "1", site], capture_output=True).returncode

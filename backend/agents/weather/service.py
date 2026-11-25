"""Provider selection + fallback. Never fabricates data: if no provider can answer, a WeatherError explains why.

Order: OpenWeatherMap (if key) -> WeatherAPI.com (if key) -> Open-Meteo (always available, no key).
"""
from datetime import date

from django.conf import settings

from .models import DayWeather, Location, ProviderUnavailable, WeatherError, WeatherResult
from .providers import OpenMeteoProvider, OpenWeatherMapProvider, WeatherApiProvider


def default_providers() -> list:
    providers = []
    if settings.OPENWEATHER_API_KEY:
        providers.append(OpenWeatherMapProvider(settings.OPENWEATHER_API_KEY))
    if settings.WEATHERAPI_KEY:
        providers.append(WeatherApiProvider(settings.WEATHERAPI_KEY))
    providers.append(OpenMeteoProvider())
    return providers


class WeatherService:
    def __init__(self, providers: list | None = None):
        self.providers = default_providers() if providers is None else providers

    def _attempt(self, capability: str, *args) -> WeatherResult:
        """Try each provider in order, recording (for the user) why earlier ones were skipped."""
        notes: list[str] = []
        last_error: WeatherError | None = None
        for provider in self.providers:
            try:
                return WeatherResult(getattr(provider, capability)(*args), provider.name, notes)
            except ProviderUnavailable as error:
                last_error = error
                notes.append(f"{provider.name} could not provide this ({error}); trying another provider.")
            except WeatherError as error:
                if "not found" in str(error).lower():
                    raise  # an unknown place will not exist for the other providers either
                last_error = error
                notes.append(f"{provider.name} failed ({error}); trying another provider.")
        raise last_error or WeatherError("No weather provider is configured.")

    def locate(self, city: str) -> WeatherResult:
        return self._attempt("geocode", city)

    def current(self, loc: Location) -> WeatherResult:
        return self._attempt("current", loc)

    def forecast(self, loc: Location, days: int) -> WeatherResult:
        if not 1 <= days <= 16:
            raise WeatherError("Forecasts are available for 1 to 16 days ahead.")
        result = self._attempt("forecast", loc, days)
        if len(result.data) < days:
            # Free plans cover only ~3-5 days; ask the next provider (Open-Meteo reaches 16 days).
            remaining = [p for p in self.providers if p.name != result.source]
            for provider in remaining:
                try:
                    longer = provider.forecast(loc, days)
                except WeatherError:
                    continue
                if len(longer) >= days:
                    return WeatherResult(longer, provider.name, [f"{result.source} covers fewer than {days} days on its plan, so {provider.name} was used."])
        if not result.data:
            raise WeatherError("No forecast data is available for that location.")
        return result

    def history(self, loc: Location, start: date, end: date) -> WeatherResult:
        if end >= date.today():
            raise WeatherError("Historical data is only available for days before today.")
        if start > end:
            raise WeatherError("The start date must not be after the end date.")
        if (end - start).days > 30:
            raise WeatherError("Please ask for at most 31 days of history at a time.")
        return self._attempt("history", loc, start, end)

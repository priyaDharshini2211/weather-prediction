"""HTTP clients for OpenWeatherMap and Open-Meteo. Both return the normalised dataclasses from models.py."""
from collections import Counter
from datetime import date, datetime, timezone
from typing import Optional

import requests
from django.conf import settings

from .models import CurrentWeather, DayWeather, Location, ProviderUnavailable, WeatherError

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
    81: "Rain showers", 82: "Violent rain showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def _get_json(url: str, params: dict, provider: str) -> dict:
    try:
        response = requests.get(url, params=params, timeout=settings.WEATHER_TIMEOUT)
    except requests.Timeout as error:
        raise WeatherError(f"{provider} timed out. Please try again.") from error
    except requests.RequestException as error:
        raise WeatherError(f"Could not reach {provider}: network error.") from error

    if response.status_code in (401, 403):
        raise ProviderUnavailable(f"{provider} rejected the request (HTTP {response.status_code}): invalid key or plan limitation.")
    if response.status_code == 429:
        raise WeatherError(f"{provider} rate limit reached. Please try again shortly.")
    if response.status_code == 404:
        raise WeatherError("Location not found.")
    if not response.ok:
        raise WeatherError(f"{provider} returned an error (HTTP {response.status_code}).")
    try:
        return response.json()
    except ValueError as error:
        raise WeatherError(f"{provider} returned an unreadable response.") from error


def _avg(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


class OpenMeteoProvider:
    """Free, no API key. Supports geocoding, current, forecast and history."""

    name = "Open-Meteo"
    DAILY = "temperature_2m_max,temperature_2m_min,temperature_2m_mean,relative_humidity_2m_mean,wind_speed_10m_max,precipitation_sum,weather_code"

    def geocode(self, city: str) -> Location:
        data = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1, "language": "en"}, self.name
        )
        results = data.get("results") or []
        if not results:
            raise WeatherError(f"I couldn't find a place called '{city}'.")
        top = results[0]
        return Location(top["name"], top.get("country", ""), top["latitude"], top["longitude"])

    def current(self, loc: Location) -> CurrentWeather:
        data = _get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": loc.lat, "longitude": loc.lon, "wind_speed_unit": "ms", "timezone": "auto",
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,pressure_msl,weather_code",
            },
            self.name,
        )
        cur = data["current"]
        return CurrentWeather(
            temp=cur["temperature_2m"], feels_like=cur.get("apparent_temperature"),
            humidity=cur.get("relative_humidity_2m"), wind_speed=cur.get("wind_speed_10m"),
            pressure=cur.get("pressure_msl"), condition=WMO_CODES.get(cur.get("weather_code"), "Unknown"),
            observed_at=cur["time"],
        )

    def _daily(self, url: str, params: dict) -> list[DayWeather]:
        data = _get_json(url, {**params, "daily": self.DAILY, "wind_speed_unit": "ms", "timezone": "auto"}, self.name)
        d = data["daily"]
        days = []
        for i, day in enumerate(d["time"]):
            days.append(
                DayWeather(
                    date=day, temp_min=d["temperature_2m_min"][i], temp_max=d["temperature_2m_max"][i],
                    temp_avg=d["temperature_2m_mean"][i], humidity=d["relative_humidity_2m_mean"][i],
                    wind_speed=d["wind_speed_10m_max"][i], precipitation=d["precipitation_sum"][i],
                    condition=WMO_CODES.get(d["weather_code"][i], "Unknown"),
                )
            )
        return days

    def forecast(self, loc: Location, days: int) -> list[DayWeather]:
        result = self._daily(
            "https://api.open-meteo.com/v1/forecast", {"latitude": loc.lat, "longitude": loc.lon, "forecast_days": min(days + 1, 16)}
        )
        today = date.today().isoformat()
        return [d for d in result if d.date > today][:days]

    def history(self, loc: Location, start: date, end: date) -> list[DayWeather]:
        age_days = (date.today() - start).days
        if age_days <= 80:  # forecast endpoint serves recent past days (analysis data) without the archive lag
            rows = self._daily(
                "https://api.open-meteo.com/v1/forecast", {"latitude": loc.lat, "longitude": loc.lon, "past_days": age_days + 1, "forecast_days": 1}
            )
        else:
            rows = self._daily(
                "https://archive-api.open-meteo.com/v1/archive",
                {"latitude": loc.lat, "longitude": loc.lon, "start_date": start.isoformat(), "end_date": end.isoformat()},
            )
        wanted = [d for d in rows if start.isoformat() <= d.date <= end.isoformat()]
        if not wanted or all(d.temp_avg is None for d in wanted):
            raise WeatherError("No observations are available for that period.")
        return wanted


class WeatherApiProvider:
    """weatherapi.com. Needs WEATHERAPI_KEY. Free plan: 3-day forecast and ~7 days of history (otherwise falls back)."""

    name = "WeatherAPI.com"
    BASE = "https://api.weatherapi.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, path: str, **params) -> dict:
        try:
            response = requests.get(f"{self.BASE}{path}", params={**params, "key": self.api_key}, timeout=settings.WEATHER_TIMEOUT)
        except requests.Timeout as error:
            raise WeatherError("WeatherAPI.com timed out. Please try again.") from error
        except requests.RequestException as error:
            raise WeatherError("Could not reach WeatherAPI.com: network error.") from error

        if response.ok:
            try:
                return response.json()
            except ValueError as error:
                raise WeatherError("WeatherAPI.com returned an unreadable response.") from error

        try:
            error_body = response.json().get("error", {})
        except ValueError:
            error_body = {}
        code, message = error_body.get("code"), error_body.get("message", f"HTTP {response.status_code}")
        if code == 1006:
            raise WeatherError("Location not found.")
        # Bad key, exceeded quota, or a request outside the plan (e.g. history too far back).
        raise ProviderUnavailable(f"WeatherAPI.com: {message}")

    def geocode(self, city: str) -> Location:
        results = self._get("/search.json", q=city)
        if not results:
            raise WeatherError(f"I couldn't find a place called '{city}'.")
        top = results[0]
        return Location(top["name"], top.get("country", ""), top["lat"], top["lon"])

    @staticmethod
    def _query(loc: Location) -> str:
        return f"{loc.lat},{loc.lon}"

    @staticmethod
    def _day(entry: dict) -> DayWeather:
        day = entry["day"]
        return DayWeather(
            date=entry["date"], temp_min=day["mintemp_c"], temp_max=day["maxtemp_c"], temp_avg=day["avgtemp_c"],
            humidity=day.get("avghumidity"), wind_speed=round(day["maxwind_kph"] / 3.6, 1),
            precipitation=day.get("totalprecip_mm"), condition=day["condition"]["text"],
        )

    def current(self, loc: Location) -> CurrentWeather:
        cur = self._get("/current.json", q=self._query(loc))["current"]
        return CurrentWeather(
            temp=cur["temp_c"], feels_like=cur.get("feelslike_c"), humidity=cur.get("humidity"),
            wind_speed=round(cur["wind_kph"] / 3.6, 1), pressure=cur.get("pressure_mb"),
            condition=cur["condition"]["text"], observed_at=cur["last_updated"],
        )

    def forecast(self, loc: Location, days: int) -> list[DayWeather]:
        data = self._get("/forecast.json", q=self._query(loc), days=min(days + 1, 14))
        today = date.today().isoformat()
        return [self._day(e) for e in data["forecast"]["forecastday"] if e["date"] > today][:days]

    def history(self, loc: Location, start: date, end: date) -> list[DayWeather]:
        days, cursor = [], start
        while cursor <= end:
            data = self._get("/history.json", q=self._query(loc), dt=cursor.isoformat())
            days.append(self._day(data["forecast"]["forecastday"][0]))
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return days


class OpenWeatherMapProvider:
    """Needs OPENWEATHER_API_KEY. Free plan: current + 5-day forecast. History needs the One Call 3.0 subscription."""

    name = "OpenWeatherMap"
    BASE = "https://api.openweathermap.org"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, path: str, **params) -> dict:
        return _get_json(f"{self.BASE}{path}", {**params, "appid": self.api_key, "units": "metric"}, self.name)

    def geocode(self, city: str) -> Location:
        results = self._get("/geo/1.0/direct", q=city, limit=1)
        if not results:
            raise WeatherError(f"I couldn't find a place called '{city}'.")
        top = results[0]
        return Location(top["name"], top.get("country", ""), top["lat"], top["lon"])

    def current(self, loc: Location) -> CurrentWeather:
        d = self._get("/data/2.5/weather", lat=loc.lat, lon=loc.lon)
        return CurrentWeather(
            temp=d["main"]["temp"], feels_like=d["main"].get("feels_like"), humidity=d["main"].get("humidity"),
            wind_speed=d.get("wind", {}).get("speed"), pressure=d["main"].get("pressure"),
            condition=d["weather"][0]["description"].capitalize(),
            observed_at=datetime.fromtimestamp(d["dt"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )

    def forecast(self, loc: Location, days: int) -> list[DayWeather]:
        """Aggregates the free 3-hourly 5-day forecast into daily values."""
        d = self._get("/data/2.5/forecast", lat=loc.lat, lon=loc.lon)
        offset = d.get("city", {}).get("timezone", 0)
        buckets: dict[str, list] = {}
        for item in d["list"]:
            local_day = datetime.fromtimestamp(item["dt"] + offset, tz=timezone.utc).date().isoformat()
            buckets.setdefault(local_day, []).append(item)

        today = date.today().isoformat()
        result = []
        for day in sorted(buckets):
            if day <= today:
                continue
            items = buckets[day]
            temps = [i["main"]["temp"] for i in items]
            result.append(
                DayWeather(
                    date=day, temp_min=round(min(i["main"]["temp_min"] for i in items), 1),
                    temp_max=round(max(i["main"]["temp_max"] for i in items), 1), temp_avg=round(sum(temps) / len(temps), 1),
                    humidity=_avg([i["main"].get("humidity") for i in items]),
                    wind_speed=round(max(i.get("wind", {}).get("speed", 0) for i in items), 1),
                    precipitation=round(sum(i.get("rain", {}).get("3h", 0) + i.get("snow", {}).get("3h", 0) for i in items), 1),
                    condition=Counter(i["weather"][0]["description"].capitalize() for i in items).most_common(1)[0][0],
                )
            )
        return result[:days]

    def history(self, loc: Location, start: date, end: date) -> list[DayWeather]:
        days, cursor = [], start
        while cursor <= end:
            d = self._get("/data/3.0/onecall/day_summary", lat=loc.lat, lon=loc.lon, date=cursor.isoformat())
            temp = d.get("temperature", {})
            days.append(
                DayWeather(
                    date=cursor.isoformat(), temp_min=temp.get("min"), temp_max=temp.get("max"),
                    temp_avg=_avg([temp.get(k) for k in ("morning", "afternoon", "evening", "night")]),
                    humidity=d.get("humidity", {}).get("afternoon"), wind_speed=d.get("wind", {}).get("max", {}).get("speed"),
                    precipitation=d.get("precipitation", {}).get("total", 0), condition="Unknown",
                )
            )
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return days

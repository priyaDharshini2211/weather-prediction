from dataclasses import asdict, dataclass
from typing import Optional


class WeatherError(Exception):
    """User-presentable weather failure (unknown city, data unavailable, ...)."""


class ProviderUnavailable(WeatherError):
    """A provider cannot serve this request (e.g. plan limitation); another provider may."""


@dataclass
class Location:
    name: str
    country: str
    lat: float
    lon: float

    @property
    def label(self) -> str:
        return f"{self.name}, {self.country}" if self.country else self.name


@dataclass
class DayWeather:
    date: str  # YYYY-MM-DD
    temp_min: Optional[float]
    temp_max: Optional[float]
    temp_avg: Optional[float]
    humidity: Optional[float]
    wind_speed: Optional[float]  # m/s
    precipitation: Optional[float]  # mm
    condition: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CurrentWeather:
    temp: float
    feels_like: Optional[float]
    humidity: Optional[float]
    wind_speed: Optional[float]
    pressure: Optional[float]
    condition: str
    observed_at: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class WeatherResult:
    """Data plus provenance, so the UI/LLM can state exactly where numbers came from."""

    data: object
    source: str
    notes: list

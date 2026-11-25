from datetime import date, timedelta

import pytest

from agents.weather import agent as weather_agent
from agents.weather import presentation
from agents.weather.models import CurrentWeather, DayWeather, Location, WeatherError, WeatherResult
from agents.weather.service import WeatherService


def make_days(n: int) -> list[DayWeather]:
    start = date.today() - timedelta(days=n)
    return [
        DayWeather((start + timedelta(days=i)).isoformat(), 24.0, 32.0 + i, 28.0 + i, 70.0, 3.5, 2.0 if i % 2 else 0.0, "Rain" if i % 2 else "Clear sky")
        for i in range(n)
    ]


class FakeService:
    def __init__(self):
        self.loc = Location("Chennai", "IN", 13.08, 80.27)

    def locate(self, city):
        if city == "Nowhereville":
            raise WeatherError("I couldn't find a place called 'Nowhereville'.")
        return WeatherResult(self.loc, "FakeProvider", [])

    def current(self, loc):
        return WeatherResult(CurrentWeather(31.0, 35.0, 70, 4.1, 1008, "Haze", "2026-01-01 10:00"), "FakeProvider", [])

    def history(self, loc, start, end):
        days = make_days((end - start).days + 1)
        return WeatherResult(days, "FakeProvider", ["history note"])

    def forecast(self, loc, days):
        return WeatherResult(make_days(days), "FakeProvider", [])


@pytest.fixture(autouse=True)
def no_real_summary(monkeypatch):
    monkeypatch.setattr(weather_agent, "chat", lambda *a, **k: "Summary text.")


def plan(monkeypatch, **fields):
    base = {"intent": "current", "city": "Chennai", "offset_days": None, "explicit_date": None, "num_days": None, "wants": []}
    monkeypatch.setattr(weather_agent, "chat_json", lambda *a, **k: {**base, **fields})


def test_last_10_days_returns_table_and_charts_from_real_rows(monkeypatch):
    plan(monkeypatch, intent="last_days", num_days=10)
    result = weather_agent.run_weather_agent("last 10 days in Chennai", [], FakeService())

    table = next(b for b in result["blocks"] if b["type"] == "table")
    assert len(table["rows"]) == 10
    charts = {b["chart"] for b in result["blocks"] if b["type"] == "chart"}
    assert charts == {"line", "bar", "pie"}
    line = next(b for b in result["blocks"] if b["type"] == "chart" and b["chart"] == "line")
    assert [p["date"] for p in line["data"]] == [row[0] for row in table["rows"]]  # charts use the same data as the table


def test_explicit_chart_request_is_respected(monkeypatch):
    plan(monkeypatch, intent="last_days", num_days=10, wants=["pie"])
    result = weather_agent.run_weather_agent("pie chart of conditions", [], FakeService())
    assert [b["chart"] for b in result["blocks"] if b["type"] == "chart"] == ["pie"]


def test_current_weather_shows_metrics_not_charts(monkeypatch):
    plan(monkeypatch, intent="current")
    result = weather_agent.run_weather_agent("weather in Chennai", [], FakeService())
    assert result["blocks"][0]["type"] == "metrics"
    assert not any(b["type"] == "chart" for b in result["blocks"])


def test_missing_city_asks_for_clarification(monkeypatch):
    plan(monkeypatch, intent="current", city=None)
    result = weather_agent.run_weather_agent("what's the weather?", [], FakeService())
    assert "city" in result["answer"].lower()
    assert result["blocks"] == []


def test_unknown_city_returns_clear_error_not_data(monkeypatch):
    plan(monkeypatch, intent="current", city="Nowhereville")
    result = weather_agent.run_weather_agent("weather in Nowhereville", [], FakeService())
    assert "couldn't find" in result["answer"]
    assert result["blocks"][0]["type"] == "notice"


def test_forecast_for_past_date_is_rejected(monkeypatch):
    plan(monkeypatch, intent="forecast", offset_days=-2)
    result = weather_agent.run_weather_agent("forecast", [], FakeService())
    assert "future" in result["answer"]


def test_service_refuses_history_for_today_or_future():
    service = WeatherService(providers=[])
    with pytest.raises(WeatherError):
        service.history(Location("X", "", 0, 0), date.today(), date.today())


def test_service_falls_back_and_explains_when_owm_history_is_not_on_plan():
    from agents.weather.models import ProviderUnavailable

    class DeniedOWM:
        name = "OpenWeatherMap"

        def history(self, *a):
            raise ProviderUnavailable("plan limitation")

    class OpenMeteo:
        name = "Open-Meteo"

        def history(self, *a):
            return make_days(2)

    service = WeatherService(providers=[DeniedOWM(), OpenMeteo()])
    yesterday = date.today() - timedelta(days=1)
    result = service.history(Location("X", "", 0, 0), yesterday - timedelta(days=1), yesterday)
    assert result.source == "Open-Meteo"
    assert any("plan limitation" in n for n in result.notes)


def test_pie_chart_counts_conditions():
    pie = presentation._pie_chart(make_days(4))
    assert {d["name"]: d["value"] for d in pie["data"]} == {"Rain": 2, "Clear sky": 2}


def test_fallback_summary_is_computed_from_data():
    days = [d.as_dict() for d in make_days(3)]
    text = weather_agent._fallback_summary("last_days", "Chennai, India", days)
    assert "3 days" in text and "Warmest day" in text and "Rain recorded on 1 of 3 days" in text

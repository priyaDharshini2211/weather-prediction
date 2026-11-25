"""Turns real weather data into UI blocks (metrics / table / charts). Charts are built ONLY from returned data."""
from collections import Counter

from .models import CurrentWeather, DayWeather

CHART_TYPES = ("line", "bar", "pie")


def _fmt(value, unit: str = "") -> str:
    return "n/a" if value is None else f"{value}{unit}"


def current_blocks(location_label: str, w: CurrentWeather) -> list[dict]:
    return [
        {
            "type": "metrics",
            "title": f"Current weather in {location_label}",
            "items": [
                {"label": "Condition", "value": w.condition},
                {"label": "Temperature", "value": _fmt(w.temp, " °C")},
                {"label": "Feels like", "value": _fmt(w.feels_like, " °C")},
                {"label": "Humidity", "value": _fmt(w.humidity, " %")},
                {"label": "Wind", "value": _fmt(w.wind_speed, " m/s")},
                {"label": "Pressure", "value": _fmt(w.pressure, " hPa")},
            ],
        }
    ]


def day_metrics_block(location_label: str, day: DayWeather, title_prefix: str) -> dict:
    return {
        "type": "metrics",
        "title": f"{title_prefix} in {location_label} ({day.date})",
        "items": [
            {"label": "Condition", "value": day.condition},
            {"label": "Min / Max", "value": f"{_fmt(day.temp_min)} / {_fmt(day.temp_max)} °C"},
            {"label": "Average temp", "value": _fmt(day.temp_avg, " °C")},
            {"label": "Humidity", "value": _fmt(day.humidity, " %")},
            {"label": "Wind (max)", "value": _fmt(day.wind_speed, " m/s")},
            {"label": "Precipitation", "value": _fmt(day.precipitation, " mm")},
        ],
    }


def table_block(days: list[DayWeather], title: str) -> dict:
    return {
        "type": "table",
        "title": title,
        "columns": ["Date", "Condition", "Min °C", "Max °C", "Avg °C", "Humidity %", "Wind m/s", "Rain mm"],
        "rows": [
            [d.date, d.condition, d.temp_min, d.temp_max, d.temp_avg, d.humidity, d.wind_speed, d.precipitation]
            for d in days
        ],
    }


def _line_chart(days: list[DayWeather]) -> dict:
    return {
        "type": "chart", "chart": "line", "title": "Temperature trend (°C)", "x_key": "date", "unit": "°C",
        "series": [{"key": "max", "label": "Max"}, {"key": "avg", "label": "Average"}, {"key": "min", "label": "Min"}],
        "data": [{"date": d.date, "max": d.temp_max, "avg": d.temp_avg, "min": d.temp_min} for d in days],
    }


def _bar_chart(days: list[DayWeather], metric: str = "precipitation") -> dict:
    labels = {
        "precipitation": ("Daily precipitation (mm)", "Rain mm", "mm"),
        "humidity": ("Average humidity (%)", "Humidity %", "%"),
        "wind": ("Maximum wind speed (m/s)", "Wind m/s", "m/s"),
    }
    title, label, unit = labels[metric]
    attribute = {"precipitation": "precipitation", "humidity": "humidity", "wind": "wind_speed"}[metric]
    return {
        "type": "chart", "chart": "bar", "title": title, "x_key": "date", "unit": unit,
        "series": [{"key": "value", "label": label}],
        "data": [{"date": d.date, "value": getattr(d, attribute)} for d in days],
    }


def _pie_chart(days: list[DayWeather]) -> dict:
    counts = Counter(d.condition for d in days)
    return {
        "type": "chart", "chart": "pie", "title": "Weather conditions (number of days)", "x_key": "name", "unit": "days",
        "series": [{"key": "value", "label": "Days"}],
        "data": [{"name": name, "value": count} for name, count in counts.most_common()],
    }


def multi_day_blocks(days: list[DayWeather], title: str, wants: list[str], include_pie_by_default: bool) -> list[dict]:
    """Pick formats from the question: explicit requests win; otherwise sensible defaults for the data shape."""
    wants = [w for w in wants if w in CHART_TYPES or w == "table"]
    blocks = [table_block(days, title)]  # a table is always shown for multi-day results

    has_rain = any((d.precipitation or 0) > 0 for d in days)
    if not wants:
        wants = ["line", "bar"] + (["pie"] if include_pie_by_default else [])

    if "line" in wants:
        blocks.append(_line_chart(days))
    if "bar" in wants:
        blocks.append(_bar_chart(days, "precipitation" if has_rain else "humidity"))
    if "pie" in wants:
        blocks.append(_pie_chart(days))
    return blocks

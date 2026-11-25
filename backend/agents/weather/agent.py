"""Weather Intelligence agent.

Flow:  LLM plans the request (intent, city, dates)  ->  tools fetch REAL data  ->  presentation builds table/charts
       ->  LLM writes a short summary grounded ONLY in the fetched data.
"""
import json
import logging
from datetime import date, timedelta

from ..llm import LLMError, chat, chat_json
from . import presentation
from .models import WeatherError
from .service import WeatherService

logger = logging.getLogger(__name__)

PLAN_PROMPT = """You extract a structured weather request from the user's message. Today's date is {today}.

Return ONLY JSON with these keys:
- "intent": one of
    "current"   - weather right now / today
    "historical"- one specific past day (yesterday, a given date)
    "forecast"  - future weather (tomorrow, a given future date, next N days)
    "last_days" - a range of past days (e.g. "last 10 days", "past week")
    "clarify"   - the city is missing/unclear and cannot be inferred from the conversation
- "city": the place name only (e.g. "Chennai"), or null
- "offset_days": integer days from today for single-day questions (yesterday=-1, today=0, tomorrow=1), else null
- "explicit_date": "YYYY-MM-DD" only if the user gave a calendar date, else null
- "num_days": number of days for ranges ("last 10 days" -> 10, "next 5 days" -> 5), else null
- "wants": list of requested formats among "table","line","bar","pie" (e.g. user asks for a pie chart -> ["pie"]); [] if unspecified
- "clarification": a short question to ask the user when intent is "clarify", else null

Use earlier conversation turns to fill in a missing city (e.g. "and tomorrow?")."""

SUMMARY_PROMPT = """You are a weather assistant. Write a concise (2-4 sentences) plain-language answer to the user's question
using ONLY the JSON data provided. Quote numbers exactly as given. Do not add facts, causes or numbers that are not in the data.
For ranges mention the overall trend (warmest/coolest day, rainy days) only if visible in the data. Temperatures are in °C,
wind in m/s, rain in mm."""


def _plan(message: str, history: list[dict]) -> dict:
    messages = [{"role": "system", "content": PLAN_PROMPT.format(today=date.today().isoformat())}]
    messages += [{"role": m["role"], "content": m["content"][:300]} for m in history[-4:]]
    messages.append({"role": "user", "content": message})
    plan = chat_json(messages, max_tokens=300)

    plan["intent"] = str(plan.get("intent", "")).lower()
    if plan["intent"] not in {"current", "historical", "forecast", "last_days", "clarify"}:
        raise LLMError(f"unknown weather intent {plan['intent']!r}")
    if not plan.get("city") and plan["intent"] != "clarify":
        plan["intent"] = "clarify"
        plan["clarification"] = plan.get("clarification") or "Which city would you like the weather for?"
    for key in ("offset_days", "num_days"):
        try:
            plan[key] = int(plan[key]) if plan.get(key) is not None else None
        except (TypeError, ValueError):
            plan[key] = None
    plan["wants"] = [w for w in (plan.get("wants") or []) if isinstance(w, str)]
    return plan


def _target_date(plan: dict, default_offset: int) -> date:
    if plan.get("explicit_date"):
        try:
            return date.fromisoformat(plan["explicit_date"])
        except ValueError as error:
            raise WeatherError(f"I couldn't understand the date '{plan['explicit_date']}'.") from error
    offset = plan["offset_days"] if plan.get("offset_days") is not None else default_offset
    return date.today() + timedelta(days=offset)


def _summarise(question: str, location_label: str, payload) -> str | None:
    try:
        return chat(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": f"Question: {question}\nLocation: {location_label}\nData: {json.dumps(payload)}"},
            ],
            temperature=0.1,
            max_tokens=250,
        )
    except LLMError:
        logger.warning("Summary generation failed; falling back to data-only answer", exc_info=True)
        return None


def _fallback_summary(intent: str, location_label: str, payload) -> str:
    """Deterministic summary computed from the data, used when the LLM is unavailable (still fully grounded)."""
    if isinstance(payload, list) and payload:
        highs = [d for d in payload if d["temp_max"] is not None]
        parts = [f"{len(payload)} days of weather for {location_label} ({payload[0]['date']} to {payload[-1]['date']})."]
        if highs:
            hottest = max(highs, key=lambda d: d["temp_max"])
            coolest = min((d for d in payload if d["temp_min"] is not None), key=lambda d: d["temp_min"], default=None)
            parts.append(f"Warmest day: {hottest['date']} ({hottest['temp_max']} °C).")
            if coolest:
                parts.append(f"Coolest night: {coolest['date']} ({coolest['temp_min']} °C).")
        rainy = [d for d in payload if (d["precipitation"] or 0) > 0]
        parts.append(f"Rain recorded on {len(rainy)} of {len(payload)} days.")
        return " ".join(parts)
    if isinstance(payload, dict) and "temp" in payload:
        return f"It is currently {payload['temp']} °C in {location_label} ({payload['condition']})."
    if isinstance(payload, dict):
        return f"{payload['date']} in {location_label}: {payload['condition']}, {payload['temp_min']}–{payload['temp_max']} °C."
    return f"Here is the {intent.replace('_', ' ')} weather data for {location_label}."


def _notice(text: str, level: str = "info") -> dict:
    return {"type": "notice", "level": level, "text": text}


def _source_block(source: str, notes: list[str]) -> list[dict]:
    blocks = [{"type": "sources", "title": "Data source", "items": [{"title": source, "url": "", "snippet": "Weather data provider"}]}]
    blocks += [_notice(note) for note in notes]
    return blocks


def _result(answer: str, blocks: list[dict], trace: list[dict]) -> dict:
    return {"agent": "weather", "answer": answer, "blocks": blocks, "tool_trace": trace}


def run_weather_agent(message: str, history: list[dict], service: WeatherService | None = None) -> dict:
    service = service or WeatherService()
    plan = _plan(message, history)
    trace = [{"step": "plan", "plan": {k: plan.get(k) for k in ("intent", "city", "offset_days", "explicit_date", "num_days", "wants")}}]

    if plan["intent"] == "clarify":
        return _result(plan.get("clarification") or "Which city would you like the weather for?", [], trace)

    try:
        located = service.locate(plan["city"])
        loc = located.data
        notes = list(located.notes)
        trace.append({"step": "tool:geocode", "city": plan["city"], "resolved": loc.label, "provider": located.source})

        if plan["intent"] == "current":
            weather = service.current(loc)
            blocks = presentation.current_blocks(loc.label, weather.data)
            payload = weather.data.as_dict()
            trace.append({"step": "tool:current_weather", "provider": weather.source})
        elif plan["intent"] == "historical":
            day = _target_date(plan, default_offset=-1)
            weather = service.history(loc, day, day)
            blocks = [presentation.day_metrics_block(loc.label, weather.data[0], "Weather")]
            payload = weather.data[0].as_dict()
            trace.append({"step": "tool:historical_weather", "date": day.isoformat(), "provider": weather.source})
        elif plan["intent"] == "last_days":
            count = plan.get("num_days") or 10
            end = date.today() - timedelta(days=1)
            weather = service.history(loc, end - timedelta(days=count - 1), end)
            blocks = presentation.multi_day_blocks(weather.data, f"Last {count} days in {loc.label}", plan["wants"], include_pie_by_default=True)
            payload = [d.as_dict() for d in weather.data]
            trace.append({"step": "tool:historical_weather", "days": count, "provider": weather.source})
        else:  # forecast
            if plan.get("num_days") and plan["num_days"] > 1:
                weather = service.forecast(loc, plan["num_days"])
                blocks = presentation.multi_day_blocks(weather.data, f"{plan['num_days']}-day forecast for {loc.label}", plan["wants"], include_pie_by_default=False)
                payload = [d.as_dict() for d in weather.data]
            else:
                day = _target_date(plan, default_offset=1)
                ahead = (day - date.today()).days
                if ahead < 1:
                    raise WeatherError("A forecast needs a future date. Ask for 'current' weather or past days instead.")
                weather = service.forecast(loc, ahead)
                match = next((d for d in weather.data if d.date == day.isoformat()), None)
                if match is None:
                    raise WeatherError(f"No forecast is available for {day.isoformat()}.")
                blocks = [presentation.day_metrics_block(loc.label, match, "Forecast")]
                payload = match.as_dict()
            trace.append({"step": "tool:forecast", "provider": weather.source})
    except WeatherError as error:
        trace.append({"step": "error", "message": str(error)})
        return _result(f"⚠️ {error}", [_notice(str(error), "warning")], trace)

    notes = list(dict.fromkeys(notes + weather.notes))  # de-duplicate repeated provider notes
    answer = _summarise(message, loc.label, payload)
    if answer is None:
        answer = _fallback_summary(plan["intent"], loc.label, payload)
    return _result(answer, blocks + _source_block(weather.source, notes), trace)

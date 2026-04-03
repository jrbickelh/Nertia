"""
Weather tool — uses Open-Meteo (free, no API key).
Lat/lon stored in profile as weather_lat / weather_lon.
"""
from typing import Any
import httpx
from claude_agent_sdk import tool
from db.database import execute

_DEFAULT_LAT = 30.2672   # Austin, TX — update via update_preference
_DEFAULT_LON = -97.7431

_WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Rain showers", 82: "Heavy rain showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}


@tool(
    "get_weather",
    "Get current conditions and today's hourly forecast. Used to adjust outdoor exercise scheduling.",
    {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD (defaults to today)"},
        },
        "required": [],
    },
)
async def get_weather(args: dict[str, Any]) -> dict[str, Any]:
    try:
        profile = await execute("SELECT key, value FROM profile WHERE key IN ('weather_lat','weather_lon')")
        pmap = {r["key"]: float(r["value"]) for r in profile}
        lat = pmap.get("weather_lat", _DEFAULT_LAT)
        lon = pmap.get("weather_lon", _DEFAULT_LON)

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,precipitation,weathercode,windspeed_10m,relativehumidity_2m"
            f"&hourly=temperature_2m,precipitation_probability,weathercode,windspeed_10m"
            f"&temperature_unit=fahrenheit&windspeed_unit=mph&precipitation_unit=inch"
            f"&forecast_days=1&timezone=auto"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        cur = data["current"]
        cond = _WMO.get(cur["weathercode"], f"Code {cur['weathercode']}")
        lines = [
            f"Current: {cur['temperature_2m']}°F (feels {cur['apparent_temperature']}°F), {cond}",
            f"Wind: {cur['windspeed_10m']} mph  Humidity: {cur['relativehumidity_2m']}%",
            f"Precipitation: {cur['precipitation']} in",
            "",
            "Hourly forecast:",
        ]

        hours = data["hourly"]
        for i, h in enumerate(hours["time"]):
            hour = h[11:16]
            if hour < "06:00" or hour > "21:00":
                continue
            t = hours["temperature_2m"][i]
            pop = hours["precipitation_probability"][i]
            wc = _WMO.get(hours["weathercode"][i], "?")
            wind = hours["windspeed_10m"][i]
            lines.append(f"  {hour}  {t}°F  {wc}  rain:{pop}%  wind:{wind}mph")

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Weather error: {e}"}]}


ALL_WEATHER_TOOLS = [get_weather]

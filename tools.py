from langchain_tavily import TavilySearch
from langchain_core.tools import tool
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import ast
import operator
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# Web Search
# -------------------------

_search_tool = TavilySearch(
    max_results=5,
    topic="general",
)

@tool
def web_search(query: str) -> str:
    """Search the web for current information using Tavily."""
    result = _search_tool.invoke({"query": query})
    return result


# -------------------------
# Core email sender (plain function, not a @tool)
# Registered in TASK_REGISTRY so schedule_task can call it.
# -------------------------

def _send_email_fn(to: str, subject: str, body: str) -> str:
    """Internal email sender used both by send_email tool and the scheduler."""
    sender_email = os.getenv("EMAIL_ADDRESS")
    sender_password = os.getenv("EMAIL_PASSWORD")

    if not sender_email or not sender_password:
        print("❌ EMAIL_ADDRESS or EMAIL_PASSWORD not set.")
        return "Error: EMAIL_ADDRESS or EMAIL_PASSWORD environment variables not set."

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print(f"✅ Scheduled email sent to {to}")
        return f"✅ Email sent to {to} with subject '{subject}'"
    except Exception as e:
        print(f"❌ Scheduled email failed: {e}")
        return f"❌ Failed to send email: {e}"


# -------------------------
# Send Email tool (immediate)
# -------------------------

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the specified recipient immediately."""
    return _send_email_fn(to=to, subject=subject, body=body)


# -------------------------
# Task Scheduler
# -------------------------

scheduler = BackgroundScheduler()
scheduler.start()

# Pre-register all built-in schedulable actions here.
# Any plain Python function can be added to this dict.
TASK_REGISTRY: dict = {
    "send_email": _send_email_fn,
}


def register_task(name: str, func):
    """Register a custom function so it can be scheduled by name."""
    TASK_REGISTRY[name] = func


@tool
def schedule_task(
    task_name: str,
    action: str,
    trigger_type: str = "interval",
    minutes: int = 0,
    seconds: int = 0,
    hours: int = 0,
    run_date: str = "",
    to: str = "",
    subject: str = "",
    body: str = "",
) -> str:
    """
    Schedule a built-in action to run in the future.

    Args:
        task_name:    Unique job ID (e.g. 'weather_email_job').
        action:       One of the registered actions: send_email.
        trigger_type: 'interval' to repeat, 'date' for one-shot, 'cron' for cron schedule.
        minutes:      Delay in minutes (for interval/date triggers).
        seconds:      Delay in seconds (for interval/date triggers).
        hours:        Delay in hours (for interval/date triggers).
        run_date:     ISO datetime string for 'date' trigger (e.g. '2024-06-01 09:00:00').
        to:           For send_email — recipient address.
        subject:      For send_email — email subject.
        body:         For send_email — email body text.

    Examples:
        Send an email in 5 minutes:
            action='send_email', trigger_type='date', minutes=5,
            to='x@example.com', subject='Hello', body='...'

        Send an email every hour:
            action='send_email', trigger_type='interval', hours=1,
            to='x@example.com', subject='Hourly update', body='...'
    """
    if action not in TASK_REGISTRY:
        return (
            f"❌ Action '{action}' is not registered. "
            f"Available actions: {list(TASK_REGISTRY.keys())}"
        )

    func = TASK_REGISTRY[action]

    # Build kwargs from the inline args (only non-empty values)
    func_kwargs: dict = {}
    if action == "send_email":
        if not to:
            return "❌ 'to' (recipient email) is required for send_email action."
        func_kwargs = {"to": to, "subject": subject, "body": body}

    # Remove existing job if rescheduling
    if scheduler.get_job(task_name):
        scheduler.remove_job(task_name)

    # Build APScheduler trigger kwargs
    trigger_kwargs: dict = {}

    if trigger_type == "date":
        if run_date:
            trigger_kwargs["run_date"] = run_date
        else:
            # Calculate future run_date from delay offsets
            from datetime import datetime, timedelta
            delta = timedelta(hours=hours, minutes=minutes, seconds=seconds)
            if delta.total_seconds() == 0:
                delta = timedelta(minutes=1)   # default: 1 minute
            trigger_kwargs["run_date"] = datetime.now() + delta

    elif trigger_type == "interval":
        if hours:   trigger_kwargs["hours"]   = hours
        if minutes: trigger_kwargs["minutes"] = minutes
        if seconds: trigger_kwargs["seconds"] = seconds
        if not trigger_kwargs:
            trigger_kwargs["minutes"] = 1    # default: every 1 minute

    scheduler.add_job(
        func,
        trigger=trigger_type,
        id=task_name,
        kwargs=func_kwargs,
        **trigger_kwargs,
    )

    # Human-readable confirmation
    delay_parts = []
    if hours:   delay_parts.append(f"{hours}h")
    if minutes: delay_parts.append(f"{minutes}m")
    if seconds: delay_parts.append(f"{seconds}s")
    delay_str = " ".join(delay_parts) if delay_parts else "soon"

    return (
        f"⏰ '{task_name}' scheduled!\n"
        f"  Action: {action}\n"
        f"  Trigger: {trigger_type}\n"
        f"  Runs in: {delay_str}\n"
        + (f"  To: {to}\n  Subject: {subject}" if action == "send_email" else "")
    )


# -------------------------
# Weather
# -------------------------

@tool
def get_weather(location: str) -> str:
    """
    Get current weather for a city or location using Open-Meteo (no API key needed).
    First geocodes the location, then fetches weather data.
    """
    try:
        # Geocode
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(location)}&count=1"
        geo_resp = requests.get(geo_url, timeout=10)
        geo_data = geo_resp.json()

        if not geo_data.get("results"):
            return f"❌ Could not find location: {location}"

        place = geo_data["results"][0]
        lat, lon = place["latitude"], place["longitude"]
        name = place.get("name", location)
        country = place.get("country", "")

        # Fetch weather
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m,relative_humidity_2m"
            f"&temperature_unit=celsius"
        )
        w_resp = requests.get(weather_url, timeout=10)
        w_data = w_resp.json()
        current = w_data.get("current", {})

        temp = current.get("temperature_2m", "N/A")
        wind = current.get("windspeed_10m", "N/A")
        humidity = current.get("relative_humidity_2m", "N/A")
        code = current.get("weathercode", 0)

        # Simple WMO code mapping
        wmo_map = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Foggy", 48: "Icy fog", 51: "Light drizzle", 61: "Slight rain",
            63: "Moderate rain", 65: "Heavy rain", 71: "Slight snow", 73: "Moderate snow",
            80: "Rain showers", 95: "Thunderstorm",
        }
        condition = wmo_map.get(code, f"Code {code}")

        return (
            f"🌤 Weather in {name}, {country}:\n"
            f"  Condition: {condition}\n"
            f"  Temperature: {temp}°C\n"
            f"  Wind speed: {wind} km/h\n"
            f"  Humidity: {humidity}%"
        )
    except Exception as e:
        return f"❌ Weather fetch failed: {e}"


# -------------------------
# Summarize URL
# -------------------------

@tool
def summarize_url(url: str) -> str:
    """
    Fetch the text content of a webpage URL and return a plain-text summary
    of the first ~2000 characters. Useful for reading articles or docs.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        # Strip HTML tags very simply
        from html.parser import HTMLParser

        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "footer"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "footer"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    stripped = data.strip()
                    if stripped:
                        self.text_parts.append(stripped)

        parser = _TextExtractor()
        parser.feed(resp.text)
        text = " ".join(parser.text_parts)[:3000]

        return f"📄 Content from {url}:\n\n{text}..."
    except Exception as e:
        return f"❌ Failed to fetch URL: {e}"


# -------------------------
# Calculator
# -------------------------

# Allowed AST node types for safe evaluation
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.FloorDiv, ast.USub, ast.UAdd,
)

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    else:
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")


@tool
def calculate(expression: str) -> str:
    """
    Safely evaluate a math expression and return the result.
    Supports +, -, *, /, **, %, //. Example: '(3 + 5) * 2 / 4'
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree)
        return f"🧮 {expression} = {result}"
    except ZeroDivisionError:
        return "❌ Division by zero."
    except Exception as e:
        return f"❌ Could not evaluate '{expression}': {e}"
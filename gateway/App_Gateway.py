import logging
import math
import os
import re
import sys
import threading
import time
from collections import OrderedDict, deque

import jwt
import requests
from dotenv import load_dotenv
from flask import Flask, g, request, Response, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

# Loads the local, git-ignored .env file (JWT_SECRET, ORS_API_KEY, ...).
load_dotenv()


class RedactQueryStringFilter(logging.Filter):
    """Hides URL query strings in access logs.

    /directions requests carry the visitor's coordinates, and the proposal commits to
    not keeping any location history on the server.
    """

    _query = re.compile(r"(?<=\s)(/[^\s?]*)\?\S*")

    def filter(self, record):
        record.msg = self._query.sub(r"\1?[redacted]", record.getMessage())
        record.args = ()
        return True


logging.getLogger("werkzeug").addFilter(RedactQueryStringFilter())

# The gateway serves no static files, so the default /static route is disabled.
app = Flask(__name__, static_folder=None)

# Every JSON body the API accepts is tiny; reject anything larger before forwarding.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


def trusted_proxy_count():
    """How many reverse proxies (e.g. a cloud host) sit in front of the gateway."""
    try:
        return max(0, int(os.environ.get("TRUSTED_PROXY_COUNT", "0")))
    except ValueError:
        return 0


# Only trust X-Forwarded-For when told how many proxies to trust (default: none).
if trusted_proxy_count() > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_count())

SERVICE_A_URL = os.environ.get(
    "SANIMAP_REGISTRY_URL", "http://127.0.0.1:5001"
).rstrip("/")
SERVICE_B_URL = os.environ.get(
    "SANIMAP_REPORTING_URL", "http://127.0.0.1:5002"
).rstrip("/")
TIMEOUT_SECONDS = 5

# Methods the gateway is willing to forward to a backend service.
FORWARDED_METHODS = {"GET", "POST", "PUT"}

JWT_ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32

# OpenRouteService (ORS) directions. The key is read from ORS_API_KEY at request time.
ORS_DEFAULT_BASE_URL = "https://api.heigit.org/openrouteservice/v2"
ORS_TIMEOUT_SECONDS = 10
ORS_ATTRIBUTION = "openrouteservice.org | OpenStreetMap contributors"
DEFAULT_PROFILE = "foot-walking"
SUPPORTED_PROFILES = ("foot-walking",)

# Nominatim public service: direct user searches only, at most one upstream
# request per second, with a short-lived in-memory cache.
NOMINATIM_DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org"
NOMINATIM_TIMEOUT_SECONDS = 5
NOMINATIM_MIN_INTERVAL_SECONDS = 1.0
NOMINATIM_CACHE_TTL_SECONDS = 3600
NOMINATIM_CACHE_MAX_ENTRIES = 128
NOMINATIM_ATTRIBUTION = "OpenStreetMap contributors"

# Rate limits per rolling window: name -> (max per client IP, max across all clients).
# The directions total stays below ORS's free Standard limit of 40 requests/minute.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMITS = {
    "directions": (10, 30),
    "feedback": (5, None),
    "geocoding": (5, None),
}
RATE_LIMITED_ROUTES = {
    ("GET", "/directions"): "directions",
    ("GET", "/geocode"): "geocoding",
    ("GET", "/reverse-geocode"): "geocoding",
    ("POST", "/feedback"): "feedback",
}

# Access policy (default deny): every gateway route must be listed here.
#   None  -> public, no token needed
#   tuple -> a valid Bearer token whose "role" claim is one of these roles
PUBLIC = None
ADMIN = ("admin",)
STAFF = ("admin", "park_manager")

ROUTE_POLICY = {
    ("GET", "/health"): PUBLIC,
    ("GET", "/auth/verify"): STAFF,
    ("GET", "/directions"): PUBLIC,
    ("GET", "/geocode"): PUBLIC,
    ("GET", "/reverse-geocode"): PUBLIC,
    ("GET", "/health/all"): STAFF,
    ("GET", "/restrooms"): PUBLIC,
    ("POST", "/restrooms"): ADMIN,
    ("GET", "/restrooms/<int:restroom_id>"): PUBLIC,
    ("PUT", "/restrooms/<int:restroom_id>/status"): ADMIN,
    ("POST", "/feedback"): PUBLIC,
    ("GET", "/feedback"): STAFF,
    ("GET", "/feedback/<int:restroom_id>"): STAFF,
    ("GET", "/feedback/reports/<int:report_id>"): PUBLIC,
    ("PUT", "/feedback/reports/<int:report_id>/status"): STAFF,
}



def jwt_settings():
    return {
        "secret": os.environ.get("JWT_SECRET", ""),
        "issuer": os.environ.get("JWT_ISSUER", ""),
        "audience": os.environ.get("JWT_AUDIENCE", ""),
    }


def config_problems():
    """Return a list of security configuration problems (empty list = OK)."""
    settings = jwt_settings()
    problems = []
    if len(settings["secret"]) < MIN_SECRET_LENGTH:
        problems.append(
            f"JWT_SECRET must be set and at least {MIN_SECRET_LENGTH} characters long."
        )
    if not settings["issuer"]:
        problems.append("JWT_ISSUER must be set.")
    if not settings["audience"]:
        problems.append("JWT_AUDIENCE must be set.")
    return problems


class SlidingWindowLimiter:
    """Small in-memory rolling-window rate limiter (resets when the gateway restarts)."""

    def __init__(self, window_seconds, clock=time.monotonic):
        self.window = window_seconds
        self.clock = clock
        self._hits = {}
        self._lock = threading.Lock()
        self._calls = 0

    def reset(self):
        with self._lock:
            self._hits.clear()

    def allow(self, checks):
        """checks is a list of (key, max_requests).

        A hit is recorded for every key only when all keys are under their limit.
        Returns (allowed, retry_after_seconds).
        """
        with self._lock:
            now = self.clock()
            cutoff = now - self.window
            self._calls += 1
            if self._calls % 500 == 0:
                self._sweep(cutoff)

            blocked = False
            retry_after = 0
            for key, limit in checks:
                hits = self._hits.setdefault(key, deque())
                while hits and hits[0] <= cutoff:
                    hits.popleft()
                if len(hits) >= limit:
                    blocked = True
                    retry_after = max(retry_after, int(hits[0] + self.window - now) + 1)
            if blocked:
                return False, retry_after

            for key, _limit in checks:
                self._hits[key].append(now)
            return True, 0

    def _sweep(self, cutoff):
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


limiter = SlidingWindowLimiter(RATE_LIMIT_WINDOW_SECONDS)


def reset_rate_limits():
    limiter.reset()


def apply_rate_limit(policy_key):
    name = RATE_LIMITED_ROUTES.get(policy_key)
    if name is None:
        return None

    per_client, overall = RATE_LIMITS[name]
    checks = [(f"{name}:ip:{request.remote_addr}", per_client)]
    if overall is not None:
        checks.append((f"{name}:all", overall))

    allowed, retry_after = limiter.allow(checks)
    if allowed:
        return None

    response = jsonify({
        "error": "RATE_LIMITED",
        "message": "Too many requests. Please try again later.",
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def auth_error(code, message, status):
    response = jsonify({"error": code, "message": message})
    response.status_code = status
    if status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def get_bearer_token():
    parts = request.headers.get("Authorization", "").split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


@app.before_request
def enforce_access_policy():
    # Unknown routes and wrong methods are handled by the JSON 404/405 handlers.
    if request.url_rule is None or request.method == "OPTIONS":
        return None

    method = "GET" if request.method == "HEAD" else request.method
    policy_key = (method, request.url_rule.rule)
    if policy_key not in ROUTE_POLICY:
        return auth_error("FORBIDDEN", "No access policy exists for this route.", 403)

    allowed_roles = ROUTE_POLICY[policy_key]
    if allowed_roles is None:
        return apply_rate_limit(policy_key)

    # Protected route: fail closed if security settings are missing.
    if config_problems():
        return auth_error(
            "AUTH_NOT_CONFIGURED", "Authentication is not configured.", 500
        )

    token = get_bearer_token()
    if token is None:
        return auth_error("UNAUTHORIZED", "A valid Bearer token is required.", 401)

    settings = jwt_settings()
    try:
        claims = jwt.decode(
            token,
            settings["secret"],
            algorithms=[JWT_ALGORITHM],
            issuer=settings["issuer"],
            audience=settings["audience"],
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        return auth_error("UNAUTHORIZED", "Token has expired.", 401)
    except jwt.InvalidTokenError as error:
        app.logger.warning(
            "JWT verification failed: %s", type(error).__name__
        )
        return auth_error("UNAUTHORIZED", "Invalid token.", 401)

    # The role comes only from the verified token, never from client headers.
    if claims.get("role") not in allowed_roles:
        return auth_error(
            "FORBIDDEN", "You do not have permission to perform this action.", 403
        )
    g.authenticated_role = claims["role"]
    return None


def forward_request(base_url, path):
    """Forward the current request (method, query string, body) to a backend."""
    method = request.method
    if method not in FORWARDED_METHODS:
        return jsonify({"error": "METHOD_NOT_ALLOWED"}), 405

    url = f"{base_url}{path}"
    forward_headers = {}
    if "Content-Type" in request.headers:
        forward_headers["Content-Type"] = request.headers["Content-Type"]
    if "Accept" in request.headers:
        forward_headers["Accept"] = request.headers["Accept"]

    # Pass the raw query string through unchanged so encoding, repeated
    # parameters and optional parameters are preserved exactly as received.
    query_string = request.query_string.decode("latin-1")
    if query_string:
        url = f"{url}?{query_string}"

    body = request.get_data() if method in {"POST", "PUT"} else None

    try:
        resp = requests.request(
            method,
            url,
            headers=forward_headers,
            data=body,
            timeout=TIMEOUT_SECONDS,
        )

        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "application/json"),
        )

    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "SERVICE_UNAVAILABLE",
            "message": f"Could not reach backend service at {base_url}."
        }), 503

    except requests.exceptions.Timeout:

        return jsonify({
            "error": "BAD_GATEWAY",
            "message": "The backend service returned an unusable response."
        }), 502

    except requests.exceptions.RequestException:
        return jsonify({
            "error": "BAD_GATEWAY",
            "message": "The backend service returned an unusable response."
        }), 502


@app.errorhandler(404)
def handle_not_found(_error):
    return jsonify({"error": "NOT_FOUND", "message": "Route not found."}), 404


@app.errorhandler(405)
def handle_method_not_allowed(_error):
    return jsonify({"error": "METHOD_NOT_ALLOWED"}), 405

@app.errorhandler(413)
def handle_payload_too_large(_error):
    return jsonify({
        "error": "PAYLOAD_TOO_LARGE",
        "message": "Request body is too large.",
    }), 413

@app.after_request
def add_security_headers(response):
    # setdefault keeps any header a route already chose (e.g. Cache-Control).
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")

    origin = request.headers.get("Origin")
    allowed_origins = {
        value.strip()
        for value in os.environ.get("SANIMAP_CORS_ORIGINS", "").split(",")
        if value.strip()
    }
    if origin and origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            "Accept, Authorization, Content-Type"
        )
        response.headers["Access-Control-Max-Age"] = "600"
        response.vary.add("Origin")
    return response


class BadRouteResponse(Exception):
    """The routing service answered, but not in the structure we expect."""


def validation_error(field, message):
    response = jsonify({"error": "VALIDATION_ERROR", "field": field, "message": message})
    response.status_code = 400
    return response


def routing_error(code, message, status, retry_after=None):
    response = jsonify({"error": code, "message": message})
    response.status_code = status
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


class NominatimClient:
    """Identify, throttle, and briefly cache requests to a Nominatim instance."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._last_request_at = None
        self._cache = OrderedDict()

    def reset(self):
        with self._lock:
            self._last_request_at = None
            self._cache.clear()

    def get(self, endpoint, params):
        base_url = os.environ.get(
            "NOMINATIM_BASE_URL", NOMINATIM_DEFAULT_BASE_URL
        ).rstrip("/")
        if not is_secure_base_url(base_url):
            return None, (
                "GEOCODING_NOT_CONFIGURED",
                "Geocoding is not available right now.",
                503,
                None,
            )

        url = f"{base_url}/{endpoint}"
        cache_key = (url, tuple(sorted(params.items())))
        with self._lock:
            now = self.clock()
            for key, (expires_at, _payload) in list(self._cache.items()):
                if expires_at <= now:
                    del self._cache[key]

            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached[1], None

            if (
                self._last_request_at is not None
                and now - self._last_request_at < NOMINATIM_MIN_INTERVAL_SECONDS
            ):
                return None, (
                    "GEOCODING_RATE_LIMITED",
                    "Please wait before searching for another location.",
                    429,
                    1,
                )

            self._last_request_at = now
            contact = os.environ.get("SANIMAP_CONTACT_EMAIL", "").strip()
            user_agent = "SaniMap/1.0 (Luneta Park sanitation mapping"
            if contact:
                user_agent += f"; contact: {contact}"
            user_agent += ")"

            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": user_agent},
                    timeout=NOMINATIM_TIMEOUT_SECONDS,
                )
            except requests.exceptions.Timeout:
                return None, (
                    "GEOCODING_TIMEOUT",
                    "The geocoding service took too long to respond.",
                    504,
                    None,
                )
            except requests.exceptions.RequestException as exc:
                app.logger.warning("Nominatim request failed: %s", type(exc).__name__)
                return None, (
                    "GEOCODING_SERVICE_ERROR",
                    "The geocoding service is currently unavailable.",
                    502,
                    None,
                )

            if response.status_code == 429:
                return None, (
                    "GEOCODING_BUSY",
                    "The geocoding service is busy. Please try again later.",
                    503,
                    60,
                )
            if response.status_code == 404:
                return None, (
                    "GEOCODING_NOT_FOUND",
                    "No matching location was found.",
                    404,
                    None,
                )
            if response.status_code != 200:
                app.logger.warning(
                    "Nominatim returned HTTP %s", response.status_code
                )
                return None, (
                    "GEOCODING_SERVICE_ERROR",
                    "The geocoding service is currently unavailable.",
                    502,
                    None,
                )

            try:
                payload = response.json()
            except (TypeError, ValueError):
                return None, (
                    "GEOCODING_BAD_RESPONSE",
                    "The geocoding service returned an unexpected response.",
                    502,
                    None,
                )

            self._cache[cache_key] = (
                self.clock() + NOMINATIM_CACHE_TTL_SECONDS,
                payload,
            )
            self._cache.move_to_end(cache_key)
            while len(self._cache) > NOMINATIM_CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)
            return payload, None


nominatim_client = NominatimClient()


def transform_nominatim_result(payload):
    """Normalize one Nominatim result to the Gateway's coordinate schema."""
    try:
        latitude = float(payload["lat"])
        longitude = float(payload["lon"])
        label = payload["display_name"]
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRouteResponse("unexpected geocoding result") from exc

    if (
        not isinstance(label, str)
        or not label.strip()
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise BadRouteResponse("invalid geocoding result")

    result = {
        "label": label[:300],
        "lat": latitude,
        "lng": longitude,
    }
    if isinstance(payload.get("osm_type"), str):
        result["osm_type"] = payload["osm_type"][:20]
    if isinstance(payload.get("osm_id"), int) and not isinstance(
        payload["osm_id"], bool
    ):
        result["osm_id"] = payload["osm_id"]
    return result


def nominatim_error(error):
    code, message, status, retry_after = error
    return routing_error(code, message, status, retry_after)


def geocoding_response(payload, reverse=False):
    try:
        if reverse:
            result = transform_nominatim_result(payload)
            body = {"result": result}
        else:
            if not isinstance(payload, list):
                raise BadRouteResponse("unexpected search response")
            body = {"results": [transform_nominatim_result(item) for item in payload]}
    except (BadRouteResponse, TypeError):
        app.logger.warning("Nominatim returned an unexpected response")
        return routing_error(
            "GEOCODING_BAD_RESPONSE",
            "The geocoding service returned an unexpected response.",
            502,
        )

    body["attribution"] = NOMINATIM_ATTRIBUTION
    response = jsonify(body)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/geocode", methods=["GET"])
def geocode_location():
    query = request.args.get("q", "").strip()
    if not query or len(query) > 200:
        return validation_error("q", "q is required and must be at most 200 characters.")

    payload, error = nominatim_client.get(
        "search",
        {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "countrycodes": "ph",
            "addressdetails": 1,
        },
    )
    if error:
        return nominatim_error(error)
    return geocoding_response(payload)


@app.route("/reverse-geocode", methods=["GET"])
def reverse_geocode_location():
    latitude, error = parse_coordinate(request.args, "lat", -90, 90)
    if error:
        return error
    longitude, error = parse_coordinate(request.args, "lng", -180, 180)
    if error:
        return error

    payload, error = nominatim_client.get(
        "reverse",
        {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "zoom": 18,
            "addressdetails": 1,
        },
    )
    if error:
        return nominatim_error(error)
    return geocoding_response(payload, reverse=True)


def parse_coordinate(args, name, low, high):
    """Return (value, None) or (None, error_response) for one query parameter."""
    raw = args.get(name)
    if raw is None or raw.strip() == "":
        return None, validation_error(name, f"{name} is required.")
    try:
        value = float(raw)
    except ValueError:
        return None, validation_error(name, f"{name} must be a number.")
    if not math.isfinite(value) or not low <= value <= high:
        return None, validation_error(name, f"{name} must be between {low} and {high}.")
    return value, None


def is_secure_base_url(base_url):
    """The API key is only ever sent over HTTPS (or to a local test server)."""
    return base_url.startswith(("https://", "http://127.0.0.1:", "http://localhost:"))


def transform_ors_route(payload, profile, start, end):
    """Convert an ORS GeoJSON route into SaniMap's response schema.

    ORS coordinates are [longitude, latitude]; the output path uses
    [latitude, longitude] so Leaflet can draw it without any conversion.
    """
    try:
        feature = payload["features"][0]
        summary = feature["properties"]["summary"]
        distance = float(summary["distance"])
        duration = float(summary["duration"])
        raw_coordinates = feature["geometry"]["coordinates"]

        path = []
        for point in raw_coordinates:
            lng, lat = float(point[0]), float(point[1])  # ignore any elevation value
            if not (math.isfinite(lat) and math.isfinite(lng)
                    and -90 <= lat <= 90 and -180 <= lng <= 180):
                raise BadRouteResponse("coordinate out of range")
            path.append([lat, lng])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise BadRouteResponse("unexpected route structure") from exc

    if (len(path) < 2 or not math.isfinite(distance) or not math.isfinite(duration)
            or distance < 0 or duration < 0):
        raise BadRouteResponse("invalid route values")

    steps = []
    segments = feature["properties"].get("segments")
    for segment in segments if isinstance(segments, list) else []:
        raw_steps = segment.get("steps") if isinstance(segment, dict) else None
        for step in raw_steps if isinstance(raw_steps, list) else []:
            if not isinstance(step, dict):
                continue
            try:
                steps.append({
                    "instruction": str(step.get("instruction") or "")[:300],
                    "distance_meters": float(step.get("distance") or 0),
                    "duration_seconds": float(step.get("duration") or 0),
                })
            except (TypeError, ValueError):
                continue

    latitudes = [point[0] for point in path]
    longitudes = [point[1] for point in path]
    return {
        "profile": profile,
        "distance_meters": distance,
        "duration_seconds": duration,
        "start": {"lat": start[0], "lng": start[1]},
        "end": {"lat": end[0], "lng": end[1]},
        "path": path,
        "bounds": [[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]],
        "steps": steps,
        "attribution": ORS_ATTRIBUTION,
    }


def upstream_error_response(status):
    # Log only the status code: never the key, the URL or the user's coordinates.
    app.logger.warning("OpenRouteService returned HTTP %s", status)
    if status in (400, 404):
        return routing_error(
            "ROUTE_NOT_FOUND", "No walking route could be found between these points.", 422
        )
    if status == 429:
        return routing_error(
            "ROUTING_BUSY", "The routing service is busy. Please try again shortly.", 503,
            retry_after=60,
        )
    return routing_error(
        "ROUTING_SERVICE_ERROR", "The routing service is currently unavailable.", 502
    )


@app.route("/directions", methods=["GET"])
def directions():
    values = {}
    for name, low, high in (
        ("start_lat", -90, 90), ("start_lng", -180, 180),
        ("end_lat", -90, 90), ("end_lng", -180, 180),
    ):
        value, error = parse_coordinate(request.args, name, low, high)
        if error is not None:
            return error
        values[name] = value

    profile = request.args.get("profile", DEFAULT_PROFILE)
    if profile not in SUPPORTED_PROFILES:
        return validation_error("profile", f"profile must be one of {list(SUPPORTED_PROFILES)}.")

    api_key = os.environ.get("ORS_API_KEY", "").strip()
    base_url = os.environ.get("ORS_BASE_URL", ORS_DEFAULT_BASE_URL).rstrip("/")
    if not api_key or not is_secure_base_url(base_url):
        return routing_error(
            "ROUTING_NOT_CONFIGURED", "Directions are not available right now.", 503
        )

    # ORS expects longitude first, then latitude.
    url = (
        f"{base_url}/directions/{profile}"
        f"?start={values['start_lng']:.6f},{values['start_lat']:.6f}"
        f"&end={values['end_lng']:.6f},{values['end_lat']:.6f}"
    )
    try:
        resp = requests.request(
            "GET",
            url,
            headers={
                "Authorization": api_key,
                "Accept": "application/geo+json, application/json",
            },
            timeout=ORS_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        app.logger.warning("OpenRouteService request timed out")
        return routing_error(
            "ROUTING_TIMEOUT", "The routing service took too long to respond.", 504
        )
    except requests.exceptions.RequestException as exc:
        app.logger.warning("OpenRouteService request failed: %s", type(exc).__name__)
        return routing_error(
            "ROUTING_SERVICE_ERROR", "The routing service is currently unavailable.", 502
        )

    if resp.status_code != 200:
        return upstream_error_response(resp.status_code)

    try:
        route = transform_ors_route(
            resp.json(),
            profile,
            (values["start_lat"], values["start_lng"]),
            (values["end_lat"], values["end_lng"]),
        )
    except (ValueError, BadRouteResponse):  # invalid JSON or unexpected structure
        app.logger.warning("OpenRouteService returned an unexpected response")
        return routing_error(
            "ROUTING_BAD_RESPONSE", "The routing service returned an unexpected response.", 502
        )

    response = jsonify(route)
    response.headers["Cache-Control"] = "no-store"  # the request contains the user's location
    return response


@app.route("/health", methods=["GET"])
def gateway_health():
    return jsonify({"service": "API Gateway", "status": "UP"}), 200


@app.route("/auth/verify", methods=["GET"])
def verify_staff_token():
    return jsonify({"role": g.authenticated_role}), 200


@app.route("/health/all", methods=["GET"])
def aggregated_health():
    results = {}
    for name, base_url in [("registry_service", SERVICE_A_URL), ("reporting_service", SERVICE_B_URL)]:
        try:
            r = requests.get(f"{base_url}/health", timeout=TIMEOUT_SECONDS)
            payload = r.json()
            if not r.ok or not isinstance(payload, dict) or payload.get("status") != "UP":
                results[name] = {"status": "DOWN"}
            else:
                results[name] = payload
        except (requests.exceptions.RequestException, ValueError):
            results[name] = {"status": "DOWN"}
    status_code = (
        200
        if all(service["status"] == "UP" for service in results.values())
        else 503
    )
    return jsonify({"gateway": "UP", "services": results}), status_code


@app.route("/restrooms", methods=["GET", "POST"])
def restrooms_root():
    return forward_request(SERVICE_A_URL, "/restrooms")


@app.route("/restrooms/<int:restroom_id>", methods=["GET"])
def get_restroom(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}")


@app.route("/restrooms/<int:restroom_id>/status", methods=["PUT"])
def update_restroom_status(restroom_id):
    return forward_request(SERVICE_A_URL, f"/restrooms/{restroom_id}/status")


@app.route("/feedback", methods=["GET", "POST"])
def feedback_root():
    # POST = public report submission, GET = staff list (see ROUTE_POLICY).
    return forward_request(SERVICE_B_URL, "/feedback")


@app.route("/feedback/<int:restroom_id>", methods=["GET"])
def get_feedback(restroom_id):
    return forward_request(SERVICE_B_URL, f"/feedback/{restroom_id}")


@app.route("/feedback/reports/<int:report_id>", methods=["GET"])
def get_report_status(report_id):
    return forward_request(SERVICE_B_URL, f"/feedback/reports/{report_id}")

@app.route("/feedback/reports/<int:report_id>/status", methods=["PUT"])
def update_report_status(report_id):
    return forward_request(SERVICE_B_URL, f"/feedback/reports/{report_id}/status")


if __name__ == "__main__":
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    debug = os.environ.get("GATEWAY_DEBUG") == "1"

    # Refuse to start with unsafe or incomplete security configuration.
    problems = config_problems()
    if debug and host != "127.0.0.1":
        problems.append("GATEWAY_DEBUG=1 is only allowed when GATEWAY_HOST is 127.0.0.1.")
    if problems:
        for problem in problems:
            print(f"Startup refused: {problem}", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("ORS_API_KEY", "").strip():
        print("Warning: ORS_API_KEY is not set; /directions will return 503.", file=sys.stderr)

    # Debug mode is OFF unless GATEWAY_DEBUG=1 is set explicitly (local dev only).
    app.run(host=host, port=int(os.environ.get("GATEWAY_PORT", "5000")), debug=debug)
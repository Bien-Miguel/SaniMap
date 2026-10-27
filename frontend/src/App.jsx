import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import {
  Accessibility,
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  Compass,
  LocateFixed,
  MapPin,
  Menu,
  Navigation,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Toilet,
  TriangleAlert,
  X,
} from "lucide-react";
import { api, MOCK_MODE, roleFromToken } from "./api.js";

const CENTER = [14.5825, 120.9786];
const REPORT_TYPES = [
  "UNSANITARY_FACILITY",
  "CLEANLINESS",
  "DAMAGED_FIXTURE",
  "OUT_OF_WATER",
  "CLOSED",
  "OTHER",
];
const STATUS_LABEL = {
  open: "Open",
  closed: "Closed",
  under_maintenance: "Maintenance",
};

// The Gateway returns metres and seconds (distance_meters / duration_seconds).
function formatDistance(meters) {
  if (!Number.isFinite(meters)) return "-";
  return meters < 1000
    ? `${Math.round(meters / 10) * 10} m`
    : `${(meters / 1000).toFixed(1)} km`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "-";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

function markerIcon(status, active = false) {
  const color =
    status === "open" ? "#2e8b66" : status === "closed" ? "#d86159" : "#d49a39";
  return L.divIcon({
    className: "marker-wrap",
    html: `<div class="map-marker ${
      active ? "is-active" : ""
    }" style="--marker-color:${color}"></div>`,
    iconSize: [38, 46],
    iconAnchor: [19, 41],
    popupAnchor: [0, -38],
  });
}

function MapViewport({ selected, route }) {
  const map = useMap();
  useEffect(() => {
    if (route?.bounds?.length === 2)
      map.fitBounds(route.bounds, { padding: [42, 42] });
    else if (selected)
      map.flyTo(
        [selected.latitude, selected.longitude],
        Math.max(map.getZoom(), 16),
        { duration: 0.7 }
      );
  }, [map, selected, route]);
  return null;
}

function Modal({
  title,
  onClose,
  children,
  wide = false,
  closeOnBackdrop = true,
}) {
  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) =>
        closeOnBackdrop &&
        event.target === event.currentTarget &&
        onClose()
      }
    >
      <section
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="modal-header">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={19} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

function App() {
  const [restrooms, setRestrooms] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [view, setView] = useState(() => {
    if (window.location.pathname === "/admin") return "admin";
    if (window.location.pathname === "/map") return "map";
    return "welcome";
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [accessibleOnly, setAccessibleOnly] = useState(false);
  const [modal, setModal] = useState("");
  const [toast, setToast] = useState("");
  const [route, setRoute] = useState(null);
  const [routeMessage, setRouteMessage] = useState("");
  const [reportReceipt, setReportReceipt] = useState(null);
  const [lookupId, setLookupId] = useState("");
  const [lookupResult, setLookupResult] = useState(null);
  const [token, setToken] = useState(
    () => sessionStorage.getItem("sanimap-admin-token") || ""
  );
  const [staffAuthenticated, setStaffAuthenticated] = useState(false);
  const [tokenDraft, setTokenDraft] = useState("");
  const [adminTab, setAdminTab] = useState("facilities");
  const [adminReports, setAdminReports] = useState([]);
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const mapRef = useRef(null);
  const reportRequestId = useRef(0);
  const routeRequestFor = useRef(null);

  const navigateTo = (nextView) => {
    const paths = { welcome: "/", map: "/map", admin: "/admin" };
    const path = paths[nextView] || "/";
    if (window.location.pathname !== path)
      window.history.pushState({}, "", path);
    if (nextView !== "admin") {
      setStaffAuthenticated(false);
      setAdminReports([]);
    }
    setView(nextView);
    setMobileMenu(false);
  };

  useEffect(() => {
    const handleHistoryChange = () => {
      const path = window.location.pathname;
      const nextView =
        path === "/admin" ? "admin" : path === "/map" ? "map" : "welcome";
      if (nextView !== "admin") {
        setStaffAuthenticated(false);
        setAdminReports([]);
      }
      setView(nextView);
    };
    window.addEventListener("popstate", handleHistoryChange);
    return () => window.removeEventListener("popstate", handleHistoryChange);
  }, []);

  useEffect(() => {
    if (view !== "admin" || staffAuthenticated) return undefined;

    setModal("admin-login");
    if (!token) return undefined;

    let active = true;
    api
      .verifyStaff(token)
      .then(() => {
        if (!active) return;
        setStaffAuthenticated(true);
        setModal("");
      })
      .catch((err) => {
        if (!active) return;
        setToken("");
        setTokenDraft("");
        sessionStorage.removeItem("sanimap-admin-token");
        setToast(err.message);
      });

    return () => {
      active = false;
    };
  }, [view, token, staffAuthenticated]);

  const refreshRestrooms = useCallback(async () => {
    setLoading(true);
    try {
      setRestrooms(await api.listRestrooms());
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshRestrooms();
  }, [refreshRestrooms]);
  useEffect(() => {
    if (!toast) return undefined;
    const timeout = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const selected =
    restrooms.find((item) => item.restroomId === selectedId) || null;
  const filteredRestrooms = useMemo(
    () =>
      restrooms.filter(
        (item) =>
          (statusFilter === "all" || item.status === statusFilter) &&
          (!accessibleOnly || item.pwdAccessible) &&
          `${item.name} ${item.genderType} ${item.amenities.join(" ")}`
            .toLowerCase()
            .includes(query.toLowerCase())
      ),
    [restrooms, statusFilter, accessibleOnly, query]
  );
  const openCount = restrooms.filter((item) => item.status === "open").length;

  // One place to change the selected facility, so a route or message that
// belongs to the previous facility is never left on the map.
function selectFacility(id) {
  routeRequestFor.current = null;
  setSelectedId(id);
  setRoute(null);
  setRouteMessage("");
  setBusy(false);
}

  const flashError = (err) =>
    setToast(err?.message || "Something went wrong. Please try again.");

  async function submitSearch(event) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const payload = await api.searchPlaces(query.trim());
      setSearchResults(payload.results || []);
      if (!payload.results?.length)
        setToast("No places found. Try a nearby landmark.");
    } catch (err) {
      flashError(err);
    } finally {
      setSearching(false);
    }
  }

  function chooseSearchResult(result) {
    const map = mapRef.current;
    map?.flyTo([result.lat, result.lng], 16, { duration: 0.7 });
    setSearchResults([]);
  }

 async function requestDirections() {
  setRouteMessage("");
  setRoute(null);
  if (!selected) return;

  if (!navigator.geolocation) {
    setRouteMessage(
      "This browser cannot share your location, so directions are unavailable."
    );
    return;
  }

  if (!window.isSecureContext) {
    setRouteMessage(
      "Location only works on HTTPS or localhost. Open SaniMap using a secure address."
    );
    return;
  }

  const target = {
    id: selected.restroomId,
    lat: selected.latitude,
    lng: selected.longitude,
  };

  routeRequestFor.current = target.id;
  setBusy(true);

  navigator.geolocation.getCurrentPosition(
    async ({ coords }) => {
      try {
        const result = await api.directions(
          { lat: coords.latitude, lng: coords.longitude },
          { lat: target.lat, lng: target.lng }
        );
        // Ignore the answer if the visitor picked another facility meanwhile.
        if (routeRequestFor.current !== target.id) return;
        setRoute(result);
        setRouteMessage("");
      } catch (err) {
        if (routeRequestFor.current === target.id) setRouteMessage(err.message);
      } finally {
        setBusy(false);
      }
    },
    (geoError) => {
      const reasons = {
        1: "Location permission was not granted. You can still browse the map.",
        2: "Your position could not be determined. Check your device location settings.",
        3: "Finding your location took too long. Please try again.",
      };
      setRouteMessage(
        reasons[geoError?.code] || "Your location could not be read."
      );
      setBusy(false);
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
  );
}

  async function submitReport(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const receipt = await api.createReport({
        restroomId: Number(form.get("restroomId")),
        reportType: form.get("reportType"),
        description: form.get("description").trim(),
      });
      setReportReceipt(receipt);
      setAdminReports((currentReports) => [receipt, ...currentReports]);
      setModal("receipt");
    } catch (err) {
      flashError(err);
    } finally {
      setBusy(false);
    }
  }

  async function submitLookup(event) {
    event.preventDefault();
    try {
      setLookupResult(await api.getReport(lookupId.trim()));
    } catch (err) {
      setLookupResult({ error: err.message });
    }
  }

  async function enterAdmin() {
    if (!tokenDraft.trim()) {
      setToast("Paste a valid staff Bearer token to continue.");
      return;
    }
    try {
      const staffToken = tokenDraft.trim();
      await api.verifyStaff(staffToken);
      setToken(staffToken);
      setStaffAuthenticated(true);
      setTokenDraft("");
      sessionStorage.setItem("sanimap-admin-token", staffToken);
      navigateTo("admin");
      setAdminTab("facilities");
      setModal("");
      setHealth("Connected to staff services.");
    } catch (err) {
      flashError(err);
    }
  }

  // A 401 means the staff token expired or was rejected: sign out and ask again.
  const handleAuthError = useCallback((err) => {
    if (err?.status !== 401) return false;
    setToken("");
    setStaffAuthenticated(false);
    setAdminReports([]);
    setTokenDraft("");
    sessionStorage.removeItem("sanimap-admin-token");
    setModal("admin-login");
    setToast("Your staff session ended. Paste a new token to continue.");
    return true;
  }, []);

  const loadAdminReports = useCallback(
    async (restroomId = null) => {
      const requestId = ++reportRequestId.current;
      try {
        const loadedReports = await api.listReports({ restroomId }, token);
        if (requestId !== reportRequestId.current) return;
        setAdminReports(loadedReports);
      } catch (err) {
        if (requestId !== reportRequestId.current) return;
        if (!handleAuthError(err)) setToast(err.message);
        setAdminReports([]);
      }
    },
    [token, handleAuthError]
  );

  useEffect(() => {
    if (view !== "admin" || !staffAuthenticated) return undefined;
    loadAdminReports();
    const refreshTimer = window.setInterval(() => loadAdminReports(), 5000);
    return () => window.clearInterval(refreshTimer);
  }, [view, staffAuthenticated, loadAdminReports]);

  async function changeReportStatus(reportId, status) {
    try {
      await api.updateReportStatus(reportId, status, token);
      await loadAdminReports();
      setToast(`Report #${reportId} marked ${status.toLowerCase()}.`);
    } catch (err) {
      if (!handleAuthError(err)) flashError(err);
    }
  }

  async function updateStatus(id, status) {
    try {
      await api.updateStatus(id, status, token);
      await refreshRestrooms();
      setToast("Facility status updated.");
    } catch (err) {
  if (!handleAuthError(err)) flashError(err);
  }
  }

  async function createRestroom(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const data = {
      name: form.get("name").trim(),
      latitude: Number(form.get("latitude")),
      longitude: Number(form.get("longitude")),
      operatingHours: form.get("operatingHours").trim(),
      pwdAccessible: form.get("pwdAccessible") === "true",
      genderType: form.get("genderType"),
      amenities: form
        .get("amenities")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      status: form.get("status"),
    };
    try {
      await api.createRestroom(data, token);
      await refreshRestrooms();
      setModal("");
      setToast("New restroom added to the registry.");
    } catch (err) {
  if (!handleAuthError(err)) flashError(err);
    }
  }

  async function checkHealth() {
    try {
      setHealth(await api.health(token, true));
    } catch (err) {
      setHealth({ error: err.message });
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="brand"
          onClick={() => navigateTo("welcome")}
          aria-label="SaniMap home"
        >
          <span className="brand-mark">
            <MapPin size={22} fill="currentColor" />
          </span>
          <span className="brand-name">
            sani<span>map</span>
            <small>RIZAL PARK • LUNETA</small>
          </span>
        </button>
        <nav className={`main-nav ${mobileMenu ? "nav-open" : ""}`}>
          <button
            className={view === "map" ? "nav-link active" : "nav-link"}
            onClick={() => navigateTo("map")}
          >
            <Compass size={17} /> Explore map
          </button>
        </nav>
        <div className="topbar-right">
          <button
            className="mobile-menu icon-button"
            onClick={() => setMobileMenu(!mobileMenu)}
            aria-label="Toggle navigation"
          >
            <Menu size={20} />
          </button>
        </div>
      </header>

      {view === "welcome" ? (
        <main className="welcome-page">
          <section className="welcome-hero">
            <div className="welcome-copy">
              <div className="panel-eyebrow">
                <span className="eyebrow-dot" /> RIZAL PARK · LUNETA
              </div>
              <h1>
                Explore with
                <br />
                <em>peace of mind.</em>
              </h1>
              <p>
                Find nearby comfort rooms, check accessibility and opening
                hours, and plan your visit around Rizal Park.
              </p>
              <button
                className="button-primary welcome-cta"
                onClick={() => navigateTo("map")}
              >
                Explore the map <ArrowRight size={19} />
              </button>
              <div className="welcome-features" aria-label="SaniMap features">
                <span>
                  <MapPin size={19} /> Nearby locations
                </span>
                <span>
                  <Accessibility size={19} /> Accessibility details
                </span>
                <span>
                  <Clock3 size={19} /> Facility hours
                </span>
              </div>
            </div>
            <figure className="welcome-photo">
              <img
                src="https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Rizal_Park_from_above.jpg/1280px-Rizal_Park_from_above.jpg"
                alt="Aerial view of Rizal Park, also known as Luneta, in Manila"
              />
              <figcaption>
                <span>
                  <MapPin size={17} /> Rizal Park · Luneta, Manila
                </span>
                <a
                  href="https://commons.wikimedia.org/wiki/File:Rizal_Park_from_above.jpg"
                  target="_blank"
                  rel="noreferrer"
                >
                  Photo: Richmond Chi / CC BY-SA 4.0
                </a>
              </figcaption>
            </figure>
          </section>
          <p className="welcome-note">
            A simple guide to facilities around Luneta.
          </p>
        </main>
      ) : view === "map" ? (
        <main className="map-layout">
          <aside className="discover-panel">
            <div className="panel-eyebrow">
              <span className="eyebrow-dot" /> YOUR PARK, MADE EASIER
            </div>
            <h1>
              Find a comfort
              <br />
              room <em>nearby.</em>
            </h1>
            <p className="intro-copy">
              A little more peace of mind while you explore Luneta.
            </p>
            <form className="search-box" onSubmit={submitSearch}>
              <Search size={18} />
              <input
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSearchResults([]);
                }}
                placeholder="Search a restroom or place"
                aria-label="Search a restroom or place"
              />
              <button aria-label="Search" disabled={searching}>
                {searching ? (
                  <span className="spinner small" />
                ) : (
                  <ArrowRight size={18} />
                )}
              </button>
            </form>
            {searchResults.length > 0 && (
              <div className="search-results">
                {searchResults.map((result, index) => (
                  <button
                    key={`${result.label}-${index}`}
                    onClick={() => chooseSearchResult(result)}
                  >
                    <MapPin size={16} />
                    <span>{result.label}</span>
                    <ArrowUpRight size={15} />
                  </button>
                ))}
              </div>
            )}
            {!MOCK_MODE && (
              <p className="search-hint">
                Place search is submitted manually; no autocomplete requests.
              </p>
            )}
            <div className="list-heading">
              <div>
                <h2>Nearby facilities</h2>
                <span>{filteredRestrooms.length} places in Luneta</span>
              </div>
              <SlidersHorizontal size={18} />
            </div>
            <div className="filter-row">
              <label className="select-wrap">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label="Filter by status"
                >
                  <option value="all">All statuses</option>
                  <option value="open">Open now</option>
                  <option value="closed">Closed</option>
                  <option value="under_maintenance">Maintenance</option>
                </select>
                <ChevronDown size={14} />
              </label>
              <button
                className={`filter-chip ${
                  accessibleOnly ? "chip-selected" : ""
                }`}
                onClick={() => setAccessibleOnly(!accessibleOnly)}
              >
                <Accessibility size={15} /> PWD accessible
              </button>
            </div>
            <div className="facility-list">
              {loading && (
                <div className="empty-state">
                  <span className="spinner" />
                  Loading restroom locations… The first request after inactivity can take up to about a minute.
                </div>
              )}
              {!loading && error && (
                <div className="error-card">
                  <CircleAlert size={19} />
                  <span>{error}</span>
                  <button onClick={refreshRestrooms}>Retry</button>
                </div>
              )}
              {!loading &&
                !error &&
                filteredRestrooms.map((item) => (
                  <button
                    className={`facility-card ${
                      selectedId === item.restroomId ? "selected" : ""
                    }`}
                    key={item.restroomId}
                    onClick={() => selectFacility(item.restroomId)}
                  >
                    <span className={`facility-icon status-${item.status}`}>
                      <Toilet size={20} />
                    </span>
                    <span className="facility-info">
                      <strong>{item.name}</strong>
                      <span>
                        <i className={`status-dot status-dot-${item.status}`} />
                        {STATUS_LABEL[item.status]} <b>·</b>{" "}
                        {item.operatingHours}
                      </span>
                      <span className="facility-meta">
                        {item.pwdAccessible
                          ? "♿ Accessible"
                          : "Standard access"}{" "}
                        <b>·</b> {item.genderType}
                      </span>
                    </span>
                    <ArrowRight className="card-arrow" size={16} />
                  </button>
                ))}
              {!loading && !error && !filteredRestrooms.length && (
                <div className="empty-state">
                  No restrooms match these filters.
                </div>
              )}
            </div>
            <div className="panel-foot">
              <span className="mini-stat">
                <strong>{openCount}</strong> currently open
              </span>
              <span className="foot-divider" />
              <span>Data for Rizal Park</span>
            </div>
          </aside>

          <section
            className="map-stage"
            aria-label="Map of restrooms in Rizal Park"
          >
            <MapContainer
              center={CENTER}
              zoom={16}
              zoomControl={false}
              className="leaflet-map"
              whenReady={(event) => {
                mapRef.current = event.target;
              }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <MapViewport selected={selected} route={route} />
              {restrooms.map((item) => (
                <Marker
                  key={item.restroomId}
                  position={[item.latitude, item.longitude]}
                  icon={markerIcon(item.status, selectedId === item.restroomId)}
                  eventHandlers={{
                    click: () => selectFacility(item.restroomId),
                  }}
                />
              ))}
              {route?.path?.length > 0 && (
                <Polyline
                  positions={route.path}
                  pathOptions={{ color: "#2e8b66", weight: 5, opacity: 0.86 }}
                />
              )}
            </MapContainer>
            <div className="map-label">
              <span className="map-label-icon">
                <MapPin size={16} />
              </span>
              <span>
                <strong>Rizal Park</strong>
                <small>Manila, Philippines</small>
              </span>
            </div>
            <div className="map-legend">
              <span>
                <i className="legend-dot green" /> Open
              </span>
              <span>
                <i className="legend-dot amber" /> Maintenance
              </span>
              <span>
                <i className="legend-dot red" /> Closed
              </span>
            </div>
            {selected && (
              <article className="map-detail-card">
                <button
                  className="detail-close icon-button"
                  onClick={() => selectFacility(null)}
                  aria-label="Close details"
                >
                  <X size={17} />
                </button>
                <div className="detail-kicker">
                  <span
                    className={`status-pill status-pill-${selected.status}`}
                  >
                    <i className={`status-dot status-dot-${selected.status}`} />
                    {STATUS_LABEL[selected.status]}
                  </span>
                  <span>Facility #{selected.restroomId}</span>
                </div>
                <h2>{selected.name}</h2>
                <p className="detail-address">
                  <MapPin size={14} /> Rizal Park, Manila
                </p>
                <div className="detail-facts">
                  <div>
                    <Clock3 size={16} />
                    <span>
                      <small>HOURS</small>
                      <strong>{selected.operatingHours}</strong>
                    </span>
                  </div>
                  <div>
                    <Accessibility size={16} />
                    <span>
                      <small>ACCESS</small>
                      <strong>
                        {selected.pwdAccessible
                          ? "PWD accessible"
                          : "Standard access"}
                      </strong>
                    </span>
                  </div>
                </div>
                <div className="detail-amenities">
                  <span>{selected.genderType}</span>
                  {selected.amenities.map((amenity) => (
                    <span key={amenity}>{amenity}</span>
                  ))}
                </div>
                {route && (
                  <div className="route-summary">
                    <Navigation size={16} />
                    <span>
                      <strong>{formatDistance(route.distance_meters)}</strong>{" "}
                      {formatDuration(route.duration_seconds)} walk
                    </span>
                    <button
                      onClick={() => setRoute(null)}
                      aria-label="Clear directions"
                    >
                      <X size={14} />
                    </button>
                  </div>
                )}
                {route?.distance_meters > 5000 && (
                  <p className="inline-warning">
                    <TriangleAlert size={15} />
                    You appear to be far from Rizal Park, so this walking route
                    is long.
                  </p>
                )}
                {selected.status !== "open" && (
                  <p className="inline-warning">
                    <TriangleAlert size={15} />
                    This facility is currently{" "}
                    {STATUS_LABEL[selected.status].toLowerCase()}. Check before
                    you walk there.
                  </p>
                )}
                {route?.attribution && (
                  <small className="muted-copy">{route.attribution}</small>
                )}
                {routeMessage && (
                  <p className="inline-warning">
                    <TriangleAlert size={15} />
                    {routeMessage}
                  </p>
                )}
                <div className="detail-actions">
                  <button
                    className="button-primary"
                    onClick={requestDirections}
                    disabled={busy}
                  >
                    <Navigation size={16} />
                    {busy ? "Finding route…" : "Get directions"}
                  </button>
                  <button
                    className="button-secondary"
                    onClick={() => {
                      setReportReceipt(null);
                      setModal("report");
                    }}
                  >
                    <TriangleAlert size={16} />
                    Report a problem
                  </button>
                </div>
              </article>
            )}
            <button
              className="map-locate"
              onClick={() =>
                navigator.geolocation?.getCurrentPosition(
                  ({ coords }) =>
                    mapRef.current?.flyTo(
                      [coords.latitude, coords.longitude],
                      17
                    ),
                  () => setToast("Location permission was not granted.")
                )
              }
              aria-label="Show my location"
            >
              <LocateFixed size={19} />
            </button>
            {route?.steps?.length > 0 && (
              <div className="route-steps">
                <strong>Walking route</strong>
                {route.steps.slice(0, 4).map((step, index) => (
                  <p key={index}>
                    <span>{index + 1}</span>
                    {step.instruction ||
                      step.name ||
                      "Continue along the route"}
                  </p>
                ))}
              </div>
            )}
            <div className="map-attribution">
              Map tiles © OpenStreetMap contributors
            </div>
          </section>
        </main>
      ) : staffAuthenticated ? (
        <AdminDashboard
          restrooms={restrooms}
          reports={adminReports}
          tab={adminTab}
          setTab={setAdminTab}
          onAdd={() => setModal("add-restroom")}
          onUpdate={updateStatus}
          onRefreshReports={loadAdminReports}
          onHealth={checkHealth}
          health={health}
          token={token}
          onLogout={() => {
            setToken("");
            setStaffAuthenticated(false);
            setAdminReports([]);
            sessionStorage.removeItem("sanimap-admin-token");
            navigateTo("welcome");
          }}
          onShowReceipt={() => setModal("report-lookup")}
          onReportStatus={changeReportStatus}
          role={roleFromToken(token)}
        />
      ) : (
        <main className="welcome-page" aria-live="polite">
          <p className="welcome-note">
            Staff access is required to view the administration dashboard.
          </p>
        </main>
      )}

      {modal === "report" && selected && (
        <Modal title="Report a facility issue" onClose={() => setModal("")}>
          <form className="form-body" onSubmit={submitReport}>
            <div className="form-context">
              <span className="facility-icon status-open">
                <Toilet size={18} />
              </span>
              <span>
                <strong>{selected.name}</strong>
                <small>Your report will be sent to the park team.</small>
              </span>
            </div>
            <input
              type="hidden"
              name="restroomId"
              value={selected.restroomId}
            />
            <label>
              What needs attention?
              <select required name="reportType">
                {REPORT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type
                      .replaceAll("_", " ")
                      .toLowerCase()
                      .replace(/\b\w/g, (char) => char.toUpperCase())}
                  </option>
                ))}
              </select>
            </label>
            <label>
              More details <span className="optional">Optional</span>
              <textarea
                name="description"
                maxLength="1000"
                rows="4"
                placeholder="Tell us what you noticed…"
              />
            </label>
            <p className="privacy-note">
              <ShieldCheck size={15} />
              Reports are recorded with a timestamp and start as pending.
            </p>
            <div className="form-actions">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setModal("")}
              >
                Cancel
              </button>
              <button className="button-primary" disabled={busy}>
                {busy ? "Sending…" : "Send report"}
                <ArrowRight size={16} />
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal === "receipt" && reportReceipt && (
        <Modal title="Report received" onClose={() => setModal("")}>
          <div className="receipt-body">
            <span className="receipt-check">
              <Check size={26} />
            </span>
            <h3>Thanks for letting us know.</h3>
            <p>Your report has been recorded for the park team to review.</p>
            <div className="receipt-card">
              <span>REFERENCE NUMBER</span>
              <strong>#{reportReceipt.reportId}</strong>
              <div>
                <span>Facility</span>
                <b>{reportReceipt.restroomName}</b>
              </div>
              <div>
                <span>Issue</span>
                <b>{reportReceipt.reportType.replaceAll("_", " ")}</b>
              </div>
              <div>
                <span>Status</span>
                <b className="pending-text">{reportReceipt.status}</b>
              </div>
            </div>
            <button
              className="text-button"
              onClick={() => {
                setLookupId(String(reportReceipt.reportId));
                setLookupResult(reportReceipt);
                setModal("report-lookup");
              }}
            >
              View report status <ArrowRight size={15} />
            </button>
          </div>
        </Modal>
      )}
      {modal === "report-lookup" && (
        <Modal title="Look up a report" onClose={() => setModal("")}>
          <form className="form-body" onSubmit={submitLookup}>
            <label>
              Report reference number
              <input
                type="number"
                min="1"
                value={lookupId}
                onChange={(e) => setLookupId(e.target.value)}
                placeholder="e.g. 204"
                required
              />
            </label>
            <button className="button-primary">
              Check status <Search size={16} />
            </button>
            {lookupResult &&
              (lookupResult.error ? (
                <p className="lookup-error">{lookupResult.error}</p>
              ) : (
                <div className="receipt-card lookup-card">
                  <span>REPORT #{lookupResult.reportId}</span>
                  <strong>{lookupResult.status}</strong>
                  <div>
                    <span>Facility</span>
                    <b>{lookupResult.restroomName}</b>
                  </div>
                  <div>
                    <span>Submitted</span>
                    <b>{new Date(lookupResult.createdAt).toLocaleString()}</b>
                  </div>
                </div>
              ))}
          </form>
        </Modal>
      )}
      {modal === "add-restroom" && (
        <Modal title="Add a restroom" onClose={() => setModal("")}>
          <form className="form-body two-col-form" onSubmit={createRestroom}>
            <label className="span-2">
              Facility name
              <input
                name="name"
                required
                maxLength="120"
                placeholder="e.g. North Garden Comfort Room"
              />
            </label>
            <label>
              Latitude
              <input
                name="latitude"
                type="number"
                min="-90"
                max="90"
                step="any"
                required
                placeholder="14.5826"
              />
            </label>
            <label>
              Longitude
              <input
                name="longitude"
                type="number"
                min="-180"
                max="180"
                step="any"
                required
                placeholder="120.9787"
              />
            </label>
            <label>
              Operating hours
              <input name="operatingHours" required placeholder="06:00-20:00" />
            </label>
            <label>
              Gender type
              <select name="genderType">
                <option>Unisex</option>
                <option>Male/Female</option>
                <option>Male</option>
                <option>Female</option>
              </select>
            </label>
            <label>
              PWD accessible
              <select name="pwdAccessible">
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
            <label>
              Initial status
              <select name="status">
                <option value="open">Open</option>
                <option value="closed">Closed</option>
                <option value="under_maintenance">Under maintenance</option>
              </select>
            </label>
            <label className="span-2">
              Amenities <span className="optional">Comma separated</span>
              <input
                name="amenities"
                required
                placeholder="Handwashing Station, Soap"
              />
            </label>
            <div className="form-actions span-2">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setModal("")}
              >
                Cancel
              </button>
              <button className="button-primary">
                Add facility <Plus size={16} />
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal === "admin-login" && (
        <Modal
          title="Staff access"
          closeOnBackdrop={false}
          onClose={() => {
            setTokenDraft("");
            setModal("");
            if (!staffAuthenticated) navigateTo("map");
          }}
        >
          <form
            className="form-body"
            onSubmit={(event) => {
              event.preventDefault();
              enterAdmin();
            }}
          >
            <div className="login-message">
              <ShieldCheck size={21} />
              <p>
                Protected staff tools use the role in your Gateway-verified JWT.
                The frontend does not grant access by itself.
              </p>
            </div>
            <label>
              Staff Bearer token
              <input
                type="password"
                autoComplete="off"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                placeholder="Paste your issued token"
              />
            </label>
            <button className="button-primary">
              Verify with Gateway <ArrowRight size={16} />
            </button>
            <small className="muted-copy">
              No login or token-issuing endpoint is configured in this project.
            </small>
          </form>
        </Modal>
      )}
      {toast && (
        <div className="toast">
          <CircleAlert size={17} />
          {toast}
          <button onClick={() => setToast("")} aria-label="Dismiss">
            <X size={16} />
          </button>
        </div>
      )}
      <footer className="mobile-attribution">
        Map tiles © OpenStreetMap contributors
      </footer>
    </div>
  );
}

function AdminDashboard({
  restrooms,
  reports,
  tab,
  setTab,
  onAdd,
  onUpdate,
  onRefreshReports,
  onHealth,
  health,
  token,
  onLogout,
  onShowReceipt,
  onReportStatus,
  role,
}) {
  const [reportFacility, setReportFacility] = useState("all");
  const visibleReports =
    reportFacility === "all"
      ? reports
      : reports.filter(
          (report) => Number(report.restroomId) === Number(reportFacility)
        );
  return (
    <main className="admin-page">
      <div className="admin-heading">
        <div>
          <div className="panel-eyebrow">
            <span className="eyebrow-dot" /> FACILITY OPERATIONS
          </div>
          <h1>
            Admin <em>dashboard</em>
          </h1>
          <p>Keep the Luneta restroom directory accurate and up to date.</p>
        </div>
        <div className="admin-heading-actions">
          <button
            className="button-secondary signout-button"
            onClick={onLogout}
          >
            Exit dashboard <ArrowRight size={15} />
          </button>
        </div>
      </div>
      <div className="admin-stats">
        <div className="stat-card">
          <span>REGISTERED FACILITIES</span>
          <strong>{restrooms.length}</strong>
          <small>
            <Toilet size={14} /> In the restroom registry
          </small>
        </div>
        <div className="stat-card">
          <span>OPEN RIGHT NOW</span>
          <strong>{restrooms.filter((r) => r.status === "open").length}</strong>
          <small>
            <i className="legend-dot green" /> Available to visitors
          </small>
        </div>
        <div className="stat-card">
          <span>NEEDS ATTENTION</span>
          <strong>{restrooms.filter((r) => r.status !== "open").length}</strong>
          <small>
            <TriangleAlert size={14} /> Closed or maintenance
          </small>
        </div>
        <div className="stat-card">
          <span>REPORTS LOADED</span>
          <strong>{reports.length}</strong>
          <small>
            <Clock3 size={14} />{" "}
            {reports.length
              ? "Across all facilities"
              : "No visitor reports yet"}
          </small>
        </div>
      </div>
      <div className="admin-toolbar">
        <div className="admin-tabs">
          <button
            className={tab === "facilities" ? "active" : ""}
            onClick={() => setTab("facilities")}
          >
            Facilities
          </button>
          <button
            className={tab === "reports" ? "active" : ""}
            onClick={() => setTab("reports")}
          >
            Report history
          </button>
          <button
            className={tab === "services" ? "active" : ""}
            onClick={() => setTab("services")}
          >
            Service health
          </button>
        </div>
        {tab === "facilities" && role === "admin" && (
          <button className="button-primary add-button" onClick={onAdd}>
            <Plus size={17} /> Add restroom
          </button>
        )}
      </div>
      {tab === "facilities" && (
        <section className="admin-card">
          <div className="table-title">
            <div>
              <h2>Restroom registry</h2>
              <p>Manage facility status and verified public details.</p>
            </div>
            <span className="table-count">{restrooms.length} records</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>FACILITY</th>
                  <th>ACCESSIBILITY</th>
                  <th>HOURS</th>
                  <th>STATUS</th>
                  <th>UPDATE STATUS</th>
                </tr>
              </thead>
              <tbody>
                {restrooms.map((item) => (
                  <tr key={item.restroomId}>
                    <td>
                      <strong>{item.name}</strong>
                      <small>
                        #{item.restroomId} · {item.genderType}
                      </small>
                    </td>
                    <td>
                      {item.pwdAccessible ? (
                        <span className="yes-label">
                          <Accessibility size={15} /> PWD accessible
                        </span>
                      ) : (
                        <span className="no-label">Standard</span>
                      )}
                    </td>
                    <td>{item.operatingHours}</td>
                    <td>
                      <span
                        className={`status-pill status-pill-${item.status}`}
                      >
                        <i className={`status-dot status-dot-${item.status}`} />
                        {STATUS_LABEL[item.status]}
                      </span>
                    </td>
                    <td>
                      <label className="table-select">
                        <select
                          value={item.status}
                          onChange={(event) =>
                            onUpdate(item.restroomId, event.target.value)
                          }
                          disabled={role !== "admin"}
                        title={role !== "admin" ? "Only admins can change facility status" : undefined}
                        aria-label={`Update ${item.name} status`}

                        >
                          <option value="open">Open</option>
                          <option value="closed">Closed</option>
                          <option value="under_maintenance">Maintenance</option>
                        </select>
                        <ChevronDown size={14} />
                      </label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            <ShieldCheck size={15} /> Status updates are saved through the
            Registry API. Other record fields are read-only in the current
            backend.
          </p>
        </section>
      )}
      {tab === "reports" && (
        <section className="admin-card">
          <div className="table-title">
            <div>
              <h2>Visitor report history</h2>
              <p>New reports appear automatically every 5 seconds.</p>
            </div>
            <div className="report-controls">
              <label className="select-wrap">
                <select
                  value={reportFacility}
                  onChange={(event) => setReportFacility(event.target.value)}
                >
                  <option value="all">All facilities</option>
                  {restrooms.map((item) => (
                    <option key={item.restroomId} value={item.restroomId}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} />
              </label>
              <button
                className="button-secondary report-refresh"
                onClick={() => onRefreshReports()}
                disabled={!restrooms.length}
              >
                <ArrowDownUp size={15} /> Refresh
              </button>
            </div>
          </div>
          {visibleReports.length ? (
            <div className="report-list">
              {visibleReports.map((report) => (
                <article key={report.reportId} className="report-row">
                  <span className="report-type-icon">
                    <TriangleAlert size={18} />
                  </span>
                  <div className="report-row-main">
                    <strong>{report.reportType.replaceAll("_", " ")}</strong>
                    <span className="report-facility-name">
                      {report.restroomName ||
                        restrooms.find(
                          (restroom) =>
                            restroom.restroomId === report.restroomId
                        )?.name ||
                        `Facility #${report.restroomId}`}
                    </span>
                    <p>
                      {report.description || "No additional details provided."}
                    </p>
                    <small>
                      {new Date(report.createdAt).toLocaleString()} · Report #
                      {report.reportId}
                    </small>
                  </div>
                  <div className="report-actions">
                  <span className={`pending-badge ${report.status === "RESOLVED" ? "done-badge" : ""}`}>
                 {report.status}
                   </span>
                  {report.status === "PENDING" ? (
                  <>
                      <button
                    className="button-secondary report-action"
                   onClick={() => onReportStatus(report.reportId, "RESOLVED")}
                >
                  Resolve
                  </button>
                   <button
                  className="button-secondary report-action"
                   onClick={() => onReportStatus(report.reportId, "REJECTED")}
                 >
                   Reject
                  </button>
                  </>
               ) : (
                 <button
                   className="button-secondary report-action"
                   onClick={() => onReportStatus(report.reportId, "PENDING")}
                 >
                   Reopen
                    </button>
                 )}
                </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-admin">
              <CircleAlert size={23} />
              <strong>No reports for this restroom</strong>
              <span>
                Visitor reports will appear here as soon as they are submitted.
              </span>
            </div>
          )}
          <div className="admin-footnote">
            Reports are read-only in the current backend; status changes are not
            available.
          </div>
        </section>
      )}
      {tab === "services" && (
        <section className="admin-card health-card">
          <div className="table-title">
            <div>
              <h2>Service health</h2>
              <p>
                Check Gateway and downstream Registry and Reporting services.
              </p>
            </div>
            <button className="button-secondary" onClick={onHealth}>
              <ArrowDownUp size={15} /> Refresh status
            </button>
          </div>
          {health && (
            <pre className={health.error ? "health-error" : ""}>
              {typeof health === "string"
                ? health
                : JSON.stringify(health, null, 2)}
            </pre>
          )}
          <p className="table-note">
            <ShieldCheck size={15} />
            Aggregated health is restricted to admin and park_manager roles by
            the Gateway.
          </p>
        </section>
      )}
      <div className="admin-bottom">
        <span>
          <ShieldCheck size={15} /> Access is enforced by the API Gateway
        </span>
        <button className="text-button" onClick={onShowReceipt}>
          Look up a report <ArrowRight size={15} />
        </button>
      </div>
    </main>
  );
}

export default App;

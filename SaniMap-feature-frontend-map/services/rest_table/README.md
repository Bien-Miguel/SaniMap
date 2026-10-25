## Part 2 – Design the REST API

| Service | Method | Endpoint | Purpose |
| :--- | :--- | :--- | :--- |
| **Comfort Room Registry Service (Service A)** | `GET` | `/health` | Checks whether the Comfort Room Registry Service is running. |
| **Comfort Room Registry Service (Service A)** | `GET` | `/restrooms/{id}` | Retrieves details, location, and facilities of a specific comfort room. |
| **Comfort Room Registry Service (Service A)** | `POST` | `/restrooms` | Adds a new comfort room entry to the park registry (Admin use). |
| **Reporting and Feedback Service (Service B)** | `GET` | `/health` | Checks whether the Reporting and Feedback Service is running. |
| **Reporting and Feedback Service (Service B)** | `GET` | `/feedback/{restroom_id}` | Retrieves all visitor feedback and reports history for a specific comfort room. |
| **Reporting and Feedback Service (Service B)** | `POST` | `/feedback` | Submits a new tourist complaint or issue report regarding facility conditions. |
| **API Gateway** | `GET` | `/directions` | Calls OpenRouteService for walking directions and returns Leaflet-ready JSON. |
| **API Gateway** | `GET` | `/geocode?q={query}` | Searches a manually submitted place or address with Nominatim and returns normalized coordinates. |
| **API Gateway** | `GET` | `/reverse-geocode?lat={lat}&lng={lng}` | Resolves coordinates to a place label through Nominatim. |

The Nominatim routes are for explicit user-submitted searches, not autocomplete.
They return JSON with `[lat, lng]` coordinate properties and OpenStreetMap
attribution. Nominatim requires no API key; the Gateway identifies itself with
a SaniMap User-Agent, caches results in memory for one hour, and enforces a
one-request-per-second upstream limit. Set `SANIMAP_CONTACT_EMAIL` in the
Gateway environment to include a project contact in that User-Agent. Set
`NOMINATIM_BASE_URL` only when switching to another compliant Nominatim
instance/provider.

`/directions` continues to require `ORS_API_KEY`, configured server-side. No
map provider key should be exposed in the frontend.

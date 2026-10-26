const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
export const MOCK_MODE = import.meta.env.VITE_USE_MOCK_API !== "false";

const initialRestrooms = [
  {
    restroomId: 1,
    name: "Rizal Monument Comfort Room",
    latitude: 14.5826,
    longitude: 120.9787,
    operatingHours: "06:00-20:00",
    pwdAccessible: true,
    genderType: "Unisex",
    amenities: ["Handwashing Station", "Soap", "Bidet"],
    status: "open",
  },
  {
    restroomId: 2,
    name: "Children's Playground Comfort Room",
    latitude: 14.581,
    longitude: 120.9795,
    operatingHours: "07:00-19:00",
    pwdAccessible: false,
    genderType: "Male/Female",
    amenities: ["Handwashing Station"],
    status: "under_maintenance",
  },
  {
    restroomId: 3,
    name: "Manila Ocean Park Comfort Room",
    latitude: 14.5794,
    longitude: 120.9732,
    operatingHours: "06:00-21:00",
    pwdAccessible: true,
    genderType: "Male/Female",
    amenities: ["Handwashing Station", "Soap"],
    status: "open",
  },
  {
    restroomId: 4,
    name: "Quirino Grandstand Comfort Room",
    latitude: 14.5831,
    longitude: 120.9761,
    operatingHours: "06:00-18:00",
    pwdAccessible: false,
    genderType: "Unisex",
    amenities: ["Handwashing Station", "Baby Changing"],
    status: "closed",
  },
];

const initialReports = [
  {
    reportId: 204,
    restroomId: 1,
    restroomName: initialRestrooms[0].name,
    reportType: "CLEANLINESS",
    description: "Needs attention near the sinks.",
    status: "PENDING",
    createdAt: "2026-10-14T08:42:00Z",
  },
  {
    reportId: 203,
    restroomId: 2,
    restroomName: initialRestrooms[1].name,
    reportType: "DAMAGED_FIXTURE",
    description: "One tap is not working.",
    status: "PENDING",
    createdAt: "2026-10-13T11:15:00Z",
  },
  {
    reportId: 202,
    restroomId: 3,
    restroomName: initialRestrooms[2].name,
    reportType: "OUT_OF_WATER",
    description: "No running water at the time of visit.",
    status: "PENDING",
    createdAt: "2026-10-12T03:08:00Z",
  },
];

function stored(key, fallback) {
  try {
    const value = localStorage.getItem(`sanimap-${key}`);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

let restrooms = stored("restrooms", initialRestrooms);
let reports = stored("reports", initialReports);
let nextReportId =
  Math.max(204, ...reports.map((report) => Number(report.reportId) || 0)) + 1;

function persist() {
  localStorage.setItem("sanimap-restrooms", JSON.stringify(restrooms));
  localStorage.setItem("sanimap-reports", JSON.stringify(reports));
}

export function roleFromToken(token) {
  // Display only: decides which buttons to show. The Gateway still verifies the
  // signature and role on every request, so this grants no access by itself.
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(part)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(json).role || "";
  } catch {
    return "";
  }
}

async function request(path, { method = "GET", body, token } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    const error = new Error(
      "Cannot reach the SaniMap server. Check your connection and try again."
    );
    error.status = 0;
    throw error;
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      payload.message || payload.error || `Request failed (${response.status})`
    );
    error.status = response.status;
    error.code = payload.error;
    throw error;
  }
  return payload;
}

export const api = {
  async listRestrooms() {
    if (MOCK_MODE) return [...restrooms];
    return request("/restrooms");
  },
  async createRestroom(data, token) {
    if (MOCK_MODE) {
      const restroom = {
        ...data,
        restroomId:
          Math.max(0, ...restrooms.map((item) => item.restroomId)) + 1,
      };
      restrooms = [...restrooms, restroom];
      persist();
      return restroom;
    }
    return request("/restrooms", { method: "POST", body: data, token });
  },
  async updateStatus(id, status, token) {
    if (MOCK_MODE) {
      restrooms = restrooms.map((item) =>
        item.restroomId === id ? { ...item, status } : item
      );
      persist();
      return restrooms.find((item) => item.restroomId === id);
    }
    return request(`/restrooms/${id}/status`, {
      method: "PUT",
      body: { status },
      token,
    });
  },
  async createReport(data) {
    if (MOCK_MODE) {
      const restroom = restrooms.find(
        (item) => item.restroomId === Number(data.restroomId)
      );
      if (!restroom) throw new Error("That restroom could not be found.");
      const report = {
        ...data,
        reportId: nextReportId++,
        restroomName: restroom.name,
        status: "PENDING",
        createdAt: new Date().toISOString(),
      };
      reports = [report, ...reports];
      persist();
      return report;
    }
    return request("/feedback", { method: "POST", body: data });
  },
  async getReport(id) {
    if (MOCK_MODE) {
      const report = reports.find(
        (item) => String(item.reportId) === String(id)
      );
      if (!report) throw new Error(`Report ${id} was not found.`);
      return report;
    }
    return request(`/feedback/reports/${id}`);
  },
  async reportsForRestroom(id, token) {
    if (MOCK_MODE) {
      // Reload persisted mock reports so an admin tab sees reports submitted
      // from another tab in the same browser.
      reports = stored("reports", reports);
      return reports.filter((report) => report.restroomId === Number(id));
    }
    try {
      return await request(`/feedback/${id}`, { token });
    } catch (err) {
      // The Reporting Service answers 404 when a restroom has no reports yet.
      if (err.status === 404 && err.code === "RESOURCE_NOT_FOUND") return [];
      throw err;
    }
  },

  async listReports({ restroomId, status, limit = 200 } = {}, token) {
    if (MOCK_MODE) {
      reports = stored("reports", reports);
      return reports
        .filter(
          (report) =>
            (!restroomId || report.restroomId === Number(restroomId)) &&
            (!status || report.status === status)
        )
        .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    }
    const params = new URLSearchParams({ limit: String(limit) });
    if (restroomId) params.set("restroomId", String(restroomId));
    if (status) params.set("status", status);
    return request(`/feedback?${params.toString()}`, { token });
  },

  async updateReportStatus(id, status, token) {
    if (MOCK_MODE) {
      reports = stored("reports", reports).map((report) =>
        report.reportId === Number(id) ? { ...report, status } : report
      );
      persist();
      return reports.find((report) => report.reportId === Number(id));
    }
    return request(`/feedback/reports/${id}/status`, {
      method: "PUT",
      body: { status },
      token,
    });
  },
  async health(token, all = false) {
    if (MOCK_MODE)
      return all
        ? {
            gateway: "UP",
            services: {
              registry_service: { status: "UP" },
              reporting_service: { status: "UP" },
            },
          }
        : { service: "API Gateway", status: "UP" };
    return request(all ? "/health/all" : "/health", { token });
  },
  async verifyStaff(token) {
    return request("/health/all", { token });
  },
  async searchPlaces(query) {
    if (MOCK_MODE)
      return {
        results: [
          { label: "Rizal Park (Luneta), Manila", lat: 14.583, lng: 120.979 },
        ],
        attribution: "OpenStreetMap contributors",
      };
    return request(`/geocode?q=${encodeURIComponent(query)}`);
  },
  async directions(start, end) {
    if (MOCK_MODE)
      throw new Error(
        "Walking directions need the live Gateway and an ORS_API_KEY."
      );
    const params = new URLSearchParams({
      start_lat: start.lat,
      start_lng: start.lng,
      end_lat: end.lat,
      end_lng: end.lng,
      profile: "foot-walking",
    });
    return request(`/directions?${params.toString()}`);
  },
};

const ALLOWED_SOURCE_STATES = new Set(["live", "degraded", "stale", "unavailable"]);
const ALLOWED_CONFIDENCE = new Set(["verified", "high", "medium", "low", "unknown"]);

function assertNumber(value, name) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${name} must be a finite number`);
  }
  return value;
}

function normalizeCoordinate(input = {}) {
  const latitude = assertNumber(input.latitude, "latitude");
  const longitude = assertNumber(input.longitude, "longitude");

  if (latitude < -90 || latitude > 90) throw new RangeError("latitude out of range");
  if (longitude < -180 || longitude > 180) throw new RangeError("longitude out of range");

  const coordinate = { latitude, longitude };
  if (input.altitudeMeters != null) {
    coordinate.altitudeMeters = assertNumber(input.altitudeMeters, "altitudeMeters");
  }
  return coordinate;
}

export function normalizeSpatialObservation(input, receivedAt = new Date().toISOString()) {
  if (!input || typeof input !== "object") throw new TypeError("observation input is required");
  if (!input.source || typeof input.source !== "object") throw new TypeError("source metadata is required");

  const sourceState = ALLOWED_SOURCE_STATES.has(input.source.state) ? input.source.state : "degraded";
  const confidence = ALLOWED_CONFIDENCE.has(input.source.confidence) ? input.source.confidence : "unknown";

  return {
    observationId: String(input.observationId),
    entityId: String(input.entityId),
    entityKind: String(input.entityKind || "other"),
    coordinate: normalizeCoordinate(input.coordinate),
    headingDegrees: input.headingDegrees == null ? undefined : assertNumber(input.headingDegrees, "headingDegrees"),
    speedMps: input.speedMps == null ? undefined : assertNumber(input.speedMps, "speedMps"),
    properties: input.properties && typeof input.properties === "object" ? input.properties : {},
    provenance: {
      sourceId: String(input.source.id),
      sourceName: String(input.source.name || input.source.id),
      observedAt: String(input.source.observedAt),
      receivedAt,
      sourceState,
      license: input.source.license ? String(input.source.license) : undefined,
      attribution: input.source.attribution ? String(input.source.attribution) : undefined,
      sourceUrl: input.source.url ? String(input.source.url) : undefined,
      confidence,
    },
    jurisdictionIds: Array.isArray(input.jurisdictionIds) ? input.jurisdictionIds.map(String) : [],
    evidenceOnly: true,
  };
}

export function observationMayAuthorizeAction() {
  return false;
}

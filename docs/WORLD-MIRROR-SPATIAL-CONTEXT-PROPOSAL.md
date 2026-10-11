# WORLD MIRROR: ATLAS Spatial Context and Scene Contract (proposal)

Status: PROPOSED, not implemented or production deployed. Companion GTM integration: `AGENTROPOLIS-GTM/docs/WORLD-MIRROR-LOCAL-COMMERCE-HUMAN-OS-INTEGRATION.md`.

## Ownership
ATLAS alone owns geocoding, reverse geocoding, nearby lookup, route calculation, provider authorization, geographic source provenance, geographic uncertainty, attribution, and spatial receipts. WORLD GRID renders scenes. Human Experience OS provides permissioned human/community context. CHAOS MALL owns merchant enrollment and sponsored inventory. GTM/SIGNAL orchestrates campaigns. 54T/AEGIS governs GEO-SHIELD.

## Proposed read-only provider-neutral interfaces

- `atlas_world_context`: input generalized area, purpose, authority geometry, scoped context and consent reference where required. Return geometry/landmarks/building metadata, timestamps, provenance, confidence, provider credits/required attributions, receipt. No private person-level traces.
- `atlas_world_scene`: derive public render manifest referencing licensed 2D tiles and optional 3D resources. Mark scene objects `observed`, `mapped`, `estimated`, `synthetic`; do not suggest worldwide photorealism.
- `atlas_visual_candidates`: optional opt-in geolocation from user-provided photo. Must produce uncertain ranked *area* candidates and explicit no-match behavior; default disabled; no covert subject tracking or sensitive addresses.
- `atlas_spatial_anchor`: bind a verified public place ref to a virtual placement candidate (not rights or authority). Property/brand rights verification belongs to business registry / GEO-SHIELD.
- `atlas_world_receipt`: validate spatial evidence, licensed sources, authority geometry, provider identity, required attributions and caller mandate.

New interfaces extend, not replace, current `atlas_geocode`, `atlas_reverse`, `atlas_nearby`, `atlas_route`, and `atlas_receipt`.

## Safety contract

1. Default to user-selected city; precise device location requires explicit permission. Offer non-tracking mode.
2. Precise coordinates never enter advertiser audiences or public receipts; generalized geography alone does not authorize targeting sensitive populations.
3. No mapped venue becomes a verified advertising merchant without separate proof of representation and campaign approval.
4. No physical building facade commercial rights are inferred from map geometry. Virtual-only placements are clearly marked.
5. Honor each map/imagery provider's licensing, attribution, caching and derivative-use limitations. Reject silent proprietary provider fallbacks.
6. Fail closed or reveal degraded map modes if provider is unavailable, mock-only or evidence is uncertain.
7. All external media and text are untrusted; no source content grants execution permission.
8. Maintain location consent revocation and retention policies. Avoid persistent individual movement trails.

## Verification gates

- Approved provider adapter integration tests, not only mocks
- Mobile 2D mode when device cannot render 3D
- Correct OSM/data credits and license compliance
- Attribution and scene object provenance tests
- Explicit unknown and missing source handling
- Sensitivity tests for homes, schools, shelters, care sites, and minors
- Fake sponsor/business claim denial
- Revocation stops precise calls and associated caches
- Offline/degraded 2D scene test
- Receiver integration tests with Human Experience OS, WORLD GRID, CHAOS MALL and GTM
- ATG spatial receipt generated for each request

## Phased deployment

P0: integrate schemas, GEO-SHIELD policy, provider review, and source licenses. Human Experience OS source repository pending user confirmation; `wiredchaos/hexos` is provisional.
P1: Sacramento bounded pilot using approved live geographic adapter, no ads, no precise persistence.
P2: verified merchants and explicitly labeled sponsored virtual inventory via CHAOS MALL (GTM decision and Fiscal budget gates).
P3: opt-in visual candidate matching and more detailed 3D scene only after privacy and accuracy evaluation.

Existing ATLAS Phase 001 remains deterministic mock provider adapters; this proposal must not be described as live capabilities.

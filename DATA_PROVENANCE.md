# Data provenance

SamudraRakshak AI keeps observed data, historical replay, model forecasts, derived values, and simulated collector assets separate. Counts below were validated on 12 September 2026; `data/catalog.json`, `data/catalog.yaml`, and `data/metadata/validation.json` are the machine-readable authority after a refresh.

## Downloaded data

| Dataset | Actual cached content | Provider and source | License / attribution |
| --- | --- | --- | --- |
| Port locations | 1,081 Natural Earth records and 3,630 NGA records; 3,744 port centers after spatial deduplication | [Natural Earth ports](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/ports/) and [NOAA-hosted NGA World Port Index, 2019](https://gis.ngdc.noaa.gov/arcgis/rest/services/nccos/PIRO_DigitalAtlas/MapServer/30) | Natural Earth public domain; US government public data. Attribute Natural Earth, NGA and NOAA. |
| Land and coastline | 8 regional land features and 340 coastline features, plus a simplified world backdrop | [Natural Earth](https://www.naturalearthdata.com/downloads/10m-physical-vectors/) | [Public domain](https://www.naturalearthdata.com/about/terms-of-use/). `10m` means a 1:10 million map scale, not ten-meter accuracy. |
| Marine boundaries | 17 EEZ polygons, 15 territorial-sea polygons, 15 contiguous-zone polygons and 1 high-seas feature after regional clipping | [Marine Regions WFS](https://www.marineregions.org/webservices.php), Flanders Marine Institute (VLIZ) | [CC BY and scientific-use disclaimer](https://www.marineregions.org/disclaimer.php). Raw full provider geometries remain local; browse the provider for current downloadable products. |
| Marine microplastics | 515 actual observations, sampled 2010-03-22 through 2021-12-08 | [NOAA NCEI Marine Microplastics](https://www.ncei.noaa.gov/products/microplastics), [public feature service](https://services2.arcgis.com/C8EMgrsFcRFL6LrL/ArcGIS/rest/services/Marine_Microplastics_WGS84/FeatureServer/0) | Public scientific data; preserve NOAA attribution, the original study reference, accession, DOI and reported units. Individual study restrictions, if any, remain applicable. |
| Marine environment | 74 valid sea-grid locations, each with 72 hourly forecast slots: 5,328 location-hours, 2026-09-12 through 2026-09-14 | [Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api); underlying Météo-France/Copernicus Marine and ECMWF models | CC BY 4.0 data. The free hosted endpoint is for non-commercial use. These are model forecasts, including fields called “current conditions.” |
| Coastal weather | Six locations with seven days of hourly and daily forecasts | [Open-Meteo forecast API](https://open-meteo.com/en/docs) | CC BY 4.0 data and provider attribution; free endpoint terms apply. |
| Regional bathymetry | 21,901 grid points at 15 arc-minute sampling, 0–30°N and 55–100°E | [NOAA ETOPO1 via Atlantic OceanWatch ERDDAP](https://oceanwatch.aoml.noaa.gov/erddap/griddap/etopo180.graph) | Public US government data. Cite Amante and Eakins (2009), [DOI 10.7289/V5C8276M](https://doi.org/10.7289/V5C8276M). |
| Historical AIS | 75,286 complete broadcasts; 11,037 distinct MMSI identities in the valid sample; 60 moving vessels with 926 retained real track points for responsive replay | [NOAA MarineCadastre current public AIS files](https://noaaocm.blob.core.windows.net/ais/csv2/csv2024/index.html); [provider project and data guidance](https://github.com/ocm-marinecadastre/ais-vessel-traffic) | Public US government data. Attribute NOAA Office for Coastal Management, BOEM, and US Coast Guard. These records concern US coastal waters and demonstrate global portability, not Indian vessel activity. |

The broad microplastic acquisition region is 40–105°E, 25°S–30°N. It contains 202 records labeled Bay of Bengal and 146 labeled Laccadive Sea by the provider, alongside other Indian Ocean and nearby-sea samples. Provider region names are retained unchanged. The sample coordinates determine where markers appear; observations are never moved to the Karnataka coast. The general detailed-map region is 55–100°E, 5°S–30°N.

## Three traceable historical vessel examples

`data/demo/historical_cases.json` selects three actual vessel movements. The names below are broadcast identities, not independent registry verification. None of these examples asserts illegal fishing, a verified AIS gap, an encounter, or a satellite match.

| Case | MMSI | AIS type | Actual retained broadcasts | Actual recording window, UTC |
| --- | --- | --- | --- | --- |
| AMERICAN DREAM | 367643270 | Fishing | 16 | 2024-01-01 00:00:00–00:16:46 |
| CONTSHIP AIR | 209705000 | Cargo | 17 | 2024-01-01 00:00:02–00:17:32 |
| MARK E. KUEBLER | 368058110 | Tug | 17 | 2024-01-01 00:00:01–00:16:56 |

The replay source is a bounded, non-random prefix sample of [NOAA's compressed 2024-01-01 CSV](https://noaaocm.blob.core.windows.net/ais/csv2/csv2024/ais-2024-01-01.csv.zst). NOAA returned HTTP 206 for `Range: bytes=0-2097151`. Only 2 MiB of the 196,492,824-byte compressed source was requested. The exact compressed prefix and 75,286 complete decoded CSV rows are retained under `data/raw/`. A final partial CSV line was discarded. Local SHA-256 checksums verify the retained files; the checksum of the complete remote archive has **not** been verified because the complete file was intentionally not downloaded. This sample covers 00:00:00–00:17:40 UTC and is unsuitable for population estimates. Absence after the sample boundary is never evidence of AIS disabling.

Reprocessing merges available GFW vessel records with these real NOAA replay records. A GFW authentication failure does not erase the NOAA replay cache.

## Field-level provenance and transformations

| Field or outcome | Authority / transformation | Limits |
| --- | --- | --- |
| AIS latitude, longitude, timestamp, speed, course, heading | AISStream `PositionReport` for live data; NOAA `latitude`, `longitude`, `base_date_time`, `sog`, `cog`, `heading` for historical replay | AIS-reported positions and identity can contain errors. Live points must carry their actual reception timestamp. |
| Historical vessel type | NOAA `vessel_type` AIS code: 30 fishing, 70–79 cargo, 80–89 tanker, 60–69 passenger, 31/32/52 tug | This is AIS classification, not proof of present activity or independent registry verification. |
| Vessel identity | NOAA broadcast MMSI/name/IMO/call sign; GFW registry records only when authenticated data was actually obtained | GFW data are currently unavailable because the supplied token was rejected with HTTP 401. NOAA identity is labeled by its own source. |
| Speed / heading missing values | AIS speed sentinel ≥102.3 knots and course/heading outside 0–359.999° become `null` | Missing observations are not assigned a speed or heading. |
| Course change | Shortest angular difference: `abs((next - previous + 180) % 360 - 180)` | A maneuver can be normal navigation. |
| Distance, straightness, loitering, anomaly | Backend geospatial / statistical computation over timestamped observed points | Computed behavior is distinct from historical event-provider evidence. |
| Current speed | Open-Meteo `ocean_current_velocity`, normalized according to the returned `current_units` | The cached provider response returns km/h, so m/s = km/h ÷ 3.6. The request parameter alone is not trusted to establish units. Hourly original units are retained. |
| Current direction, waves and temperature | Open-Meteo returned forecast values | All are `MODEL FORECAST`; coastal model resolution does not support safe navigation. |
| Port coordinates | Original Natural Earth or NGA geometry | Nearby centers within 0.055° are deduplicated; NGA attributes enrich matching Natural Earth centers. This threshold is a data-cleaning heuristic, not navigational accuracy. |
| Port country | NGA source country code, or nearest Natural Earth country polygon for Natural Earth ports | Nearest-polygon country is explicitly labeled as derived. Unknown UN/LOCODE values stay `null`. |
| Boundary context | Real VLIZ WFS polygons, clipped to the region and simplified 0.01° for display | These geometries have no definitive legal value. A protected-area restriction must not be inferred from EEZ membership. |
| Land intersection | Regional Natural Earth land polygons; full-resolution clipped file retained beside browser file | Cartographic data cannot establish a navigable channel or under-keel clearance. Global background simplification is 0.18°. |
| Bathymetry | ETOPO1 elevation in meters relative to mean sea level; negative elevation indicates depth | 15 arc-minute subsampling is context only, not a chart or safety clearance model. |
| Debris coordinates and concentration | NOAA geometry and `Microplastics_measurement`, with original `Unit`, sample date and DOI | `quantity` remains `null`: concentration is never converted into item count, kilograms, or recoverable debris mass. No numeric confidence is invented. |
| Debris regions | DBSCAN on real sample coordinates, haversine distance, 25 km neighborhood, minimum three observations | Offline scene anchors are historical sampling clusters. The backend may expose separately computed mission clusters with its own displayed parameters. |
| Drift, route fuel, CO₂, assignment and risk | Backend numerical models and algorithms | Risk is a bounded triage index: event types use explicit weights, while the composite observed-track anomaly contributes up to 40 points. Confidence is a metadata-completeness score using source, timestamp, raw observation, URL, vessel linkage, identity fields, temporal coverage and named-source diversity. Neither value is a calibrated probability or legal conclusion. |
| Collector position, battery and capacity | Explicit simulated assets / simulation controls | Never presented as operational robots or measured collection results. |
| LLM narrative | Explanation of structured evidence and computed outputs | The LLM does not create numerical evidence, vessel history, coordinates or legal conclusions. |

## Unavailable data and exact recovery paths

- **Global Fishing Watch**: the official identity and event endpoints returned `HTTP 401 invalid token`. Generate or verify an API access token through [GFW API authentication](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/authentication), then set `GFW_API_ACCESS_TOKEN` (or the curl-compatible `GFW_TOKEN`) in the root `.env` or launch environment before running `python scripts/acquire_gfw.py`. Public account-controlled exports are available through the [GFW data download portal](https://globalfishingwatch.org/data-download/). Existing compatible event-response JSON can be placed at `data/raw/gfw_events_fishing_0000.json`, `gfw_events_encounter_0000.json`, `gfw_events_loitering_0000.json`, `gfw_events_port_visit_0000.json`, or `gfw_events_gap_0000.json`; each must preserve the GFW `entries` response schema and source license. Identity-response JSON belongs at `data/raw/gfw_identity_000.json`. SAR and fishing-effort report JSON belong at `data/raw/gfw_report_sar.json` and `data/raw/gfw_report_fishing_effort.json`. CSV exports require conversion to this schema before import; the pipeline does not silently treat a CSV as an API response.
- **Marine protected areas**: **DATASET REQUIRES MANUAL DOWNLOAD**. Obtain an appropriately licensed India polygon export from [Protected Planet: India](https://www.protectedplanet.net/country/IND), following its [terms](https://www.protectedplanet.net/en/legal), convert to WGS84 GeoJSON if needed, and place it at `data/raw/india_mpa.geojson`. Then run `python scripts/preprocess_data.py`. Current `data/processed/mpa.geojson` is an empty FeatureCollection. Approximate circles are not substituted.
- **Marine Debris Tracker**: **DATASET REQUIRES MANUAL DOWNLOAD**. Select an appropriate observation list through [the provider data interface](https://debristracker.org/data/) and retain the export license. Place `data/raw/debris_tracker.csv` with columns `latitude`, `longitude`, `timestamp` (or `date`), `debris_category` (or `item`), `quantity`, and optionally `id`. Run preprocessing. Tracker data are saved separately at `data/processed/debris_tracker.json` and are not automatically mixed with concentration samples.
- **Copernicus enhancement**: supply `COPERNICUSMARINE_SERVICE_USERNAME` and `COPERNICUSMARINE_SERVICE_PASSWORD` only for an authorized download workflow using [Copernicus Marine](https://data.marine.copernicus.eu/). Direct credentialed extraction is not implemented in the bootstrap. Copernicus-derived current and temperature forecasts already arrive through Open-Meteo; the catalog does not claim a direct authenticated Copernicus connection.
- **Boundary retry**: all requested non-MPA boundary classes were obtained. If a future WFS call fails, download the corresponding scientific data from [Marine Regions](https://www.marineregions.org/downloads.php), retain attribution, convert to WGS84 GeoJSON, and place `data/raw/marineregions_eez.geojson`, `marineregions_territorial_sea.geojson`, `marineregions_contiguous_zone.geojson`, or `marineregions_high_seas.geojson`.

## Reproduction and integrity

```bash
python -m pip install -r scripts/requirements-data.txt
python scripts/acquire_data.py --all
python scripts/preprocess_data.py
python scripts/validate_data.py
```

The default bootstrap reuses existing downloads. Add `--refresh` to explicitly refresh a provider, for example `python scripts/acquire_data.py --only marine --refresh`. Provider failures retain the local files. `--no-preprocess` downloads only. The individual `acquire_gfw.py`, `acquire_boundaries.py`, `acquire_debris.py`, `acquire_ports.py`, and `acquire_bathymetry.py` entry points select their provider group. Historical AIS can be regenerated with `python scripts/acquire_data.py --only historical_ais`.

`data/download_manifest.json` records the source URL, request parameters, acquisition timestamp, local byte size, SHA-256 and processing state for every retained download or source-derived CSV. Credentials are loaded from `.env`, sent only to their provider, and excluded from manifests and browser data. Validation checks all retained hashes, coordinate ranges, valid geometries, marine unit conversion, null debris quantity semantics, and traceability of the three historical cases back to exact source CSV observations. Human-readable provider status is in `docs/DATA_STATUS.md`.

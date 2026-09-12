# Data status

Validated: 2026-09-12T13:37:37.910490+00:00. Validation passed: **True**.

**19 source files verified**, 101,625,866 retained bytes (96.92 MiB). No new downloads were required for this validation.

| Cached asset | Actual count |
| --- | ---: |
| ports | 3,744 |
| debris | 515 |
| marine | 74 |
| vessels | 60 |
| bathymetry | 21,901 |
| land | 8 |
| land world | 11 |
| coastline | 340 |
| boundaries | 48 |
| mpa | 0 |
| historical ais broadcast rows | 75,286 |
| historical ais replay points | 926 |
| historical demo cases | 3 |
| vessel identities | 11,037 |

The NOAA replay is real US coastal activity from 2024-01-01, explicitly shown as global demonstration context. The exact 926 displayed track points match source CSV latitude, longitude and timestamp. Three selected movement-review examples are AMERICAN DREAM (MMSI 367643270), CONTSHIP AIR (209705000), and MARK E. KUEBLER (368058110). There is no verified historical AIS gap, SAR match, illegal fishing determination or Indian GFW case in this cache.

All 74 marine locations carry model forecasts through 2026-09-14 23:00 UTC; their current snapshots are older than the validation time. UI freshness must use the stored forecast timestamp. Run `python scripts/acquire_data.py --only marine --refresh` to refresh when needed.

The 515 debris records are historical microplastic measurements. Quantities and recoverable kilograms are unknown. `data/demo/debris_regions.json` contains 36 deterministic sampling clusters, calculated with a 25 km DBSCAN radius and three-sample minimum.

## Provider state

| Provider dataset | State | Records |
| --- | --- | ---: |
| Natural Earth world ports | ready | 1,081 |
| Natural Earth 1:10 million land | ready | 8 |
| NOAA NCEI Marine Microplastics: Indian Ocean subset | ready | 515 |
| Open-Meteo Marine regional forecast grid | ready | 74 |
| NOAA ETOPO1 Indian Ocean 15 arc-minute subset | ready | 21,901 |
| Marine Debris Tracker exports | manual_download_required | 0 |
| Global Fishing Watch vessel identity | credentials_rejected | 0 |
| Open-Meteo coastal weather forecast | ready | 6 |
| Natural Earth 1:10 million coastline | ready | 340 |
| Copernicus Marine enhanced ocean data | credentials_required | 0 |
| Marine Regions eez | ready | 17 |
| Marine Regions territorial sea | ready | 15 |
| Marine Regions contiguous zone | ready | 15 |
| Marine Regions high seas | ready | 1 |
| World Database on Protected Areas marine polygons | manual_download_required | 0 |
| NGA World Port Index 2019 via NOAA digital atlas | ready | 3,630 |
| NOAA MarineCadastre actual AIS broadcast prefix sample, 2024-01-01 | ready | 75,286 |
| Global Fishing Watch fishing events | credentials_rejected | 0 |
| Global Fishing Watch encounters | credentials_rejected | 0 |
| Global Fishing Watch loitering | credentials_rejected | 0 |
| Global Fishing Watch port visits | credentials_rejected | 0 |
| Global Fishing Watch AIS gaps | credentials_rejected | 0 |
| Global Fishing Watch SAR detection report | credentials_rejected | 0 |
| Global Fishing Watch fishing activity report | credentials_rejected | 0 |

## Access that remains unavailable

- **Global Fishing Watch:** official identity and event probes rejected the supplied token with HTTP 401. Other GFW products remain blocked by that authentication failure; they were not obtained. Replace the token in `.env`, then run `python scripts/acquire_gfw.py`. NOAA historical replay survives an unsuccessful retry.
- **Protected Planet MPA polygons:** account/terms-controlled download required. Obtain India polygons from [Protected Planet](https://www.protectedplanet.net/country/IND) and place WGS84 GeoJSON at `data/raw/india_mpa.geojson`.
- **Marine Debris Tracker:** provider export selection is required. Save a licensed CSV to `data/raw/debris_tracker.csv`; exact supported columns are in [DATA_PROVENANCE.md](../DATA_PROVENANCE.md). NOAA observations already work offline.
- **Direct Copernicus retrieval:** optional credentials and a dedicated download workflow are still required. The bootstrap does not implement direct extraction; Open-Meteo already provides Copernicus-derived forecasts.

The full source URLs, licensing, acquisition method, transformation parameters and precise recovery filenames are documented in [DATA_PROVENANCE.md](../DATA_PROVENANCE.md). Refresh commands preserve raw caches unless `--refresh` is explicitly used. `python scripts/preprocess_data.py` is offline and `python scripts/validate_data.py` verifies the retained data.

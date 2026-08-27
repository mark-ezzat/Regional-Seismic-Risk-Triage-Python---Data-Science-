import csv
import json
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

IDS_FILE = RAW_DIR / "extracted_ids.txt"
SENSOR_LOG = RAW_DIR / "regional_sensor_log.csv"
CLEAN_CSV = PROCESSED_DIR / "clean_data.csv"
USGS_CACHE = RAW_DIR / "usgs_raw.json"

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MAG_PAGE = "https://earthquake.alaska.edu/earthquake-magnitude-classes"

START_DATE = "2026-08-01"
END_DATE = "2026-08-25"
MIN_MAG = 2.5


# Tier 1 — Function definitions

def fetch_usgs_data():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if USGS_CACHE.exists():
        print("Loading cached USGS data...")
        with open(USGS_CACHE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("features", [])

    params = {
        "format": "geojson",
        "starttime": START_DATE,
        "endtime": END_DATE,
        "minmagnitude": MIN_MAG,
    }

    print("Fetching data from USGS API")
    try:
        response = requests.get(USGS_URL, params=params, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("API request failed:", e)
        return []

    payload = response.json()
    with open(USGS_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    features = payload.get("features", [])
    print(f"Fetched {len(features)} features")
    return features


def save_event_ids(features):
    ids = []
    for feature in features:
        event_id = feature.get("id")
        if event_id:
            ids.append(event_id)

    with open(IDS_FILE, "w", encoding="utf-8") as f:
        for event_id in ids:
            f.write(event_id + "\n")

    print(f"Saved {len(ids)} event ids to {IDS_FILE}")
    return ids


def scrape_great_threshold():
    try:
        response = requests.get(MAG_PAGE, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("Scrape failed, using default 8.0:", e)
        return 8.0

    text = response.text
    anchor = "magnitudes greater than"
    idx = text.find(anchor)

    if idx == -1:
        print("Anchor phrase not found, using default 8.0")
        return 8.0

    # Take a small window after the phrase and print it (as the brief asks)
    window = text[idx: idx + 60]
    print("Scrape window:", repr(window))

    after = text[idx + len(anchor):].strip()
    token = after.split(",")[0].split()[0].strip()

    try:
        threshold = float(token)
        print("Great threshold =", threshold)
        return threshold
    except ValueError:
        print("Could not parse number, using default 8.0")
        return 8.0


def load_sensor_log():
    log = {}

    if not SENSOR_LOG.exists():
        print("Sensor log not found. Run generate_aftershock_log.py first.")
        return log

    with open(SENSOR_LOG, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            event_id = (row.get("event_id") or "").strip()
            if event_id:
                log[event_id] = row

    print(f"Loaded {len(log)} rows from sensor log")
    return log


def safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_median(values):
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2


def parse_place(place):
    if not place or not isinstance(place, str):
        return None, None

    if " of " in place:
        parts = place.split(" of ", 1)
        prefix = parts[0].strip() or None
        location = parts[1].strip() or None
        return prefix, location

    return None, place.strip() or None


def depth_category(depth_km):
    if depth_km is None:
        return "unknown"
    if depth_km < 70:
        return "shallow"
    if depth_km <= 300:
        return "intermediate"
    return "deep"


def clean_and_engineer(features, great_threshold, sensor_log):
    quakes = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("type") == "earthquake":
            quakes.append(feature)

    print(f"Cohort filter: {len(features)} -> {len(quakes)} earthquakes")

    # ----- Collect non-null values for median imputation -----
    gap_vals = []
    dmin_vals = []
    nst_vals = []

    for feature in quakes:
        props = feature.get("properties") or {}
        g = safe_float(props.get("gap"))
        d = safe_float(props.get("dmin"))
        n = safe_float(props.get("nst"))
        if g is not None:
            gap_vals.append(g)
        if d is not None:
            dmin_vals.append(d)
        if n is not None:
            nst_vals.append(n)

    gap_median = compute_median(gap_vals)
    dmin_median = compute_median(dmin_vals)
    nst_median = compute_median(nst_vals)
    print(f"Medians -> gap: {gap_median}, dmin: {dmin_median}, nst: {nst_median}")

    cleaned = []

    for feature in quakes:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None, None]
        event_id = feature.get("id")

        # Geometry
        lon = safe_float(coords[0]) if len(coords) > 0 else None
        lat = safe_float(coords[1]) if len(coords) > 1 else None
        depth_km = safe_float(coords[2]) if len(coords) > 2 else None

        # Core fields
        mag = safe_float(props.get("mag"))
        sig = safe_float(props.get("sig"))
        felt = safe_float(props.get("felt"))
        cdi = safe_float(props.get("cdi"))
        gap = safe_float(props.get("gap"))
        dmin = safe_float(props.get("dmin"))
        nst = safe_float(props.get("nst"))

        # Tsunami flag
        tsunami = props.get("tsunami")
        try:
            tsunami = int(tsunami) if tsunami is not None else 0
        except (TypeError, ValueError):
            tsunami = 0

        if felt is None:
            felt = 0.0
        if cdi is None:
            cdi = 0.0

        if gap is None:
            gap = gap_median
        if dmin is None:
            dmin = dmin_median
        if nst is None:
            nst = nst_median

        # Place parsing
        place = props.get("place")
        dist_prefix, location = parse_place(place)

        # Engineered features
        depth_cat = depth_category(depth_km)

        pct_great = None
        if mag is not None and great_threshold:
            pct_great = (mag / great_threshold) * 100.0

        # Target from Phase 1 formula
        if mag is not None and mag >= 5.0:
            significant = 1
        else:
            significant = 0

        # Join sensor log (defensive .get for missing + ghost ids)
        log_row = sensor_log.get(event_id or "", {})
        station_network = (log_row.get("station_network") or "").strip() or None

        claims_raw = log_row.get("local_claims_filed")
        claims_filed = None
        if claims_raw is not None:
            cleaned_claims = str(claims_raw).strip().lower()
            if cleaned_claims not in ("", "n/a", "null"):
                try:
                    claims_filed = int(float(cleaned_claims))
                except (TypeError, ValueError):
                    claims_filed = None

        record = {
            "event_id": event_id,
            "mag": mag,
            "depth_km": depth_km,
            "lon": lon,
            "lat": lat,
            "sig": sig,
            "felt": felt,
            "cdi": cdi,
            "gap": gap,
            "dmin": dmin,
            "nst": nst,
            "tsunami": tsunami,
            "place": place,
            "distance_prefix": dist_prefix,
            "location": location,
            "depth_category": depth_cat,
            "pct_of_great_threshold": pct_great,
            "significant": significant,
            "station_network": station_network,
            "local_claims_filed": claims_filed,
            "time": props.get("time"),
            "magType": props.get("magType"),
            "status": props.get("status"),
            "net": props.get("net"),
        }
        cleaned.append(record)

    return cleaned


def min_max_scale(records, field="mag"):
    values = []
    for r in records:
        v = r.get(field)
        if v is not None:
            values.append(v)

    if not values:
        for r in records:
            r["scaled_" + field] = None
        return

    min_x = min(values)
    max_x = max(values)
    denom = max_x - min_x

    for r in records:
        x = r.get(field)
        if x is None or denom == 0:
            r["scaled_" + field] = None
        else:
            r["scaled_" + field] = (x - min_x) / denom

    print(f"Min-max scaled '{field}' (min={min_x}, max={max_x})")


def validation_check(records):
    sig_flagged = []
    sig_routine = []

    for r in records:
        s = r.get("sig")
        if s is None:
            continue
        if r.get("significant") == 1:
            sig_flagged.append(s)
        else:
            sig_routine.append(s)

    avg_flagged = sum(sig_flagged) / len(sig_flagged) if sig_flagged else 0
    avg_routine = sum(sig_routine) / len(sig_routine) if sig_routine else 0

    print(f"Avg sig (significant=1): {avg_flagged:.2f}  (n={len(sig_flagged)})")
    print(f"Avg sig (significant=0): {avg_routine:.2f}  (n={len(sig_routine)})")
    return avg_flagged, avg_routine


def write_clean_csv(records):
    if not records:
        print("No records to write.")
        return

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = list(records[0].keys())
    with open(CLEAN_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote {len(records)} rows to {CLEAN_CSV}")



# Tier 2 — Main execution guard

if __name__ == "__main__":
    print("=" * 50)
    print("Project Aftershock — Pipeline starting")
    print("=" * 50)

    # 1. Fetch USGS data
    features = fetch_usgs_data()
    print(f"Working with {len(features)} features")

    # 2. Save event ids
    save_event_ids(features)

    # 3. Scrape great-magnitude threshold
    great_threshold = scrape_great_threshold()

    # 4. Load sensor log
    #    (run: python generate_aftershock_log.py --input-ids data/raw/extracted_ids.txt --seed 42)
    sensor_log = load_sensor_log()

    # 5. Clean, impute, engineer features, join
    cleaned = clean_and_engineer(features, great_threshold, sensor_log)

    # 6. Min-max scale magnitude
    min_max_scale(cleaned, field="mag")

    # 7. Validation check
    avg_flagged, avg_routine = validation_check(cleaned)

    # 8. Write output CSV
    write_clean_csv(cleaned)

    # 9. ROI metric
    n_total = len(cleaned)
    n_flagged = 0
    for r in cleaned:
        if r.get("significant") == 1:
            n_flagged += 1

    if n_total > 0:
        pct_reduction = (1 - (n_flagged / n_total)) * 100
    else:
        pct_reduction = 0.0

    print(f"ROI: n_total={n_total}, n_flagged={n_flagged}, "
          f"pct_workload_reduction={pct_reduction:.1f}%")

    if avg_flagged > avg_routine:
        print("Validation OK: flagged events have higher average sig.")
    else:
        print("Validation warning: flagged events do NOT have higher average sig.")

    print("=" * 50)
    print("Pipeline complete.")
    print("=" * 50)
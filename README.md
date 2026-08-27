# Project Aftershock — Regional Seismic Risk Triage

**Domain:** Seismology / Public Safety & Insurance  
**Libraries used:** `requests`, `json`, `csv`, `pathlib`  
**Forbidden:** pandas, numpy, beautifulsoup4  

---

## 1. Business Objectives (Phase 1)

Build an automated first-pass triage flag for recent seismic events.  
Given a live pull from the USGS catalog, decide which events need an immediate
regional loss estimate and which can wait for routine review.

### Target Definition

```
significant = 1   if magnitude >= 5.0
significant = 0   otherwise
```

5.0 is the “moderate” magnitude floor. Using a higher floor (for example 8.0)
would produce almost no positive labels in a typical multi-week window.

### Resource Audit

| Resource        | Detail                                              |
|-----------------|-----------------------------------------------------|
| API access      | None needed — USGS catalog is public                |
| Rate limit      | One well-scoped query is enough                     |
| Data sources    | USGS FDSN API, generated sensor log, 1 web scrape   |
| Estimated time  | 3–5 hours                                           |

### Brainstormed Features (minimum 6)

1. `mag` — magnitude  
2. `depth_km` — hypocentral depth  
3. `sig` — USGS significance score  
4. `felt` — number of felt reports  
5. `gap` — station azimuthal gap  
6. `tsunami` — tsunami flag  
7. `type` — event type  
8. `location` — parsed from the place string  
9. `pct_of_great_threshold` — engineered feature  
10. `depth_category` — engineered feature (shallow / intermediate / deep)

### ROI Metric

```
pct_workload_reduction = (1 - (n_flagged / n_total)) * 100
```

On the cleaned dataset from this pipeline run:

- n_total = 1780  
- n_flagged = 156  
- **pct_workload_reduction = 91.2 %**

If only significant == 1 events create a loss-estimate ticket, manual review
volume drops by about 91 %.

---

## 2. Project Layout

```
Python Mini-Project (Aftershock)/
├── data/
│   ├── raw/
│   │   ├── extracted_ids.txt
│   │   ├── regional_sensor_log.csv
│   │   └── usgs_raw.json
│   └── processed/
│       └── clean_data.csv
├── notebooks/
│   └── exploration.ipynb
├── src/
│   └── pipeline.py
├── generate_aftershock_log.py
└── README.md
```

---

## 3. How to Run

```bash
# 1. Generate the messy sensor log from the extracted ids
python generate_aftershock_log.py --input-ids data/raw/extracted_ids.txt --seed 42

# 2. Run the pipeline
python src/pipeline.py
```

What the pipeline does step by step:

1. Fetch (or load cached) USGS data for 2026-08-01 to 2026-08-25  
2. Save event ids  
3. Scrape the “great” magnitude threshold (8.0)  
4. Load the sensor log  
5. Keep only type == "earthquake"  
6. Impute missing values (0 for felt/cdi, median for gap/dmin/nst)  
7. Engineer depth_category, pct_of_great_threshold, significant  
8. Join sensor-log fields with a defensive .get()  
9. Min-max scale magnitude  
10. Print validation numbers and write clean_data.csv  

---

## 4. Phase 2 EDA Summary

See `notebooks/exploration.ipynb`.

- Recursive structural audit shows nested properties vs geometry.coordinates  
- Native loops compute min / max / mean for mag and depth  
- Null-rate table shows high missing rates for felt, cdi, mmi, alert  
- Event-type breakdown (this window was 100 % earthquake)

---

## 5. Phase 3 Design Choices

| Choice                         | Why                                              |
|--------------------------------|--------------------------------------------------|
| Keep only type == "earthquake" | Explosions / quarry blasts are not useful here   |
| felt / cdi → 0                 | Null means “no reports” (semantic zero)          |
| gap / dmin / nst → median      | Null means “unknown quality” (not zero)          |
| Split place on " of "          | Some offshore events do not contain that token   |
| depth_category                 | Standard shallow / intermediate / deep bands     |
| pct_of_great_threshold         | mag / 8.0 * 100                                  |
| Min-max only on mag            | Exactly as required by the brief                 |

### Validation Check

Average USGS `sig` score:

- significant == 1 → about **463**  
- significant == 0 → about **209**

Flagged events have a clearly higher average significance.  
This confirms that the magnitude ≥ 5.0 rule is capturing the more important events.

---

## 6. Deliverables Checklist

| File                                   | Status |
|----------------------------------------|--------|
| README.md                              | Done   |
| notebooks/exploration.ipynb            | Done   |
| src/pipeline.py                        | Done   |
| data/processed/clean_data.csv          | Done   |
| data/raw/extracted_ids.txt             | Done   |
| data/raw/regional_sensor_log.csv       | Done   |

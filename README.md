# GDELT Knowledge Graph

An interactive knowledge graph and intelligence dashboard built on the [GDELT 2.0](https://www.gdeltproject.org/) dataset (2024). The project filters 26.7 million geopolitical events down to ~1.1 million causally significant events across the world's 10 most active countries, then visualizes them through a browser-based intelligence dashboard.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)
![DuckDB](https://img.shields.io/badge/DuckDB-0.10+-yellow)
![D3.js](https://img.shields.io/badge/D3.js-v7-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## Overview

GDELT (Global Database of Events, Language, and Tone) is the world's largest open-source event database, monitoring broadcast, print, and web news globally. This project takes the full 2024 GDELT export (~24GB, 365 daily Parquet files) and:

1. **Filters** to the top 10 countries by event volume
2. **Identifies causal chains** using temporal proximity analysis
3. **Validates source URLs** to remove events with dead news links
4. **Visualizes** the cleaned data through a 5-tab interactive dashboard

### Top 10 Countries Analyzed
| Code | Country | Code | Country |
|------|---------|------|---------|
| US | United States | UK | United Kingdom |
| IS | Israel | PK | Pakistan |
| UP | Ukraine | NI | Nigeria |
| RS | Russia | DJ | Djibouti |
| IN | India | AS | Australia |

---

## Features

### Knowledge Graph Tab
- **Circular & force-directed** graph layouts (toggle between them)
- **Curved bezier edges** with CAMEO event-type labels (e.g., "DEMAND", "COOPERATE")
- **Edge threshold slider** to control visual density
- **Click edges** to open a detail drawer showing: CAMEO description, event statistics, monthly frequency chart, causal chain analysis, and sample events with source links
- **Click nodes** to highlight a country's connections

### Timeline Tab
- Stacked bar chart showing monthly event volume by QuadClass (Verbal/Material Cooperation & Conflict)
- Goldstein Scale trend line overlay showing sentiment over time

### Country Analysis Tab
- Cards for each country with flag, total event count, QuadClass breakdown bar, and monthly sparkline

### Event Explorer Tab
- Paginated, searchable table of all events
- Filter by QuadClass (cooperation/conflict chips)
- Color-coded rows by event type

### Heatmap Tab
- 10x10 country-pair interaction matrix
- Toggle between event count and average Goldstein Scale modes

---

## Architecture

```
capstone_data/
├── app.py                  # FastAPI backend (7 API endpoints + static file serving)
├── requirements.txt        # Python dependencies
├── frontend/
│   └── index.html          # Single-page app (D3.js, Chart.js, vanilla JS)
├── pipeline/
│   ├── 01_filter_countries.py   # Step 1: Country filter (DuckDB SQL on Parquet)
│   ├── 02_causal_filter.py      # Step 2: Causal in-degree filter (DuckDB window functions)
│   ├── 03_validate_urls.py      # Step 3: Async URL validation (aiohttp)
│   ├── 04_export_neo4j.py       # Step 4: Neo4j graph database export
│   └── utils.py                 # Shared lookups (CAMEO codes, country names)
├── out/                         # Pipeline outputs (generated, not committed)
│   ├── step1_country_filtered.parquet
│   ├── step2_causal_filtered.parquet
│   ├── step3_url_validated.parquet
│   └── url_cache.json
├── out_parquet/                 # Raw GDELT Parquet data (24GB, not committed)
│   └── events/year=2024/month=MM/day=YYYYMMDD/part-00000.parquet
└── data/
    ├── reference_lookups/       # CAMEO PDF lookup tables
    └── themes/                  # GKG theme aggregations
```

---

## Data Pipeline

The pipeline progressively cleans and filters the raw GDELT data:

### Step 1: Country Filter (`01_filter_countries.py`)
- Reads all 365 daily Parquet files via **DuckDB** SQL (no need to load 24GB into RAM)
- Filters events where any actor or location matches the top 10 countries
- **Input:** 26.7M events (24GB) | **Output:** 26.7M events (data was pre-filtered)

### Step 2: Causal Filter (`02_causal_filter.py`)
- Computes **causal in-degree** for each event: how many prior events (within a 7-day window) share the same country-pair and CAMEO root code
- Uses DuckDB window functions (`COUNT(*) OVER PARTITION BY ... RANGE BETWEEN INTERVAL 7 DAYS PRECEDING`) for memory-efficient computation
- Keeps events with `causal_in_degree <= 2` (root causes and simple chains)
- **Input:** 26.7M events | **Output:** 1.12M events (4.2% retained)

### Step 3: URL Validation (`03_validate_urls.py`)
- Validates every unique `SOURCEURL` via async HTTP HEAD requests
- **aiohttp** with concurrency=50, timeout=10s, 1 retry on failure
- Marks URLs as dead if status is 404, 410, 451, or connection error
- Caches results to `url_cache.json` (resume-safe for long runs)
- **Input:** ~530K unique URLs | **Output:** drops events with dead URLs

### Step 4: Neo4j Export (`04_export_neo4j.py`)
- Loads cleaned data into **Neo4j** graph database
- Creates nodes: `Event`, `Country`, `Actor`, `Article`
- Creates relationships: `ACTOR1_IN`, `ACTOR2_IN`, `OCCURRED_IN`, `MENTIONED_IN`, `PRECEDED_BY`
- Uses batched `MERGE` statements (batch size 500) with uniqueness constraints

```
Graph Schema:
  (Actor) -[:ACTOR1_IN]-> (Event) -[:OCCURRED_IN]-> (Country)
  (Actor) -[:ACTOR2_IN]-> (Event) -[:MENTIONED_IN]-> (Article)
                          (Event) -[:PRECEDED_BY]->  (Event)
```

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Total events, date range, country count |
| `GET /api/graph` | Knowledge graph data (nodes + edges with QuadClass & CAMEO labels) |
| `GET /api/edge-detail` | Detailed edge info: CAMEO description, sample events, causal analysis |
| `GET /api/timeline` | Monthly QuadClass breakdown + Goldstein trend |
| `GET /api/country-stats` | Per-country stats with monthly sparkline data |
| `GET /api/events` | Paginated event list with search & filter |
| `GET /api/heatmap` | 10x10 country-pair interaction matrix |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.10+, FastAPI, DuckDB |
| **Frontend** | Vanilla JS, D3.js v7, Chart.js |
| **Data Processing** | DuckDB (SQL on Parquet), Polars, aiohttp |
| **Graph Database** | Neo4j (optional, for Cypher queries) |
| **Data Format** | Apache Parquet (Hive-partitioned) |

---

## Getting Started

### Prerequisites
- Python 3.10+
- GDELT 2024 Parquet data in `out_parquet/events/year=2024/` (not included in repo due to size)
- Neo4j (optional, only for Step 4)

### Installation

```bash
# Clone the repo
git clone https://github.com/<your-username>/gdelt-knowledge-graph.git
cd gdelt-knowledge-graph

# Install dependencies
pip install -r requirements.txt
pip install fastapi uvicorn
```

### Running the Pipeline

```bash
# Step 1: Filter to top 10 countries
python pipeline/01_filter_countries.py

# Step 2: Causal filtering (takes ~5 min on 26.7M events)
python pipeline/02_causal_filter.py

# Step 3: Validate URLs (long-running, resume-safe)
python pipeline/03_validate_urls.py

# Step 4: Export to Neo4j (requires running Neo4j instance)
# Set NEO4J_PASSWORD=yourpassword first
python pipeline/04_export_neo4j.py
```

### Running the Dashboard

```bash
# Start the server (uses step2 or step3 data automatically)
uvicorn app:app --reload --port 8000

# Open in browser
# http://localhost:8000
```

---

## Key Concepts

### CAMEO Event Codes
GDELT uses the [CAMEO](https://parusanalytics.com/eventdata/data.dir/CAMEO.Manual.1.1b3.pdf) coding system with 20 root event types:

| Code | Type | Code | Type |
|------|------|------|------|
| 01 | Public Statement | 11 | Disapprove |
| 02 | Appeal | 12 | Reject |
| 03 | Express Intent to Cooperate | 13 | Threaten |
| 04 | Consult | 14 | Protest |
| 05 | Diplomatic Cooperation | 15 | Exhibit Force |
| 06 | Material Cooperation | 16 | Reduce Relations |
| 07 | Provide Aid | 17 | Coerce |
| 08 | Yield | 18 | Assault |
| 09 | Investigate | 19 | Fight |
| 10 | Demand | 20 | Mass Violence |

### QuadClass
Events are categorized into 4 quadrants:
- **Verbal Cooperation** (1) — diplomatic statements, agreements
- **Material Cooperation** (2) — aid, trade, physical assistance
- **Verbal Conflict** (3) — threats, demands, accusations
- **Material Conflict** (4) — military action, violence, sanctions

### Goldstein Scale
A numeric score from **-10** (most conflictual) to **+10** (most cooperative) measuring the theoretical impact of an event on country stability.

---

## Dataset

The raw GDELT 2.0 data (not included in this repo) consists of:
- **365 daily Parquet files** (Hive-partitioned by year/month/day)
- **~26.7 million events** for the year 2024
- **13 columns per event:** GlobalEventID, EventCode, EventRootCode, QuadClass, GoldsteinScale, Actor1Name, Actor1CountryCode, Actor2Name, Actor2CountryCode, ActionGeo_CountryCode, SOURCEURL, day, datetime

To obtain the data, visit the [GDELT Project](https://www.gdeltproject.org/) and download the 2024 event files.

---

## License

This project is for educational and research purposes. GDELT data is freely available under the [GDELT Terms of Use](https://www.gdeltproject.org/about.html#termsofuse).

# 💊 TrustMed — Drug Knowledge Assistant

An intelligent conversational assistant that answers complex drug and pharmaceutical queries using **Rasa**, **Neo4j**, and a custom **medical knowledge graph** — exposed through REST and a lightweight web chat UI.

> ⚠️ **Medical Disclaimer:** TrustMed is a technical demo for information retrieval and graph exploration. It is **not** a medical device and does **not** provide medical advice. Always consult a licensed professional for medical decisions.

---

## 🧠 Overview

**TrustMed** lets you explore relationships between drugs, ingredients, brands, and related concepts using natural language. The assistant supports queries like:

- “What are the active ingredients in `<Product>`?”
- “List products that contain `<Ingredient>`.”
- “What’s the generic for `<Brand>`?”
- “Find substitutes for `<Product>` with the same active set.”
- “Common co-ingredients with `<Ingredient>`.”
- “Suggest ingredients related to `<Ingredient>` by frequent co‑formulation.”
- “Show strengths near `<Ingredient>` parsed from product names.”

### What powers the assistant

- **Rasa NLU** for intents/entities (DIET) and light regex for numeric `top_k`
- **Neo4j** graph for fast traversal queries over UMLS/RxNorm‑derived concepts
- **Custom Action Server** that calls a unified **KnowledgeBase** class
- **Docker Compose** to orchestrate Neo4j + Rasa + Actions (+ static web UI)

---

## 🧩 System Architecture

```
+-------------------+
|   Web UI (HTML)   |
+-------------------+
│   REST /webhook
▼
+-------------------+
|   Rasa Server     |  <-- intents/entities (DIET); slots incl. top_k
+-------------------+
│   actions endpoint
▼
+-------------------+
|  Action Server    |  <-- calls KnowledgeBase methods
+-------------------+
│   Bolt driver
▼
+-------------------+
|   Neo4j Graph DB  |  <-- UMLS/RxNorm concepts + relations
+-------------------+
```

All components run locally via **Docker Compose** or can be started individually.

---

## 🗂️ Project Structure

```
TrustMedProject/
│
├── actions/
│   └── actions.py              # Rasa actions + façade (high-level API)
│
├── data/                       # Training data (intents, stories, rules, tests)
│   ├── nlu.yml
│   ├── stories.yml
│   ├── rules.yml
│   └── tests/nlu.yml
│
├── web/
│   └── index.html              # Minimal chat UI (served via Nginx or any static server)
│
├── results/                    # Optional eval artifacts
│
├── knowledge_base.py           # Neo4j query layer (typed accessors)
├── load_data.py                # UMLS → Neo4j loader (MRCONSO/MRREL)
│
├── config.yml                  # NLU pipeline & policies
├── domain.yml                  # Intents, entities, slots (e.g., top_k), responses
├── credentials.yml             # Channels (REST) and Rasa Enterprise dev channel
├── endpoints.yml               # Action server URL
│
├── Dockerfile                  # Rasa image
├── Dockerfile.actions          # Action server image
├── docker-compose.yml          # Neo4j + Rasa + Actions + Web
└── README.md                   # This file
```

---

## 📦 Dataset

This project uses the **UMLS Metathesaurus** (principally **RxNorm** + **SNOMED CT US**) to build a medication-oriented graph:

> The dataset is large and license‑gated; it is **not** bundled here. Apply for a free [UMLS license](https://uts.nlm.nih.gov/uts/signup-login), download the [Metathesaurus archive (Level 0 Subset)](https://www.nlm.nih.gov/research/umls/licensedcontent/umlsknowledgesources.html), and extract it under `Data/META/` locally.

### Dataset Highlights

- **Structured for Semantics:** Unlike a simple dictionary, the UMLS provides not just terms but also the semantic relationships between them, making it ideal for building a knowledge graph.
- **Massive Scale:** Our knowledge graph was built using **354,029** unique medical concepts (nodes) derived from authoritative sources within the UMLS, including RxNorm and SNOMED CT.
- **Rich Connectivity:** The concepts are linked by over **23 million** relationships (edges), forming a dense semantic network that allows for complex queries and the discovery of non-obvious connections between drugs.

### Files expected by the loader

- `Data/META/MRCONSO.RRF`: The concepts file. This acts as our dictionary, containing the Concept Unique Identifier (CUI) for every term and its human-readable name. **Concepts** from `MRCONSO.RRF` become `(:Concept {cui, name})`
- `Data/META/MRREL.RRF`: The relationships file. This file defines the web of connections, linking concepts together with specific relationship attributes. **Relationships** from `MRREL.RRF` become `(:Concept)-[:RELATED_TO {type, rela}]->(:Concept)`

### Why UMLS/RxNorm?

- Standardized drug names and relationships
- Rich cross‑links for brands ↔ generics ↔ ingredients
- Well‑suited for graph queries like “co‑formulated” partners and ingredient overlaps

### How We Use It

1. We download the UMLS Metathesaurus Level 0 Subset.
2. A custom Python script (`load_data.py`) parses two key files from this subset.
3. The script extracts relevant concepts (drugs, formulations) and relationships.
4. This structured data is then ingested into a Neo4j graph database, which serves as the "brain" for our conversational agent.

---

## 🔎 Bottom-Up Focused Slice (Overlay Mode)

To measure quality quickly and iterate safely, the project also includes a small, **curated dataset** (overlay) that the action server can consult before querying the full graph.

### Scope

- **Therapeutic family**: ACE inhibitors (e.g., lisinopril, enalapril, captopril)
- **Common combo partner**: hydrochlorothiazide (HCTZ)

### Where it comes from

- **RxNav (RxNorm web services)**: ingredients, products (SCD/SBD), brand↔generic links
- **openFDA labels**: lightweight evidence pointers (label IDs shown in responses)

### Overlay CSVs (example counts from a reference run)

```
focused_dataset/
├── ingredients.csv            # 11 ingredients
├── products.csv               # 261 products (SCD/SBD)
├── product_ingredient.csv     # 311 product↔ingredient pairs
├── brand_generic.csv          # 164 brand↔generic links
└── evidence.csv               # 100 openFDA label IDs
```

### Generating the slice

Inside `focused_dataset/` run the scripts in order (Python 3.8+):

```
python step1_fetch_ace_ingredients.py       # seed ACE inhibitors (+ HCTZ)
python step2_expand_products.py             # expand to SCD/SBD products and pairs
python step3_brand_generic.py               # build brand↔generic links
python step4_evidence_openfda.py            # collect openFDA label IDs (optional)
python eval_runner.py                       # run a quick end-to-end evaluation
```

### Enabling overlay mode

The action server auto-loads overlays from `FOCUS_DIR` (defaults to `/app/focused_dataset`).

```
# Local processes
export FOCUS_DIR=/path/to/TrustMedProject/focused_dataset

# Docker Compose (example)
#   - mount ./focused_dataset:/app/focused_dataset:ro
#   - set environment: FOCUS_DIR=/app/focused_dataset
```

When present, the overlay is used for **brand_to_generic**, **product_ingredients**, and **products_by_ingredient**; other queries still fall back to Neo4j.

---

## 🧮 Trust Score

Each answer includes a **Trust Score (0–100)** and a short **“Why”** line.

- **Formula**: `score = round(100 × (0.5·DataPrior + 0.3·QueryQuality + 0.2·NLUConfidence))`
- **Labels**: High (≥80), Medium (60–79), Low (<60)
- **Evidence**: When available, openFDA label IDs are appended (e.g., `Evidence: <id1>, <id2>`)

This makes results transparent for reviewers and end-users.

---

## ⚙️ Setup & Prerequisites

- **OS:** macOS / Linux / Windows (WSL2 recommended)
- **Docker Desktop** (for Compose)
- **Python 3.8+** (only needed if running outside Docker)
- **Neo4j 5.x** with **APOC** plugin (enabled in Neo4j config) for strength parsing
- **Rasa Open Source 3.x** (server) and **rasa-sdk 3.x** (action server)

### Python packages (if running locally)

```bash
pip install rasa==3.* rasa-sdk==3.* neo4j==5.*
```

### Environment variables

For Neo4j connectivity (used by `knowledge_base.py` & `actions.py` CLI):

```bash
export NEO4J_URI=bolt://trustmed-db:7687   # or bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password
export NEO4J_DATABASE=neo4j
```

For Rasa → Actions wiring (used by `endpoints.yml`):

```bash
export ACTION_SERVER_URL=http://actions:5055/webhook
```

> In Compose, the service DNS name is usually `trustmed-db` (Neo4j) and `actions` (action server).

---

## 🗃️ Data Ingestion (UMLS → Neo4j)

1) **Place files** under `Data/META/`:

```
Data/
└── META/
    ├── MRCONSO.RRF
    └── MRREL.RRF
```

2) **Start Neo4j** (Docker or local) and verify port `7687` is reachable.

3) **Run the loader**:

```bash
python load_data.py
```

This script:

- Creates a uniqueness constraint on `:Concept(cui)`
- Loads concepts from **MRCONSO** (preferring RxNorm & SNOMED CT entries)
- Loads relationships from **MRREL** into `:RELATED_TO {type, rela}`

> See `load_data.py` for details and progress logging. It uses modern `CREATE CONSTRAINT … IF NOT EXISTS` and sets both `type` (e.g., RO/RN) and `rela` (descriptive attribute) on each edge.

4) Post‑load normalization (recommended)

The query layer uses **lower‑cased names** and benefits from **typed edges**. Run these once after ingestion:

```cypher
// (1) lowercase name & index for fast lookups
MATCH (c:Concept) WHERE c.name IS NOT NULL SET c.name_lc = toLower(c.name);
CREATE RANGE INDEX concept_name_lc IF NOT EXISTS FOR (c:Concept) ON (c.name_lc);

// (2) promote common relationship attributes to r.type
MATCH ()-[r:RELATED_TO]->()
WHERE r.rela IN ['has_tradename','tradename_of','has_active_ingredient','has_ingredient','has_boss','has_dose_form','isa','is_a','parent']
SET r.type = r.rela;

// (3) optional: keep both directions for active ingredient
// (depends on how you want to traverse)
```

> Have a curated CSV (e.g., DailyMed)? You can adapt `load_data.py` or write a one‑off importer to build the same node/edge shape.

---

## 🤖 Rasa NLU & Configuration

`config.yml`:

- Tokenization + features: `WhitespaceTokenizer`, `RegexFeaturizer`, `LexicalSyntacticFeaturizer`
- Sparse features: `CountVectorsFeaturizer` (word), `CountVectorsFeaturizer` (char_wb 3–5)
- Regex entity extraction for a **single numeric slot**: `top_k` (limits list sizes)
- Intent+entity model: `DIETClassifier` (100 epochs) with synonyms & fallback
- Policies: `RulePolicy`, `MemoizationPolicy`, `TEDPolicy`

> The `RegexEntityExtractor` is **restricted** to `entity_types: ["top_k"]` so Rasa handles numeric “show 10 …” while drug‑like entities are learned by DIET.

`domain.yml`: defines intents, entities (`product_name`, `ingredient_name`, `brand_name`, `generic_name`, `top_k`), and bot responses.

`credentials.yml`: REST is on by default. (Optional) `rasa.url: http://localhost:5002/api` for Enterprise dev channel.

`endpoints.yml`: action endpoint uses an **env var**:

```yaml
action_endpoint:
  url: ${ACTION_SERVER_URL}
```

In Docker Compose, this is set to `http://action-server:5055/webhook`.

---

## 🧱 Core Code Components

### `knowledge_base.py` — Neo4j Access Layer

High‑level methods used by actions/web to answer queries:

- `product_ingredients(product_name)` — active ingredients for a product (both directions)
- `products_by_ingredient(ingredient_name, limit)` — products containing an ingredient
- `product_substitutes_same_actives(product_name, limit)` — same active set
- `co_ingredient_partners(ingredient_name, limit)` — frequent co‑ingredients (filters brand/forms/strength strings)
- `similar_by_combo_overlap(ingredient_name, limit)` — rank ingredients by partner overlap
- `brand_to_generic(brand_name)` / `generic_to_brands(generic_name)` — brand ↔ generic via tradename
- `extract_strengths_from_products(drug_name, limit)` — parse strengths from product names (**APOC** regex)
- `ancestry_path(drug_name, max_depth)` — optional ontology-ish paths across isa/parent links

Defaults honor `NEO4J_URI/USER/PASSWORD/DATABASE`. Connectivity is verified at init; failures fall back to a no‑op driver.


### `actions/actions.py` — Action Server + Façade

Two layers:

1. **`Actions` façade** — pure Python helpers that call the KnowledgeBase and return a consistent dict `{ok, data, text}` for easy reuse (bots, web API, tests).
2. **Rasa `Action` classes** — one class per intent, reading slots (`product_name`, `ingredient_name`, `brand_name`, `generic_name`, optional `top_k`) and replying with the façade’s `text`.

> A simple `__main__` block lets you smoke‑test without Rasa:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_pass
python actions.py
```

### `load_data.py` — UMLS Loader

- Creates `:Concept(cui)` uniqueness
- Ingests **MRCONSO** concept names (RxNorm/SNOMED CT)
- Ingests **MRREL** edges with `type` (RO/RN/…) and `rela` (descriptive attribute)
- Designed to print progress every 100k rows

> After loading, run the **post‑load normalization** section above to set `name_lc`, index it, and promote known `rela` values into `type` for faster, cleaner queries.

---

## 🌐 Channels & Endpoints

- **REST channel** is enabled by default in `credentials.yml`.
- For Rasa Enterprise dev channel, `rasa.url: "http://localhost:5002/api"` is included (optional).
- The action server URL is referenced from `endpoints.yml` using `${ACTION_SERVER_URL}` env var.

---

## 🛠️ How It Works

**Rasa** extracts intents/entities → **Actions Server** calls the **Knowledge Base (Neo4j)** → results come back as clean text lists.

```
User → Rasa (intent/entities) → actions.py → knowledge_base.py → Neo4j → response text
```

- `knowledge_base.py` contains **all Cypher**. It lowercases lookups (`name_lc`) and uses typed edges like `has_active_ingredient` / `has_tradename`.
- `actions.py` exposes a small set of helper methods that return `{ok, data, text}` so UI/bot code stays simple.
- The **REST channel** is enabled; the web chat hits Rasa’s REST webhook.

---

## 🚀 Run It

### A) Docker Compose (recommended)

```bash
docker-compose up --build
```

Expected ports:

| Service          | Purpose              | URL/Port                                        |
| ---------------- | -------------------- | ----------------------------------------------- |
| **Neo4j**        | Graph database       | http://localhost:7474  / bolt://…:7687         |
| **Rasa Server**  | NLU engine           | http://localhost:5005                           |
| **Action Server**| Custom backend logic | 5055                                           |
| **Web Chat UI**  | Static site          | http://localhost:8080                           |

### B) Manual (local processes)

1. Start **Neo4j** (ensure APOC enabled)
2. Start **Action Server**:

   ```bash
   rasa run actions --port 5055
   ```

3. Start **Rasa**:

   ```bash
   rasa run --enable-api --port 5005
   ```

4. Serve **web/** (any static server), e.g.:

   ```bash
   python -m http.server 8080 -d web
   ```

---

## 💬 Example Conversations

- **“What are the ingredients in Zestoretic 20/25 Oral Tablet?”**  
  → hydroCHLOROthiazide, and lisinopril

- **“List 10 products that contain ibuprofen.”**
  → 2 ML Neoprofen 10 MG/ML Injection, APAP 250 MG / Ibuprofen 200 MG Oral Capsule, APAP 250 MG / Ibuprofen 250 MG Oral Tablet, APAP 250 MG / ibuprofen 125 MG Oral Tablet, Addaprin 200 MG Oral Tablet, Advil 100 MG Chewable Tablet, Advil 100 MG Oral Tablet, Advil 100 MG per 5 ML Oral Suspension, Advil 200 MG Oral Capsule, and Advil 200 MG Oral Tablet

- **“What’s the generic for Zestril?”**
  → *lisinopril*

- **“Common co‑ingredients with ibuprofen.”**
  → acetaminophen, chlorpheniramine maleate, diphenhydrAMINE citrate, diphenhydrAMINE hydrochloride, famotidine, HYDROcodone bitartrate, phenylephrine hydrochloride, and pseudoephedrine hydrochloride

---

## 🔧 Troubleshooting

- **No results for otherwise common queries**  
  Ensure you ran the **post‑load normalization** to set `name_lc` and promoted `rela` into `type`. Without it, lookups by lower‑case and typed traversals will underperform.

- **`extract_strengths_*` returns nothing**  
  Make sure **APOC** is installed and enabled and that product names actually contain strength tokens (e.g., “200 mg”).

- **Driver can’t connect**  
  Check `NEO4J_URI`, network/ports, and that Neo4j is accepting Bolt connections.

- **Large ingest is slow**  
  Run ingest on a faster disk; consider increasing Neo4j page cache; keep the uniqueness constraint in place.

---

## 🧠 Tech Stack

| Stack                   | Purpose                        |
| ----------------------- | ------------------------------ |
| **Rasa 3.x**            | Intents / entities / policies  |
| **rasa-sdk 3.x**        | Custom actions server          |
| **Neo4j 5.x**           | Knowledge graph backend        |
| **APOC**                | Text/regex utilities           |
| **Python 3.8+**         | Ingestion & actions            |
| **Docker Compose**      | Orchestration                  |
| **HTML/CSS/JavaScript** | Minimal web chat               |

---

## 👥 Team Members

- **Harsh Nitinkumar Chandak** `hchanda4@asu.edu`
- **Swathi Gudivada** `sgudiva3@asu.edu`
- **Soham Sachin Joshi** `sjosh117@asu.edu`
- **Animesh Kumar** `akuma509@asu.edu`
- **Sankarshana Wadheendra Nanjangud** `snanjan2@asu.edu`

---

## 📝 License

This repository contains code and configuration only. UMLS/RxNorm/SNOMED CT content is subject to their respective licenses and **must be obtained from official sources**.

> “Turning unstructured drug queries into structured medical knowledge — one question at a time.” 💡

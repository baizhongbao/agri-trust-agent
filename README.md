# Agri-Trust Agent — Contract Credibility for Order Agriculture

[![CI](https://github.com/baizhongbao/agri-trust-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/baizhongbao/agri-trust-agent/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

> Upload an order-agriculture contract, get back verifiable structured facts, the
> standards they must comply with, and a quantified view of performance risk.

One contract in, one **evidence-backed assessment** out. The system does not ask a
language model to make judgment calls on your behalf — it lays the facts scattered
across dense legal clauses on the table, turns them into numbers, and checks them
line by line against statutes, national standards, and court precedents, so that
both signing parties can read, verify, and challenge every conclusion.

---

## Why This Project Exists

Order agriculture — the "company + farmer" model — is one of the main bridges
connecting smallholder farms to modern supply chains: farmers grow to order,
companies purchase at agreed prices, farmers gain a stable outlet, and companies
gain a reliable source of supply. In practice, the model keeps getting stuck at
the same point: **the contract**.

- **Severe information asymmetry.** The company has lawyers, templates, and years
  of experience. Most farmers are reading a contract this long for the first time —
  unclear what "moisture ≤ 14.5%" actually implies, or that a 20% down payment is
  a legal ceiling, not a suggestion.
- **Disputes are frequent, and the cost is asymmetric.** Planted area, purchase
  volume, quality specs, settlement timing — any ambiguity turns into a dispute at
  harvest. When it does, the farmer typically risks an entire year's income while
  the company risks a penalty clause.
- **Risk is underestimated, not calculated.** Will the company still take delivery
  after a price crash? Does a natural disaster count as force majeure? Can the
  penalty cover actual losses? On signing day, nobody can answer.
- **Verification is expensive.** Does the counterparty actually exist? Does its
  business scope cover the deal? Does it carry a track record of lawsuits? Ordinary
  people have only word of mouth.

This project aims to turn what only professional firms could offer — contract due
diligence — into a capability available with a single upload. It makes no decision
for farmers or companies; it **puts the evidence needed for the decision on the
table**. That is also why the project is named "credibility" rather than "scoring".

---

## What It Does

### 1. Contract Parsing — turning clauses into verifiable facts

Upload a PDF or an image (scanned contracts and phone photos are supported).
The system produces two layers of output:

- **Presentation layer**: contracting parties, subject matter, quantity, unit
  price, total amount, quality standards, delivery deadlines, settlement terms,
  breach liabilities — **each field carries the exact source text that supports
  it**, so every value can be checked against the original document.
- **Reasoning layer**: amounts become numbers, dates become machine-readable
  values, quality metrics become *name–operator–threshold* triples. "486,000 CNY"
  becomes a number you can compare, which everything downstream — compliance
  checks, loss simulation — depends on.

Extraction runs through **two independent channels — a deterministic rule engine
and a large language model — and every field is arbitrated item by item**. When the
two disagree, the deterministic result is kept, the conflict is explicitly flagged,
and the item is routed to human review. The system never pretends to know which
side is right.

### 2. Standards Compliance — checking against statutes and national standards

A structured knowledge base holds **8 legal instruments / 48 clauses / 32
machine-comparable limits**, anchored on the *Guidelines for Order-Agriculture
Contracts* and *Model Clauses for Agricultural Product Orders*, extended with the
Civil Code (contract provisions), grain circulation regulations, and quantifiable
standards such as pesticide residue limits, contaminant limits, and rice quality
grading — each entry tagged with rule strength and effective dates.

- **Missing-clause detection**: an 18-item checklist (11 mandatory + 7
  recommended) lists exactly which clauses are absent and what to add.
- **Numeric compliance checks**: down-payment ratios, penalty rates, moisture,
  impurity, and pesticide residue indicators are compared against statutory and
  standard limits, surfacing problems like "contract says 25% vs the 20% legal
  ceiling". Checks are **filtered by commodity applicability** — a rice contract
  is never benchmarked against wheat limits.
- Every conclusion traces back to a specific provision — checkable, reviewable.

### 3. Enterprise Verification — is the counterparty real?

Three progressive levels; a failure at any level is always visible, never silent:

- **Level 1 — local checksum**: Unified Social Credit Code validation
  (GB 32100-2015). No database, no network — yet it already catches the cheapest
  and most common fraud: a fabricated code.
- **Level 2 — business registry lookup**: registered name, legal representative,
  incorporation date, operating status, business scope.
- **Level 3 — cross-checking**: contract facts vs registry facts, item by item.
  A party name that doesn't match, a signing date earlier than the company's
  incorporation date, a business scope that doesn't cover the traded commodity —
  these contradictions are caught before signatures are applied.

When the system cannot judge, it returns "needs human review" instead of guessing.

### 4. Performance Simulation — turning risk into money

Scenario simulation around the three most common sources of order-agriculture
disputes: **price volatility, natural disasters, and breach of contract**.

**Every number is computed by deterministic Python code** — the full calculation
trail is exportable for audit — while the LLM is restricted to qualitative
analysis, because a model that misreads 14.5 as 15 is an accident waiting to
happen. Liability reasoning cites rules distilled from **50 real court judgments**
covering agricultural contracting, purchase-and-sale, and land-management-rights
disputes, each annotated with its case number.

### 5. Overall Verdict and Report

The four modules' conclusions are consolidated into an overall credibility rating
(trustworthy / basically trustworthy / needs attention / high risk / not
assessable), with **veto items** listed separately (e.g., an unverifiable party,
a two-source conflict on a mandatory field). The result exports to PDF / Word —
printable and readable by the farmer across the table.

---

## Why It Is Trustworthy

The biggest danger of any "AI reads your contract" product is that people blindly
trust it. This project's design principle is: **rather admit it failed to read
than produce a confident wrong answer.**

- **Every conclusion carries evidence.** A field without supporting source text
  is not allowed to appear in results.
- **Numbers never pass through the LLM.** Compliance checks and loss calculations
  are deterministic code — reproducible and auditable.
- **Missing, conflicting, and failed states are always explicit.** Parsing gates,
  module degradation notices, and "not assessable" statuses are structured
  outputs; the system never dresses up a zero as "no risk found".
- **Self-checks do not rely on the model.** Date-order contradictions, down
  payments above the statutory ceiling, totals inconsistent with unit price ×
  quantity — all detected by pure Python, emitting machine-readable reason codes.
- **The verdict rounds down, not up.** One high-risk dimension makes the overall
  verdict high risk; missing dimensions are never averaged away.

---

## Scope and Limitations

An honest account of what it cannot do today:

- **It is not legal advice.** It does not replace lawyers or negotiation; output
  is risk indication plus an evidence index.
- The knowledge base covers the statutes and guidelines currently structured
  into it — **not the entire body of applicable law**. Numeric limits today focus
  on grain commodities (paddy / rice); other categories and regional regulations
  need to be added case by case.
- Precedent rules are distilled from 50 judgments — they indicate **liability
  tendencies**, not binding legal authority.
- For badly typeset, handwritten, or heavily degraded documents, extraction
  quality drops; the system degrades explicitly and demands human review.
- Simulation output is **risk magnitude and liability tendency**, not a prediction
  of court outcomes.

---

## Roadmap

- **Agent orchestration on Huawei Cloud AgentArts**: the MCP server is ready;
  the capability set will be exposed as tools for autonomous agents, letting an
  agent extend the local analysis with live web evidence (litigation records,
  policy changes, similar cases).
- **Upgrading the LLM backbone to OpenAI's ChatGPT API (GPT series)**: all LLM
  calls already go through one OpenAI-compatible interface, so switching the
  provider from the current models to ChatGPT is a configuration change, not a
  rewrite — the plan is to adopt GPT-class models for contract structuring and
  qualitative risk analysis as the project matures.
- **True multimodal reading**: image and scanned contracts are currently parsed
  after OCR; the next step is letting vision models read layout, tables, and
  seals directly, bringing layout-level signals ("is it stamped?", "are there
  handwritten amendments?") into verification.
- **Growing the knowledge base**: applicability filtering by commodity (grain,
  produce, livestock, aquaculture, medicinal herbs) and by region, incorporating
  more current standards and local regulations.
- **Replicable to adjacent scenarios**: farm-machinery service contracts,
  land-management-rights transfers, agricultural input purchases, and
  agricultural socialized services — the same
  *parse → check against standards → cross-verify → quantify risk* skeleton
  transfers by swapping the knowledge base.
- **County-level services**: agriculture departments, cooperatives, and rural
  financial institutions can use it as the first-pass screen in loan review and
  dispute mediation.

For farmers, it lowers the information barrier before signing; for companies, it
reduces performance disputes caused by contract defects; for regulators and
mediators, it turns "is this contract sound?" from a subjective judgment into a
checkable list. That is why we believe this project is worth building.

---

## Quick Start

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts\make_sample_contract.py
start.bat
```

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
python scripts/make_sample_contract.py
uvicorn app.main:app --app-dir backend --reload
```

Frontend <http://127.0.0.1:5173> · Backend <http://127.0.0.1:8000> · API docs <http://127.0.0.1:8000/docs>

**Works out of the box with no API keys.** The default configuration runs entirely
on offline providers (hashing embeddings + rule-based extraction + a bundled demo
business registry), so a fresh clone runs the full pipeline and produces a complete
assessment report for the sample contract. When you need stronger capabilities,
flip the provider switches in `.env` to enable LLM structuring, cloud OCR, real
business-registry data, and semantic retrieval — zero business-code changes. The
full switch list is documented in `.env.example`.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ · FastAPI · SQLite + local file storage |
| Frontend | Vue3 + Vite (zero UI-framework dependencies) |
| LLM | OpenAI ChatGPT API (GPT series) · Huawei Cloud Pangu MaaS · offline mock — all behind one OpenAI-compatible interface |
| OCR | Huawei Cloud OCR · cloud vision models · can be disabled |
| Retrieval | Vector + BM25 hybrid recall → cross-encoder reranking (`bge-m3` / `bge-reranker-v2-m3`, degradable) |
| Agent | MCP stdio server, registrable as a tool source for AgentArts and any MCP client |
| Reports | PyMuPDF (PDF, bundled CJK fonts) · python-docx (Word) |

The most important architectural constraint: **every external dependency sits
behind a provider abstraction layer**, so the credentialed and credential-free
paths share the same business code, and any vendor can be swapped in isolation.

---

## Contributing and License

Issues and pull requests are welcome. Before submitting a PR, please read
[`AGENTS.md`](./AGENTS.md) (architecture rules and red lines) and make sure both
CI jobs are green.

This project is licensed under the [Apache License 2.0](./LICENSE).

> **Looking for implementation details?** The API list, data models, provider
> switches, module responsibilities, testing, and troubleshooting all live in
> [`AGENTS.md`](./AGENTS.md); environment and technical analyses are under
> [`docs/`](./docs/). This file only explains what the project is and why it
> matters.

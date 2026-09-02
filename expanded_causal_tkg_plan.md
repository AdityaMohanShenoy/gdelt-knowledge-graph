# Expanded Causal TKG Plan

## 1. Project Scope

The project should not be framed as:

> Build a knowledge graph containing only 2024 India protest events.

Instead, the scope should be:

> **Explain the causal histories of protest events occurring in India during 2024.**

This means:

- **Seed / target events:** 2024 protest events in India
- **Causal ancestor events:** may include any relevant event type
- Examples of ancestor events:
  - policy announcements
  - arrests
  - negotiations
  - court rulings
  - economic changes
  - speeches
  - mobilization events
  - violence
  - foreign events with explicit linkage
- All accepted causal events must remain grounded in **GDELT-backed source articles**
- The graph is **event-centric**

---

## 2. Core Modeling Principle

The graph should distinguish between:

1. **Source articles**
2. **Event mentions**
3. **Canonical events**
4. **Entities / actors**
5. **Causal edges**

The source article is **provenance**, not the event itself.

A single article may describe multiple atomic events.

Example:

```text
Article
 ├── Government announces policy
 ├── Union rejects policy
 ├── Union calls for march
 └── Protest begins
```

The final graph should reason over those atomic events, not over the article as one bundled node.

---

# 3. Data Architecture

## 3.1 GDELT as Discovery and Metadata Layer

Keep the original GDELT data as the discovery/index layer.

Useful fields include:

- Actor1
- Actor2
- Event code
- Goldstein score
- Date
- Location
- Source URL
- GKG themes
- GKG entities
- Other useful event metadata

Do **not** assume:

```text
1 GDELT row = 1 final KG node
```

and do **not** assume:

```text
1 URL = 1 final KG node
```

GDELT rows should be treated as noisy event hints / mentions that help locate relevant information.

---

## 3.2 Article Acquisition

Current dataset contains URLs, so articles must first be fetched.

Pipeline:

```text
GDELT URL
    ↓
Fetch article
    ↓
Store raw HTML
    ↓
Extract main article text
    ↓
Store cleaned text
```

Store one article document row per normalized URL to avoid repeated ingestion while preserving every GDELT event observation that points to that URL.

The bulk dispatcher processes the queue with checkpointed, host-aware concurrency so a slow publisher cannot monopolize the global worker pool. The local event viewer also exposes a targeted fetch action for an individual source URL, so a selected article can be retrieved immediately without waiting for the bulk queue to reach it; both paths write through the same Postgres status record and extraction pipeline.

Local pilot storage:

### Docker Postgres

The local Docker Postgres store holds:

- source URL and final URL metadata
- fetch status, HTTP status, retry attempts, and leases
- cleaned article text and extraction metadata
- content hashes and raw HTML paths

The schema is standard PostgreSQL so it can be moved to Supabase later. Raw HTML remains compressed on the local evidence volume for the pilot; Supabase Object Storage is the planned destination when remote storage is needed.

### Supabase Postgres

The later Supabase store will hold the structured research records:

- source metadata
- event mentions
- canonical events
- entities
- causal edges
- annotation decisions
- review status
- rejected candidates

### Supabase Object Storage

For large content:

- raw HTML
- cleaned article text
- extraction artifacts

Do not store large HTML/text blobs directly inside Postgres unless necessary.

Suggested source fields:

```text
source_id
url
published_at
fetched_at
content_hash
raw_storage_path
clean_text_storage_path
fetch_status
```

The full article text should remain private to the research team unless redistribution rights permit otherwise.

---

# 4. Atomic Event Extraction

## 4.1 Goal

Convert each article into one or more **atomic event mentions**.

Example article:

> The government increased procurement prices. Farmer unions rejected the move and later called for a march. Thousands demonstrated in Delhi.

Extract:

```text
E1: Government increased procurement prices
E2: Farmer unions rejected the policy
E3: Farmer unions called for a march
E4: Farmers demonstrated in Delhi
```

---

## 4.2 ML / NLP Use

ML/NLP is allowed for event extraction.

The restriction is:

> **ML may extract or propose events, but it must not invent unsupported causal relations.**

Every extracted event must reference an exact evidence span from the article.

Suggested event representation:

```text
event_mention_id
source_id
actor(s)
action
target/topic
location
event_time
event_type
evidence_start
evidence_end
confidence
```

A human-readable sentence can then be constructed deterministically from the structured fields.

Example:

```text
Actor: Farmer unions
Action: called for
Target: protest march
Location: Punjab
Date: 13 Feb 2024
```

Canonical sentence:

> Farmer unions called for a protest march in Punjab on 13 February 2024.

---

# 5. Event Verification

For the initial gold/prototype dataset:

```text
ML extracts atomic event
        ↓
Human verifies
        ↓
Accept / Edit / Reject
        ↓
Verified event becomes eligible for causal reasoning
```

This keeps the graph human-auditable.

Later, sufficiently reliable event extraction can be automatically accepted above a strict threshold.

---

# 6. Event Canonicalization

Different articles may report the same real-world event.

Example:

```text
Article 1 → Farmers began protesting in Delhi
Article 2 → Thousands joined the Delhi farmer protest
Article 3 → Farmer demonstrations continued into the next day
```

These should not automatically become three separate graph nodes.

Instead:

```text
Multiple Event Mentions
        ↓
Canonicalization
        ↓
One Canonical Event
```

Candidate merge signals:

- actor overlap
- same / nearby location
- close timestamps
- same event type
- similar action
- semantic similarity
- shared entities/themes

Automation strategy:

```text
high-confidence merge → automatic
uncertain merge → human review
```

Canonical event representation may include:

```text
event_id
canonical_description
event_type
actors
location
best_event_time
time_range
time_confidence
supporting_sources
```

---

# 7. Temporal Representation

Use:

1. **Extracted event occurrence time** when available
2. GDELT event date as fallback
3. Publication date as final fallback

Store:

- best timestamp
- confidence
- possible interval/range when vague

Example:

```text
best_time: 2024-02-13
time_range: 2024-02-12 → 2024-02-13
time_confidence: 0.82
```

For the prototype, causal history is truncated at:

```text
1 January 2024
```

---

# 8. Seed Event Selection

Initial seed set:

> **2024 India protest events only**

The number ~500 is only a rough target for experimentation.

It is not a hard dataset limit.

The purpose of the seed set is to:

- understand how causal chains form
- test annotation workflow
- estimate graph depth
- evaluate retrieval
- train later models
- build a demo graph

Ancestor events may be any event type.

---

# 9. Candidate Cause Retrieval

For a target event `B`, search backward approximately:

```text
B.time - 7 days
```

This 7-day window is only for the initial prototype and can later be expanded.

Candidate retrieval should be broad and permissive.

Possible retrieval signals:

- Actor overlap
- Entity overlap
- GKG theme overlap
- Location proximity
- Event type compatibility
- Temporal proximity
- Lexical similarity
- Semantic embeddings
- Shared organizations
- Shared policy/topic references

Suggested retrieval flow:

```text
Target Event B
      ↓
Previous 7-day event universe
      ↓
Structured filtering
      ↓
Semantic ranking
      ↓
Top candidate causes
```

Important principle:

> **Retrieval is not causality.**

These signals only decide which prior events are worth checking.

---

# 10. Evidence Retrieval

For each candidate pair:

```text
A → ? → B
```

search GDELT-backed articles for textual evidence connecting the two events.

Supporting evidence may appear in:

- A's source article
- B's source article
- another GDELT-sourced article

Example:

```text
A = Government passes policy
B = Farmers protest
```

Supporting article:

> Farmers began demonstrations in response to the government's newly announced policy.

This is acceptable evidence.

General Google/web search is not required for the causal evidence universe.

The supporting article must come through the GDELT corpus.

---

# 11. Causal Acceptance Rule

A candidate relationship is accepted only when there is textual evidence linking the events.

Not sufficient:

```text
A happened before B
A and B have similar actors
A and B have matching themes
```

Sufficient:

- explicit causal wording
- explicit response wording
- clear semantic relation
- explicit protest-against / action-in-response-to relation
- other inspectable causal linkage

Core rule:

> **Structural similarity can retrieve a candidate, but it can never create a causal edge.**

---

# 12. Positive Causal Relation Taxonomy

Use a small fixed taxonomy initially.

Suggested types:

## `TRIGGERS`

Immediate precipitating cause.

Example:

```text
arrest → protest
```

## `MOTIVATES`

Creates the grievance/incentive behind the later event.

Example:

```text
wage cuts → worker protest
```

## `MOBILIZES`

Organizing or coordination causes collective action.

Example:

```text
union calls strike → workers demonstrate
```

## `ENABLES`

Creates a condition that allows the event to occur.

Example:

```text
court permission → march proceeds
```

## `ESCALATES`

Makes an existing situation more intense.

Example:

```text
police violence → larger protest
```

## `PROMPTS_RESPONSE`

Causes an institution or actor to react.

Example:

```text
protest → government negotiations
```

## `CONTRIBUTES_TO`

Fallback when causality is supported but a more specific mechanism is not justified.

Example:

```text
economic pressure → unrest
```

---

# 13. Causal Edge Structure

Do not store the relation only as natural-language prose.

Store structured causal edges.

Example:

```text
source_event_id
target_event_id
relation_type
machine_relation_type
machine_strength
final_strength
temporal_gap
primary_evidence
supporting_evidence
evidence_quality
corroboration_count
review_status
reviewer_id
```

Logical graph representation:

```text
Event A --MOBILIZES--> Event B
```

Natural-language explanations should be generated later from structured data.

---

# 14. Edge Strength

Each causal edge should have a strength/confidence score.

The score can combine:

- textual evidence quality
- number of independent supporting sources
- actor consistency
- temporal proximity
- location consistency
- event-type compatibility
- source agreement

Keep textual evidence quality separately visible for auditability.

Suggested workflow:

```text
System suggests strength
        ↓
Annotator reviews
        ↓
Accept or override
        ↓
Store both machine + final value
```

This later enables calibration analysis.

---

# 15. Annotation Workflow

Humans should not manually search hundreds of events.

The workflow should mimic the future automated system.

```text
Target Event
    ↓
System retrieves candidate prior events
    ↓
System retrieves supporting evidence
    ↓
System suggests causal relation type
    ↓
System suggests edge strength
    ↓
Human:
    Accept / Reject / Edit
```

The annotation UI should show:

- target event
- candidate cause
- primary evidence span
- other supporting spans
- causal type suggestion
- strength suggestion
- full source article on demand

---

# 16. Rejected Candidate Storage

Rejected edges are valuable training data.

Store them.

Suggested rejection taxonomy:

- `NO_CAUSAL_EVIDENCE`
- `TEMPORALLY_INVALID`
- `WRONG_EVENT_MATCH`
- `DUPLICATE_EVENT`
- `CORRELATED_ONLY`
- `INSUFFICIENT_EVIDENCE`
- `WRONG_DIRECTION`
- `OTHER`

Optional free-text note may be added.

These become useful **hard negatives** later.

---

# 17. Unverifiable Candidates

If a candidate looks plausible but the supporting source cannot be fetched or verified:

```text
UNVERIFIABLE_CANDIDATE
```

Do not add it as a causal graph edge.

This preserves possible future work without compromising graph reliability.

---

# 18. Recursive Causal Graph Expansion

Once a causal edge is accepted:

```text
A → B
```

A becomes a new effect whose causes must be searched.

Process:

```text
Find causes of B
      ↓
Accept A → B
      ↓
Find causes of A
      ↓
Accept X → A
      ↓
Continue recursively
```

If multiple parents exist:

```text
A → C
B → C
```

explore causes of both `A` and `B`.

Follow all accepted parent branches.

Do not impose a depth limit initially.

Stop when:

- no supported parent is found
- January 1, 2024 is reached

If needed later, depth limits are easy to impose during traversal.

---

# 19. DAG, Not Linear Chains

Real causal histories should be represented as a directed causal subgraph / DAG.

Example:

```text
Policy change ───────┐
                     ↓
Economic grievance → Protest
                     ↑
Opposition mobilization
```

One event may have multiple direct causes.

One cause may influence multiple downstream effects.

When branches converge on an already-known event, reuse the canonical node instead of duplicating it.

---

# 20. Completion State

Every reviewed event should have an explicit search status.

Example:

```text
PARENTS_FOUND
NO_SUPPORTED_PARENT_FOUND
NOT_YET_REVIEWED
UNVERIFIABLE
```

This prevents confusion between:

> no cause exists in the current evidence

and

> nobody has searched yet

---

# 21. Event-Centric Graph

The final graph is primarily:

```text
Event → causal relation → Event
```

Actors/entities remain secondary nodes:

```text
Actor → PARTICIPATED_IN → Event
Event → OCCURRED_AT → Location
Event → SUPPORTED_BY → Source
```

Example:

```text
Government announces policy
          ↓ MOTIVATES
Union rejects policy
          ↓ MOBILIZES
Union calls march
          ↓ TRIGGERS
Farmers protest
```

This is better for causal history reconstruction than an actor-centric traversal.

---

# 22. Query Grounding

Natural-language questions do not directly traverse the graph.

First map the query to a target event.

Example:

```text
"Why were farmers protesting?"
        ↓
Extract:
farmers + protest
        ↓
Search Canonical Events
        ↓
Choose latest matching event
```

Rule:

- choose latest matching event by default
- if multiple plausible matches remain, ask the user for clarification

Specific query:

```text
Why did farmers protest in Delhi on February 13?
```

can map more directly.

---

# 23. Query-Conditioned Path Retrieval

Once the target event is found:

```text
Question
   ↓
Target Event
   ↓
Incoming causal subgraph
   ↓
Relevant path ranking
```

Do not always return every causal path.

Return the **strongest paths relevant to the query context**.

Possible ranking signals:

```text
causal strength
+ query relevance
+ evidence quality
+ corroboration
+ temporal coherence
```

---

# 24. Reusing the Same Chain for Different Questions

The causal graph should be reusable.

Example graph:

```text
A → B → C → D
```

Query 1:

> Why did D happen?

May retrieve:

```text
A → B → C → D
```

Query 2:

> What role did B play?

May focus on:

```text
B → C → D
```

Query 3:

> Which government action contributed to D?

May retrieve the branch beginning at the relevant governmental event.

The graph remains unchanged.

Only path selection changes.

This solves the problem of using the same causal history for many different questions.

---

# 25. Natural-Language Explanation Layer

The graph should store structured knowledge.

The explanation layer generates prose only after relevant paths are selected.

Pipeline:

```text
Question
    ↓
Event grounding
    ↓
Causal subgraph retrieval
    ↓
Path ranking
    ↓
Evidence-backed explanation
```

The explanation may cite:

- event sequence
- causal relation types
- timestamps
- strength
- supporting article spans
- provenance URLs

---

# 26. Manual Annotation Strategy

Manual annotation is still required, but not as manual search.

Bad workflow:

```text
Human reads hundreds of events
↓
Human invents causal chain
```

Preferred workflow:

```text
Machine retrieves
↓
Machine extracts evidence
↓
Machine proposes
↓
Human verifies
```

This makes annotation scalable and closely mirrors the final automated system.

---

# 27. Annotation Team Strategy

Team size: 4 annotators.

Recommended process:

- one primary annotator per edge/event
- smaller double-annotated subset
- rotate overlap across annotator pairs
- measure inter-annotator agreement
- resolve disagreements through discussion

This balances annotation cost and reliability.

---

# 28. Precision-First Philosophy

Final system should optimize for **precision over recall**.

Reason:

A wrong causal edge can contaminate many downstream multi-hop explanations.

Therefore:

> It is better to miss a real causal edge than to insert an unsupported causal edge.

The graph is intentionally incomplete.

If evidence is insufficient:

```text
no edge
```

not:

```text
low-confidence guessed edge
```

---

# 29. Eventual Automation

The human-reviewed dataset can later train:

## Candidate Ranker

Ranks which prior events are worth examining.

## Causal Relation Classifier

Suggests:

- `TRIGGERS`
- `MOTIVATES`
- `MOBILIZES`
- etc.

## Edge Strength Model

Predicts causal strength/confidence.

## Event Canonicalization Model

Decides whether event mentions refer to the same underlying event.

---

# 30. Human-in-the-Loop Deployment

Final operating mode:

```text
High-confidence evidence-backed edge
        ↓
Auto-accept

Uncertain edge
        ↓
Human review
```

The automatic acceptance threshold should be calibrated for very high precision.

Every accepted edge must still remain inspectable.

---

# 31. Dataset Usage

The reviewed dataset should eventually be split into:

## Train

Used for:

- candidate ranking
- causal relation classification
- event extraction
- canonicalization

## Dev

Used for:

- retrieval threshold tuning
- edge scoring
- rule refinement
- relation taxonomy refinement

## Test / Gold

Held out for final evaluation.

Do not tune on the gold set.

## Demo Graph

Can use reviewed events and chains for interactive demonstration.

---

# 32. End-to-End Architecture

```text
                 GDELT
                   │
          Event + GKG metadata
                   │
                   ▼
          Fetch Source Articles
                   │
                   ▼
          Clean / Store Articles
                   │
                   ▼
          Atomic Event Extraction
                   │
                   ▼
          Human Event Verification
                   │
                   ▼
          Event Canonicalization
                   │
                   ▼
          Canonical Event Graph
                   │
                   ▼
       Select India Protest Seeds
                   │
                   ▼
        Previous 7-Day Retrieval
                   │
                   ▼
        Candidate Cause Ranking
                   │
                   ▼
        Causal Evidence Search
                   │
                   ▼
     Relation + Strength Proposal
                   │
                   ▼
          Human Verification
             /            \
        Accept            Reject
          │                 │
          ▼                 ▼
      Causal Edge      Negative Label
          │
          ▼
     Recursive Expansion
          │
          ▼
       Causal DAG
          │
          ▼
        Query Layer
          │
          ▼
      Event Grounding
          │
          ▼
 Query-Conditioned Path Ranking
          │
          ▼
Evidence-Backed Causal Explanation
```

---

# 33. System Decomposition

The complete system is best viewed as three independent but connected subsystems.

## A. Event Construction

```text
GDELT
→ Source Articles
→ Atomic Event Mentions
→ Verified Events
→ Canonical Events
```

## B. Causal Graph Construction

```text
Effect Event
→ Candidate Retrieval
→ Evidence Search
→ Relation Proposal
→ Verification
→ Causal Edge
→ Recursive Expansion
```

## C. Causal Question Answering

```text
Natural Language Question
→ Event Grounding
→ Causal Subgraph Retrieval
→ Query-Conditioned Path Ranking
→ Evidence-Backed Explanation
```

---

# 34. Key Research Principle

> **ML retrieves and proposes; evidence decides causality.**

The project should not claim causal edges based only on:

- co-occurrence
- similarity
- temporal order
- embeddings
- model intuition

Every accepted relation must remain traceable to real textual evidence.

---

# 35. One-Slide Summary

## Proposed Causal TKG Pipeline

**Scope:** Explain causal histories of **2024 India protest events**, while allowing upstream causes to include any relevant GDELT-backed event.

```text
GDELT + Source Articles
        ↓
Atomic Event Extraction
        ↓
Event Canonicalization
        ↓
Candidate Cause Retrieval
        ↓
Evidence-Based Causal Verification
        ↓
Typed + Weighted Causal Edge
        ↓
Recursive Graph Expansion
        ↓
Causal DAG
        ↓
Natural-Language Query
        ↓
Event Grounding
        ↓
Relevant Causal Paths
        ↓
Evidence-Backed Explanation
```

### Key Principle

> **ML retrieves and proposes; evidence decides causality.**

The graph stores reusable structured causal relations, while explanations are generated dynamically based on the query.

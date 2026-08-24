# Decoding the Domino Effect

Project context and research contract for the CFT-KG project.

## 1. Project identity

**Primary name:** Decoding the Domino Effect  
**Domain:** Causal reasoning over Temporal Knowledge Graphs  
**Initial setting:** Protests and civil unrest in India during calendar year 2024  
**Primary data source:** GDELT 2.x Events, Mentions, and Global Knowledge Graph (GKG)

This is a research/thesis project with a practical, understandable user experience. It is not merely a GDELT visualization, a country-interaction graph, or a conventional temporal link-prediction system.

The system should help a user investigate a protest episode and answer questions such as:

> What plausibly contributed to this protest?

The answer must expose the underlying event chain, actors, locations, issues, time uncertainty, supporting evidence, confidence, conflicts, and alternative explanations.

## 2. Research objective

Most Temporal Knowledge Graph systems learn temporal association:

> Event A tends to occur before Event B.

This project investigates the stronger claim:

> Is there sufficient evidence to say that Event A plausibly caused or contributed to Event B?

The system must keep these concepts distinct:

1. Temporal precedence.
2. Co-occurrence or association.
3. Candidate causality.
4. Plausible causality.
5. Verified causality.

Temporal precedence or co-occurrence must never automatically become a causal edge.

## 3. Initial scope

### Geographic scope

The initial dataset is restricted to events whose action location is in India. External actors, organizations, sources, and cross-border context may still be retained when they are relevant to an India-based event.

Geography must remain hierarchical:

- Location feature, city, or landmark when available.
- ADM2/district when available.
- ADM1/state.
- India/country level.

An explanation should answer at the most specific reliable geographic level. A national event may contribute to a local protest when evidence establishes geographic relevance.

### Temporal scope

The first reproducible experiment covers 2024 only. The architecture should not assume that 2024 is the final research period, but all v1 evaluation and published numbers must identify the frozen 2024 snapshot.

### Phenomenon scope

Use a broad unrest lifecycle rather than only direct protest rows. The candidate universe may include:

- Demonstrations and rallies.
- Strikes, boycotts, and hunger strikes.
- Riots, clashes, and violent protests.
- Arrests, repression, curfews, and state responses.
- Internet shutdowns and service disruptions.
- Political, economic, social, or security events that may plausibly contribute to unrest.
- Government, institutional, or societal responses after unrest.

The broad universe is for candidate generation. It does not mean every retained event is causal.

### Language scope

The system processes English-readable text, including GDELT-translated records when available. Translation provenance must be retained. V1 does not build separate native-language NLP pipelines.

### External data

V1 uses GDELT-derived evidence only:

- Events.
- Mentions.
- GKG metadata.
- Retrieved article text where permitted and available.
- Features derived from those sources.

External economic, political, weather, or demographic datasets are out of scope for v1, although the data model may later support them.

## 4. GDELT interpretation

GDELT is a large-scale news-monitoring and information-extraction system. Its records are observations extracted from reporting, not ground-truth annotations of reality.

### Events

An Event record represents a structured CAMEO action in which Actor1 performs an action upon Actor2. Important fields include:

- `GlobalEventID`.
- Event date / `SQLDATE` / `day`.
- `EventCode`, `EventBaseCode`, and `EventRootCode`.
- `QuadClass`.
- `GoldsteinScale`.
- Actor names and CAMEO actor attributes.
- Actor and action geography.
- `DATEADDED`.
- `SOURCEURL`.

CAMEO event codes must remain strings because leading zeroes are meaningful.

The GDELT event date is an inferred, generally day-level event date. It is not guaranteed to be the exact physical occurrence time. `DATEADDED` is the time GDELT recorded the event, not necessarily when the event happened. `SOURCEURL` is the first or an early report found by GDELT and must not be treated as a guaranteed earliest or authoritative report.

### Mentions

The Mentions stream contains article-level observations of Event records. It can provide:

- The referenced `GlobalEventID`.
- Event and mention update timestamps.
- Source collection and document identifier.
- Source name.
- Sentence and character offsets.
- Whether the event was found in raw text.
- Extraction confidence.
- Document length and tone.
- Translation provenance.

Mentions are essential for distinguishing one GDELT event record from the reports that discuss it.

### GKG

GKG is primarily document-level metadata. GKG 2.1 records include:

- Globally unique GKG record identifiers.
- Publication timestamp.
- Source collection identifier.
- Source/common name.
- Document identifier.
- Themes.
- Persons and organizations.
- Locations.
- Counts.
- Enhanced offsets.
- Explicit date mentions.
- Tone and GCAM measures.

GKG co-occurrence is contextual association only. A person, organization, location, and theme appearing in one article does not establish that they are related, nor that one caused another.

### Official references

- [GDELT 2.0 overview](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/)
- [GDELT Event Codebook](https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf)
- [GDELT GKG 2.1 Codebook](https://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf)
- [CAMEO event codes](https://www.gdeltproject.org/data/lookups/CAMEO.eventcodes.txt)

## 5. Units of analysis

### Raw observation

A raw GDELT row or source record. Raw records are immutable and retained for provenance.

### Event observation

A normalized representation of one GDELT Event record, retaining its original `GlobalEventID` and all relevant source fields.

### Canonical event

A project-level hypothesis that several observations refer to the same real-world event. A canonical event retains all source observation IDs and all merge evidence.

Canonical event clustering must be conservative. Same themes or similar reasons are insufficient to merge events.

### Protest episode

A higher-level grouping of related canonical events across time. A broader episode may only be created when continuity evidence supports it, such as:

- Shared organizers or actors.
- Shared demands or issues.
- Temporal continuity.
- Geographic continuity.
- Explicit reporting that events belong to the same movement or episode.

Two protests in different locations must remain separate when the evidence does not establish continuity, even if they share a theme or stated reason.

### Primary graph orientation

The causal graph is event-centric:

```text
sanction event -> economic-stress event -> protest event -> government-response event
```

Actors, organizations, locations, themes, issues, documents, and evidence are attached context. Actors are not automatically causal nodes merely because they participate in an event.

## 6. Event and entity normalization

### Actors

Use GDELT actor codes and names as the base identity. Apply only conservative aliases and preserve raw names and provenance. Do not perform aggressive external entity linking in v1.

Actor features may include:

- Actor name.
- Country code.
- Actor role/type.
- Organization or group code.
- Actor direction: Actor1 or Actor2.
- Continuity across events.

Actor continuity is evidence for causal verification, not proof of causality.

### Locations

Prefer GDELT geographic identifiers and hierarchy:

- Country code.
- ADM1/state.
- ADM2/district when available.
- Feature ID.
- Surface name.
- Geographic resolution.

Surface names and normalized identifiers must both be retained.

### Themes and issues

The supplied cleaned Level 1 and Level 2 theme taxonomy is frozen for v1. It is a strict modeling allowlist.

Raw GDELT themes may remain in provenance and exploratory artifacts but must not enter the causal model unless explicitly approved through a taxonomy change.

Normalized issue/demand entities should be derived from approved themes and article text. Examples include:

- Fuel prices.
- Agricultural policy.
- Employment.
- Land or environmental concerns.
- Political reform.
- Identity, discrimination, or rights.
- Governance or corruption.
- Security or repression.

## 7. Temporal uncertainty model

Every normalized event should preserve separate temporal concepts:

- Estimated occurrence interval.
- GDELT event date.
- Article publication time.
- GDELT ingestion/addition time.
- Mention time.
- Explicit dates extracted from text.
- Temporal granularity and confidence.

### Time authority

1. GDELT event date is the primary occurrence estimate.
2. Explicit textual dates refine the estimate when reliable.
3. Publication time provides an upper bound.
4. Mention time can refine ordering between observations.
5. A one-day reporting-delay baseline is used when occurrence time must be bounded from publication time.

### Ordering

For same-day or overlapping events, use this ordering hierarchy:

1. Explicit textual temporal ordering.
2. Mention-time ordering.
3. Publication-time ordering.
4. Event-date ordering.

If ordering remains unresolved, the relation stays uncertain and cannot become a verified causal edge.

### Long-range links

There is no fixed maximum causal time gap. A cause may be far earlier than an effect if the evidence is strong. Temporal distance reduces confidence and affects ranking but does not automatically reject a link.

Candidate retrieval remains computationally bounded by retaining the top 50 strongest prior candidates per effect.

Retrospective articles may support or contextualize an event, but their publication time must remain separate from event occurrence time and must not create temporal leakage.

## 8. Evidence model

### Documents

Documents should preserve:

- Source collection.
- Document identifier.
- Canonical URL when available.
- Source/common name.
- Publication time.
- Language and translation provenance.
- Retrieval time.
- Retrieval status.
- Content hash.
- Full text location for private local research.

Web text is the primary causal evidence source. Non-web or citation-only records may provide context but should not be treated as equivalent text evidence when no text is available.

Article retrieval is best effort. Retrieved full text is private local research data and must not be distributed by default. Portable artifacts should contain permitted excerpts, offsets, URLs, hashes, and provenance.

### Evidence spans

An evidence span should include:

- Document ID.
- Sentence and character offsets when available.
- Text excerpt.
- Evidence type: causal cue, temporal cue, actor relation, issue relation, support, contradiction, or alternative cause.
- Whether it supports or contradicts an edge.
- Extraction method and model version.

### Evidence linkage

Link Events, Mentions, and GKG using source-collection-aware identifiers first. Use canonicalized URLs as fallback. Preserve every attempted linkage and its confidence.

### Source agreement

Source agreement is an evidence feature, never a causal proof. Identical or near-identical syndicated reports should be conservatively deduplicated and counted as one source group rather than many independent sources.

## 9. Causal ontology

### Relation types

V1 uses:

- `causes`
- `contributes_to`
- `triggers`
- `enables`
- `prevents`
- `responds_to`

### Relation layers

Temporal precedence, association, and causality are represented separately:

- `TEMPORALLY_PRECEDES`
- `ASSOCIATED_WITH`
- `CANDIDATE_CAUSAL`
- `PLAUSIBLE_CAUSAL`
- `VERIFIED_CAUSAL`

### Edge status lifecycle

```text
candidate -> plausible -> verified
```

The audit model may also represent:

- `unknown`
- `rejected`
- `conflicted`

Unsupported or missing evidence must not be silently converted into a negative causal label.

### Actor role in causality

Actors are used as participants and continuity evidence:

- Actor identity.
- Actor role.
- Actor direction.
- Shared actors between events.
- Actor change or escalation.

An actor alone does not establish that an event caused another event.

### Causal graph constraints

- Verified causal edges form a temporal DAG.
- Cause must defensibly precede effect.
- Unresolved same-time ordering cannot become verified causality.
- Conflicting evidence lowers confidence and remains visible.
- Alternative causes are explicitly searched and displayed.
- Missing accessible article text prevents an edge from entering the causal graph.
- The underlying event remains available in the observation and event layers.

## 10. Candidate generation and verification

### Candidate generation

Candidate retrieval should use a ranked index rather than an unrestricted pairwise join. For each effect, retrieve up to 50 prior candidates using:

- Temporal precedence.
- Geographic relevance.
- Actor overlap or continuity.
- Issue and theme overlap.
- CAMEO event compatibility.
- Semantic similarity.
- Document linkage.
- Source and publication context.

There is no fixed maximum time horizon, but temporal distance is penalized.

### Verification signals

Verification may use:

- Event structure.
- Article text.
- Explicit causal and temporal cues.
- Semantic/NLI compatibility.
- Actor involvement and continuity.
- Location and geographic relevance.
- Issue/demand compatibility.
- Source diversity.
- Mention extraction confidence.
- Article position and document length.
- Alternative or confounding events.
- Conflicting evidence.

### Promotion policy

Use a neural relation classifier as the primary scoring model, but retain an interpretable rule-based baseline for comparison and ablation.

Promotion uses a learned score plus hard gates. Hard gates include:

- Defensible temporal direction.
- Accessible text evidence for causal graph inclusion.
- No unresolved contradiction strong enough to invalidate the relation.
- No temporal cycle.

An edge may become verified through either:

1. Clear direct causal support in text.
2. Strong convergent evidence from independent sources and structured signals.

The neural score is not itself an explanation. Explanations come from the evidence ledger and explicit verifier features.

## 11. Data pipeline architecture

The pipeline is batch-oriented and reproducible:

```text
frozen GDELT raw snapshot
        |
        v
immutable ingestion manifest
        |
        v
normalized Events / Mentions / GKG
        |
        v
English-readable India event universe
        |
        v
document linkage and article evidence
        |
        v
canonical events and protest episodes
        |
        v
issues, themes, actors, locations
        |
        v
ranked causal candidates
        |
        v
plausibility and verification
        |
        v
causal graph and evidence graph
        |
        v
Neo4j projection, API, web explorer
```

Each stage must produce versioned artifacts and a JSON manifest containing:

- Input artifact identifiers.
- Output artifact identifiers.
- Schema version.
- Configuration.
- Thresholds.
- Model versions.
- Counts and quality checks.
- Run timestamp.

Use Parquet for large typed artifacts and JSON manifests for provenance and configuration. DuckDB is the primary analytical engine. Neo4j is a serving/projection layer, not the authoritative source of truth.

## 12. Canonical data entities

### Event

Minimum fields:

- `canonical_event_id`
- `source_event_ids`
- `episode_id`
- `occurrence_interval`
- `event_date`
- `published_at`
- `added_at`
- `event_code`
- `event_root_code`
- `quad_class`
- `goldstein_scale`
- `actor1`
- `actor2`
- `action_location`
- `themes`
- `issues`
- `document_ids`
- `mention_ids`
- `cluster_evidence`
- `provenance`

### Document

Minimum fields:

- `document_id`
- `source_collection`
- `source_name`
- `document_identifier`
- `canonical_url`
- `published_at`
- `language`
- `translated`
- `retrieval_status`
- `content_hash`
- `text_reference`

### Evidence span

Minimum fields:

- `evidence_id`
- `document_id`
- `event_ids`
- `causal_edge_id`
- `sentence_id`
- `char_start`
- `char_end`
- `excerpt`
- `evidence_type`
- `polarity`
- `extractor`
- `extractor_version`

### Causal edge

Minimum fields:

- `causal_edge_id`
- `cause_event_id`
- `effect_event_id`
- `relation_type`
- `status`
- `confidence`
- `temporal_gap_days`
- `features`
- `evidence_ids`
- `alternative_event_ids`
- `conflict_ids`
- `decision_reason`
- `model_version`

## 13. Graph projection

Neo4j should contain all relevant India event nodes, not only verified edges, so users can inspect the full reasoning context.

Primary node types:

- `Event`
- `Episode`
- `Actor`
- `Organization`
- `Location`
- `Issue`
- `Theme`
- `Document`
- `Evidence`

Important relationships:

- `PART_OF_EPISODE`
- `INVOLVES_ACTOR`
- `LOCATED_IN`
- `HAS_ISSUE`
- `HAS_THEME`
- `MENTIONED_IN`
- `SUPPORTED_BY`
- `CONTRADICTED_BY`
- `TEMPORALLY_PRECEDES`
- `ASSOCIATED_WITH`
- `CANDIDATE_CAUSAL`
- `PLAUSIBLE_CAUSAL`
- `VERIFIED_CAUSAL`

The direction of causal edges is always cause to effect.

## 14. Query and explanation behavior

The first user workflow is protest-episode investigation.

The API should accept natural-language questions plus optional structured filters:

- Location.
- Date range.
- Event or episode ID.
- Issue or theme.
- Actor.
- Causal status.
- Maximum hops.

The conversational layer is deterministic and template-based in v1. No LLM or autonomous agent is required.

Supported query families include:

- What plausibly contributed to this protest?
- What events happened next?
- What responses followed this protest?
- Which issues or themes recur across similar protests?
- How did a local event relate to broader India-level events?

The answer layer may summarize only retrieved graph facts and evidence. It must explicitly say when no supported path is found.

Default explanations may rank candidate, plausible, and verified paths, but every edge status must be visible.

Each explanation should expose:

- Event chain.
- Event and episode identities.
- Actors and actor roles.
- Locations and geographic levels.
- Occurrence and publication times.
- Temporal gap.
- Relation type and status.
- Confidence components.
- Supporting evidence excerpts.
- Source groups.
- Conflicting evidence.
- Alternative causes.
- Missing evidence.

Paths are ranked by:

- Weakest-edge confidence.
- Temporal coherence.
- Evidence coverage.
- Actor continuity.
- Location and issue continuity.
- Source diversity.
- Alternative-cause penalties.
- Path length.

The default maximum explanation depth is four hops.

## 15. User interface

The system should be available to the research team through a lightweight web interface and API on a trusted internal server. Authentication is not required for v1.

The main experience should allow a user to:

1. Search for or select a protest episode.
2. Ask what plausibly contributed to it.
3. Inspect the ranked event chains.
4. Expand every event and edge.
5. View supporting articles and evidence spans.
6. Compare plausible and verified paths.
7. Inspect rejected, unknown, conflicted, and alternative links in an audit view.
8. Filter by location, date, issue, actor, theme, and status.

The main explanation should remain understandable while the audit view exposes deeper model details.

## 16. Evaluation plan

Build the complete detected 2024 India protest universe, then select a stratified reviewed sample based on:

- Geographic coverage.
- Protest size and media volume.
- Event complexity.
- Source coverage.
- Translation provenance.
- Causal difficulty.

The initial human evaluation set should contain approximately 300–500 candidate edges.

Use weak labels for scale but evaluate against manually reviewed labels. One primary reviewer will perform v1 review.

Each reviewed edge should receive:

- Causal status.
- Causal direction.
- Relation type.
- Temporal coherence.
- Supporting evidence span.
- Alternative or confounding events.
- Evidence accessibility.

Use a temporal holdout split rather than a random split.

Primary success criteria:

- Evidence-backed India protest case studies.
- High causal precision.
- Correct causal direction.
- Low unsupported-edge rate.
- Evidence grounding.
- Understandable multi-hop explanations.

Also report:

- Causal precision, recall, and F1.
- Direction accuracy.
- Temporal robustness.
- Evidence grounding.
- Explanation faithfulness.
- Temporal coherence.
- Causal consistency.
- Scalability.

## 17. Testing requirements

The implementation must include tests for:

- GDELT parsing and schema normalization.
- Leading-zero CAMEO codes.
- Events, Mentions, and GKG linkage.
- URL canonicalization.
- Syndicated-source deduplication.
- India geographic filtering.
- English-readable and translated-record handling.
- Event clustering.
- Separation of same-theme protests in different locations.
- Episode grouping only with continuity evidence.
- Temporal intervals and one-day reporting-delay bounds.
- Same-day ordering and unresolved ordering.
- Long-range candidate retrieval.
- Top-50 candidate limit.
- Missing-text exclusion from causal edges.
- Alternative-cause analysis.
- Conflict preservation.
- DAG enforcement.
- Candidate/plausible/verified lifecycle.
- Neural verifier versus interpretable baseline.
- Evidence provenance.
- Grounded query answers.
- No-answer behavior when no supported chain exists.
- Reproducible batch manifests.

## 18. Non-goals for v1

- Treating temporal precedence as causality.
- Treating GKG co-occurrence as a relationship.
- Building a multilingual native-language NLP system.
- Using external economic or political data.
- Publishing retained full article text.
- Building an autonomous LLM agent.
- Claiming definitive philosophical or scientific causation from news metadata alone.
- Automatically merging protests solely because they share an issue, theme, actor name, or location.
- Replacing human review with model confidence.

## 19. Known limitations

- GDELT records reflect media coverage and extraction behavior, not an unbiased census of reality.
- Publication time and event time may differ.
- Retrospective reporting can create apparent temporal relationships.
- Source repetition may reflect syndication rather than independent confirmation.
- Actor and location extraction can be ambiguous.
- GKG themes and entities are contextual metadata, not verified semantic relations.
- Article retrieval may fail or change over time.
- A causal edge in this project means an evidence-backed plausible causal claim, not experimentally proven causation.

## 20. Fixed v1 defaults

- Project name: Decoding the Domino Effect.
- Scope: India, 2024, protests and civil unrest.
- Inclusion: action location in India; external context allowed.
- Language: English-readable, including GDELT translations.
- Streams: Events, Mentions, GKG.
- Snapshot: frozen and reproducible.
- Taxonomy: supplied cleaned taxonomy, frozen as an allowlist.
- Event graph: event-centric with actor context.
- Event identity: conservative canonical event clusters.
- Episode identity: hierarchical and continuity-based.
- Time: event date primary, publication-bound, one-day reporting delay.
- Candidate horizon: no fixed maximum.
- Candidate retrieval: top 50 per effect.
- Causal depth: four hops.
- Causal statuses: candidate, plausible, verified, with audit states for unknown, rejected, and conflicted.
- Evidence: web text primarily, best-effort retrieval.
- Full text: private local research storage.
- Missing text: event retained, causal edge excluded.
- Verification: neural scorer plus hard gates and interpretable baseline.
- Source agreement: conservative deduplicated source groups.
- Confounds: explicit alternative-cause analysis.
- Storage: Parquet and JSON manifests, DuckDB analytics, Neo4j projection.
- Querying: deterministic structured retrieval and template explanations.
- UI: lightweight web explorer plus API.
- Deployment: trusted team server without authentication in v1.
- Evaluation: 300–500 manually reviewed edges, temporal holdout, trust/precision priority.


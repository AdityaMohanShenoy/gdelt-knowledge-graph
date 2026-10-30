const REVIEW_FIELDS = [
  "review_status",
  "reviewer",
  "label_source",
  "cohort",
  "split",
  "focal_event_summary",
  "supporting_sentence_ids",
  "notes",
  "eligibility",
  "model_evidence_inspections",
];
const STATUS_NAMES = {
  UNREVIEWED: "To review",
  REVIEWED: "Reviewed",
  UNSUITABLE: "Excluded",
};
const ELIGIBILITY_LABELS = {
  protest_relevance: ["PROTEST", "PROTEST_LINKED", "UNRELATED", "UNCERTAIN"],
  body_quality: ["COMPLETE", "LIMITED", "INSUFFICIENT"],
  scope: ["INDIA_2024", "OUT_OF_SCOPE", "UNCERTAIN"],
  exclusion_reason: ["UNRELATED", "INSUFFICIENT_TEXT", "OUT_OF_SCOPE", "NO_FOCAL_EVENT", "OTHER"],
};
const ENTITY_LABELS = ["PERSON", "ORGANIZATION", "LOCATION", "DATE"];

function entityLabels(record) {
  if (record.entity_schema === undefined) return ENTITY_LABELS;
  if (
    !record.entity_schema ||
    typeof record.entity_schema !== "object" ||
    Array.isArray(record.entity_schema) ||
    !Object.keys(record.entity_schema).length ||
    Object.entries(record.entity_schema).some(
      ([label, description]) =>
        !label.trim() || typeof description !== "string" || !description.trim(),
    )
  )
    throw new Error("The entity schema is invalid.");
  return Object.keys(record.entity_schema);
}

function validateNerAnnotation(record) {
  const ner = record.ner_annotation;
  if (ner === undefined) return;
  if (
    !ner ||
    !["UNREVIEWED", "REVIEWED"].includes(ner.review_status) ||
    typeof ner.whole_article_checked !== "boolean" ||
    (ner.reviewer !== null && typeof ner.reviewer !== "string") ||
    (ner.label_source !== null && !["human", "ai_assisted"].includes(ner.label_source)) ||
    (ner.reviewed_at !== null &&
      (typeof ner.reviewed_at !== "string" ||
        !/^\d{4}-\d{2}-\d{2}T/.test(ner.reviewed_at) ||
        !Number.isFinite(Date.parse(ner.reviewed_at))))
  )
    throw new Error("Entity annotation review metadata is invalid.");
  if (
    ner.review_status === "REVIEWED" &&
    (!ner.reviewer?.trim() ||
      !["human", "ai_assisted"].includes(ner.label_source) ||
      !ner.whole_article_checked ||
      !ner.reviewed_at ||
      !Array.isArray(record.gold_entities))
  )
    throw new Error("Reviewed entities require a reviewer, provenance and a whole-article check.");
}

function spanFromUtf16(text, begin, finish) {
  if (
    typeof text !== "string" ||
    !Number.isInteger(begin) ||
    !Number.isInteger(finish) ||
    Math.min(begin, finish) < 0 ||
    Math.max(begin, finish) > text.length
  )
    throw new Error("Select an entity within the original article.");
  const start = Math.min(begin, finish);
  const end = Math.max(begin, finish);
  const chars = Array.from(text);
  const startChar = Array.from(text.slice(0, start)).length;
  const endChar = Array.from(text.slice(0, end)).length;
  if (
    chars.slice(0, startChar).join("").length !== start ||
    chars.slice(0, endChar).join("").length !== end
  )
    throw new Error("The selection splits a Unicode character.");
  const selected = chars.slice(startChar, endChar).join("");
  const trimmed = selected.trim();
  if (!trimmed) throw new Error("Select a nonempty entity span.");
  const offset = Array.from(selected).length - Array.from(selected.trimStart()).length;
  return {
    text: trimmed,
    start_char: startChar + offset,
    end_char: startChar + offset + Array.from(trimmed).length,
  };
}

function entityDraft(record, metadata = {}) {
  record.ner_annotation = {
    review_status: "UNREVIEWED",
    reviewer: record.ner_annotation?.reviewer || null,
    label_source: record.ner_annotation?.label_source || null,
    ...metadata,
    whole_article_checked: false,
    reviewed_at: null,
  };
}

function addGoldEntity(record, span, label) {
  const candidate = { ...span, label };
  const entities = [...(record.gold_entities || []), candidate];
  validateAnnotation({ ...record, gold_entities: entities });
  record.gold_entities = entities;
  entityDraft(record);
}

function removeGoldEntity(record, index) {
  if (!Number.isInteger(index) || index < 0 || index >= (record.gold_entities || []).length)
    throw new Error("Choose an existing entity annotation.");
  record.gold_entities = record.gold_entities.filter((_, position) => position !== index);
  entityDraft(record);
}

function completeNerReview(record, metadata, reviewedAt = new Date().toISOString()) {
  const candidate = {
    ...record,
    gold_entities: record.gold_entities || [],
    ner_annotation: { ...metadata, review_status: "REVIEWED", reviewed_at: reviewedAt },
  };
  validateAnnotation(candidate);
  record.gold_entities = candidate.gold_entities;
  record.ner_annotation = candidate.ner_annotation;
}

function validateEligibility(eligibility) {
  if (!eligibility || !["UNREVIEWED", "REVIEWED"].includes(eligibility.review_status))
    throw new Error("Unknown article screening status.");
  for (const [field, choices] of Object.entries(ELIGIBILITY_LABELS))
    if (eligibility[field] != null && !choices.includes(eligibility[field]))
      throw new Error(`Invalid article screening label: ${field}.`);
  if (eligibility.review_status !== "REVIEWED") return;
  if (typeof eligibility.reviewer !== "string" || !eligibility.reviewer.trim())
    throw new Error("Enter the screening reviewer name.");
  if (["protest_relevance", "body_quality", "scope"].some((field) => !eligibility[field]))
    throw new Error("Choose protest relevance, article body quality and geographic/time scope.");
}

function validateReview(record) {
  if (!Object.hasOwn(STATUS_NAMES, record.review_status)) throw new Error("Unknown review status.");
  if (!["pilot", "train", "dev", "test"].includes(record.split))
    throw new Error("Choose a valid evaluation split.");
  const ids = new Set(record.sentences.map((sentence) => sentence.sentence_id));
  if (
    !Array.isArray(record.supporting_sentence_ids) ||
    record.supporting_sentence_ids.some((id) => !Number.isInteger(id) || !ids.has(id))
  ) {
    throw new Error("Evidence must refer to sentences in this article.");
  }
  if (new Set(record.supporting_sentence_ids).size !== record.supporting_sentence_ids.length)
    throw new Error("Evidence sentence IDs must be unique.");
  for (const field of ["reviewer", "cohort", "focal_event_summary", "notes"]) {
    if (record[field] !== null && typeof record[field] !== "string")
      throw new Error(`Invalid ${field} field.`);
  }
  if (record.label_source !== null && !["human", "ai_assisted"].includes(record.label_source))
    throw new Error("Choose a valid label source.");
  if (record.eligibility !== undefined) validateEligibility(record.eligibility);
  validateModelInspections(record.model_evidence_inspections);
  validateNerAnnotation(record);
  if (record.review_status === "UNREVIEWED") return;
  if (!record.reviewer?.trim()) throw new Error("Enter your reviewer name.");
  if (!["human", "ai_assisted"].includes(record.label_source))
    throw new Error("Choose a label source.");
  if (record.review_status === "UNSUITABLE") {
    if (record.eligibility?.exclusion_reason === "OTHER" && !record.notes?.trim())
      throw new Error("Explain the other exclusion reason in notes.");
    if (!record.notes?.trim() && !record.eligibility?.exclusion_reason)
      throw new Error("Choose an exclusion reason or add it in notes.");
    return;
  }
  if (!record.focal_event_summary?.trim()) throw new Error("Describe the primary event.");
  if (!record.supporting_sentence_ids.length)
    throw new Error("Select at least one supporting sentence.");
}

function validateModelInspections(inspections) {
  if (inspections === undefined) return;
  if (
    !Array.isArray(inspections) ||
    inspections.some(
      (entry) =>
        !entry ||
        typeof entry.filename !== "string" ||
        !entry.filename.trim() ||
        !/^[a-f0-9]{64}$/.test(entry.input_sha256) ||
        typeof entry.viewed_at !== "string" ||
        !/^\d{4}-\d{2}-\d{2}T/.test(entry.viewed_at) ||
        !Number.isFinite(Date.parse(entry.viewed_at)),
    ) ||
    new Set(inspections.map((entry) => entry.input_sha256)).size !== inspections.length
  )
    throw new Error("Model evidence inspection history is invalid.");
}

function recordModelInspection(record, evidence, viewedAt = new Date().toISOString()) {
  if (
    evidence.schema_version !== "focal-evidence-review.v1" ||
    evidence.result?.article_id !== record.article_id ||
    evidence.result?.article_text_sha256 !== record.article_text_sha256
  )
    throw new Error("Model evidence does not match this article snapshot.");
  const inspection = {
    filename: evidence.filename,
    input_sha256: evidence.input_sha256,
    viewed_at: viewedAt,
  };
  validateModelInspections([inspection]);
  validateModelInspections(record.model_evidence_inspections);
  const previous = record.model_evidence_inspections || [];
  if (!previous.some((entry) => entry.input_sha256 === inspection.input_sha256))
    record.model_evidence_inspections = [...previous, inspection];
}

function entityLabelConflicts(entities) {
  const labels = new Map();
  for (const entity of entities) {
    const key = `${entity.start_char}:${entity.end_char}`;
    if (!labels.has(key)) labels.set(key, new Set());
    labels.get(key).add(entity.label);
  }
  return new Set(
    Array.from(labels)
      .filter(([, values]) => values.size > 1)
      .map(([key]) => key),
  );
}

function validateAnnotation(record) {
  if (!record || record.schema_version !== "focal-event-gold.v1")
    throw new Error("Choose an annotation JSONL file created by the annotate command.");
  if (typeof record.article_id !== "string" || !record.article_id)
    throw new Error("An article ID is missing.");
  if (typeof record.article_text !== "string" || !/^[a-f0-9]{64}$/.test(record.article_text_sha256))
    throw new Error("The article snapshot or text hash is invalid.");
  if (record.headline !== null && typeof record.headline !== "string")
    throw new Error("The headline is invalid.");
  if (!Array.isArray(record.sentences)) throw new Error("The numbered sentences are missing.");
  const chars = Array.from(record.article_text);
  const seen = new Set();
  let previousEnd = 0;
  for (const sentence of record.sentences) {
    if (
      !Number.isInteger(sentence.sentence_id) ||
      sentence.sentence_id < 1 ||
      seen.has(sentence.sentence_id)
    )
      throw new Error("Sentence IDs must be positive and unique.");
    seen.add(sentence.sentence_id);
    if (
      !Number.isInteger(sentence.start_char) ||
      !Number.isInteger(sentence.end_char) ||
      sentence.start_char < previousEnd ||
      sentence.end_char <= sentence.start_char ||
      sentence.end_char > chars.length
    )
      throw new Error("Sentence offsets are invalid or out of article order.");
    if (chars.slice(sentence.start_char, sentence.end_char).join("") !== sentence.text)
      throw new Error("A sentence does not match the original article text.");
    previousEnd = sentence.end_char;
  }
  if (record.gold_entities !== null && !Array.isArray(record.gold_entities))
    throw new Error("Entity annotations must be a list or null.");
  const labels = entityLabels(record);
  const entityKeys = new Set();
  for (const entity of record.gold_entities || []) {
    if (
      !entity ||
      !labels.includes(entity.label) ||
      !Number.isInteger(entity.start_char) ||
      !Number.isInteger(entity.end_char) ||
      entity.start_char < 0 ||
      entity.end_char <= entity.start_char ||
      entity.end_char > chars.length ||
      chars.slice(entity.start_char, entity.end_char).join("") !== entity.text
    )
      throw new Error("An entity annotation does not match the original article text.");
    const key = `${entity.start_char}:${entity.end_char}:${entity.label}`;
    if (entityKeys.has(key)) throw new Error("Duplicate gold entity spans.");
    entityKeys.add(key);
  }
  validateReview(record);
}

function parseAnnotations(text) {
  const records = text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line, index) => {
      try {
        const record = JSON.parse(line);
        validateAnnotation(record);
        return record;
      } catch (error) {
        throw new Error(`Line ${index + 1}: ${error.message}`);
      }
    });
  if (!records.length) throw new Error("This annotation file is empty.");
  if (new Set(records.map((record) => record.article_id)).size !== records.length)
    throw new Error("The annotation file contains duplicate article IDs.");
  return records;
}

function immutableSnapshot(record, allowEntityEdits = false) {
  return JSON.stringify({
    article_id: record.article_id,
    article_text_sha256: record.article_text_sha256,
    headline: record.headline,
    article_text: record.article_text,
    sentences: record.sentences,
    gold_entities: allowEntityEdits === true ? undefined : record.gold_entities,
    entity_schema: record.entity_schema,
    screening: record.screening,
    source_metadata: record.source_metadata,
  });
}

function serializeAnnotations(records, snapshots, allowEntityEdits = false) {
  const lines = records
    .map((record, index) => {
      validateAnnotation(record);
      if (snapshots && immutableSnapshot(record, allowEntityEdits) !== snapshots[index])
        throw new Error("Original article evidence changed. Reload your annotation file.");
      return JSON.stringify(record);
    })
    .join("\n");
  return `${lines}\n`;
}

function draftFields(record, allowEntityEdits = false) {
  return Object.fromEntries(
    [
      "article_id",
      ...REVIEW_FIELDS,
      ...(allowEntityEdits === true ? ["gold_entities", "ner_annotation"] : []),
    ].map((field) => [field, record[field]]),
  );
}

function applyDrafts(records, drafts, allowEntityEdits = false) {
  if (
    !Array.isArray(drafts) ||
    new Set(drafts.map((draft) => draft.article_id)).size !== drafts.length
  )
    throw new Error("Saved drafts contain invalid or duplicate article IDs.");
  const map = new Map(drafts.map((draft) => [draft.article_id, draft]));
  const ids = new Set(records.map((record) => record.article_id));
  if (drafts.some((draft) => !ids.has(draft.article_id)))
    throw new Error("Saved drafts belong to a different batch.");
  return records.map((record) => {
    const draft = map.get(record.article_id);
    if (!draft) return record;
    const merged = { ...record };
    for (const field of [
      ...REVIEW_FIELDS,
      ...(allowEntityEdits === true ? ["gold_entities", "ner_annotation"] : []),
    ])
      if (Object.hasOwn(draft, field)) merged[field] = draft[field];
    validateAnnotation(merged);
    return merged;
  });
}

async function sha256(text) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifySnapshots(records) {
  await Promise.all(
    records.map(async (record) => {
      if ((await sha256(record.article_text)) !== record.article_text_sha256)
        throw new Error(
          `Article ${record.article_id}: the full text does not match its saved hash.`,
        );
    }),
  );
}

async function batchStorageKey(records, allowEntityEdits = false) {
  const identity = records.map((record) => {
    const snapshot = [
      record.article_id,
      record.article_text_sha256,
      record.headline,
      record.sentences,
    ];
    if (record.screening !== undefined || record.source_metadata !== undefined)
      snapshot.push(record.screening, record.source_metadata);
    if (allowEntityEdits === true) snapshot.push(record.entity_schema);
    return snapshot;
  });
  return `focal-review.${allowEntityEdits === true ? "v2" : "v1"}:${await sha256(JSON.stringify(identity))}`;
}

if (typeof module !== "undefined") {
  module.exports = {
    ELIGIBILITY_LABELS,
    validateEligibility,
    validateReview,
    validateAnnotation,
    parseAnnotations,
    serializeAnnotations,
    immutableSnapshot,
    draftFields,
    applyDrafts,
    verifySnapshots,
    batchStorageKey,
    validateModelInspections,
    recordModelInspection,
    entityLabelConflicts,
    entityLabels,
    validateNerAnnotation,
    spanFromUtf16,
    addGoldEntity,
    removeGoldEntity,
    completeNerReview,
  };
}

if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const state = {
    records: [],
    snapshots: [],
    active: 0,
    key: null,
    timer: null,
    inspector: { key: null, controller: null, evidence: null },
    entitySelection: null,
  };
  const formFields = {
    focal_event_summary: "event-summary",
    cohort: "cohort",
    reviewer: "reviewer",
    label_source: "label-source",
    split: "split",
    notes: "notes",
  };
  const eligibilityFields = {
    protest_relevance: "protest-relevance",
    body_quality: "body-quality",
    scope: "scope",
    exclusion_reason: "exclusion-reason",
    reviewer: "screening-reviewer",
  };

  function showMessage(text, error = false) {
    $("message").textContent = text;
    $("message").dataset.error = String(error);
    $("message").hidden = !text;
  }

  function persistNow() {
    clearTimeout(state.timer);
    if (!state.key) return;
    try {
      localStorage.setItem(
        state.key,
        JSON.stringify({
          schema_version: "focal-review-drafts.v2",
          drafts: state.records.map((record) => draftFields(record, true)),
        }),
      );
      $("save-status").textContent =
        "Drafts saved in this browser. Export a backup to keep them elsewhere.";
      $("save-status").dataset.error = "false";
    } catch {
      $("save-status").textContent =
        "Browser storage is unavailable. Export a backup before closing.";
      $("save-status").dataset.error = "true";
    }
  }

  function queueSave() {
    clearTimeout(state.timer);
    $("save-status").textContent = "Saving draft…";
    state.timer = setTimeout(persistNow, 180);
  }

  function readForm() {
    const record = state.records[state.active];
    for (const [field, id] of Object.entries(formFields))
      record[field] = $(id).value.trim() || null;
    record.eligibility ||= { review_status: "UNREVIEWED", reviewed_at: null };
    for (const [field, id] of Object.entries(eligibilityFields))
      record.eligibility[field] = $(id).value.trim() || null;
    if (record.reviewer) {
      try {
        localStorage.setItem("focal-review.reviewer.v1", record.reviewer);
      } catch {}
    }
    if (record.eligibility.reviewer) {
      try {
        localStorage.setItem("focal-review.screening-reviewer.v1", record.eligibility.reviewer);
      } catch {}
    }
    return record;
  }

  function filterQueue() {
    const query = $("search").value.trim().toLowerCase();
    const filter = $("queue-filter").value;
    let visible = 0;
    for (const [index, record] of state.records.entries()) {
      const element = $("article-list").children[index];
      const match =
        (filter === "all" || record.review_status === filter) &&
        `${record.headline || ""} ${record.article_id}`.toLowerCase().includes(query);
      element.hidden = !match;
      visible += Number(match);
    }
    $("no-matches").hidden = visible > 0;
  }

  function resetEntitySelection() {
    state.entitySelection = null;
    $("entity-selection").textContent = "No entity span selected.";
    $("add-entity").disabled = true;
  }

  function renderGoldEntities(record) {
    const container = $("gold-entities");
    container.replaceChildren();
    const entities = record.gold_entities || [];
    const ner = record.ner_annotation;
    $("ner-state").textContent =
      ner?.review_status === "REVIEWED"
        ? `${entities.length} entity occurrences confirmed by ${ner.reviewer}.`
        : ner
          ? `${entities.length} entity occurrences in draft; excluded from NER metrics.`
          : record.gold_entities === null
            ? "Entity annotation has not started."
            : `${entities.length} legacy entity occurrences. Confirm a whole-article check to record entity provenance.`;
    for (const { entity, index } of entities
      .map((entity, index) => ({ entity, index }))
      .sort(
        (a, b) =>
          a.entity.start_char - b.entity.start_char || a.entity.end_char - b.entity.end_char,
      )) {
      const item = document.createElement("li");
      item.className = "gold-entity";
      const body = document.createElement("div");
      const name = document.createElement("span");
      name.className = "entity-name";
      name.textContent = entity.text;
      const label = document.createElement("span");
      label.className = "entity-label";
      label.textContent = `${entity.label} · article characters ${entity.start_char}–${entity.end_char}`;
      body.append(name, label);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove";
      remove.setAttribute(
        "aria-label",
        `Remove ${entity.label}: ${entity.text} at ${entity.start_char}`,
      );
      remove.addEventListener("click", () => {
        removeGoldEntity(record, index);
        refreshEntityDraft(record);
      });
      item.append(body, remove);
      container.append(item);
    }
  }

  function refreshEntityDraft(record) {
    entityDraft(record, {
      reviewer: $("ner-reviewer").value.trim() || null,
      label_source: $("ner-label-source").value,
    });
    $("ner-whole-article").checked = false;
    $("ner-error").hidden = true;
    renderGoldEntities(record);
    queueSave();
  }

  function captureEntitySelection() {
    if (state.records[state.active]?.review_status !== "REVIEWED") return;
    const selection = window.getSelection();
    if (!selection?.rangeCount || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    const node = $("original-text").firstChild;
    if (range.startContainer !== node || range.endContainer !== node) {
      resetEntitySelection();
      return;
    }
    try {
      state.entitySelection = spanFromUtf16(node.textContent, range.startOffset, range.endOffset);
      const span = state.entitySelection;
      $("entity-selection").textContent =
        `Selected: ${span.text} · article characters ${span.start_char}–${span.end_char}`;
      $("add-entity").disabled = false;
      $("ner-error").hidden = true;
    } catch (error) {
      resetEntitySelection();
      $("ner-error").textContent = error.message;
      $("ner-error").hidden = false;
    }
  }

  function renderEntityEditor(record) {
    $("entity-editor").open = false;
    resetEntitySelection();
    $("entity-label").replaceChildren();
    for (const label of entityLabels(record)) {
      const option = document.createElement("option");
      option.value = label;
      option.textContent = label;
      $("entity-label").append(option);
    }
    $("ner-reviewer").value = record.ner_annotation?.reviewer || "";
    $("ner-label-source").value =
      record.ner_annotation?.label_source ||
      (record.gold_entities !== null ? record.label_source : null) ||
      "human";
    $("ner-whole-article").checked = record.ner_annotation?.whole_article_checked === true;
    $("ner-error").hidden = true;
    renderGoldEntities(record);
  }

  function syncModelInspector(record) {
    const panel = $("model-inspector");
    const key = `${record.article_id}:${record.article_text_sha256}:${record.review_status}`;
    panel.hidden = record.review_status === "UNREVIEWED";
    if (state.inspector.key === key) return;
    state.inspector.controller?.abort();
    state.inspector = { key, controller: null, evidence: null };
    panel.open = false;
    $("model-evidence-state").textContent = "";
    $("model-evidence-state").dataset.error = "false";
    $("model-evidence-candidates").replaceChildren();
    $("model-evidence-source").textContent = "";
    $("model-provenance").textContent = "";
    $("model-provenance-panel").hidden = true;
    $("model-provenance-panel").open = false;
  }

  function renderModelEvidence(record, evidence) {
    const prediction = evidence.result;
    const candidates = prediction.candidate_sentences;
    const matching = candidates.filter((sentence) =>
      record.supporting_sentence_ids.includes(sentence.sentence_id),
    );
    $("model-evidence-state").dataset.error = "false";
    $("model-evidence-state").textContent =
      prediction.processing_status === "ERROR"
        ? "Extraction recorded an error. Inspect the available evidence and processing notes."
        : record.review_status === "UNSUITABLE"
          ? "This article is excluded from focal-event evaluation."
          : matching.length
            ? `Your saved evidence includes ${matching.length} of these ${candidates.length} candidates.`
            : "None of your saved evidence sentences appears in the retrieved candidates.";
    const container = $("model-evidence-candidates");
    container.replaceChildren();
    for (const sentence of candidates) {
      const section = document.createElement("section");
      section.className = "model-candidate";
      const heading = document.createElement("h3");
      heading.textContent = `Rank ${sentence.rank}: sentence ${sentence.sentence_id}${record.supporting_sentence_ids.includes(sentence.sentence_id) ? " — selected evidence" : ""}`;
      const text = document.createElement("p");
      text.className = "model-candidate-text";
      text.textContent = sentence.text;
      const signals = document.createElement("p");
      signals.className = "model-signals";
      signals.textContent = `${[
        ["Importance", "importance_score"],
        ["Headline", "headline_score"],
        ["Position", "position_score"],
        ["Event cues", "event_relevance"],
      ]
        .map(
          ([label, field]) =>
            `${label}: ${Number.isFinite(sentence[field]) ? sentence[field].toFixed(3) : "unavailable"}`,
        )
        .join(" · ")}. Article characters ${sentence.start_char}–${sentence.end_char}.`;
      section.append(heading, text, signals);
      const entities = document.createElement("ul");
      entities.className = "model-entities";
      const conflicts = entityLabelConflicts(sentence.entities);
      for (const entity of sentence.entities) {
        const item = document.createElement("li");
        item.className = "model-entity";
        item.dataset.conflict = String(conflicts.has(`${entity.start_char}:${entity.end_char}`));
        const name = document.createElement("span");
        name.className = "entity-name";
        name.textContent = entity.text;
        const label = document.createElement("span");
        label.className = "entity-label";
        label.textContent = `${entity.label}. Confidence: ${entity.confidence == null ? "unavailable" : entity.confidence.toFixed(3)}. Article characters ${entity.start_char}–${entity.end_char}; sentence characters ${entity.sentence_start_char}–${entity.sentence_end_char}.`;
        item.append(name, label);
        if (item.dataset.conflict === "true") {
          const conflict = document.createElement("span");
          conflict.className = "entity-conflict";
          conflict.textContent = "Multiple labels predicted for this span";
          item.append(conflict);
        }
        entities.append(item);
      }
      if (sentence.entities.length) section.append(entities);
      const nerNote = document.createElement("p");
      nerNote.className = "model-note";
      nerNote.textContent =
        sentence.ner_status === "ERROR"
          ? "Entity extraction failed for this sentence."
          : sentence.ner_status !== "COMPLETE"
            ? "Entity extraction is not complete for this sentence."
            : sentence.entities.length
              ? `${sentence.entities.length} entity predictions. Verify spans and labels before acceptance.`
              : "Entity extraction returned no entities for this sentence.";
      section.append(nerNote);
      container.append(section);
    }
    if (!candidates.length) {
      const empty = document.createElement("p");
      empty.className = "model-note";
      empty.textContent = "No ranked candidate sentences were saved.";
      container.append(empty);
    }
    for (const error of prediction.errors || []) {
      const note = document.createElement("p");
      note.className = "model-note";
      note.textContent = `${error.stage}: ${error.message}`;
      container.append(note);
    }
    $("model-evidence-source").textContent =
      `Results file: ${evidence.filename}\nSHA-256: ${evidence.input_sha256}`;
    $("model-provenance").textContent = JSON.stringify(prediction.models || {}, null, 2);
    $("model-provenance-panel").hidden = false;
  }

  async function inspectModelEvidence() {
    if (!$("model-inspector").open) {
      state.inspector.controller?.abort();
      state.inspector.controller = null;
      return;
    }
    const record = state.records[state.active];
    if (!record || record.review_status === "UNREVIEWED" || state.inspector.evidence) return;
    state.inspector.controller?.abort();
    const controller = new AbortController();
    const key = state.inspector.key;
    state.inspector.controller = controller;
    $("model-evidence-state").textContent = "Checking the saved model evidence…";
    $("model-evidence-state").dataset.error = "false";
    try {
      const response = await fetch(
        `/api/focal-review/evidence/${encodeURIComponent(record.article_id)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(record),
          cache: "no-store",
          signal: controller.signal,
        },
      );
      const evidence = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(
          typeof evidence.detail === "string"
            ? evidence.detail
            : "Model evidence could not be loaded. Use the matching extraction results file.",
        );
      if (state.inspector.key !== key || state.inspector.controller !== controller) return;
      renderModelEvidence(record, evidence);
      recordModelInspection(record, evidence);
      state.inspector.evidence = evidence;
      persistNow();
    } catch (error) {
      if (error.name === "AbortError") return;
      if (state.inspector.key === key && state.inspector.controller === controller) {
        $("model-evidence-state").textContent = error.message;
        $("model-evidence-state").dataset.error = "true";
        $("model-evidence-candidates").replaceChildren();
        $("model-evidence-source").textContent = "";
        $("model-provenance-panel").hidden = true;
      }
    } finally {
      if (state.inspector.controller === controller) state.inspector.controller = null;
    }
  }

  function updateChrome() {
    const record = state.records[state.active];
    const quality = record.screening?.text_quality;
    $("screening-summary").hidden = !quality;
    if (quality) {
      const bodyNote =
        quality.status === "SHORT_REVIEW"
          ? "Short extract: check whether the body supports the event."
          : quality.status === "UNVERIFIED"
            ? "Stored extract: body quality needs verification."
            : "Saved article body rechecked.";
      const reviewNote =
        record.eligibility?.review_status === "REVIEWED"
          ? "Article screening saved. Event evidence has a separate review."
          : "Protest relevance still needs review.";
      $("screening-summary").textContent = `${quality.word_count} words. ${bodyNote} ${reviewNote}`;
    }
    const complete = state.records.filter((entry) => entry.review_status !== "UNREVIEWED").length;
    $("progress-label").textContent = `${complete} of ${state.records.length} done`;
    $("screening-progress").textContent =
      `${state.records.filter((entry) => entry.eligibility?.review_status === "REVIEWED").length} of ${state.records.length} screened`;
    $("progress").max = state.records.length;
    $("progress").value = complete;
    $("article-position").textContent = `Article ${state.active + 1} of ${state.records.length}`;
    $("review-status").textContent = STATUS_NAMES[record.review_status];
    $("review-status").dataset.status = record.review_status;
    $("previous").disabled = state.active === 0;
    $("next").disabled = state.active === state.records.length - 1;
    $("selection-label").textContent = record.supporting_sentence_ids.length
      ? `Evidence: ${record.supporting_sentence_ids.length === 1 ? "sentence" : "sentences"} ${record.supporting_sentence_ids.join(", ")}`
      : "No evidence selected";
    for (const [index, entry] of state.records.entries()) {
      const item = $("article-list").children[index];
      item.setAttribute("aria-current", String(index === state.active));
      item.lastElementChild.textContent = `${STATUS_NAMES[entry.review_status]} · ${entry.article_id}`;
      item.lastElementChild.dataset.status = entry.review_status;
    }
    for (const button of $("sentence-list").querySelectorAll(".sentence"))
      button.setAttribute(
        "aria-pressed",
        String(record.supporting_sentence_ids.includes(Number(button.dataset.sentenceId))),
      );
    filterQueue();
    syncModelInspector(record);
    $("entity-editor").hidden = record.review_status !== "REVIEWED";
    if (record.review_status !== "REVIEWED") {
      $("entity-editor").open = false;
      resetEntitySelection();
    }
  }

  function changeDraft(event) {
    const record = readForm();
    record.review_status = "UNREVIEWED";
    if (event && Object.values(eligibilityFields).includes(event.target.id)) {
      record.eligibility.review_status = "UNREVIEWED";
      record.eligibility.reviewed_at = null;
    }
    $("review-error").hidden = true;
    updateChrome();
    queueSave();
  }

  function renderArticle() {
    const record = state.records[state.active];
    $("article-headline").textContent = record.headline || "Untitled article";
    $("article-id").textContent = `Article ID ${record.article_id}`;
    $("sentence-count").textContent = `${record.sentences.length} sentences`;
    $("original-text").textContent = record.article_text;
    $("original-article").open = false;
    renderEntityEditor(record);
    $("sentence-list").replaceChildren();
    let paragraph = null;
    let paragraphId = null;
    for (const sentence of record.sentences) {
      if (!paragraph || sentence.paragraph_id !== paragraphId) {
        paragraph = document.createElement("div");
        paragraph.className = "paragraph";
        $("sentence-list").append(paragraph);
        paragraphId = sentence.paragraph_id;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sentence";
      button.dataset.sentenceId = sentence.sentence_id;
      button.setAttribute("aria-label", `Sentence ${sentence.sentence_id}: ${sentence.text}`);
      const number = document.createElement("span");
      number.className = "sentence-number";
      number.textContent = sentence.sentence_id;
      number.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      text.className = "sentence-text";
      text.textContent = sentence.text;
      button.append(number, text);
      button.addEventListener("click", () => {
        const selected = new Set(record.supporting_sentence_ids);
        if (selected.has(sentence.sentence_id)) selected.delete(sentence.sentence_id);
        else selected.add(sentence.sentence_id);
        record.supporting_sentence_ids = Array.from(selected).sort((a, b) => a - b);
        changeDraft();
      });
      paragraph.append(button);
    }
    if (!record.sentences.length)
      $("sentence-list").textContent =
        "This article has no readable sentences. Add a note before excluding it.";
    let preferredReviewer = "";
    try {
      preferredReviewer = localStorage.getItem("focal-review.reviewer.v1") || "";
    } catch {}
    for (const [field, id] of Object.entries(formFields)) {
      let value = record[field] || "";
      if (field === "reviewer" && !value) value = preferredReviewer;
      if (field === "label_source" && !value) value = "human";
      const input = $(id);
      if (
        input.tagName === "SELECT" &&
        !Array.from(input.options).some((option) => option.value === value)
      ) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        input.append(option);
      }
      input.value = value;
    }
    for (const [field, id] of Object.entries(eligibilityFields))
      $(id).value = record.eligibility?.[field] || "";
    if (!$("screening-reviewer").value) {
      try {
        $("screening-reviewer").value =
          localStorage.getItem("focal-review.screening-reviewer.v1") || "";
      } catch {}
    }
    $("eligibility-panel").open = record.eligibility?.review_status !== "REVIEWED";
    $("review-error").hidden = true;
    updateChrome();
  }

  function moveTo(index) {
    if (index < 0 || index >= state.records.length || index === state.active) return;
    persistNow();
    state.active = index;
    renderArticle();
    $("article-headline").scrollIntoView({ block: "start", behavior: "auto" });
  }

  function renderQueue() {
    $("article-list").replaceChildren();
    for (const [index, record] of state.records.entries()) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "queue-item";
      const title = document.createElement("span");
      title.className = "queue-title";
      title.textContent = record.headline || "Untitled article";
      const status = document.createElement("span");
      status.className = "queue-status";
      button.append(title, status);
      button.addEventListener("click", () => moveTo(index));
      $("article-list").append(button);
    }
  }

  async function loadDataset(text, restoreDrafts) {
    let records = parseAnnotations(text);
    await verifySnapshots(records);
    const key = await batchStorageKey(records, true);
    let restored = false;
    let restoreError = null;
    persistNow();
    if (restoreDrafts) {
      try {
        const cached = localStorage.getItem(key);
        if (cached) {
          const envelope = JSON.parse(cached);
          if (envelope.schema_version !== "focal-review-drafts.v2")
            throw new Error("Unknown saved draft format.");
          records = applyDrafts(records, envelope.drafts, true);
          restored = true;
        } else {
          const legacy = localStorage.getItem(await batchStorageKey(records));
          if (legacy) {
            records = applyDrafts(records, JSON.parse(legacy));
            restored = true;
          }
        }
      } catch (error) {
        restoreError = error.message;
      }
    }
    state.records = records;
    state.inspector.controller?.abort();
    state.inspector = { key: null, controller: null, evidence: null };
    state.snapshots = records.map((record) => immutableSnapshot(record, true));
    state.key = key;
    state.active = Math.max(
      0,
      records.findIndex((record) => record.review_status === "UNREVIEWED"),
    );
    $("search").value = "";
    $("queue-filter").value = "all";
    renderQueue();
    renderArticle();
    $("workspace").hidden = false;
    $("empty").hidden = true;
    $("export-file").disabled = false;
    persistNow();
    if (restoreError)
      showMessage(
        `Saved drafts could not be restored: ${restoreError} Import your exported backup to recover them.`,
        true,
      );
    else
      showMessage(
        restored
          ? `Restored your browser drafts for ${records.length} articles.`
          : `Loaded ${records.length} articles. Drafts stay in this browser; exported annotations are your backup.`,
      );
  }

  async function loadPilot() {
    $("load-pilot").disabled = true;
    showMessage("Loading pilot annotations…");
    try {
      const response = await fetch("/api/focal-review/annotations", {
        cache: "no-store",
      });
      if (!response.ok)
        throw new Error(
          "The pilot annotation file is unavailable. Import an annotation JSONL file to begin.",
        );
      await loadDataset(await response.text(), true);
    } catch (error) {
      showMessage(error.message, true);
      if (!state.records.length) {
        $("empty").querySelector("h2").textContent = "Bring an article batch to review";
        $("empty-message").textContent =
          "Import an annotation JSONL file using the button above. Your existing files will stay unchanged.";
      }
    } finally {
      $("load-pilot").disabled = false;
    }
  }

  function completeReview(status) {
    const record = readForm();
    const candidate = { ...record, review_status: status };
    try {
      validateReview(candidate);
    } catch (error) {
      $("review-error").textContent = error.message;
      $("review-error").hidden = false;
      return;
    }
    record.review_status = status;
    persistNow();
    updateChrome();
    const remaining = state.records
      .map((entry, index) => ({ entry, index }))
      .filter(({ entry }) => entry.review_status === "UNREVIEWED");
    const next = remaining.find(({ index }) => index > state.active) || remaining[0];
    if (next) moveTo(next.index);
    else showMessage("This batch is reviewed. Export your annotations to evaluate the results.");
  }

  function saveScreening() {
    const record = readForm();
    const eligibility = {
      ...record.eligibility,
      review_status: "REVIEWED",
      reviewed_at: new Date().toISOString(),
    };
    try {
      validateEligibility(eligibility);
    } catch (error) {
      $("review-error").textContent = error.message;
      $("review-error").hidden = false;
      return;
    }
    record.eligibility = eligibility;
    $("eligibility-panel").open = false;
    $("review-error").hidden = true;
    persistNow();
    updateChrome();
    showMessage("Article screening saved. Event evidence keeps its separate review status.");
  }

  $("load-pilot").addEventListener("click", loadPilot);
  $("model-inspector").addEventListener("toggle", inspectModelEvidence);
  $("show-entity-source").addEventListener("click", () => {
    $("original-article").open = true;
    $("original-article").scrollIntoView({ block: "start" });
  });
  document.addEventListener("selectionchange", captureEntitySelection);
  $("add-entity").addEventListener("click", () => {
    if (!state.entitySelection) return;
    const record = state.records[state.active];
    try {
      addGoldEntity(record, state.entitySelection, $("entity-label").value);
      refreshEntityDraft(record);
      resetEntitySelection();
    } catch (error) {
      $("ner-error").textContent = error.message;
      $("ner-error").hidden = false;
    }
  });
  for (const id of ["ner-reviewer", "ner-label-source"])
    $(id).addEventListener("input", () => refreshEntityDraft(state.records[state.active]));
  $("ner-whole-article").addEventListener("change", () => {
    if (!$("ner-whole-article").checked) refreshEntityDraft(state.records[state.active]);
  });
  $("save-entities").addEventListener("click", () => {
    const record = state.records[state.active];
    try {
      completeNerReview(record, {
        reviewer: $("ner-reviewer").value.trim() || null,
        label_source: $("ner-label-source").value,
        whole_article_checked: $("ner-whole-article").checked,
      });
      $("ner-error").hidden = true;
      renderGoldEntities(record);
      persistNow();
    } catch (error) {
      $("ner-error").textContent = error.message;
      $("ner-error").hidden = false;
    }
  });
  $("import-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      await loadDataset(await file.text(), false);
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      event.target.value = "";
    }
  });
  $("export-file").addEventListener("click", () => {
    try {
      persistNow();
      const text = serializeAnnotations(state.records, state.snapshots, true);
      const url = URL.createObjectURL(
        new Blob([text], { type: "application/x-ndjson;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `focal-events.annotations.${new Date().toISOString().replace(/[:.]/g, "-")}.jsonl`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showMessage(
        `Exported ${state.records.length} article annotations, including unfinished drafts.`,
      );
    } catch (error) {
      showMessage(error.message, true);
    }
  });
  for (const id of Object.values(formFields)) $(id).addEventListener("input", changeDraft);
  for (const id of Object.values(eligibilityFields)) $(id).addEventListener("input", changeDraft);
  $("save-screening").addEventListener("click", saveScreening);
  $("search").addEventListener("input", filterQueue);
  $("queue-filter").addEventListener("change", filterQueue);
  $("previous").addEventListener("click", () => moveTo(state.active - 1));
  $("next").addEventListener("click", () => moveTo(state.active + 1));
  $("review-form").addEventListener("submit", (event) => {
    event.preventDefault();
    completeReview("REVIEWED");
  });
  $("mark-unsuitable").addEventListener("click", () => completeReview("UNSUITABLE"));
  document.addEventListener("keydown", (event) => {
    if (event.altKey && ["ArrowLeft", "ArrowRight"].includes(event.key) && state.records.length) {
      event.preventDefault();
      moveTo(state.active + (event.key === "ArrowLeft" ? -1 : 1));
    }
  });
  window.addEventListener("pagehide", persistNow);
  loadPilot();
}

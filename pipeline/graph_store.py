"""Phase 12: load the text pipeline into the evidence store, and compile the graph.

Loading (`gather` + `load`) copies Phases 7–11's JSONL into the store's tables:
sources, event and condition mentions with their spans, canonical events and
conditions with their search status, every claim (accepted or rejected), and
every judgement as an annotation. Pipeline ids become `external_id`, so a reload
converges instead of duplicating.

Building (`snapshot` + `compile_graph`) reads the store and a config and returns
the graph as bytes. It is a pure function of the two: rows are read in id order,
JSON is written with sorted keys and no clock, so the same store and config
always give byte-identical output, and its SHA-256 is the graph's version. A new
threshold gives a new version; the evidence tables are only ever read.
"""

import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from causal_expansion import find_cycle

GRAPH_SCHEMA = "causal-graph.v1"
TIME_LABELS = ("high", "medium", "low")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def day(text: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC) if text else None


def gather(annotations: Path, mentions: Path, canonical: Path, conditions: Path,
           condition_mentions: Path, levels: list[tuple[Path, Path, Path]],
           status: Path, spot_check: Path | None = None,
           merges: Path | None = None) -> dict:
    """Everything to load, from the pipeline's files. `levels` is one
    (claims, primary edges, second edges) triple per expansion level, in order."""
    articles = {}
    for gold in rows(annotations):
        if gold["review_status"] != "REVIEWED":
            continue
        meta = gold["source_metadata"]
        articles[gold["article_id"]] = {
            "url": meta.get("final_url") or meta.get("source_url") or meta["url_key"],
            "url_key": meta["url_key"],
            "fetched_at": meta.get("fetched_at"),
            "content_hash": meta.get("content_hash"),
            "raw_html_path": meta.get("raw_html_path"),
            "fetch_status": meta.get("status") or "extracted",
        }
    events = rows(canonical)
    members = {m: e["canonical_event_id"] for e in events for m in e["mentions"]}
    event_mentions = [m for m in rows(mentions) if m["event_mention_id"] in members]
    conds = rows(conditions)
    cond_members = {m: c["canonical_condition_id"] for c in conds for m in c["mentions"]}
    claims, edges = [], []
    for level, (claims_path, primary, second) in enumerate(levels, 1):
        claims += [{**c, "expansion_level": level} for c in rows(claims_path)]
        edges += rows(primary) + rows(second)
    return {
        "articles": articles,
        "events": events,
        "event_mentions": [{**m, "canonical": members[m["event_mention_id"]]}
                           for m in event_mentions],
        "conditions": conds,
        "condition_mentions": [{**m, "canonical": cond_members[m["condition_mention_id"]]}
                               for m in rows(condition_mentions)
                               if m["condition_mention_id"] in cond_members],
        "claims": claims,
        "edges": edges,
        "status": {s["node_id"]: s["search_status"] for s in rows(status)},
        "spot_check": rows(spot_check) if spot_check else [],
        "merges": rows(merges) if merges else [],
    }


async def load(connection, data: dict) -> dict:
    """Insert what is not already there. Idempotent: run it twice, nothing changes."""
    counts: dict[str, int] = {}

    async def insert(table: str, sql: str, args: list[tuple]) -> None:
        before = await connection.fetchval(f"SELECT count(*) FROM {table}")
        if args:
            await connection.executemany(sql, args)
        counts[table] = await connection.fetchval(f"SELECT count(*) FROM {table}") - before

    async with connection.transaction():
        known = {r["url_key"] for r in await connection.fetch("SELECT url_key FROM sources")}
        await insert("sources", """
            INSERT INTO sources (url, url_key, fetched_at, content_hash, raw_html_path,
                fetch_status, external_id)
            VALUES ($1, $2, $3::timestamptz, $4, $5, $6, $7)""", [
            (a["url"], a["url_key"],
             dt.datetime.fromisoformat(a["fetched_at"]) if a["fetched_at"] else None,
             a["content_hash"], a["raw_html_path"], a["fetch_status"], aid)
            for aid, a in sorted(data["articles"].items(), key=lambda kv: kv[1]["url_key"])
            if a["url_key"] not in known])
        source = {r["url_key"]: r["source_id"] for r in await connection.fetch(
            "SELECT url_key, source_id FROM current_sources")}
        source_of = {aid: source[a["url_key"]] for aid, a in data["articles"].items()}

        await insert("events", """
            INSERT INTO events (external_id, event_type, description, best_time,
                time_range_start, time_range_end, time_confidence_label, supporting_sources,
                source_urls, status, actors, targets, locations)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb, $12::jsonb,
                $13::jsonb)
            ON CONFLICT (external_id) DO NOTHING""", [
            (e["canonical_event_id"], e["event_type"], e["description"], day(e["best_time"]),
             day(e["time_range"][0]), day(e["time_range"][1]), e["time_confidence"],
             len(e["supporting_sources"]),
             json.dumps(sorted({data["articles"][a]["url"] for a in e["supporting_sources"]})),
             e["status"], json.dumps(e["actors"]), json.dumps(e["targets"]),
             json.dumps(e["locations"]))
            for e in data["events"]])
        await insert("conditions", """
            INSERT INTO conditions (external_id, description, valid_from, valid_to, evidence,
                kind, role, holders, locations, valid_from_stated)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8::jsonb, $9::jsonb, $10)
            ON CONFLICT (external_id) DO NOTHING""", [
            (c["canonical_condition_id"], c["description"], day(c["valid_from"]),
             day(c["valid_to"]),
             json.dumps({"phrasings": c["phrasings"], "observed": c["observed"],
                         "supporting_sources": c["supporting_sources"],
                         "review_status": c["review_status"], "conflicts": c["conflicts"]}),
             c["kind"], c["role"], json.dumps(c["holders"]), json.dumps(c["locations"]),
             c["valid_from_stated"])
            for c in data["conditions"]])
        event_id = {r["external_id"]: r["event_id"] for r in await connection.fetch(
            "SELECT external_id, event_id FROM events WHERE external_id IS NOT NULL")}
        cond_id = {r["external_id"]: r["condition_id"] for r in await connection.fetch(
            "SELECT external_id, condition_id FROM conditions WHERE external_id IS NOT NULL")}

        def spans(m: dict, fields: tuple) -> str:
            return json.dumps({f: m[f] for f in fields if m.get(f) is not None})

        await insert("mentions", """
            INSERT INTO mentions (external_id, source_id, event_id, condition_id, action,
                event_type, evidence_start, evidence_end, text_sha256, spans, reviewer,
                label_source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12)
            ON CONFLICT (external_id) DO NOTHING""", [
            (m["event_mention_id"], source_of[m["source_article_id"]],
             event_id[m["canonical"]], None, (m["action"] or {}).get("text"), m["event_type"],
             m["evidence_start"], m["evidence_end"], m["text_sha256"],
             spans(m, ("action", "actors", "targets", "locations", "event_time", "status")),
             m["reviewer"], m["label_source"])
            for m in data["event_mentions"]] + [
            (m["condition_mention_id"], source_of[m["source_article_id"]], None,
             cond_id[m["canonical"]], None, None, m["evidence_start"], m["evidence_end"],
             m["text_sha256"],
             spans(m, ("condition", "holders", "locations", "since", "until", "status")),
             m["reviewer"], m["label_source"])
            for m in data["condition_mentions"]])

        node = {**{k: ("event", v) for k, v in event_id.items()},
                **{k: ("condition", v) for k, v in cond_id.items()}}
        primary = {e["claim_id"]: e for e in data["edges"] if e["annotation_role"] == "primary"}
        second = {e["claim_id"]: e for e in data["edges"] if e["annotation_role"] == "second"}
        await insert("claims", """
            INSERT INTO claims (external_id, cause_kind, cause_id, effect_kind, effect_id,
                relation_type, machine_strength, verdict, primary_annotator, review_annotator,
                retriever, signals, temporal_gap_days, expansion_level, machine_relation_type)
            VALUES ($1, $2, $3, $4, $5, $6, NULL, $7, $8, $9, $10, $11::jsonb, $12, $13, NULL)
            ON CONFLICT (external_id) DO NOTHING""", [
            (c["claim_id"], *node[c["cause_event_id"]], *node[c["effect_event_id"]],
             primary[c["claim_id"]]["relation_type"],
             primary[c["claim_id"]]["review_status"].lower(),
             primary[c["claim_id"]]["reviewer_id"],
             second[c["claim_id"]]["reviewer_id"] if c["claim_id"] in second else None,
             c["retriever"], json.dumps(c["signals"]), c["lag_days"], c["expansion_level"])
            for c in data["claims"]])
        claim_id = {r["external_id"]: r["claim_id"] for r in await connection.fetch(
            "SELECT external_id, claim_id FROM claims WHERE external_id IS NOT NULL")}

        def judgement(e: dict) -> tuple:
            accepted = e["review_status"] == "ACCEPTED"
            return (f"{e['claim_id']}:{e['annotation_role']}", claim_id[e["claim_id"]],
                    e["reviewer_id"], "accept" if accepted else "reject", e["reject_reason"],
                    e["why"], e["final_strength"], e["relation_type"],
                    json.dumps(e["primary_evidence"]) if e["primary_evidence"] else None,
                    json.dumps(e["supporting_evidence"]), e["evidence_quality"],
                    e["corroboration_count"] if accepted else None,
                    dt.datetime.fromisoformat(e["reviewed_at"]), e["label_source"],
                    e["annotation_role"])

        def spot(s: dict) -> tuple:
            # A human verdict on the AI's call: agreeing repeats it, disagreeing flips it.
            ai_accepts = s["ai_review_status"] == "ACCEPTED"
            accepts = ai_accepts if s["human_verdict"] == "agree" else not ai_accepts
            return (f"{s['claim_id']}:spot-check", claim_id[s["claim_id"]], s["reviewer_id"],
                    "accept" if accepts else "reject", None if accepts else "OTHER",
                    s["note"] or f"spot check: {s['human_verdict']} with the AI",
                    None, None, None, "[]", None, None,
                    dt.datetime.fromisoformat(s["reviewed_at"].replace("Z", "+00:00")),
                    s["label_source"], "spot-check")

        await insert("annotations", """
            INSERT INTO annotations (external_id, claim_id, annotator, action, reject_reason,
                reason_text, human_strength, relation_type, primary_evidence,
                supporting_evidence, evidence_quality, corroboration_count, reviewed_at,
                label_source, role, machine_strength)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, $12, $13,
                $14, $15, NULL)
            ON CONFLICT (external_id) DO NOTHING""",
            [judgement(e) for e in data["edges"]]
            + [spot(s) for s in data["spot_check"] if s["human_verdict"] != "unsure"])

        await insert("node_merges", """
            INSERT INTO node_merges (external_id, node_a, node_b, decision, why, reviewer,
                label_source, reviewed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (external_id) DO NOTHING""", [
            (m["key"], m["a"], m["b"], m["decision"], m["why"], m["reviewer"],
             m["label_source"], dt.datetime.fromisoformat(m["reviewed_at"]))
            for m in data.get("merges", [])])

        # Search status is the node's current state, not evidence: it is updated.
        for table, key, ids in (("events", "event_id", event_id),
                                ("conditions", "condition_id", cond_id)):
            await connection.executemany(
                f"UPDATE {table} SET search_status = $1 WHERE {key} = $2"
                " AND search_status IS DISTINCT FROM $1",
                [(s, ids[n]) for n, s in sorted(data["status"].items()) if n in ids])
    return counts


async def snapshot(connection) -> dict:
    """Every row the build reads, in a fixed order. Only text-pipeline rows
    (those with an external_id) belong to this graph."""
    def plain(record) -> dict:
        out = {}
        for k, v in dict(record).items():
            if isinstance(v, dt.datetime):
                v = v.astimezone(dt.UTC).isoformat()
            elif isinstance(v, str) and k in {"actors", "targets", "locations", "holders",
                                               "primary_evidence", "supporting_evidence",
                                               "source_urls"}:
                v = json.loads(v)
            out[k] = v
        return out

    query = {
        "events": """SELECT event_id, external_id, event_type, description, best_time,
            time_range_start, time_range_end, status, actors, locations, search_status,
            source_urls FROM events WHERE external_id IS NOT NULL ORDER BY external_id""",
        "conditions": """SELECT condition_id, external_id, description, valid_from, valid_to,
            valid_from_stated, kind, role, holders, locations, search_status
            FROM conditions WHERE external_id IS NOT NULL ORDER BY external_id""",
        "claims": """SELECT claim_id, external_id, cause_kind, cause_id, effect_kind, effect_id,
            verdict, temporal_gap_days, expansion_level, machine_strength, machine_relation_type
            FROM claims WHERE external_id IS NOT NULL ORDER BY external_id""",
        "annotations": """SELECT a.external_id, c.external_id AS claim, a.annotator, a.role,
            a.action, a.relation_type, a.reject_reason, a.human_strength, a.primary_evidence,
            a.supporting_evidence, a.evidence_quality, a.corroboration_count, a.reviewed_at,
            a.label_source FROM annotations a JOIN claims c USING (claim_id)
            WHERE a.external_id IS NOT NULL ORDER BY a.external_id""",
        "sources": """SELECT external_id, url FROM sources WHERE external_id IS NOT NULL
            ORDER BY external_id""",
        "merges": """SELECT external_id, node_a, node_b, decision, reviewed_at FROM node_merges
            ORDER BY external_id""",
    }
    return {name: [plain(r) for r in await connection.fetch(sql)] for name, sql in query.items()}


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            + "\n").encode()


def compile_graph(snap: dict, config: dict) -> bytes:
    """The graph as bytes: accepted edges that pass the config's thresholds, their
    endpoints, and each edge's full review history including rejections."""
    store_fingerprint = hashlib.sha256(canonical_json(snap)).hexdigest()
    relation_map = config.get("relation_map", {})
    nodes = {("event", e["event_id"]): {
        "id": e["external_id"], "kind": "event", "description": e["description"],
        "event_type": e["event_type"], "status": e["status"], "date": e["best_time"],
        "time_range": [e["time_range_start"], e["time_range_end"]], "actors": e["actors"],
        "locations": e["locations"], "search_status": e["search_status"],
        "source_urls": e["source_urls"]} for e in snap["events"]}
    nodes |= {("condition", c["condition_id"]): {
        "id": c["external_id"], "kind": "condition", "description": c["description"],
        "condition_kind": c["kind"], "role": c["role"], "valid_from": c["valid_from"],
        "valid_from_stated": c["valid_from_stated"], "valid_to": c["valid_to"],
        "holders": c["holders"], "locations": c["locations"],
        "search_status": c["search_status"]} for c in snap["conditions"]}
    history: dict[str, list] = {}
    for a in snap["annotations"]:
        history.setdefault(a["claim"], []).append({k: a[k] for k in (
            "annotator", "role", "action", "relation_type", "reject_reason", "reviewed_at",
            "label_source")})
    primary = {a["claim"]: a for a in snap["annotations"] if a["role"] == "primary"}
    url = {s["external_id"]: s["url"] for s in snap["sources"]}

    claim_edges = []
    for c in snap["claims"]:
        p = primary.get(c["external_id"])
        if c["verdict"] != "accepted" or p is None:
            continue
        if c["cause_kind"] not in config.get("kinds", ["event", "condition"]):
            continue
        if (p["human_strength"] or 0) < config.get("min_strength", 0):
            continue
        if (p["corroboration_count"] or 0) < config.get("min_corroboration", 0):
            continue
        if p["evidence_quality"] not in config.get("evidence_quality", ["explicit", "implicit"]):
            continue
        if not config.get("include_ai_labels", True) and p["label_source"] != "human":
            continue
        cause, effect = nodes[(c["cause_kind"], c["cause_id"])], nodes[
            (c["effect_kind"], c["effect_id"])]
        spans = [p["primary_evidence"], *p["supporting_evidence"]]
        claim_edges.append({
            "claim_id": c["external_id"],
            "source": cause["id"], "target": effect["id"],
            "relation": relation_map.get(p["relation_type"], p["relation_type"]),
            "judged_relation": p["relation_type"],
            "machine_relation": c["machine_relation_type"],
            "strength": p["human_strength"], "machine_strength": c["machine_strength"],
            "evidence_quality": p["evidence_quality"],
            "corroboration_count": p["corroboration_count"],
            "temporal_gap_days": c["temporal_gap_days"],
            "expansion_level": c["expansion_level"],
            "source_date": cause.get("date") or cause.get("valid_from"),
            "target_date": effect.get("date") or effect.get("valid_from"),
            "evidence": spans,
            "source_article_ids": sorted({s["article_id"] for s in spans}),
            "source_urls": sorted({url[s["article_id"]] for s in spans}),
            "review_history": sorted(history[c["external_id"]],
                                     key=lambda h: (h["role"], h["annotator"])),
        })
    by_id = {n["id"]: n for n in nodes.values()}
    # node_merges is append-only, so a corrected decision is a newer row for the
    # same pair; the most recent one per pair is the one that counts.
    latest: dict[tuple[str, str], dict] = {}
    for m in sorted(snap.get("merges", []),
                    key=lambda m: (m.get("reviewed_at") or "", m["external_id"])):
        latest[tuple(sorted((m["node_a"], m["node_b"])))] = m
    same = [(m["node_a"], m["node_b"]) for m in latest.values()
            if m["decision"] == "same" and m["node_a"] in by_id and m["node_b"] in by_id]
    alias = representatives(same if config.get("merge_duplicates", True) else [], by_id)
    edges, loops = fold(claim_edges, alias, by_id)
    used = {e["source"] for e in edges} | {e["target"] for e in edges}
    members: dict[str, list[str]] = {}
    for node, rep in alias.items():
        members.setdefault(rep, []).append(node)
    graph = {
        "graph_schema": GRAPH_SCHEMA,
        "config": config,
        "store_fingerprint": store_fingerprint,
        "nodes": sorted((merged_node(by_id, n, members.get(n, [])) for n in used),
                        key=lambda n: n["id"]),
        "edges": edges,
        "counts": {
            "claims": len(snap["claims"]),
            "accepted_claims": sum(c["verdict"] == "accepted" for c in snap["claims"]),
            "rejected_claims": sum(c["verdict"] == "rejected" for c in snap["claims"]),
            "claim_edges": len(claim_edges),
            "edges": len(edges),
            "nodes": len(used),
            "nodes_merged_away": sum(len(v) for v in members.values()),
            "self_loops_dropped": loops,
            # Merging can join two branches into a loop the unmerged graph never had.
            "cycle": find_cycle([{"review_status": "ACCEPTED", "source_event_id": e["source"],
                                  "target_event_id": e["target"]} for e in edges]),
        },
    }
    return canonical_json(graph)


# The more useful status wins when duplicates merge: one of them was searched.
STATUS_RANK = ("PARENTS_FOUND", "NO_SUPPORTED_PARENT_FOUND", "NOT_YET_REVIEWED",
               "UNVERIFIABLE", "OUT_OF_SCOPE", None)


def representatives(pairs: list[tuple[str, str]], nodes: dict) -> dict[str, str]:
    """Duplicate node -> the node it merges into, over judged-same pairs. Each
    cluster keeps one node: an event before a condition, then the smallest id."""
    parent = {n: n for pair in pairs for n in pair}

    def find(n: str) -> str:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for a, b in sorted(pairs):
        parent[find(a)] = find(b)
    clusters: dict[str, list[str]] = {}
    for n in parent:
        clusters.setdefault(find(n), []).append(n)
    alias: dict[str, str] = {}
    for group in clusters.values():
        keep = min(group, key=lambda n: (nodes[n]["kind"] != "event", n))
        alias |= {n: keep for n in group if n != keep}
    return alias


def merged_node(nodes: dict, keep: str, absorbed: list[str]) -> dict:
    node = dict(nodes[keep])
    if absorbed:
        node["merged_from"] = sorted(absorbed)
        statuses = [nodes[n]["search_status"] for n in [keep, *absorbed]]
        node["search_status"] = min(statuses, key=STATUS_RANK.index)
    return node


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def fold(claim_edges: list[dict], alias: dict, nodes: dict) -> tuple[list[dict], list[str]]:
    """Edges between merged nodes: claims joining the same pair become one edge
    whose evidence is all of theirs; a claim whose two ends merged is dropped."""
    groups: dict[tuple[str, str], list[dict]] = {}
    loops = []
    for e in claim_edges:
        source, target = alias.get(e["source"], e["source"]), alias.get(e["target"], e["target"])
        if source == target:
            loops.append(e["claim_id"])
            continue
        groups.setdefault((source, target), []).append(e)
    edges = []
    for (source, target), group in sorted(groups.items()):
        lead = min(group, key=lambda e: (-(e["strength"] or 0),
                                         e["evidence_quality"] != "explicit", e["claim_id"]))
        spans = sorted({json.dumps(s, sort_keys=True) for e in group for s in e["evidence"]})
        evidence = [json.loads(s) for s in spans]
        urls = sorted({u for e in group for u in e["source_urls"]})
        edges.append({
            **{k: lead[k] for k in ("relation", "judged_relation", "machine_relation",
                                    "strength", "machine_strength", "evidence_quality",
                                    "temporal_gap_days")},
            "id": "e:" + hashlib.sha256(f"{source}|{target}".encode()).hexdigest()[:16],
            "source": source, "target": target,
            "claim_ids": sorted(e["claim_id"] for e in group),
            "judged_relations": sorted({e["judged_relation"] for e in group}),
            "expansion_level": min(e["expansion_level"] for e in group),
            "source_date": nodes[source].get("date") or nodes[source].get("valid_from"),
            "target_date": nodes[target].get("date") or nodes[target].get("valid_from"),
            "evidence": evidence,
            "source_article_ids": sorted({s["article_id"] for s in evidence}),
            "source_urls": urls,
            # Independent outlets carrying the link, across every merged claim.
            "corroboration_count": len({host(u) for u in urls}),
            "review_history": sorted(
                ({**h, "claim_id": e["claim_id"]} for e in group for h in e["review_history"]),
                key=lambda h: (h["claim_id"], h["role"], h["annotator"])),
        })
    return sorted(edges, key=lambda e: e["id"]), sorted(loops)


def version(graph: bytes) -> str:
    return hashlib.sha256(graph).hexdigest()

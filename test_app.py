"""Run: python test_app.py   (needs out/step2_causal_filtered.parquet)"""
import asyncio, json, app

# SQL NULL reaches us two ways depending on the cursor API used.
assert app.num(None) == 0.0            # fetchone() tuple
assert app.num(float("nan")) == 0.0    # _rows() dict
assert app.num(-2.5) == -2.5
assert app.num(None, 9) == 9

# The regression: AVG() over zero matching rows is NULL. Every endpoint that
# averages Goldstein must survive a country pair that has no events.
r = asyncio.run(app.edge_detail(source="ZZ", target="ZZ", root_code="01"))
assert r["stats"]["total"] == 0, r["stats"]
assert r["stats"]["avg_goldstein"] == 0, r["stats"]

for name in ("stats", "graph", "timeline", "country_stats", "heatmap"):
    asyncio.run(getattr(app, name)())

# ── Causal evidence endpoints ────────────────────────────────────────────────
seeds = asyncio.run(app.causal_seeds(country="IN"))
assert seeds["seeds"], "no seed events"
sid = seeds["seeds"][0]["id"]

mat = asyncio.run(app.causal_matrix(country="IN"))
assert mat["pairs"], "empty type matrix"
assert all(p["cause"] != p["effect"] for p in mat["pairs"]), "self-pairs shown"

sc = asyncio.run(app.causal_score(event_id=sid, country="IN"))
assert sc["target"] and sc["candidates"], "no scoring result"
assert 0.0 <= sc["coverage"] <= 1.0, sc["coverage"]
# Each event type appears at most once -- same type on five days is one cause.
rcs = [c["root_code"] for c in sc["candidates"]]
assert len(rcs) == len(set(rcs)), "duplicate root codes among candidates"
for c in sc["candidates"]:
    assert 0.0 <= c["confidence"] <= 1.0, c
    assert c["grade"] in ("confirmed", "reported", "pattern", "weak", "dropped"), c
# A channel with no corpus must stay unavailable, never silently scored.
assert any(not ch["available"] for ch in sc["channels"])

# Golden comparison is byte-identical, so every query needs a full sort key.
assert json.dumps(asyncio.run(app.causal_score(event_id=sid, country="IN")), sort_keys=True) == \
       json.dumps(asyncio.run(app.causal_score(event_id=sid, country="IN")), sort_keys=True)

# Bad input must not 500.
assert asyncio.run(app.causal_score(event_id=""))["error"] == "no_event"
assert asyncio.run(app.causal_score(event_id="not-an-id"))["error"] == "no_event"
assert asyncio.run(app.causal_score(event_id="999999999999"))["error"] == "not_found"
assert asyncio.run(app.causal_matrix(country="ZZ"))["country"] == "IN"
assert asyncio.run(app.causal_seeds(country="'; DROP TABLE events; --"))["country"] == "IN"

print("ok")

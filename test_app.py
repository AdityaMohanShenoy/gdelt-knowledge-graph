"""Run: python test_app.py   (needs out/step2_causal_filtered.parquet)"""
import asyncio, app

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

print("ok")

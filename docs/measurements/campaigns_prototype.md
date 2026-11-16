# Campaign layer — prototype

**Status: prototype, not wired into the build.** It reads the published graph
(`85204eba`) and writes a separate prototype graph. The live graph, the store and
the dashboard are unchanged.

## The problem

**Ongoing protests split into one event per day.**
- **The size of it.** Of the 330 protest mentions, 65 (20%) describe something
  continuing: a sit-in, a camp, a fast-unto-death, "continued", "Nth day". They
  are spread over 58 separate canonical events.

**Why it happens:**
- **Each mention gets one date.** Extraction keeps a single time phrase
  ("Saturday", "February 13"), and about half of these mentions have none, so
  they fall back to the article's report date.
- **Merging needs overlapping dates.** Phase 8 only compares two mentions whose
  dates overlap within a day. A camp reported on its first day and again two
  weeks later is never compared.

**Why not merge everything inside a time window.** One week of the farmers'
movement held several actions the judges kept apart on purpose: the Delhi Chalo
march, the Shambhu camp, the tear-gas clash, the 10 March rail roko and a
solidarity protest in Tamil Nadu. Merging them would delete the cause-and-effect
links between them: the stopped march *triggered* the camp.

## What the prototype does

`pipeline/campaigns.py` and `pipeline/27_campaigns.py`:

1. **Reads durations.**
   - **Stated starts.** "Since February 13", "for N days", "nearly 50 days",
     "Nth day" and "entered its tenth day" become a start date.
   - **Ongoing wording.** "Indefinite", "continued", "camping" and "sit-in" keep
     the range open to the report date, but count as unstated.
2. **Pairs protest events within a story.** A story is a connected cluster.
   Four were chosen for the prototype: the farmers' movement, the RG Kar doctors,
   the Haryana doctors and Ladakh. That gave 25 events and 104 pairs.
3. **Judges each pair** with `docs/same-campaign-rubric.md`:
   - **Same campaign:** one continuing action seen on different days.
   - **Different:** a separate action, even within the same movement, such as a
     march and the camp it became, or a rail roko during a sit-in.
4. **Applies a guard.** Two events joined by a human-verified link that says one
   triggered, mobilised, motivated or prompted the other are never folded into
   one campaign. The verified link already says they are two things. Only
   *escalates into* (an earlier stage of the same action) may sit inside a
   campaign. The guard also stops transitive joins.
5. **Builds campaign nodes.**
   - Each campaign spans its members' ranges and is named after the member whose
     text states the range.
   - Edges re-point to the campaign, and parallel edges join.
   - A link between two episodes of one campaign would disappear into it. This
     prototype has none.

## Results

The judge called 8 pairs "same campaign". **The guard blocked 3 of them,**
correctly in each case:

| Blocked pair | Why |
|---|---|
| The KMM's "Delhi Chalo" call / farmers began the march | a verified link says the call **mobilised** the march |
| The IMA's one-day boycott call / Salem doctors boycotted | a verified link says the call **mobilised** the boycott |
| The two forums' 10 March call / farmers blocked rail tracks | a verified link connects them as cause and effect |

**Three campaigns were formed:**

| Campaign | Range | Episodes |
|---|---|---|
| The Shambhu–Khanauri farmers' camp | 13 Feb – 29 Dec, from "since February 13" | "farmers have been camping"; "protesting at the two border points"; Vinesh Phogat joining the farmers (day 200) |
| The West Bengal junior doctors' cease-work | 25 Aug – 14 Oct, from "nearly 50 days" | "nearly 50 days of cease work"; "thousands of junior doctors have been on a strike" |
| Sonam Wangchuk's climate fast | 6 Mar – 23 Mar, from "18th day" | his fast's launch; the same fast on day 18 |

**The prototype graph** has 173 edges and 183 nodes, against 176 and 187. No
link was lost inside a campaign. File
`data/evidence/graph/causal-graph.campaigns-prototype.json`
(`b3263ed5fa112cdbc6574245c171a4112075289ad11b01a03a2db3a290846641`).

## Before and after, on questions

| Question | Before | After |
|---|---|---|
| Why did Sonam Wangchuk go on hunger strike? | 4 recorded direct causes | **7**: the launch report's causes now join the day-18 report's |
| Why did West Bengal junior doctors stop work? | 16 direct causes over two cease-work nodes | 15 over one cease-work campaign, dated 25 Aug – 14 Oct |
| Why are farmers camping at the Shambhu border? | the camp is a node dated 21 Feb | the same chains; the camp is a campaign dated 13 Feb – 29 Dec |

**The gain on this corpus is real but small.** The duplicate-merge pass had
already caught the worst splits: the Shambhu camp went from 4 nodes to 1, and
the doctors' fast from 3 to 1. The main improvements are:
- **Proper date ranges.** A campaign now carries when it ran, not one report's
  day.
- **Fuller cause lists** where the same action was extracted on two days, as
  with Wangchuk's fast.

## What this taught us

1. **"Part of" is the missing piece.** The judge wanted to fold three kinds of
   thing into a campaign: the call that organised a protest, a new person
   joining a camp (Vinesh Phogat), and a rail roko held during the farmers'
   agitation. These belong *to* the campaign but are separate actions. They
   need a `PART_OF` link, not a merge. Phogat's joining was folded here only
   because no verified link connected it to the camp. **It should be undone in
   a real run.**
2. **Duration reading is worth having on its own.** Feeding the ranges into
   Phase 8's date resolution would let the existing merge step compare a camp's
   first and tenth day. It would also fix the backwards-dated cards that come
   from report-date fallbacks.
3. **The guard is the safety net.** A judge alone over-merged 3 of 8. The
   human-verified links caught all 3 mechanically.

## To make it real

1. Add a `PART_OF` relation, so calls, joinings and one-day actions attach to a
   campaign without merging.
2. Feed `duration()` into `canonical_events.resolve_time` so Phase 8 sees
   ranges.
3. Run over every cluster, not 4. Then load campaigns into the store as judged
   decisions (`node_merges`-style, append-only) and apply them in
   `40_build_graph.py`.
4. Have a person review the campaign decisions, as with the edges.

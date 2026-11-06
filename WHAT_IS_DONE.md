# What is done

This page explains, in plain words, everything this project has built so far:
what each step does, why it exists, and a real example of its output. Release
`v1.0` (1 November 2026) marks the point described here.

The measurement reports in `docs/measurements/` have the full detail and the
file hashes.

---

## The project in one paragraph

News reports about a protest usually say *why* it happened: "doctors boycotted
work **in protest against** the rape and murder of a doctor in Kolkata". This
project reads 2024 Indian news about protests, finds those stated reasons, and
links them into a **causal graph**: a network where each arrow says "this led to
that". Every arrow carries the exact sentence it is based on, a link to the
article, and a record of who checked it. You can ask the graph *"why did X
happen?"* on the dashboard and get an answer built only from those checked
arrows.

```
news articles ──► protests and their stated causes ──► checked cause → effect arrows ──► "why?" answers
```

---

## Who did what

All 176 arrows in the graph were **checked by a person** (the repo owner).
Almost everything before that was done by **AI**, with checks around it. This
matters when reading any number below.

| Step | Who labelled it |
|---|---|
| Choosing which articles are about protests | AI |
| Picking each article's main event | AI |
| Extracting events, grievances and statements from sentences | Rules plus AI review |
| Deciding which reports describe the same event | AI |
| Deciding whether A caused B | AI first, then a blind AI re-check, **then a person reviewed every arrow** |

No paid AI service was used. Language processing ran on local models (spaCy,
GLiNER2, and the `all-mpnet-base-v2` sentence model). The judging was done by
Claude agents inside Claude Code.

---

## Step by step

### 1. Collecting articles

**What:** GDELT is a public database that logs news events worldwide. From its
2024 records for India we took news articles about protests and downloaded the
article text. A sample of **300 articles** became the working set.

**Why:** we needed the full text, not just GDELT's codes, because the reasons
for a protest are only written in the article.

### 2. Screening: is this article really about a protest?

**What:** every article was read and labelled. Is it about a protest? Is the
text complete? Is it about India in 2024? **139 articles** were kept and 161
were excluded, each with a reason.

**Example of an exclusion:** an article that only mentions a past protest in
passing, or whose download was a cookie banner instead of the story.

**Report:** `docs/measurements/screening.md`

### 3. The main event of each article

**What:** for each kept article we picked the single main development and the
sentences that support it. A ranking model helps by suggesting the best
sentences.

**Example:** for *"Salem doctors boycott work in protest against Kolkata
doctor's murder"*, the main event is *the doctors' one-hour boycott on
Saturday*.

**How good is the ranking model?** On test articles it never saw while being
tuned, its top sentence is the core sentence 67% of the time. The test set was
scored only once, at the end, so the tuning could not overfit to it.

**Reports:** `focal_review.md`, `focal_baseline.md`

### 4. Pulling events out of sentences

**What:** a sentence often holds several events. A rules engine (spaCy) proposes
each one as structured fields, with every field an exact piece of the sentence:
- **who acted** (actors)
- **what they did** (action)
- **to whom** (targets)
- **where** (locations)
- **when** (time)

AI review then accepts, fixes or rejects each proposal.

**Example sentence:** *"Doctors at Salem Government Mohan Kumaramangalam
Medical College Hospital boycotted their duties for an hour on Saturday in
protest against the recent rape and murder of a female doctor in Kolkata."*

| Field | Value |
|---|---|
| actor | Doctors at Salem Government Mohan Kumaramangalam Medical College Hospital |
| action | boycotted their duties |
| time | Saturday |
| type | protest |

**Result:** 911 reviewed event mentions. Of the rest, 286 proposals were
rejected and 11 were left unreviewed. Step 6 later adds 213 remarks, making
1,124 event mentions in all.

Every field is checked to be the exact text at an exact character position in
the saved article, so nothing is made up.

**Report:** `event_mentions.md`

### 5. Recognising the same event across articles

**What:** different outlets report the same event. We find pairs of mentions
that might be the same (same type, overlapping dates, similar actors and
wording). AI judges each pair, and only pairs judged "same" are joined.

**Example:** Arvind Kejriwal's arrest by the Enforcement Directorate became
**one** event backed by **7 reports**.

**Result:** 1,073 distinct ("canonical") events from the 1,124 mentions. Most
events are reported by only one article, so 1,045 stay as they are. The other
79 mentions were judged to be the same event across articles and joined into 28
events.

**Report:** `canonical_events.md`

### 6. Grievances and remarks

**What:** an early check showed that most protest causes are not one-day
events. They are standing **conditions** (a water crisis, a policy, a demand
that hasn't been met) or **remarks** (an insult, an accusation). So we added
both:
- **244 conditions**, merged into 200 distinct ones;
- **213 remarks**, added as events.

**Examples:**
- **Condition:** *"MSP guarantee legal law"*, the farmers' demand for a legal
  guarantee of minimum crop prices. It is mentioned in many articles and is one
  node in the graph.
- **Remark:** BJP workers allegedly calling a Sikh police officer "Khalistani",
  which set off protests.

Adding these raised the share of named causes we could find from 46% to 92% on
the same 20 test protests.

**Report:** `conditions.md`

### 7. Finding candidate causes

**What:** for each protest we list everything that *could* be a cause:
- events up to 7 days before;
- events up to 180 days before, if they share wording and actors or places;
- conditions in effect at the time.

These are only candidates. Nothing is accepted at this step.

**Example:** for the Salem boycott, candidates include the RG Kar killing, the
Indian Medical Association's strike call, and other doctors' protests that week.

**Result:** 1,101 candidates for 63 protests, about 17 each.

**Report:** `causal_candidates.md`

### 8. Judging causes

**What:** a judge reads each candidate against the protest's article and
accepts it **only if the text states or plainly shows the link**: "because of",
"in protest against", "in response to", a call that organised the protest, and
so on. Shared topic, timing or wording is never enough.

Every accepted arrow gets:
- **a relation type:**

| Relation | Meaning | Example |
|---|---|---|
| TRIGGERS | a specific event set it off | the RG Kar killing → Salem doctors' boycott |
| MOTIVATES | a grievance or reason behind it | Haryana cutting Delhi's water share → Atishi's hunger strike |
| MOBILIZES | the call or decision that organised it | the IMA's call for a one-day boycott → Salem doctors' boycott |
| ESCALATES | an earlier stage of the same dispute | a letter to the PM went unanswered → the hunger strike |
| PROMPTS_RESPONSE | it answers another side's action | AAP's protests → BJP's counter-protest burning effigies |

- **a strength** from 1 to 3 (3 means the text states it directly);
- **the exact quote** that shows the link.

Rejected candidates are **kept, with their reason**, such as "same topic but no
stated link". They are useful "this is *not* a cause" examples for training
later.

**Result:** 156 accepted, 945 rejected. A quarter were judged twice by
different AI judges, who agreed on accept or reject 98% of the time.

**Report:** `causal_edges.md`

### 9. Going deeper: causes of causes

**What:** once "A caused the protest" is accepted, A becomes the next question:
what caused A? We did this for three levels. Every event records whether its
causes were searched:
- **causes found**
- **searched, none found**
- **not searched yet**
- **can't be verified** (an announced event that hasn't happened)
- **before 2024** (out of scope)

That way "we looked and found nothing" never looks like "nobody looked".

**Example chain, three levels deep:** the KMM and SKM unions' "Delhi Chalo"
call → **mobilised** → farmers from Punjab began the march → which the later
protests in the chain continue.

**Result:** branches stay small (about 2.5 causes per protest, then fewer each
level) and often meet. The RG Kar killing, for example, explains 11 different
protests.

**Report:** `expansion.md`

### 10. Storing and building the graph

**What:** everything is loaded into a Postgres database: articles, events,
mentions, every candidate (accepted *and* rejected) and every judgement. Then a
build script compiles the graph from the database and a small settings file.

The build is **reproducible**: the same inputs give the identical file, byte for
byte, and the file's fingerprint (SHA-256) is the graph's version number.
Changing a setting, such as "only strong links", gives a new version without
touching the stored evidence.

**Report:** `graph_build.md`

### 11. Merging duplicate nodes

**What:** some real events had ended up as two or three separate nodes. The RG
Kar killing was one. Pairs of look-alike nodes were judged, and the "same" ones
are merged when the graph is built, without rewriting the stored evidence.

**Examples:**
- The RG Kar killing went from 3 nodes to 1.
- The farmers' Shambhu border camp went from 4 nodes to 1.

**One merge was later found wrong and undone.** The MSP grievance had been
merged with a single "farmers demanding" event, which made a 14-article
grievance look like one dated event. Decisions are never edited, so a newer
"different" decision was added on top. The build always uses the latest
decision for each pair.

### 12. Asking "why?" on the dashboard

**What:** the dashboard's **Causal Evidence** tab answers questions from the
graph. It:
1. finds the events the question is about, and asks you to choose if it matches
   several stories;
2. collects their causes up to three steps back;
3. ranks the cause chains by strength, how clearly the text states them,
   independent outlets, and fit to the question;
4. writes the answer using only graph records, quoting the evidence and linking
   the articles;
5. says how much of the event's known causes the answer covers, and which
   earlier events nobody searched.

**Real example.** *"Why did doctors in Salem boycott work?"*
> - "rape and murder" **triggered** "Doctors boycotted" (2024-08-17). Strength
>   3/3, stated in the text. Evidence: *"in protest against the recent rape and
>   murder of a female doctor in Kolkata, West Bengal"*.
> - The IMA's "call … for a one-day boycott" **mobilised** "Doctors boycotted".
>   Strength 3/3. Evidence: *"In response to a call from the Indian Medical
>   Association (IMA) for a one-day boycott"*.
>
> These chains cover 100% of the recorded causes (2 of 2 direct causes).

**Another.** *"Why did Delhi's water minister go on hunger strike?"* The answer
shows:
- Haryana's reduction of Delhi's water share **motivated** it (3/3);
- the water shortage **motivated** it (2/3);
- an unanswered letter to the Prime Minister **escalated into** it (2/3).

The answer covers 73% of the recorded causes, 5 of 8 direct causes.

The answer never invents a link, and a test checks that every arrow it cites
exists in the graph. Each link is marked "Checked by a person".

**The other direction: "What did X lead to?"** A toggle on the tab switches to
consequences, served by `/api/consequences`.

*"What did the excise policy case lead to?"*
1. The excise policy case **escalated into** Kejriwal's arrest.
2. The arrest **triggered** the AAP workers' protests.
3. Those protests **prompted** the BJP's counter-protest.

Because the graph was built by tracing the causes of protests, the effects it
knows are protests and the steps toward them, and the answer says so.

**Report:** `query.md`

---

## How we checked it is right

Reviewers agreeing only shows consistency, not correctness, so we also used
checks that don't rely on our own labels.

| Check | What it tests | Result |
|---|---|---|
| **Two AI judges** on a quarter of decisions | consistency | agreed on 98% of accept/reject calls (κ 0.93) |
| **Negative controls**: fake causes slipped in blind | does it accept nonsense? | 0 of 60 unrelated pairs accepted; 0 of 35 "cause happens after effect" pairs accepted |
| **Published accounts**: causes that Wikipedia and explainers give for 17 events, from 67 sources outside our articles | does it find real causes? | 25% exactly, 43% counting partial matches |
| **Blind AI re-check** of all 207 arrows | which arrows look doubtful? | flagged 59 arrows |
| **Human review** of all 207 arrows | are they right? | 176 kept, **31 removed (15%)**; all 31 were among the 59 the blind re-check flagged |

**What these say:**
- The system **doesn't make things up**. It never linked unrelated events and
  never reversed time.
- Its mistakes were borderline calls, and the blind re-check caught every one.
- It **misses many causes** (recall 25–43%). Mostly that's because 139 articles
  simply don't mention the call, the deadline or the earlier incident behind a
  protest, even when other outlets did.

**Report:** `final_evaluation.md`

---

## The numbers at a glance

| | |
|---|---:|
| Articles collected / kept as protest stories | 300 / 139 |
| Event mentions (911 extracted + 213 remarks) / distinct events | 1,124 / 1,073 |
| Grievances and conditions / remarks | 200 / 213 |
| Candidate causes judged (three levels) | 2,748 |
| Arrows in the final graph | **176, all human-verified** |
| Nodes in the final graph | 187 |
| Protests with at least one explained cause | 57 |
| Rejected candidates kept as "not a cause" examples | 2,504 + 31 human rejections |
| Graph version | `85204eba` |
| Tests | 339 passing |

---

## What is not done

- **Named-entity benchmark.** A hand-checked list of every person, place,
  organisation and date in the test articles was planned and never built. It is
  the one unmet item in the completion checklist, and nothing in the graph
  depends on it.
- **Human labels before the graph.** Screening, main events and extraction were
  labelled by AI. Numbers about those steps mean "agrees with an independent AI
  reading", not "correct according to a person".
- **Coverage.** With 139 articles, most protests have a single report, so many
  documented causes are missing. More articles is the main way to improve this.
- **Question matching uses words, not meaning.** Asking with a synonym the
  articles never use ("agitation" for "protest") may not match.

---

## Where things are

| What | Where |
|---|---|
| Plan and phase status | `docs/BUILD_PLAN.md` |
| Measurement reports (with file hashes) | `docs/measurements/` |
| Rules the judges followed | `docs/*rubric*.md` |
| Pipeline scripts, in order | `pipeline/10_…` to `pipeline/40_build_graph.py` |
| Question answering | `causal_query.py`, `/api/explain` in `app.py` |
| The published graph the app reads | `out/causal_graph.json` |
| Database tables | `store/schema.sql` (the graph lives in the `text_graph` schema) |
| Raw evidence (gitignored, local only) | `data/evidence/` |
| How to run each step | `README.md` |

---

## Words used here

- **Event:** something that happened on a date, such as a march, an arrest or a
  statement.
- **Condition:** an ongoing state or grievance, such as a water shortage, a
  policy or an unmet demand.
- **Mention:** one sentence's report of an event.
- **Canonical event:** one real event, built from all the mentions that report
  it.
- **Candidate / claim:** a possible "A caused B" pair waiting to be judged.
- **Edge / arrow:** an accepted "A caused B" link with its evidence.
- **Seed:** a protest we started from.
- **Hard negative:** a rejected candidate that looked plausible. It's useful for
  teaching a future model what is *not* a cause.
- **Blind:** judged without seeing anyone else's earlier answer.

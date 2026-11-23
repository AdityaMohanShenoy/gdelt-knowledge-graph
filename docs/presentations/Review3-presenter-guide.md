# Review 3 presenter's guide: what every number means

Nov 23, 2026

Every number on the Review 3 slides, in slide order: what it counts, where it comes from, and one line you can say out loud. All figures come from the paper (paper/iccids2027.tex) and docs/measurements/.

## The four headline numbers (slides 1–3)

These four numbers are the whole project in one line: we read 2,000 articles, found 1,416 quoted cause-and-effect links that explain 358 protests, and a person checking a random sample found 90% of them correct.

| Number | What it counts | Say it like this |
| --- | --- | --- |
| 2,000 | News articles fetched from the web addresses GDELT records for 2024 Indian protest events | "We read two thousand real news articles that GDELT points to." |
| 1,416 | Cause-and-effect links in the published graph (v2.0). Each one stores the exact sentence that supports it and the article it came from | "Every one of these 1,416 links comes with its own quote and source." |
| 358 | Protests that have at least one recorded cause, out of 373 protests found in the articles | "For 358 of 373 protests, the graph can tell you why they happened." |
| 90% | 89 of 99 links judged correct when a person checked 100 links picked at random from the ones nobody had reviewed (one was left undecided) | "When we checked a random hundred by hand, nine in ten were right." |

The live website shows 1,415 links by default, not 1,416: one implied link has never been reviewed by a person, so the query box hides it unless you tick "Include links that are only implied".

## How 2,000 articles become 1,416 links (slides 5 and 13)

Each step throws away what the text does not support, so the numbers shrink from 20,129 candidate causes to 1,416 published links. Walk the panel down this list in order.

1. **2,000 articles read.** Fetched from the web addresses in GDELT's records of 2024 Indian protest events, in a fixed order so the sample can be rebuilt.
2. **915 kept.** Screening kept only articles that actually report a protest in India in 2024. The other 1,085 were off-topic, unreadable, or about something else.
3. **7,083 event mentions.** Every event an article reports (who did what, where, when), copied word for word from the text. Nothing is paraphrased, so every node can be found in its article.
4. **6,152 distinct events.** Many articles report the same event. We compared 8,913 pairs of mentions and judged 1,970 of them to be the same event, then merged those.
5. **Plus 810 grievances.** Standing conditions that are not one-day events, such as "MSP guarantee" or "water shortage": 1,146 mentions merged into 810. They matter because most protests are caused by a grievance, not a single incident.
6. **20,129 candidate causes judged.** For each protest we proposed possible causes and asked, for each one, "does the article say this caused that?" A link is accepted only if an exact supporting quote is found and checked by code. This ran three steps back (cause of a cause of a cause), plus rounds that recovered causes the articles state but extraction had missed.
7. **143 links removed by the gate.** Every accepted link got a second, independent check that did not see the first verdict. To make sure that check was not just saying yes to everything, 1,352 real links were mixed one-to-one with 1,352 links that had been rejected earlier (decoys). It passed only 44 of the decoys (3%) and removed 143 of the real links.
8. **Repair.** 151 same-event decisions folded 131 duplicate events into others, 5 wrong merges were blocked, 25 links whose two ends became one event were dropped, and 11 links were removed to break loops (A causes B causes A).
9. **1,416 links published.** No loops, and rebuilding from the stored files gives exactly the same graph, byte for byte.

On slide 5 the line "No model at query time" means answering a question uses only the stored graph and plain ranking maths, never an AI model, so the same question always gets the same answer.

## Numbers inside the algorithms (slides 7–8)

The algorithms have few tuning numbers, and each one has a plain reason. If a panel member points at one, this table is the answer.

| Symbol or number | Where | What it means |
| --- | --- | --- |
| L = 3 | Build | Causes are traced at most three steps back: the protest, its cause, the cause's cause, and one more. |
| k = 8 | Build | For each event, every candidate cause from the same article is checked, plus the 8 best-matching events from other articles. This keeps the work growing in step with the number of articles, not with its square. |
| A(c) and B(c) | Build | A is the first verdict on a claim c; B is the blind second check. B never sees A's verdict or quote. |
| Gate rule | Build | Keep a link if a person accepted it, or if A accepted it and B did not reject it. A person's verdict always wins. |
| Decoys 1:1 | Build | B's work is half real accepted links and half earlier rejections, so a checker that says yes to everything would be caught. |
| Cannot-link | Repair | Two events joined by a person-accepted cause link can never be merged into one event (the call for a march is not the march). |
| Tarjan | Repair | A standard algorithm (1972) that finds loops in a graph. In each loop we drop the link whose quote does not support it. |
| 151 / 131 / 5 / 11 | Repair | 151 same-event decisions removed 131 duplicate events (several decisions can fold into one group); 5 wrong merges were blocked by the cannot-link rule, all from one verdict carried over from the pilot; 11 links were removed to break loops. |
| BM25 | Query | The standard search-engine scoring (as in library search) used to match the question's words to events. |
| 0.8 | Query | If a second story matches at least 80% as well as the best one, the site asks "which one do you mean?" instead of guessing. |
| 1/2 | Query | Events in the chosen story that match at least half as well as the best match are treated as what the question is about. |
| ≤ 3 links | Query | Answers are chains of up to three links, matching L = 3. |
| Strength 1–3 | Query | How strongly the article states the link (3 = stated outright). |
| 1.0 / 0.7 | Query | Evidence weight: a link stated in causal words counts fully, an implied link counts 70%. |
| +10% per outlet | Query | A link reported by more news outlets ranks higher: each extra outlet adds 10%. |
| Top m | Query | How many chains are returned; the engine returns 5 and the demo shows the top 3. |

Say it like this: "These are fixed rules chosen up front, not learned from data. The pilot was used only to check that the gate can be trusted."

## What the graph holds (slide 13)

Most links explain a protest by the grievance behind it (676 of 1,416), and three in four links (1,067) rest on explicit causal wording.

| Slide label | Relation | Count | What it means | Example from the graph |
| --- | --- | --- | --- | --- |
| Motivated by | MOTIVATES | 676 | A grievance or demand gives people a reason to protest | The demand for a legal MSP guarantee motivated the "Delhi Chalo" march |
| Set off by | TRIGGERS | 325 | A specific event sparks the protest | The march being stopped at the border set off the farmers' demonstration |
| Escalated from | ESCALATES | 235 | An earlier stage of the same dispute grows into this one | The Kolkata junior doctors' protest escalating into a fast-unto-death ("some of them have started the fast-unto-death agitation") |
| Response to | PROMPTS_RESPONSE | 119 | One side's action draws a response from another | The march prompted security forces to stop it |
| Organised by | MOBILIZES | 61 | A call or organisation brings people out | "Samyukta Kisan Morcha (Non-Political) and Kisan Mazdoor Morcha are spearheading the 'Delhi Chalo' march" |

- **1,067 stated vs 349 implied.** Stated = the article uses causal words ("protesting against", "in response to"). Implied = the article clearly shows the link without saying "because". Implied links turn out to be less reliable (next section).
- **358 of 373 protests explained.** 15 protests have no recorded cause, because their articles never say why.
- **No cycles.** No chain loops back on itself (A causes B causes A), which would make "why" questions endless.
- **Rebuilds byte for byte.** Running the build again on the stored files gives an identical file; its SHA-256 fingerprint is the graph's version number, so anyone can check they have the same graph.

## Accuracy (slide 14)

90% of links nobody had reviewed are correct, and every link stated in plain causal words was correct (69 of 69). Implied links are the weak spot at two in three.

**How the audit worked.** A seeded random draw picked 100 links from those no person had ever checked. One author judged each on a web form showing both events, the quotes and the source. Result: 89 correct, 10 wrong, 1 undecided, so the rate is 89 of the 99 decided = 90%.

| Bar on the chart | Correct / checked | What to say |
| --- | --- | --- |
| All | 89 / 99 (90%) | Nine in ten unreviewed links are right. |
| Stated wording | 69 / 69 (100%) | When the article says "because" or "protesting against", the graph never got it wrong in the sample. |
| Implied only | 20 / 30 (67%) | Implied links are right only two times in three, so the site hides unreviewed ones by default. |
| Depth 1 | 48 / 49 (98%) | Direct causes of a protest are almost always right. |
| Depth 2 | 33 / 42 (79%) | Causes of causes are harder; most of the errors sit here. |
| Depth 3 | 8 / 8 (100%) | Only 8 links, too few to read much into (the slide says so). |

- **The 82–94% range.** 100 links is a sample, so 90% is an estimate. The 95% range (a Wilson interval) means: if we checked every link, the true share correct would very likely fall between 82% and 94%.
- **69 of 69 is not "perfect".** Zero errors in 69 means the true error rate for stated links is very likely below about 5%, not that it is zero.
- **What the 10 errors were.** Six linked two reports of the same ongoing protest as if one escalated into the other. The rest quoted only one side of the link, or quoted a different event.
- **Why implied links are hidden.** A stricter re-check could not pick out the wrong implied links (it kept only 6 of the 20 the audit found correct), so the safe choice is to show them only after a person reviews them.

## Comparison with the GDELT-only method (slide 15)

A method that scores causes from GDELT's own fields flags random pairs as often as real ones (4.0% vs 3.8%), so it cannot tell a cause from a coincidence. Our text-based method rejects every fake pair it was shown.

**What the GDELT-only method was.** Our first attempt (August 2026): a scorer that rates a possible cause from six signals in GDELT's records, such as shared actors, which event codes tend to occur together, and the number of days between the events. Its strongest grade is called "pattern".

**The test (negative controls).** A good cause-finder must reject pairs that cannot be causes. We fed it three kinds of pairs:

- **Real candidates:** possible causes found near real protests (within the scorer's time window). Not confirmed causes, just the pairs it would normally rank.
- **Shuffled pairs:** a protest paired with an event from an unrelated story. These should never be causes.
- **Future pairs:** the "cause" happens after the protest. Impossible by definition.

| Result | GDELT-only scorer | Our text-based method |
| --- | --- | --- |
| "Pattern" grade on real candidates vs shuffled pairs | 3.8% vs 4.0%: no difference | not applicable |
| Shuffled pairs accepted | 4.0% of 557 | 0 of 60 |
| Impossible future pairs accepted | 3.1% of 1,058 | 0 of 35 |
| Real candidates accepted | 5.4% of 1,147 | not applicable |
| Proposed causes the articles actually support | 0 of 322 (for 23 protests) | 27 of 32 known causes found again (84%) |

- **0 of 322.** For 23 protests the scorer proposed 322 causes. We read the articles behind each: not one was a cause the text supports.
- **27 of 32.** Causes a person had already confirmed, hidden among the tests: the method found 27 of them again, blind.

Say it like this: "GDELT's codes tell you what happened, not why. Fake pairs scored as well as real ones, so we stopped scoring codes and started reading the text."

## Planned vs obtained (slide 16)

Human checking per published link fell about 17 times, from 1.18 to 0.07, while the method still finds most causes the articles state.

**1.18 → 0.07 checks per link ("about 17 times less").**

- **Pilot (300 articles), 1.18.** A person reviewed every link: 207 verdicts for the 176 links that were published (31 were rejected). 207 ÷ 176 = 1.18 checks per published link.
- **Scale-up (2,000 articles), 0.07.** No person took part in building the graph. The only human work was the 100-link audit, spread over 1,416 published links: 100 ÷ 1,416 = 0.07.
- **About 17 times.** 1.18 ÷ 0.07 ≈ 17. Say "about seventeen-fold", not exactly 17.
- **What did the work instead.** The pluggable annotator (an LLM following a written rubric), checked by the blind second annotation with decoys. The pilot is what showed that check can be trusted: of the 148 links it accepted, a person rejected none.

**Recall of stated causes.** Of the causes an article states for an event, the share the method found.

| Depth | Raw recall | Corrected | Meaning of "corrected" |
| --- | --- | --- | --- |
| 1 (direct causes) | 0.82 | about 0.93 | The judge only sees causes not yet linked, so a cause the graph already has gets reported as "missed". Counting those as found gives the corrected figure. It is a lenient estimate (matched by text similarity), so say "about". |
| 2 | 0.74 | about 0.82 | Same correction. |
| 3 | 0.78 | about 0.82 | Same correction. |

The Recover step is what lifts recall: when an article states a cause that extraction missed, that cause is created as a new event and linked. Search stopped when a further round accepted only 3 of 113 candidates.

The other two rows on the slide are covered above: the GDELT-only plan (comparison section) and implied links being hidden (accuracy section).

## Testing and demo numbers (slides 9–12)

The code is checked by 355 automated tests on every change, and the method's accuracy is measured separately, by agreement scores, controls and the audit.

| Number or term | Slide | What it means |
| --- | --- | --- |
| 355 tests in 32 files | 11 | Small programs that run each part of the pipeline, database, query engine, API and website and check the output. All pass before any change is merged. |
| Byte-identical goldens | 11 | Every API endpoint is called, and its answer must match a saved copy exactly. Same question, same answer, every time. |
| --help | 11 | Every pipeline script must start and print its usage. It was added after a malformed help text crashed every article re-fetch batch. |
| 250 MB | 11 | Vercel's size limit for the deployed app. One data library (pandas) took 186 MB of it, so it was removed. |
| Decoys 1:1 | 11 | The blind second check gets as many known-bad links as real ones, so blanket approval would show. |
| Cohen's kappa | 11 | Agreement between two independent annotations of the same claims (a quarter of protests were annotated twice), corrected for agreeing by chance. 1 = perfect, 0 = chance. Ours: 0.82–0.89 at scale, 0.78–0.93 in the pilot, usually read as very strong agreement. |
| 95% Wilson interval | 11 | The standard way to put a range on a rate measured from a sample, such as 82–94% for the audit. |
| 101 events, 185 links | 10 | The size of the story (the connected group of events) the farmers' border question falls in. |
| Top 3 chains | 10 | The engine returns up to 5 chains; the demo shows the best 3 so they fit on a projector. |
| 358 and 821 | 10 | The browse list: 358 explained protests when asking "What caused it", 821 causes when asking "What it led to". |
| 13 earlier events | 10 | The farmers' answer also says 13 earlier events in that story were never searched for their own causes, so the graph is honest about where it stops. |

Demo tip: press 6 to jump to "Ask it why", or / to go straight to the question box. If the Wi-Fi drops, the four featured questions still show their saved answers, labelled "saved answer".

## Questions the panel may ask

The strongest answers admit the limits up front and point to how each one is measured.

- **"Isn't this just ChatGPT reading articles?"** An LLM did the annotation, to make it fast, and the paper says so. The contribution is the algorithm around it: word-for-word spans, quotes checked by code, a blind second check with decoys, safe merging, loop removal and a query that runs no model. The annotator is pluggable, so a person could do the same job; the audit measures the result either way.
- **"Who checked the 100 links? Is that independent?"** One author, on a seeded random sample. A single reviewer is a limitation; a second reviewer would strengthen it.
- **"Were any links accepted carelessly?"** Yes, and it is disclosed: in a later pass one author accepted all 285 implied links in under three minutes. The paper records that pass as cursory and excludes it from every figure. The website still counts those links as reviewed, which is why the default view hides only 1 implied link.
- **"Is 90% good enough?"** Every link shows its quote and source, so anyone can verify it. Stated links were 69 of 69 correct, and the weaker implied links are hidden by default.
- **"Why do 15 protests have no cause?"** Their articles never say why. The graph only records causes the text states.
- **"Does the 3.8% vs 4.0% prove GDELT is useless?"** It shows that our six-signal scorer over GDELT's fields could not tell causes from coincidences. Reading the articles behind its 322 proposals confirmed it: none was supported. GDELT is still how we find the articles.
- **"Can it predict the next protest?"** No. It explains what happened, with sources. Prediction models over event graphs exist, but they cannot show why.
- **"Why only 2,000 articles?"** Cost and time. The work grows in step with the number of articles (each event is compared with a fixed 8 outside candidates), and human effort does not grow at all, so it can scale.
- **"What is still weak?"** Implied links (two in three right), causes of causes (79% at depth 2), screening and extraction labels that no person reviewed, and some duplicate events. Next steps: group dated events into campaigns, and review implied links by hand.

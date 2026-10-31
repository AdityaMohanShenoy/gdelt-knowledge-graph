# Audit rubric — conditions and remarks

Each article comes with its sentences and the CONDITIONS and REMARKS an extractor took from it.

**Condition** = a specific persistent state or grievance (policy, shortage, pattern of violence,
economic problem, governance failure) that holds over a period, as opposed to a one-off event.
For each condition judge:
- `valid`: `yes` if it is such a state AND the text states it; `no` if it is a one-off event, a
  vague phrase ("various issues"), merely a demand with no state behind it, or not in the text.
- `holders`, `locations`: `correct` | `wrong` | `empty` (correct = right party/place for this state).
- `kind`: `correct` | `wrong`. `role`: `correct` | `wrong` (`protest_cause` = the article presents it
  as a reason for a protest/demand/dispute).

**Remark** = a specific statement by an identifiable party at a particular time that the article
treats as significant (insult, accusation, threat, announcement, rejection) — not routine commentary.
For each remark judge:
- `valid`: `yes` / `no` (`no` for routine quotes, explanations, the article's own words).
- `actors`: `correct` | `wrong` | `empty`; `event_type`: `correct` | `wrong`
  (01 statement/announcement, 11 criticise/insult/accuse, 12 reject, 13 threaten).

Then list `missed`: important conditions the article presents as a protest cause that the
extractor did not capture (`{"sentence_id": int, "what": "<= 12 words"}`).
Judge only from the text. Be strict.

# Part 8 — Evaluation and Iteration

> **Level:** Advanced
> **What you'll learn:** why evaluation is inseparable from prompt engineering, the four RAGAS metrics and how they localize failures to a prompt surface, how LLM-as-judge evaluation works and where its biases lie, and the prompts-as-code workflow for changing prompts safely.
> **Prerequisites:** Parts [1](01-foundations.md)–[5](05-output-control.md); [Part 7](07-advanced-architectures.md) helpful.

Every part so far ended with claims like "this phrasing improves grounding." This part is about the machinery that lets *you* verify such claims on *your* system — because without measurement, prompt engineering is superstition with good intentions.

---

## 8.1 Why Evaluation Is Part of Prompt Engineering

### A prompt change is a code change

Change one sentence in the TechNova system message and you have changed the behavior of every conversation the system will ever have. That is the definition of a production code change — yet teams that would never merge code without tests routinely edit prompts by feel, eyeball two or three chat responses, and ship.

The failure mode this produces is **regression by improvement**: you strengthen the fallback instruction, over-refusal goes up, and nobody notices for a month because the answers that *were* checked looked great. Prompts have coupled, competing objectives (groundedness vs. helpfulness, format compliance vs. flexibility, caution vs. coverage) — improving one silently moves the others.

### The evaluation loop

The remedy is the same loop software engineering always uses:

```text
1. Build an evaluation set: representative questions + the contexts
   retrieved for them (+ ideally reference answers for a subset).
2. Run the current prompts over the set. Record metric scores.
   This is your baseline.
3. Change ONE thing (a prompt block, an ordering rule, a technique).
4. Re-run. Compare against baseline — all metrics, not just the
   one you meant to improve.
5. Keep the change if the trade-off is acceptable. Log the result
   either way.
```

The evaluation set should include, at minimum: happy-path questions, questions whose answers are *not* in the corpus (to measure fallback behavior), partial-coverage questions, multi-part questions, conflicting-source questions, out-of-scope questions, and a handful of injection probes (Part 6). Fifty to two hundred well-chosen cases beat five thousand random ones — and note that several of these categories directly mirror the few-shot examples of Part 5.3: what you demonstrate, you should also measure.

---

## 8.2 RAGAS Metrics

### The framework

**RAGAS** (Retrieval Augmented Generation Assessment; Es et al., arXiv:2309.15217) is the standard open-source framework for evaluating RAG pipelines. Its central practical virtue: its headline metrics are **reference-free** — they need no hand-written gold answers, only what your pipeline already produces (question, retrieved context, generated answer). That is what makes evaluation affordable at scale. Under the hood, the metrics use an LLM judge (section 8.3).

Four core metrics, two per pipeline stage:

| Metric | Stage measured | Question it answers | Needs ground truth? |
|---|---|---|---|
| **Faithfulness** | Generation | Is every claim in the answer supported by the retrieved context? | No |
| **Answer relevance** | Generation | Does the answer address the question that was asked? | No |
| **Context precision** | Retrieval | Of the retrieved chunks, how many were actually useful? | No |
| **Context recall** | Retrieval | Did retrieval surface all information needed to answer? | Yes (reference answer) |

**Faithfulness** — the hallucination detector — decomposes the answer into atomic claims, then asks the judge, per claim, whether the context entails it; the score is the supported fraction. **Answer relevance** catches the orthogonal failure: a perfectly grounded answer to the wrong question (it is commonly computed by reverse-generating candidate questions from the answer and comparing them to the original). **Context precision** measures retrieval noise (signal-to-noise of the injected chunks); **context recall** measures retrieval gaps, and is the one metric requiring a reference answer — so many teams run it on a small golden subset only.

### The diagnostic power: metrics → prompt surface

The reason RAGAS earns its place in a *prompting* article: the four scores, read together, tell you **which prompt surface from Part 1.4 is broken** — turning "the bot is bad" into a work item.

| Score pattern | Diagnosis | Where to fix |
|---|---|---|
| Context recall low | The evidence never arrived | Surface 1: query-side prompts (Part 4) — or the retriever/index itself |
| Context precision low, recall fine | Evidence arrived buried in noise | Retrieval tuning, reranking, retrieval grading (Part 7.2); fewer chunks (Part 3.2) |
| Faithfulness low, retrieval metrics fine | Right evidence, model went beyond it | Surface 2: Faithfulness Mandate, fallbacks, citations (Part 2); ordering (Part 3) |
| Answer relevance low, faithfulness fine | Grounded answer to the wrong question | Surface 3: synthesis prompt; or the query rewriter drifted (Part 4.2) |

### A worked example

TechNova evaluation case. Question: *"Can I schedule hourly backups on the Basic plan?"* Retrieved context: Source 1 (pricing guide — plans and prices, no scheduling info), Source 2 (release notes v4.2 — "scheduled backups on Pro and Business plans, hourly/daily/weekly"). Generated answer:

> *"Yes, NovaVault supports hourly scheduled backups. Scheduling was added in version 4.2 [Source 2]. The Basic plan costs $5/month [Source 1]."*

Scoring it:

- **Faithfulness:** decompose into claims: (a) "NovaVault supports hourly scheduled backups *[implied: on Basic]*" — **not supported**; Source 2 grants scheduling to Pro and Business only; (b) "scheduling was added in v4.2" — supported; (c) "Basic costs $5/month" — supported. **2 of 3 claims supported ⇒ ≈ 0.67. The "Yes" is a hallucination** — the context actually implies the opposite.
- **Answer relevance:** the answer addresses the question asked (plan + scheduling), though claim (c) is padding. **Moderately high, slightly penalized for the irrelevant pricing sentence.**
- **Context precision:** Source 2 was essential; Source 1 contributed only the padding. **≈ 0.5 — retrieval brought one strong chunk and one weak one.**
- **Context recall** (against a reference answer "No — scheduled backups are only available on Pro and Business [Source 2]"): everything the reference needs is in Source 2. **1.0 — retrieval was sufficient.**

Reading the pattern: recall 1.0, precision mediocre, faithfulness failing ⇒ **the evidence was there; the generation went beyond it ⇒ fix Surface 2.** And notice the answer's tell: the false claim (a) carries no citation — the citation rules of Part 2.4 ("no citation → no claim") would have blocked exactly this sentence, and the support-checking checkpoint of Part 7.2 would have caught it inline. The metrics, the citation contract, and the reflection checkpoints are one system seen from three angles.

### Running it

RAGAS ships as a Python library — the shape of an evaluation run:

```python
from ragas import evaluate
from ragas.metrics import (faithfulness, answer_relevancy,
                           context_precision, context_recall)
from datasets import Dataset

dataset = Dataset.from_dict({
    "question":     [...],   # your eval questions
    "contexts":     [...],   # retrieved chunks per question
    "answer":       [...],   # generated answers
    "ground_truth": [...],   # reference answers (context_recall only)
})

results = evaluate(dataset, metrics=[faithfulness, answer_relevancy,
                                     context_precision, context_recall])
```

Configure the judge model explicitly (see 8.3), and track scores **per category** of your evaluation set, not just in aggregate — an average hides the fact that fallback questions regressed while happy-path questions improved.

---

## 8.3 LLM-as-Judge: Power and Caveats

### How it works

Every reference-free RAGAS metric is an **LLM-as-judge** pattern: a judge model receives the question, context, and answer with a rubric prompt, and renders structured verdicts (claim extraction, entailment checks, relevance judgments). This is what makes evaluation scale — thousands of cases for the price of API calls, no human labeling per sample.

It also means your metrics are themselves LLM outputs, with everything that implies: **a weak judge produces weak scores**, and judges carry documented, systematic biases:

| Bias | Effect | Mitigation |
|---|---|---|
| **Position bias** | In pairwise comparisons, judges favor the first-presented option | Randomize or swap presentation order and average |
| **Verbosity bias** | Longer, more elaborate answers score higher at equal accuracy | Rubrics that explicitly exclude length; length-controlled comparisons |
| **Self-preference bias** | Judges rate outputs of their own model family higher | Judge from a different family than the generator, or use a judge panel |
| **Leniency drift** | Judges over-extend charity to borderline entailment ("close enough") | Strict rubric wording ("supported means explicitly stated, not plausible"); spot-check against humans |

### Working rules

- **Judge prompts are prompts.** Everything in Part 2.7 applies: imperative rubrics, one criterion per check, explicit output schema. Version them and eval them like any other prompt — you are now two levels deep, and that is normal.
- **Calibrate once, then trust but verify:** have a human label 50–100 cases, measure judge-human agreement, and re-check whenever you change judge model or rubric. Track score *movements* rather than worshipping absolute values — 0.87 vs. 0.91 faithfulness means little in isolation; a 0.04 drop after a prompt change means a lot.
- **Use a strong model for judging** even if generation uses a cheaper one; judge calls are a fraction of production volume and are the wrong place to economize.

---

## 8.4 Prompts as Code

The final piece is operational, and it comes directly from OpenAI's current official guidance: **treat prompts as application code.** Concretely:

**Prompts live in the repository, versioned.** Every prompt — system message, query rewriter, judge rubrics — is a named, reviewed artifact (e.g. `prompts/synthesis_system.md`, `prompts/query_rewriter.md`), not a string pasted into a dashboard. Changes arrive as pull requests, reviewed like the behavior changes they are, revertable via git history. OpenAI is deprecating its hosted reusable-prompt objects in favor of exactly this code-managed workflow.

**Templates take typed parameters.** The assembled prompt is built by a function with validated inputs, not string concatenation scattered across the codebase:

```python
def build_synthesis_prompt(chunks: list[Chunk],
                           query: str,
                           history: list[Turn]) -> str:
    """Assembles: system md + few-shot + <context> (smart-ordered,
    escaped, ids assigned) + reminder block + query."""
```

One function means the ordering rules (Part 3.2), escaping (Part 3.1), id assignment (Part 3.3), and reminder placement (Part 6.3) are implemented once and tested once.

**Every prompt change runs the evals.** Wire the Part 8.1 loop into CI: a PR that touches `prompts/` triggers the evaluation suite; the diff shows metric movements next to the text change. Regression gates (e.g. "faithfulness may not drop more than 0.02") make the groundedness-vs-helpfulness trade-off an explicit, reviewed decision instead of a silent drift.

**Releases are tagged and rollbackable.** Prompt versions ride the same release train as code; a bad prompt ships and rolls back like a bad build. Log which prompt version served each production response — when an incident arrives (Part 6.4's monitoring), "which prompt was live?" must be answerable in one query.

This workflow closes the article's loop: Parts 2–7 taught you what to write; this part ensures that every future edit to it is measured, reviewed, and reversible.

---

## Key Takeaways

- **A prompt change is a code change**: without an evaluation loop (baseline → change one thing → re-run → compare all metrics), improvements silently regress the objectives you weren't looking at.
- **RAGAS gives four reference-free-mostly metrics** — faithfulness, answer relevance, context precision, context recall — that together **localize failures to a prompt surface**: recall fails → query side; faithfulness fails with good retrieval → system message; relevance fails with good faithfulness → synthesis or rewriter drift.
- **LLM-as-judge is what makes evaluation scale, and it is biased**: position, verbosity, self-preference, leniency. Calibrate against humans, use strong judges from a different model family, track movements not absolutes.
- **Prompts are code**: versioned in the repo, assembled by typed functions, gated by CI evals, released and rolled back like builds, with per-response version logging in production.

**Next:** [Part 9 — Production Playbook](09-production-playbook.md) — everything from Parts 1–8 condensed into master templates, a diagnostic table, and a shipping checklist.

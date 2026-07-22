# Part 4 — Query-Side Prompt Engineering

> **Level:** Intermediate
> **What you'll learn:** why raw user queries make bad search queries, and the prompt techniques that fix them — query rewriting, HyDE, step-back prompting, decomposition and multi-query, self-query metadata filtering — plus a decision table for choosing among them.
> **Prerequisites:** [Part 1](01-foundations.md); Parts 2–3 helpful but not required.

Everything in Parts 2–3 assumed the retriever already found the right chunks. This part is about **Surface 1** — the prompts that run *before* retrieval and determine what evidence the model ever gets to see. No synthesis prompt, however well engineered, can recover from retrieval that returned the wrong documents.

All techniques in this part share one shape: **an extra LLM call that transforms the query before (or during) retrieval.** Each targets a different failure mode, and each costs latency — so the part ends with a decision table for diagnosing before stacking.

---

## 4.1 Why Raw User Queries Fail

Users write messages for a human conversation. Retrievers need search queries. The gap between the two has four recurring failure modes:

**1. Vocabulary mismatch.** The user's words are not the documentation's words.
> User: *"my files vanished"* — Documentation: *"restoring deleted files," "file recovery," "version history"*
Embeddings bridge some of this gap, but short colloquial queries against long technical documents remain a weak match: the query and the answer live in different regions of embedding space.

**2. Ambiguity and underspecification.**
> User: *"how much is it?"*
How much is *what*? Basic? Pro? Per user? The query embeds to something generic and retrieves generic chunks.

**3. Context-dependence on conversation history.**
> Turn 1: *"Does the Pro plan support scheduled backups?"*
> Turn 2: *"and how do I set that up?"*
Embedded alone, turn 2 contains no retrievable content at all — "that" is doing all the work, and the retriever cannot see the previous turn.

**4. Multi-part questions.**
> User: *"What's the price difference between Basic and Pro, and does Pro work on Linux?"*
One embedding must now match pricing chunks *and* platform-support chunks. It will usually match neither well — the average of two directions points at nothing.

Each technique below fixes one or more of these modes.

---

## 4.2 Query Rewriting

### The technique

The workhorse of the query surface: an LLM call that cleans, expands, and decontextualizes the user's message into a search-ready query.

```text
You are a search query generator for TechNova's NovaVault
documentation search system.

Given the conversation history and the customer's latest message,
produce ONE search query that:
- is self-contained (resolve all pronouns and references like "it",
  "that plan", "the feature you mentioned"),
- uses likely documentation terminology rather than casual phrasing,
- preserves the customer's actual intent — do not add topics they did
  not ask about,
- is a short keyword-style phrase, not a full sentence.

Conversation history:
{history}

Latest message: {user_message}

Search query:
```

### Worked example

| Input | Output |
|---|---|
| History: *"Does the Pro plan support scheduled backups?"* → *"Yes…"*; latest message: *"and how do I set that up?"* | `set up scheduled backups NovaVault Pro plan` |
| Latest message: *"my files vanished after the update!!"* | `restore missing files after NovaVault update` |

Both rewritten queries hit documentation vocabulary and are self-contained — failure modes 1 and 3 fixed with one call.

### The risk to gate: intent drift

The rewrite is itself an LLM generation, and it can *drift* — adding topics the user never mentioned or narrowing the question wrongly. If the rewriter turns *"my files vanished"* into `NovaVault sync conflict resolution`, retrieval will be confidently wrong. Two mitigations:

1. The instruction "preserve the customer's actual intent — do not add topics" in the prompt above, which measurably reduces drift.
2. An evaluation check (Part 8) comparing rewritten queries against intent on a labeled sample. Gate the rewriter with this before shipping changes to it.

**Cost:** one extra LLM call per user message — use a small, fast model; this task does not need your best generator.

---

## 4.3 HyDE — Hypothetical Document Embeddings

### The idea

**HyDE** (Hypothetical Document Embeddings; Gao et al., 2022) attacks the vocabulary-mismatch problem from the opposite direction. Instead of embedding the *question*, prompt an LLM to write a **hypothetical answer** — and embed *that* for the vector search.

```text
Write a short passage that could appear in NovaVault's official
documentation and that would answer the following customer question.
Write it in documentation style. It does not need to be factually
correct — it will be used only as a search probe.

Question: {query}

Passage:
```

### Why it works

Questions and answers live in different regions of embedding space: *"my files vanished"* is colloquial, short, and question-shaped; the documentation chunk that helps is declarative, technical, and answer-shaped. A hypothetical answer —

> *"To recover deleted files, open the NovaVault dashboard and select Restore. NovaVault retains previous versions of files for 30 days on the Basic plan…"*

— has the **semantic shape of the real target chunk**, so its embedding lands near real answer documents even though its facts are invented. The facts don't matter; only the neighborhood does. The hypothetical passage is a search probe — it is **never shown to the user and never injected as context**.

### When it shines and when it fails

- **Shines:** short or vague queries against a technical corpus; domains where users don't know the terminology (medical, legal, technical support).
- **Fails:** when the hypothetical drifts to the wrong subject entirely — a hallucinated premise produces a confidently wrong probe. Mitigation: generate 2–3 hypotheticals and average or union their retrievals; or fall back to hybrid search (embedding + keyword) so the raw query still contributes.
- **Costs:** one LLM call plus (in the multi-hypothetical variant) extra retrievals.

---

## 4.4 Step-Back Prompting

### The idea

**Step-back prompting** (Zheng et al., 2023) handles questions that are *too specific* for direct retrieval: the corpus contains the general principles, but no chunk matches the hyper-specific query. The fix: prompt the model to "step back" and generate a **more general question**, retrieve for both, and answer the specific question using both result sets.

```text
Given a specific customer question, produce ONE more general question
whose answer would provide the background needed to answer the
specific question.

Examples:
Specific: "Why does my NovaVault backup fail at exactly 2:00 AM on
Tuesdays?"
General: "What causes scheduled NovaVault backups to fail?"

Specific: "Can I restore a file version from 45 days ago on the Basic
plan?"
General: "How long does NovaVault retain file version history per plan?"

Specific: {query}
General:
```

### The pipeline

1. Generate the step-back question.
2. Retrieve for **both** the original and step-back questions.
3. Inject both result sets (labeled normally, per Part 3) and answer the original question.

For the 45-days example: nothing in the docs mentions "45 days," so direct retrieval flails — but the step-back question retrieves the version-retention policy table ("Basic: 30 days, Pro: 180 days"), from which the model grounds a correct "no, Basic retains versions for 30 days [Source 1]."

**Use for:** troubleshooting and edge-case questions where specifics are unindexed but principles are documented. **Cost:** one LLM call + one extra retrieval.

---

## 4.5 Decomposition and Multi-Query

Two related techniques that replace *one* retrieval with *several* — for opposite reasons.

### Decomposition: one query per sub-question

For multi-part and multi-hop questions (failure mode 4), prompt the model to split the question into independent sub-queries:

```text
Break the customer's question into the minimal set of independent
search queries needed to answer it fully. Return a JSON array of
strings. Do not invent sub-questions the customer did not ask.

Question: "What's the price difference between Basic and Pro, and
does Pro work on Linux?"

["NovaVault Basic plan price", "NovaVault Pro plan price",
 "NovaVault Pro Linux support"]
```

Retrieve per sub-query, pool the results (deduplicated, with source ids assigned per Part 3), and synthesize a single answer. Each retrieval now points in *one* direction instead of averaging several.

*Multi-hop variant:* when sub-question 2 depends on the answer to sub-question 1 ("Which plan does my company use, and does *that plan* support SSO?"), run retrieval and a short intermediate answer sequentially. This is the doorway to agentic RAG (Part 7).

### Multi-query: several phrasings of the same question

For recall-critical situations, generate 3–4 *paraphrases* of the same query, retrieve for all, and merge:

```text
Generate 3 alternative phrasings of this search query, each using
different vocabulary a technical writer might have used.

Query: "restore missing files after NovaVault update"

1. recover deleted files NovaVault
2. file version history rollback NovaVault
3. NovaVault data recovery after upgrade
```

Merging uses **Reciprocal Rank Fusion (RRF)** — a simple, robust scheme where each chunk's score is the sum of `1/(k + rank)` over all result lists it appears in. Chunks ranked well by *multiple* phrasings float to the top; single-list flukes sink.

| | Decomposition | Multi-query |
|---|---|---|
| Splits by | Topic (different sub-questions) | Phrasing (same question) |
| Fixes | Multi-part/multi-hop questions | Vocabulary-sensitivity, recall |
| Merge | Pool per-sub-query results | RRF over paraphrase results |
| Cost | 1 LLM call + N retrievals | 1 LLM call + N retrievals |

---

## 4.6 Self-Query and Metadata Filtering

### The idea

Part 3 (section 3.4) attached metadata to chunks — dates, types, sections. **Self-query** puts that metadata to work at retrieval time: prompt an LLM to extract **structured filters** from the natural-language question, then run the semantic search *constrained by those filters*.

```text
Extract search parameters from the customer's question.
Return JSON with:
- "query": the semantic search text
- "filters": any of {doc_type, plan, date_after, date_before, platform}
  that the question explicitly implies. Omit filters not implied.

Question: "What changed in the release notes since April about the
Business plan?"

{
  "query": "Business plan changes new features",
  "filters": {
    "doc_type": "release-notes",
    "plan": "business",
    "date_after": "2026-04-01"
  }
}
```

The retriever then searches *only* release notes about the Business plan dated after April — constraints that pure embedding similarity handles badly (embeddings are notoriously weak at dates and hard categorical boundaries) but a metadata `WHERE`-clause handles perfectly.

### Requirements and cautions

- Your index must store the metadata fields and support filtered search (all mainstream vector databases do).
- **Constrain the schema in the prompt** — list the exact allowed fields and values; a freeform filter generator will invent fields your index doesn't have. Validate the JSON against the schema and drop invalid filters rather than failing the search.
- Beware over-filtering: a wrongly inferred filter silently excludes the right documents. When in doubt, run the filtered *and* unfiltered search and merge (RRF again).

---

## 4.7 Choosing a Technique

Every technique in this part adds at least one LLM call of latency and a new failure surface. The professional move is to **diagnose the failure mode first, then apply the lightest technique that fixes it** — not to stack everything.

### The decision table

| Observed failure | Diagnosis | Lightest fix | Cost | Escalate to |
|---|---|---|---|---|
| Follow-up questions retrieve junk ("how do I set *that* up?") | Context-dependence | **Query rewriting** with history | 1 LLM call | — |
| Casual queries miss technical docs ("my files vanished") | Vocabulary mismatch | **Query rewriting** (terminology mapping) | 1 LLM call | **HyDE** if rewriting is not enough |
| Short/vague queries against a deep technical corpus | Vocabulary + shape mismatch | **HyDE** | 1 LLM call | Multi-hypothetical HyDE |
| Hyper-specific questions miss the general docs that answer them | Specificity gap | **Step-back prompting** | 1 LLM call + 1 retrieval | — |
| Multi-part questions get half-answered | Averaged embedding | **Decomposition** | 1 LLM call + N retrievals | Sequential (multi-hop) decomposition |
| Same question phrased differently gets different results | Phrasing sensitivity | **Multi-query + RRF** | 1 LLM call + N retrievals | — |
| Questions with dates/types/categories retrieve stale or wrong-type chunks | Metadata-blind search | **Self-query filtering** | 1 LLM call | — |
| Everything above is fine but precision is still low | Retrieval-side, not query-side | Hybrid search + reranking (Part 7) | — | — |

### Three rules of thumb

1. **Start with query rewriting.** It is the cheapest, fixes the two most common failure modes (history and vocabulary), and nearly every conversational RAG system needs it anyway.
2. **Add one technique at a time, measured.** Use retrieval metrics (context precision/recall, Part 8) to confirm each addition pays for its latency. A technique that does not move the metric is pure cost.
3. **Gate every query-transforming prompt against drift.** Each transformation is a place where the system can silently change the user's question. The rewrite/decomposition/filter outputs should be logged and sampled in evaluation — they are code paths, not magic.

---

## Key Takeaways

- Raw user messages fail as search queries in four ways: **vocabulary mismatch, ambiguity, history-dependence, and multi-part structure**. Query-side prompts fix these before retrieval — and nothing downstream can compensate if they don't.
- **Query rewriting** is the workhorse: resolve references, map to documentation vocabulary, preserve intent (and test for drift).
- **HyDE** searches with a hypothetical *answer* instead of the question, matching the semantic shape of target documents; its facts are irrelevant, its neighborhood is everything.
- **Step-back prompting** retrieves general principles for hyper-specific questions; **decomposition** splits multi-part questions; **multi-query + RRF** defeats phrasing sensitivity.
- **Self-query** turns natural language into metadata filters — the right tool for dates, types, and categories that embeddings handle poorly.
- **Diagnose, then apply the lightest fix, one at a time, measured.** Every technique is an extra LLM call and a new drift surface.

**Next:** [Part 5 — Output Control](05-output-control.md) — engineering the *shape* of the answer: structured output, machine-parseable citations, few-shot examples, and conflicting sources.

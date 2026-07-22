# Part 7 — Advanced Architectures

> **Level:** Advanced
> **What you'll learn:** prompting when retrieval moves inside the reasoning loop (agentic RAG), self-reflective patterns adapted from Self-RAG and CRAG, multi-turn conversational RAG, token-budget engineering and prompt caching, and per-vendor model considerations.
> **Prerequisites:** Parts [1](01-foundations.md)–[6](06-security.md). This part assumes fluency with everything built so far.

The pipeline in Parts 1–6 is *linear*: reformulate → retrieve → synthesize, once, in a fixed order. This part covers what changes when the pipeline becomes a **loop** — when the model itself decides when to retrieve, judges what it retrieved, and iterates — and the operational engineering (cost, caching, per-model tuning) that production systems at this level require.

---

## 7.1 Prompting in Agentic RAG

### From pipeline to loop

In **agentic RAG**, retrieval becomes a *tool the model calls*, inside a reasoning loop:

```mermaid
flowchart LR
    Q[User question] --> Think["Model reasons: do I need evidence?"]
    Think -->|yes| Search["search_docs(query)"]
    Search --> Judge["Model reads results: sufficient?"]
    Judge -->|"no, reformulate"| Search
    Judge -->|yes| Answer["Grounded answer with citations"]
    Think -->|"already sufficient"| Answer
```

The model can ask for more evidence, rewrite its own query mid-task, follow a multi-hop chain (retrieve → learn → retrieve again), or stop early. This subsumes much of Part 4 — decomposition and step-back become things the agent *does* rather than fixed pipeline stages.

The price: **you no longer control the sequence, only the policy.** The system message stops being a script and becomes a policy document for a decision-maker. Three policy areas need explicit prompting:

### Tool-use instructions

Define the tool precisely, then define *when to use it* — the part teams under-specify:

```text
## Tools
You have one tool: search_docs(query: string) — searches TechNova's
documentation and returns up to 5 chunks with ids, titles, and dates.

## Retrieval policy
- ALWAYS search before answering any factual question about NovaVault.
  Your own knowledge about NovaVault is considered outdated.
- Write search queries in documentation vocabulary, not the customer's
  casual phrasing (e.g. "restore deleted files", not "files vanished").
- If the first search returns nothing useful, reformulate ONCE with
  different terms. Vary the vocabulary, not just word order.
- For multi-part questions, run one search per sub-question.
```

The first rule matters most: an agent that believes it already knows the answer skips retrieval and answers from parametric memory — the exact failure RAG exists to prevent. Stating "your knowledge is considered outdated" makes retrieval the default, not the exception.

### Evidence-sufficiency criteria

The agent needs a definition of *enough*:

```text
## Sufficiency
Before answering, check: does the retrieved evidence directly support
every factual claim you are about to make?
- If yes: answer, citing per the citation rules.
- If partly: answer the supported part; state explicitly what the
  documentation does not cover (partial-coverage fallback).
- If no: do not answer from memory. Use the fallback response.
```

This is the Faithfulness Mandate (Part 2.2) restated as a *loop-exit condition* — the same contract, adapted to a system that decides its own control flow.

### Stopping conditions

Loops need brakes. Unbounded agents burn tokens re-searching the same gap:

```text
## Limits
- At most 4 searches per customer question.
- If 4 searches have not produced sufficient evidence, stop and use
  the fallback response. Never keep searching past the limit, and
  never substitute memory for missing evidence.
```

Explicit numeric limits outperform vague guidance ("don't search excessively") for the same reason all of Part 2.7's rules do: they are testable, and the model treats them as constraints rather than suggestions.

### Security note

Agentic RAG raises the injection stakes from Part 6: retrieved text now sits adjacent to *tool-calling capability*, so a successful injection can trigger tool calls, and tool outputs re-enter the context, enabling chained effects. The full Part 6 stack — inert-data policy, output validation, least-privilege tools, human confirmation for consequential actions — is not optional at this level.

---

## 7.2 Self-Reflective Patterns: Self-RAG and CRAG

Two research architectures — **Self-RAG** (Asai et al., 2023) and **CRAG** (Corrective RAG; Yan et al., 2024) — formalized the idea that the model should *critique the retrieval and its own answer* instead of trusting both blindly. Self-RAG trains a model to emit reflection tokens grading whether retrieval is needed (`Retrieve`), whether each passage is relevant (`ISREL`), whether the output is supported (`ISSUP`), and whether it is useful (`ISUSE`); CRAG adds a retrieval evaluator that routes to *correct / ambiguous / incorrect* handling, including corrective re-retrieval or web-search fallback.

You do not need fine-tuning to benefit. The durable insight translates directly into **prompt patterns** — three checkpoints you can add to any pipeline:

### Checkpoint 1 — Retrieval grading (before synthesis)

A cheap LLM call that filters what the retriever returned:

```text
You are a relevance grader. For each document below, decide whether it
contains information that helps answer the question.

Question: {query}

<document id="3">...</document>
...

Return JSON: [{"id": 3, "relevant": true|false, "reason": "..."}]
Grade strictly: topical overlap is not enough — the document must
contain information usable in the answer.
```

Irrelevant chunks are dropped *before* they reach the synthesis prompt — remember from Part 3.2 that distractors actively harm generation, so this grading pass converts retrieval noise into a smaller, cleaner context. CRAG's routing then falls out naturally in your application code:

- **all relevant** → synthesize normally;
- **mixed** → synthesize from the relevant subset;
- **none relevant** → re-retrieve with a reformulated query (Part 4 techniques), or go straight to the fallback response.

### Checkpoint 2 — Support checking (after synthesis)

Self-RAG's `ISSUP` as a standalone verification call:

```text
You are a groundedness checker. For each claim in the answer, decide
whether the provided documents support it.

Documents: {the exact chunks used}
Answer: {the generated answer}

Return JSON: [{"claim": "...", "supported": true|false, "source_id": N|null}]
```

Unsupported claims trigger regeneration (with the checker's findings appended as feedback) or removal of the offending sentences. This is the same machinery as evaluation-time faithfulness checking (Part 8) moved *inline* — Part 8's metrics measure the system offline; this checkpoint enforces the property per-response.

### Checkpoint 3 — Usefulness checking

Cheapest of the three: does the answer actually address the question? Catches the failure where the model, grounded and cited, faithfully answers a *related but different* question. One judge call comparing question to answer; low scores route to regeneration.

### When the loops pay for themselves

Each checkpoint adds an LLM call. Deploy them where the cost-benefit lands:

| Checkpoint | Adds | Deploy when |
|---|---|---|
| Retrieval grading | ~1 fast-model call | Retrieval precision is your measured weak point; corpus is noisy |
| Support checking | ~1 call + possible regeneration | Hallucination cost is high (billing, legal, medical) |
| Usefulness checking | ~1 fast-model call | Users report "correct but useless" answers |

A pragmatic production pattern: run checkpoints 2–3 on a *sample* of traffic plus all high-stakes routes, not on every request.

---

## 7.3 Multi-Turn Conversational RAG

Multi-turn conversation stresses three specific joints of everything built so far:

### Query reformulation with history

Part 4.2's rewriter becomes mandatory, because follow-ups are referentially dependent: *"and how do I set **that** up?"* retrieves nothing without coreference resolution against history. One addition earns its place — a **retrieval-necessity gate** in the same call:

```text
Given the conversation history and the latest customer message:
1. Decide whether answering requires searching the documentation.
   - Messages like "thanks!", "ok great", or pure chit-chat: NO.
   - New factual questions or follow-ups needing detail: YES.
2. If YES, produce ONE self-contained search query (resolve every
   pronoun and reference from the history).

Return JSON: {"needs_retrieval": bool, "query": string|null}
```

Skipping retrieval for "thanks!" saves a retrieval round-trip on a large fraction of real conversation turns.

### Context management across turns

Naively re-injecting every turn's retrieved chunks bloats the window and pushes early rules into the dead middle (Part 3.2). Working defaults:

- Inject **only the current turn's** retrieved chunks; prior turns keep their *answers* in history, not their evidence.
- Cap conversation history (last N turns, or a running summary for long sessions).
- Assign source ids **fresh per turn**, and make citations refer to the current turn's context only — stale ids pointing at evicted chunks are silent citation corruption.

### Keeping the mandate intact across turns

Two documented multi-turn decay modes need explicit countermeasures. First, **rule drift**: instructions stated once, far back in a long conversation, gradually lose force. The fix is the anchoring pattern from Part 6.3 applied per-turn — the reminder block after each turn's context re-states grounding, citation, and fallback rules in compressed form. Second, **premise creep**: the model treats *its own previous answers* as evidence, compounding any earlier error. Add one rule:

```text
Your previous replies in this conversation are not sources. Every
factual claim in every reply must be supported by the CURRENT
<context> section, or use the fallback response.
```

---

## 7.4 Token Budget and Prompt Caching

At production volume, prompt engineering is also cost engineering. Two disciplines:

### Static-first ordering for prompt caching

Both OpenAI and Anthropic offer **prompt caching**: when consecutive requests share a long identical *prefix*, the shared prefix is processed once and reused, cutting input cost and latency substantially on cache hits (billed details vary by vendor; Anthropic documents up to 90% cost and 85% latency reduction on cached content, OpenAI offers automatic discounts of 50–90% depending on model). Caching works on **exact prefixes** — so the prompt must be laid out with everything stable first and everything variable last:

```text
┌───────────────────────────────┐
│ System message                │ static   ← cached
│ Tool definitions              │ static   ← cached
│ Few-shot examples             │ static   ← cached
├───────────────────────────────┤
│ Conversation history          │ semi-static (append-only)
├───────────────────────────────┤
│ <context> retrieved chunks    │ variable ← never cacheable
│ Reminder block                │ static text but after variable ⇒ not cached
│ User query                    │ variable
└───────────────────────────────┘
```

This is the fourth time the same ordering has been independently justified — recency for the query (Part 1), smart ordering for chunks (Part 3), reinforcement-after-context for security (Part 6), and now caching economics. The conclusions all agree, which is why the canonical RAG layout is stable across vendors. Two operational corollaries: **don't put timestamps, request ids, or per-user values in the system message** (one changed byte invalidates the prefix), and version your static blocks deliberately since every prompt edit is a temporary cache reset.

### Spending the window deliberately

The token budget is one pool with competing claimants: system message + examples (fixed overhead on *every* request), history, retrieved context, and output room. The discipline is to treat each as a line item with a cap — compact scenario blocks (Part 2.6), 2–3 examples not six (Part 5.3), top 3–5 chunks not twenty (Part 3.2), capped history (7.3) — and to remember that the *effective* context (where the model reliably uses information, per Lost in the Middle) is smaller than the *nominal* window the spec sheet advertises. When the budget is under pressure, cut context count before cutting the rules: five well-chosen chunks with intact rules beat fifteen chunks with diluted ones.

---

## 7.5 Model-Specific Considerations

> **Last verified: July 2026.** This section dates faster than any other in the article — vendor guidance changes with each model generation. Re-check the linked official docs before applying to a new model version, and pin model snapshots in production so behavior changes arrive on your schedule, not the vendor's.

The whole architecture of this article is vendor-neutral. Tuning the last 10% is not:

### Claude (Anthropic)

- **XML tags are the officially recommended structure** — Anthropic's docs explicitly advise XML-tagged prompts (`<context>`, `<instructions>`, `<example>`), so Part 3's structure is native here.
- **Long-context prompting:** for large context blocks, Anthropic recommends placing long documents near the top of the prompt and asking the model to **extract relevant quotes before answering** — which dovetails with the quote-grounded citations of Part 5.2.
- **Extended thinking:** on Claude models with extended thinking, prefer high-level guidance ("think through which documents are relevant before answering") over rigidly prescriptive step lists; the model's own reasoning process handles decomposition well.

### GPT (OpenAI)

- **Delimiters and structure:** OpenAI's guidance emphasizes clear delimiters and sectioned prompts; Markdown headers and XML both work.
- **Reasoning models:** do **not** add "think step by step" or similar chain-of-thought scaffolding to reasoning-capable models — OpenAI's own documentation warns it can degrade performance, since the model already reasons internally. State the *goal and constraints*; skip the *how*.
- **Pin snapshots:** OpenAI model endpoints evolve (including router-based systems); production apps should pin dated snapshots and treat model upgrades as releases with eval runs (Part 8).
- **Structured Outputs:** prefer the native JSON-schema enforcement over prompt-only schemas (Part 5.1) when on this platform.

### Gemini (Google)

- **Query last, after the data:** Google's prompting guidance recommends placing the specific question at the **end**, after the data context — consistent with the canonical RAG layout.
- **Few-shot strongly preferred:** Google's prompt engineering guidance explicitly recommends always including few-shot examples — zero-shot prompting is called out as not preferred; Part 5.3's examples are not optional here.
- **Very long contexts:** with multi-million-token windows, position effects and per-request cost make deliberate placement and context caps *more* consequential, not less. A huge window is a budget, not a mandate to fill it.

The meta-rule: the architecture transfers; the tuning doesn't. When switching vendors, keep every Part 1–6 decision, re-verify the ordering heuristics and formatting preferences against the new vendor's current documentation, and re-run your evaluation suite — which is exactly what Part 8 builds.

---

## Key Takeaways

- **Agentic RAG turns the pipeline into a loop** and the system message into policy: explicit retrieval triggers ("your knowledge is outdated — always search"), reformulation rules, evidence-sufficiency criteria, and hard numeric stopping limits.
- **Self-RAG and CRAG translate into three prompt checkpoints** you can adopt without fine-tuning: grade retrieval before synthesis, check support after synthesis, check usefulness last — deployed selectively where their cost pays off.
- **Multi-turn RAG** needs a retrieval-necessity gate, per-turn context management with fresh source ids, per-turn rule anchoring, and an explicit "your previous replies are not sources" rule.
- **Prompt caching rewards the canonical layout** (static first, variable last) with major cost and latency cuts — the same ordering that recency, smart ordering, and security reinforcement already justified. Budget the window per line item, and prefer cutting chunks over cutting rules.
- **Vendor tuning is real but shallow:** XML and quote-extraction for Claude, no CoT scaffolding on reasoning models and pinned snapshots for GPT, few-shot-always and query-last for Gemini — verify against current docs (this section: July 2026) and re-run evals when anything changes.

**Next:** [Part 8 — Evaluation and Iteration](08-evaluation.md) — how to measure whether any of this actually works, and how to change prompts without breaking them.

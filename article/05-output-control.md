# Part 5 — Output Control

> **Level:** Intermediate
> **What you'll learn:** how to control the *shape* of RAG answers — structured JSON output, machine-parseable citation contracts, few-shot examples that teach grounding behavior, and prompt patterns for handling conflicting sources.
> **Prerequisites:** [Part 2](02-system-message.md) (citation rules) and [Part 3](03-context-injection.md) (source identifiers).

Parts 2–4 governed what the model *says*. This part governs the **form it says it in** — which matters because in production, the model's output is rarely read only by a human. It is parsed by your application, rendered in a UI, logged, verified, and measured. Output that cannot be parsed cannot be checked.

---

## 5.1 Structured Output

### Why RAG systems need structure

A plain-prose answer is fine for a chat window. But the TechNova assistant's answer also needs to carry: which sources were used (for UI links), whether the fallback fired (for analytics), whether escalation was requested (for routing), and a confidence signal (for review queues). Cramming all that into prose makes it invisible to code. The fix is to make the model emit **JSON with a declared schema**.

### Two ways to enforce a schema

**Option A — Schema in the prompt.** Works on every model:

```text
## Output format
Respond with a single JSON object matching exactly this schema:
{
  "answer": string,          // the customer-facing answer text
  "citations": [             // every source used, may be empty
    { "source_id": number, "claim": string }
  ],
  "fallback_used": boolean,  // true if you could not answer from context
  "escalate": boolean,       // true if this needs a human agent
  "escalation_reason": string | null
}
Return ONLY the JSON object. No markdown fences, no commentary.
```

**Option B — Native structured output.** OpenAI's Structured Outputs and equivalent features on other platforms accept a JSON Schema through the API and *guarantee* syntactically valid conformance — the model literally cannot produce invalid JSON. Prefer this when your platform offers it; keep the schema description in the prompt anyway, because the API guarantees *syntax*, while your prompt must still explain the *semantics* ("`fallback_used` means…").

Even with native enforcement, validate downstream: syntactic validity does not mean the *content* is right (a well-formed `citations` array can still cite the wrong source — Part 8 covers checking that).

### Worked TechNova example

Question: *"Can I schedule backups on the Basic plan?"* (context: pricing guide = Source 1, release notes = Source 2):

```json
{
  "answer": "Scheduled backups are available on the Pro and Business plans, added in version 4.2. The documentation does not indicate that the Basic plan supports scheduled backups.",
  "citations": [
    { "source_id": 2, "claim": "Scheduled backups are available on the Pro and Business plans, added in version 4.2." }
  ],
  "fallback_used": false,
  "escalate": false,
  "escalation_reason": null
}
```

The UI renders `answer`, links `citations`, analytics counts `fallback_used`, and the router checks `escalate` — four consumers, one output, zero parsing heuristics.

### How structure interacts with grounding

A subtle, well-documented trade-off: **heavy format constraints compete for the model's attention with content constraints.** If you demand an elaborate nested schema *and* perfect grounding, small models especially will sacrifice one for the other. Mitigations:

- Keep the schema as flat and small as the application allows.
- Put the grounding rules *before* the format rules in the system message; repeat the crucial "ONLY from context" line inside the format section if you observe drift.
- The `fallback_used` field is itself a grounding aid: it gives the "I don't know" path a first-class, low-friction representation in the output — the model doesn't have to "break format" to decline.

---

## 5.2 Machine-Parseable Citations

Section 2.4 established the citation *rules*; this section establishes the citation *output contract* — the exact shape citations take so software can consume them.

### Three contract levels

**Level 1 — Inline markers** (what Part 2 used):

```text
The Pro plan costs $12/month [Source 1]. Scheduled backups were added
in version 4.2 [Source 2].
```

Cheap, human-readable, and parseable with a regex (`\[Source (\d+)\]`). Fine for chat UIs. Weakness: the *claim boundary* is implicit (the sentence), so automated verification has to guess what each marker covers.

**Level 2 — Per-claim citation array** (the JSON pattern from 5.1): each entry pairs a `source_id` with the exact `claim` string it supports. This makes verification mechanical: for each pair, check whether document `source_id` entails `claim`. This is precisely the shape that automated faithfulness checking (Part 8) consumes.

**Level 3 — Quote-grounded citations.** For high-stakes domains, require the model to *quote its evidence*:

```text
For every claim, include the exact sentence from the source document
that supports it, copied verbatim, in the "evidence" field.
```

```json
{
  "claim": "Scheduled backups were added in version 4.2.",
  "source_id": 2,
  "evidence": "Version 4.2 adds scheduled backups on the Pro and Business plans."
}
```

Verbatim quotes can be string-matched against the actual chunks — fabricated evidence is caught by an exact-match check, no LLM judge needed. Anthropic's guidance for long-context prompting recommends quote-first patterns for exactly this reason (asking the model to extract relevant quotes *before* answering also focuses its attention on the evidence).

### Why "cite your sources" without a contract fails

Left to improvise, models produce: citations at paragraph granularity (which claim?), "according to the documentation" (which document?), bibliography-style source lists at the end (unlinkable to claims), or invented ids. Every one of these is unusable by code. **A citation format you cannot parse is a citation format you cannot verify — and unverifiable citations are decoration, not grounding.**

### Post-hoc citation verification

The citation contract enables a cheap output-side safety net that production systems should run on every response:

1. Parse all cited `source_id`s → every id must exist in the injected context (catches invented sources).
2. (Level 3) String-match every `evidence` quote against its source chunk (catches fabricated evidence).
3. (Sampled or high-stakes traffic) LLM-judge check: does the source entail the claim? (Part 8.)

Responses failing checks 1–2 can be blocked or regenerated automatically — they are deterministic, sub-millisecond string operations.

---

## 5.3 Few-Shot Examples for Grounding Behavior

### What few-shot buys in RAG

Instructions *describe* desired behavior; examples *demonstrate* it. For output shape especially — citation placement, JSON structure, tone — a single concrete demonstration outperforms a paragraph of description. In a RAG prompt, include one to three examples covering the three behaviors that matter:

**Example 1 — a correctly grounded, cited answer** (the happy path):

```text
<example>
  <question>How much storage does the Basic plan include?</question>
  <answer>{"answer": "The Basic plan includes 50 GB of storage.",
  "citations": [{"source_id": 1, "claim": "The Basic plan includes
  50 GB of storage."}], "fallback_used": false, "escalate": false,
  "escalation_reason": null}</answer>
</example>
```

**Example 2 — a correct fallback on an unanswerable question:**

```text
<example>
  <question>Does NovaVault support end-to-end encryption?</question>
  <!-- context in this example contains nothing about encryption -->
  <answer>{"answer": "I don't have enough information in the
  documentation to answer that. You can reach TechNova support at
  support@technova.example.", "citations": [], "fallback_used": true,
  "escalate": false, "escalation_reason": null}</answer>
</example>
```

**Example 3 — a partial-coverage answer** (answer what's covered, flag what isn't):

```text
<example>
  <question>Does Pro include scheduled backups, and can I back up an
  external drive?</question>
  <answer>{"answer": "Yes — scheduled backups are included in the Pro
  plan. As for external drives, the documentation I have doesn't cover
  that.", "citations": [{"source_id": 2, "claim": "Scheduled backups
  are included in the Pro plan."}], "fallback_used": true,
  "escalate": false, "escalation_reason": null}</answer>
</example>
```

### The fallback example is the one teams forget — and the one that matters most

Nearly every prompt with few-shot examples demonstrates the happy path. But the happy path is the behavior the model would produce anyway. The **fallback example teaches the behavior the model resists**: declining fluently when evidence is missing. Without a demonstration, the fallback instruction competes against billions of training examples of models answering questions; with one, "produce the fallback JSON" is just pattern-matching. If you include only one example, make it the fallback.

### Placement and hygiene

- Place examples **after the system message, before the live context** (the static-first order also maximizes prompt caching — Part 7).
- Wrap them in `<example>` tags so they cannot be confused with live context or the live question.
- Keep example contexts *fictional but realistic*, and don't reuse document ids that commonly appear live (or state clearly the examples' context is separate) — you don't want the model citing an example's source.
- Few-shot examples are among the most token-expensive parts of the prompt and are billed on every request; two or three well-chosen ones nearly always beat six.

---

## 5.4 Handling Conflicting Sources

### The scenario

Real corpora contain contradictions: last year's pricing page says $10/month, this year's says $12/month; a user guide predates a feature that release notes describe. Sooner or later, both versions land in the same context window. An unprepared model resolves the conflict silently and arbitrarily — by position, by fluency, or by mixing the two into a third answer nobody wrote.

### The rules

Add a conflict block to the system message (it depends on the `date` metadata from Part 3.4):

```text
## Conflicting sources
If two documents in the context disagree on a fact:
1. Prefer the document with the more recent date.
2. Say explicitly that the information changed, citing both documents.
3. Never average, blend, or split the difference between conflicting
   facts. Never present a fact from an older document as current
   without noting the newer one.
4. If the conflicting documents have no dates or equal dates, present
   both versions and recommend confirming with support.
```

### Bad vs. good

Context: Source 1 (pricing guide, 2025-04-10): *"Pro costs $10/month."* Source 3 (pricing guide, 2026-05-02): *"Pro costs $12/month."* Question: *"How much is Pro?"*

**Without conflict rules** (typical failures): *"The Pro plan costs $10/month [Source 1]"* (stale — the model happened to anchor on the first chunk), or worse, *"The Pro plan costs $10–12/month"* (a blended fact that appears in no document).

**With conflict rules:**

> The Pro plan currently costs $12/month [Source 3]. Note that this price changed — earlier documentation listed it at $10/month [Source 1].

Correct, current, transparent about the change, and both sources cited — a human can verify the whole chain.

### Why "never blend" needs to be explicit

Blending is the model's natural failure mode under conflict, because generation is a weighted average by construction — when the evidence pulls in two directions, the fluent middle path is a compromise statement. Only an explicit prohibition ("never average, blend, or split the difference") reliably suppresses it. This is the same principle as the Faithfulness Mandate: name the exact failure behavior; don't gesture at accuracy.

### Escalation for irresolvable conflicts

For high-stakes domains (billing, legal, safety), add one more rule: if the conflict affects an action the customer is about to take, set `escalate: true` rather than adjudicating. A conflict between documents is a *data-quality bug* in your corpus; the model's job is to surface it, and your team's job is to fix it at the source.

---

## Key Takeaways

- **Structured output makes answers consumable by code**: a small flat JSON schema with `answer`, `citations`, `fallback_used`, and `escalate` serves the UI, analytics, routing, and verification at once. Use native structured-output APIs when available, and keep format constraints modest so they don't compete with grounding.
- **Citations need an output contract, not a virtue statement**: inline markers for chat, per-claim arrays for verification, verbatim-quote evidence for high stakes — each level enables progressively stronger automated checking, including deterministic invented-source and fabricated-quote detection.
- **Few-shot examples teach what instructions only describe** — and the fallback demonstration is the single highest-value example, because it teaches the behavior the model resists most.
- **Conflicting sources demand explicit rules**: prefer recent, disclose the change, never blend — and escalate when the conflict is high-stakes. Silent arbitrary resolution is the default you are overriding.

**Next:** [Part 6 — Security: Defending the Prompt](06-security.md) — what happens when the text inside your context window is written by an attacker.

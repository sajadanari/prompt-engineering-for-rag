# Part 2 — Architecting the System Message

> **Level:** Beginner → Intermediate
> **What you'll learn:** how to build the control plane of a RAG system — persona, the Faithfulness Mandate, guardrails and fallback behavior, citation rules, scope management, scenario-based instructions, and the craft of writing instructions models actually follow.
> **Prerequisites:** [Part 1 — Foundations](01-foundations.md).

The system message is **Surface 2** from Part 1: the contract that decides whether your model stays grounded in retrieved evidence or drifts into hallucination. This part builds the TechNova system message section by section. By the end, you will have a complete, professional system message — and, more importantly, you will understand why every line of it is there.

---

## 2.1 Persona Assignment

### What it is

The persona defines **who the assistant is**: its role, its domain of expertise, and its tone. It is almost always the first line of the system message.

```text
You are Nova, a customer support assistant for TechNova's NovaVault
cloud backup product. You are precise, friendly, and concise. You write
for non-technical customers and avoid jargon unless the customer uses
it first.
```

### Why it matters in RAG specifically

A persona is not decoration. It does two mechanical jobs:

1. **It narrows the response distribution.** "You are a support assistant for NovaVault" makes product-support phrasings, structures, and levels of detail more probable, and off-topic ramblings less probable — before any other rule is applied.
2. **It anchors scope.** The persona is the natural place from which scope rules (section 2.5) follow. An assistant whose identity is "NovaVault support" has a principled reason to decline a request for medical advice; an unnamed "helpful assistant" does not.

### Bad vs. good

**Weak:**

```text
You are a helpful assistant. Answer the user's questions.
```

*Failure it causes:* the model happily answers questions about competitors' products, gives legal opinions, and adopts whatever tone the user's message suggests. There is no identity to hold behavior in place.

**Strong:**

```text
You are Nova, a customer support assistant for TechNova's NovaVault
cloud backup product.

Your expertise: NovaVault features, plans and pricing, setup,
troubleshooting, and account management.

Your tone: professional and warm. Use short paragraphs. Address the
customer directly. Never blame the customer for a problem.
```

Note the three components: **identity** (name and role), **expertise boundary** (which doubles as a scope anchor), and **tone contract** (specific and testable — "short paragraphs" can be checked; "be nice" cannot).

### Practical tips

- Give the assistant a name if it is customer-facing; it stabilizes voice across turns.
- State expertise as a *list of topics*, not an adjective ("expert-level" adds nothing; "features, pricing, setup, troubleshooting" defines a boundary).
- Put tone rules here, not scattered through the prompt — one home per concern.

---

## 2.2 The Faithfulness Mandate

This is **the single most important instruction block in a RAG system prompt**. Everything else in this article assumes it is in place.

### What it is

The Faithfulness Mandate is an explicit contract that the model answers **only** from the provided context — never from parametric memory. Without it, the model treats retrieved chunks as *inspiration* rather than *evidence*: it blends them with training-data knowledge, fills gaps with plausible inventions, and produces answers that cannot be traced to any source.

### The three components

**1. Source restriction — with load-bearing keywords.**

```text
Answer using ONLY the information contained in the <context> section.
```

The word **ONLY** (and words like "exclusively" or "solely") is load-bearing: it converts a preference into a constraint. Compare the two phrasings that beginners write:

| Phrasing | What the model hears |
|---|---|
| "Use the context to answer" | *"The context is available if helpful"* — parametric memory remains a permitted source |
| "Answer using ONLY the context" | *"Any claim not in the context is a rule violation"* |

**2. Explicit prohibition of speculation.**

```text
Never speculate, extrapolate, or infer beyond what the context
explicitly states.
```

Direct prohibitions of speculation are consistently more effective than soft hedges like "try to be accurate." "Accurate" is a property the model believes its guesses already have; "never speculate beyond the context" names the exact behavior to suppress.

**3. Prohibition of silent fallback to parametric memory.**

```text
If the context does not contain the information needed, do NOT answer
from your own knowledge — even if you believe you know the answer.
```

This clause matters because the model often *does* know the answer (or a stale version of it) from training data. Without this line, a question about NovaVault pricing might be answered with training-data pricing from two years ago — fluent, confident, and wrong. In a RAG system, *an ungrounded correct answer is still a failure*, because it is unverifiable and will silently become wrong when reality changes.

### The assembled mandate

```text
## Grounding rules
- Answer using ONLY the information contained in the <context> section.
- Never speculate, extrapolate, or infer beyond what the context
  explicitly states.
- If the context does not contain the information needed, do NOT answer
  from your own knowledge — even if you believe you know the answer.
  Follow the fallback procedure below instead.
- Treat the context as your complete and only knowledge about NovaVault.
```

### Bad vs. good, end to end

Customer asks: *"What's the maximum file size NovaVault can back up?"* — and the retrieved chunks do not mention a file size limit.

**Without the mandate:** *"NovaVault supports files up to 5 GB in size."* (Fabricated — the model pattern-matched from other backup products in its training data.)

**With the mandate:** *"The documentation provided doesn't specify a maximum file size for backups. I'd recommend contacting TechNova support directly for this detail."* (Honest, grounded, safe.)

### Why vague instructions fail

A useful mental model: the model always takes the **path of least resistance** to a fluent answer. A vague instruction ("try to use the context," "be factual") leaves the fluent-fabrication path open and cheap. The Faithfulness Mandate works by making that path *expensive* — explicitly labeled a violation — and by making the honest path *cheap*, which is the job of the next section.

---

## 2.3 Guardrails and Fallback Behavior

### The key insight: faithfulness needs an exit

Here is the argument beginners miss, and the reason this section exists:

> **A model with no permitted "way out" will invent one.** If your prompt demands grounded answers but never says what to do when the context is insufficient, the model faces two options: break the grounding rule (hallucinate) or produce something that feels like a non-answer (which its training penalized). It will usually hallucinate. **A defined fallback path is therefore a prerequisite for the Faithfulness Mandate to work — not an optional politeness feature.**

Designing fallbacks is designing **graceful degradation**: when retrieval fails, the system's quality should degrade to "honest and unhelpful," never to "confidently wrong" (**confabulation**).

### The canonical fallback instruction

```text
If the answer is not in the provided context, respond:
"I don't have enough information in the documentation to answer that.
You can reach TechNova support at support@technova.example."
Do not apologize excessively. Do not guess.
```

Three design points:

- **Give exact or near-exact wording.** A concrete fallback sentence is far more reliably triggered than "say you don't know," and it keeps the response consistent across thousands of conversations.
- **Give the user a next step** (a support address, a link) — the fallback should end the *model's* answer, not the *user's* journey.
- **Forbid over-apology.** Models pad refusals with paragraphs of apology; a short instruction prevents it.

### One fallback is not enough: the three failure cases

Production systems distinguish three situations that beginners lump together:

```text
## Fallback procedures

1. EMPTY RETRIEVAL — the context section is empty or contains nothing
   related to the question:
   Respond: "I couldn't find anything about this in the NovaVault
   documentation. You can reach TechNova support at
   support@technova.example."

2. PARTIAL COVERAGE — the context answers part of the question:
   Answer the covered part normally (with citations), then state
   explicitly which part the documentation does not cover. Never fill
   the gap with assumptions.

3. OUT OF SCOPE — the question is not about NovaVault at all:
   Follow the scope rules (see Scope section). Do not use the
   "insufficient documentation" fallback for these — it would be
   misleading.
```

The partial-coverage case is the one that separates professional systems from demos. Example — customer asks: *"Does the Pro plan include scheduled backups, and can I back up an external drive?"* The context confirms scheduled backups but says nothing about external drives:

**Good partial answer:**

> Yes — scheduled backups are included in the Pro plan [Source 2]. As for backing up external drives, the documentation I have doesn't cover that; TechNova support at support@technova.example can confirm.

Half an answer plus an honest boundary beats a full answer that is half invented.

---

## 2.4 Citation Rules

### Why citations are not cosmetic

Requiring citations does three jobs at once:

1. **Auditability.** Every claim carries a pointer to its evidence — an *audit trail* a human (or an automated checker, see Part 8) can verify.
2. **Anchoring.** This is the subtle one: forcing per-claim attribution *changes the model's generation behavior*. When every sentence must name its source, the model is continuously pulled back to the chunks — writing an unsupported sentence becomes structurally awkward. Citation is a grounding mechanism, not just a display feature.
3. **User trust.** An answer with sources invites verification; an answer without them demands faith.

### Demand a format, not a virtue

The classic beginner mistake:

```text
Cite your sources.
```

*Failure it causes:* the model appends "(according to the documentation)" to random sentences, or lists all sources at the end regardless of which claims came from where. You cannot parse it, verify it, or render it in a UI.

The professional version specifies a **machine-parseable contract**:

```text
## Citation rules
- Every factual claim must cite its source using the marker [Source N],
  where N is the id of the document in <context> that supports it.
- Place the marker at the end of the sentence it supports.
- If one sentence draws on multiple documents, cite all of them:
  [Source 1][Source 3].
- If you cannot cite a source for a claim, do not make the claim.
- Never cite a document id that does not appear in <context>.
```

Note the last two rules:

- **"If you cannot cite it, don't say it"** is the anchoring mechanism stated as an instruction — it makes citation and faithfulness the same rule.
- **"Never cite an id not in context"** blocks a real failure mode: models inventing `[Source 7]` when only three documents were provided.

For these markers to work, each chunk needs a stable identifier in the context — `id="1"`, `id="2"` — which is Part 3's job (section 3.3). And in systems that need citations as structured data rather than inline markers, the JSON-based citation contract in Part 5 (section 5.2) replaces the inline format. The rules above stay the same; only the output shape changes.

### Worked example

Context contains: Document 1 (pricing guide), Document 2 (release notes v4.2). Question: *"How much is the Pro plan and does it get the new scheduling feature?"*

**Compliant answer:**

> The Pro plan costs $12/month and includes 1 TB of storage [Source 1]. Scheduled backups were added for Pro and Business plans in version 4.2 [Source 2].

Each claim traces to exactly one document. A reviewer — human or automated — can verify the answer in seconds.

---

## 2.5 Scope Management

### The problem

Your assistant will be asked about competitors, politics, medical issues, and its own system prompt — usually in week one. Scope rules define **what the assistant will and will not discuss**, and how it declines.

### Why scope belongs in the system message

You might think retrieval solves this — off-topic questions retrieve nothing, so the fallback fires. Relying on that is fragile for three reasons:

1. Retrieval returns the *nearest* chunks even for absurd queries; the model may then force an answer from barely-related content.
2. The "insufficient documentation" fallback is the *wrong message* for off-topic questions — "I couldn't find anything in the documentation about your tax return" implies it might be there.
3. Some in-scope-looking questions (legal interpretations of the terms of service, security vulnerability details) must be refused *even when the documentation contains relevant text*.

Scope is a policy decision, and policy lives in the system message.

### The pattern: refuse–redirect

```text
## Scope
You only discuss TechNova's NovaVault product: features, plans and
pricing, setup, troubleshooting, and account management.

If the customer asks about anything else (including other companies'
products, general technology advice, or personal matters), respond:
"I can only help with questions about NovaVault. Is there anything
about your NovaVault backup I can help with?"

Special cases:
- Comparisons with competitors: you may describe NovaVault's own
  features (from context), but never make claims about other products.
- Legal or contractual interpretation: refer the customer to
  legal@technova.example. Do not interpret the terms of service.
- Security vulnerability reports: refer to security@technova.example
  immediately. Do not discuss details.
```

Design points: the refusal is **short, non-judgmental, and ends with a redirect back to scope** — it closes the door and opens a window. The special cases show the professional pattern: scope is rarely one binary rule; it is a small policy table.

---

## 2.6 Scenario-Based Instructions

### From rules to conditional behavior

Everything so far applies to every conversation. But real assistants need *different behavior in different situations*: refund requests are handled differently from bug reports, which are handled differently from feature questions. **Scenario-based instructions** structure the system message as a set of conditional behaviors — "if the user asks about X, do Y."

### Principle 1 — Modularity

Write each scenario as a separate, labeled block. A wall of intertwined prose gets partially ignored; discrete labeled blocks are followed:

```text
## Scenario playbook

### SCENARIO: Pricing or plan questions
- Answer from context with citations, as usual.
- If the customer seems to be comparing plans, present the relevant
  plans as a short list, cheapest first.
- Never offer discounts or make pricing commitments not in the context.

### SCENARIO: Bug reports or technical failures
- Express brief empathy (one sentence, no more).
- Collect: NovaVault version, operating system, exact error message.
- If the context contains a matching troubleshooting article, walk the
  customer through it step by step.
- If not, or if the steps fail, escalate (see Escalation).

### SCENARIO: Refund or cancellation requests
- Do NOT attempt to talk the customer out of it.
- State the refund policy from context, with citation.
- Escalate to a human agent for the actual processing (see Escalation).

### SCENARIO: Angry or distressed customer
- Acknowledge the frustration in one sentence.
- Do not match the customer's tone. Stay calm and concrete.
- Prioritize the fastest path to resolution, escalating early if needed.
```

### Principle 2 — Explicit priority and conflict resolution

Scenarios overlap: an *angry customer reporting a bug* triggers two blocks at once. Without a precedence rule, behavior is undefined. State one:

```text
## Priority order
If multiple scenarios apply, or any instructions conflict:
1. Safety and security rules always take precedence.
2. Grounding rules (answer only from context) are never suspended
   by any scenario.
3. The "angry or distressed customer" tone guidance applies on top of
   whatever scenario handles the content of the request.
4. If still ambiguous, prefer the more cautious behavior and offer
   escalation.
```

Rule 2 deserves a highlight: **no scenario ever suspends the Faithfulness Mandate.** Empathy changes tone, not evidence requirements.

### Principle 3 — Escalation paths

Every scenario playbook needs an exit to a human:

```text
### Escalation
Escalate to a human agent when: the customer explicitly asks for a
human; a refund/cancellation needs processing; troubleshooting from
context has failed; or the customer reports data loss.
To escalate, respond: "I'm connecting you with a TechNova support
specialist who can take this further." and emit the tag
<escalate reason="..."/> at the end of your reply.
```

(The machine-readable tag lets the surrounding application detect the escalation — a preview of structured output, Part 5.)

### Principle 4 — Respect the token budget

Every scenario block consumes context-window space in **every single request**, whether or not the scenario fires. Two disciplines keep the playbook affordable:

- **Compress ruthlessly.** Bullet fragments, not paragraphs. "One sentence of empathy, no more" is seven words that replace a paragraph of tone coaching.
- **Cut scenarios that never fire.** Review production logs; if a scenario has not triggered in months, its tokens are better spent on retrieved context.

A system message that grows unboundedly eventually crowds out the very evidence the model needs — and long prompts also dilute attention on the rules themselves.

---

## 2.7 The Craft of Instruction Writing

The previous sections gave you *what* to say. This section is about *how to phrase it* — cross-cutting principles that come directly from the official prompting guidance published by OpenAI and Anthropic, and that apply to every block above.

### Imperative, unambiguous, one instruction per sentence

Write commands, not descriptions or wishes:

| Weak | Strong |
|---|---|
| "It would be good to keep answers short." | "Keep answers under 150 words." |
| "The assistant should generally try to cite sources when it seems appropriate." | "Cite every factual claim as [Source N]." |
| "Ideally avoid technical language, being mindful of the audience." | "Avoid jargon. If a technical term is unavoidable, define it in one clause." |

Each strong version is imperative (a command), specific (testable), and atomic (one behavior per sentence). Sentences that bundle three behaviors get partially followed.

### Prefer positive framing — tell the model what to do

Instructions that name the desired behavior outperform instructions that only name the forbidden one. A "don't" leaves the model searching for an alternative; a "do" hands it one:

| Negative only | Positive (better) |
|---|---|
| "Don't be verbose." | "Answer in at most three short paragraphs." |
| "Don't use markdown tables." | "Format lists as bullet points." |
| "Don't answer from your own knowledge." | "Answer using ONLY the context. If it's not in the context, use the fallback response." |

Notice the third row: we did not *remove* the prohibition (the Faithfulness Mandate keeps its "never" clauses — prohibitions are appropriate for behaviors that must be suppressed), we *paired* it with the positive alternative. Prohibition plus alternative is the most robust combination.

### Make constraints explicit — length, format, tone

Every implied constraint is a constraint the model will sometimes ignore. Say it:

```text
## Response format
- Length: at most 3 short paragraphs, or a list of at most 6 bullets.
- Formatting: plain text with bullet lists where helpful. No headers.
- Language: reply in the language the customer used.
- Always end with: "Is there anything else about NovaVault I can help
  with?" unless you are escalating.
```

### Separate instruction blocks structurally

Use Markdown headers (`## Grounding rules`) or XML tags (`<grounding_rules>`) to give each concern its own labeled home, as every example in this part has done. Structure helps twice: the model reliably distinguishes rule categories (and you can *reference* them — "see Escalation"), and you can edit one block without re-reading the whole prompt. Anthropic's guidance explicitly recommends XML-tagged structure for Claude; OpenAI's guidance recommends clear delimiters; Markdown headers work well across all vendors.

### The golden rule

Before shipping any instruction, apply this test:

> **If a competent human contractor — new to your company, with no chance to ask questions — could not follow the instruction unambiguously, neither will the model.**

"Be helpful but appropriately cautious" fails the contractor test (cautious how? about what?). "State the refund policy with a citation, then escalate for processing" passes it. When a prompt misbehaves, the first debugging step is to reread the relevant instruction as a literal-minded contractor would — the ambiguity you find is usually the bug.

---

## The Assembled TechNova System Message (v1)

Everything from this part, in one block. This is the system message we will *extend* in later parts (context structure in Part 3, few-shot examples in Part 5, injection defense in Part 6) and assemble finally in Part 10:

```text
You are Nova, a customer support assistant for TechNova's NovaVault
cloud backup product.
Your expertise: NovaVault features, plans and pricing, setup,
troubleshooting, and account management.
Your tone: professional and warm. Short paragraphs. Address the
customer directly. Never blame the customer.

## Grounding rules
- Answer using ONLY the information contained in the <context> section.
- Never speculate, extrapolate, or infer beyond what the context
  explicitly states.
- If the context does not contain the information needed, do NOT answer
  from your own knowledge — even if you believe you know the answer.
  Follow the fallback procedures instead.
- Treat the context as your complete and only knowledge about NovaVault.

## Citation rules
- Every factual claim must cite its source as [Source N], at the end of
  the sentence it supports.
- Multiple supporting documents: cite all, e.g. [Source 1][Source 3].
- If you cannot cite a source for a claim, do not make the claim.
- Never cite a document id that does not appear in <context>.

## Fallback procedures
1. Empty retrieval: respond "I couldn't find anything about this in the
   NovaVault documentation. You can reach TechNova support at
   support@technova.example."
2. Partial coverage: answer the covered part with citations, then state
   explicitly what the documentation does not cover. Never fill gaps.
3. Out of scope: follow the Scope rules below.

## Scope
You only discuss NovaVault. For anything else, respond: "I can only
help with questions about NovaVault. Is there anything about your
NovaVault backup I can help with?"
- Competitor comparisons: describe only NovaVault's features, from
  context. No claims about other products.
- Legal/contractual interpretation: refer to legal@technova.example.
- Security vulnerability reports: refer to security@technova.example.

## Scenario playbook
### Pricing or plan questions
Answer from context with citations. Present plan comparisons as a short
list, cheapest first. Never offer discounts or commitments not in
context.
### Bug reports
One sentence of empathy. Collect: version, OS, exact error message.
Walk through matching troubleshooting steps from context; otherwise
escalate.
### Refunds or cancellations
Do not argue. State the refund policy from context with citation.
Escalate for processing.
### Angry or distressed customer
Acknowledge frustration in one sentence. Stay calm and concrete.
Escalate early if needed.

## Priority order
1. Safety and security rules take precedence over everything.
2. Grounding rules are never suspended by any scenario.
3. Tone guidance stacks on top of content scenarios.
4. If ambiguous, choose the more cautious behavior and offer escalation.

## Escalation
Escalate when: customer asks for a human; refund needs processing;
troubleshooting failed; data loss is reported.
Respond: "I'm connecting you with a TechNova support specialist who can
take this further." and emit <escalate reason="..."/>.

## Response format
- At most 3 short paragraphs or 6 bullets.
- Plain text with bullets. No headers.
- Reply in the customer's language.
- End with "Is there anything else about NovaVault I can help with?"
  unless escalating.
```

---

## Key Takeaways

- The **persona** (identity + expertise boundary + tone contract) narrows behavior before any rule is applied.
- The **Faithfulness Mandate** — ONLY-from-context, no speculation, no silent parametric fallback — is the core of the system message; vague phrasings like "try to use the context" do not constrain anything.
- **Fallback behavior is a prerequisite for faithfulness**: a model with no honest exit will invent one. Define exact fallback wording for empty retrieval, partial coverage, and out-of-scope questions separately.
- **Citations need a format, not a virtue**: machine-parseable markers, "no citation → no claim," anchoring as a side effect.
- **Scope is policy** and lives in the system message, not in the retriever's behavior.
- **Scenario blocks** give conditional behavior; give them explicit priority rules (grounding is never suspended), escalation exits, and a token budget.
- Write instructions **imperatively, positively, one per sentence, structurally separated** — and test each against the contractor rule.

**Next:** [Part 3 — Context Injection](03-context-injection.md), where we engineer the other half of the prompt: how the retrieved chunks themselves are structured, identified, enriched, and ordered.

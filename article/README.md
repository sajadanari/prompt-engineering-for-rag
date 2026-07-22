# Prompt Engineering for RAG — From Zero to Expert

A complete, practical guide to prompt engineering for Retrieval-Augmented Generation (RAG) systems. It takes a reader with no RAG background to the level of designing, hardening, and measuring production-grade RAG prompts — with copy-pasteable examples in every section and one running example (the **TechNova / NovaVault** support assistant) built up across all parts and completed in the capstone.

Grounded in verified primary sources: OpenAI and Anthropic official prompting documentation, Anthropic's Contextual Retrieval, the OWASP RAG Security Cheat Sheet and LLM Top 10, the RAGAS paper, and peer-reviewed research (*Lost in the Middle*, HyDE, Step-Back, Self-RAG, CRAG). Full bibliography in [Part 9](09-production-playbook.md#94-references-and-further-reading).

---

## Reading Order

Read in order for the beginner-to-expert path; each part builds on the previous ones.

| # | Part | Level | What it covers |
|---|---|---|---|
| 1 | [Foundations](01-foundations.md) | Beginner | What RAG is, why RAG prompting is its own discipline, the four blocks of a RAG prompt, the three prompt surfaces |
| 2 | [Architecting the System Message](02-system-message.md) | Beginner → Intermediate | Persona, the Faithfulness Mandate, guardrails and fallbacks, citation rules, scope, scenario playbooks, instruction-writing craft |
| 3 | [Context Injection](03-context-injection.md) | Beginner → Intermediate | XML structuring, Lost in the Middle and smart ordering, source identifiers, metadata enrichment, Contextual Retrieval |
| 4 | [Query-Side Prompt Engineering](04-query-side-prompting.md) | Intermediate | Query rewriting, HyDE, step-back, decomposition and multi-query, self-query filters, a technique decision table |
| 5 | [Output Control](05-output-control.md) | Intermediate | Structured JSON output, machine-parseable citation contracts, few-shot grounding examples, conflicting sources |
| 6 | [Security: Defending the Prompt](06-security.md) | Intermediate → Advanced | Direct and indirect prompt injection (OWASP LLM01), attack vectors, prompt-level defenses and their limits, defense in depth, prompt leakage |
| 7 | [Advanced Architectures](07-advanced-architectures.md) | Advanced | Agentic RAG, Self-RAG/CRAG reflection checkpoints, multi-turn RAG, token budgets and prompt caching, per-vendor tuning |
| 8 | [Evaluation and Iteration](08-evaluation.md) | Advanced | The eval loop, RAGAS metrics and failure localization, LLM-as-judge biases, prompts-as-code |
| 9 | [Production Playbook](09-production-playbook.md) | Reference | Three annotated master templates, symptom → fix diagnostic table, shipping checklist, bibliography |
| 10 | [Capstone Walkthrough](10-capstone-walkthrough.md) | All | The whole article applied end to end: a production RAG prompt built step by step from a blank file, with every decision narrated |

**Shortcuts for non-linear readers:**
- *"I need a working prompt today"* → [Part 9 templates](09-production-playbook.md#91-complete-annotated-templates), then the [capstone](10-capstone-walkthrough.md) to understand what you copied.
- *"My RAG system misbehaves"* → the [diagnostic table](09-production-playbook.md#92-common-failure-modes-and-fixes), which routes every symptom to its explaining section.
- *"Am I ready to ship?"* → the [checklist](09-production-playbook.md#93-the-rag-prompt-engineering-checklist).

---

## The One-Paragraph Summary

RAG prompt engineering governs how a model behaves in the presence of **injected, machine-selected, untrusted** context: the retrieved text must be the model's only source of truth, yet never a source of instructions. In practice this means a system message built around a **Faithfulness Mandate with a defined fallback exit**, machine-parseable **citations** bound to uniquely identified, metadata-enriched, deliberately ordered chunks, **query-side prompts** that fix retrieval before generation can fail, **structured output** that code can verify, **layered injection defenses** that are honest about their limits, and an **evaluation loop** that treats every prompt change as a code change. Each of those clauses is one part of this guide.

---

## Companion Files

- [`../TABLE_OF_CONTENTS.md`](../TABLE_OF_CONTENTS.md) — the annotated outline this article was written from
- [`../ROADMAP.md`](../ROADMAP.md) — the phased writing plan and source-verification errata

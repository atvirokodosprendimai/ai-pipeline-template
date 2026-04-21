# Commercial Idle Policy

Use this policy when the delivery pipeline is idle or nearly idle.

## Objective

Primary objective: increase the probability of getting the first paying external customer for cloudroof.eu.

Current reality: the product already works internally. The main bottleneck is no longer "can we build it?" but "can an external user understand it, try it, trust it, and pay for it?"

Long-term objective: build a repeatable path from first customer to $100K ARR.

## Idle work rule

When the delivery pipeline is idle, do **not** optimize the pipeline itself unless pipeline failure directly blocks customer progress.

Instead, select the **single highest-leverage 2–4 hour task** that most increases the probability of getting the first paying external customer.

## Task selection priority

Choose work in this order:

1. **Proof of value**
   - capture concrete usage evidence
   - turn reliability into proof points
   - document specific outcomes, not vague claims

2. **Offer clarity**
   - clarify who cloudroof.eu is for
   - define the painful problem it solves
   - explain why it is better than current alternatives
   - sharpen pilot/pricing/CTA framing

3. **Time-to-first-value**
   - quickstart
   - install path
   - evaluation checklist
   - demo path
   - onboarding docs

4. **Distribution**
   - landing page positioning
   - outreach copy
   - target-account list
   - case-study material

5. **Customer delivery readiness**
   - reliability fixes that block real usage
   - observability needed for pilots
   - support or onboarding runbooks

6. **Internal tooling**
   - only if it directly unlocks one of the above

## Avoid by default

Do not choose these unless they unblock a customer-facing outcome:

- speculative platform work
- architecture cleanup without customer pull
- internal dashboard polish
- generic refactors
- abstract framework improvements
- features with no clear path to first-customer progress

## 2–4 hour task quality bar

A good idle task must:

- fit inside 2–4 hours
- produce a concrete artifact
- reduce a real bottleneck
- be reviewable asynchronously
- avoid hidden dependencies where possible

Preferred artifacts:

- landing page copy
- quickstart or install guide
- proof-of-value note
- case study draft
- pilot or pricing page draft
- demo script
- outreach message pack
- evaluation checklist
- onboarding checklist
- reliability fix tied to real usage

## Decision rule

If several tasks are plausible, rank them by:

- customer impact × 3
- evidence gained × 2
- speed to artifact × 2
- reversibility × 1
- effort × -1
- dependency risk × -2

Pick the highest-scoring task.

## Output format

Return JSON only:

```json
{
  "current_bottleneck": "Why first-customer progress is blocked right now",
  "best_2_to_4h_task": "Single recommended task",
  "why_now": "Why this task is highest leverage right now",
  "artifact": "Concrete deliverable that will exist after 2-4 hours",
  "done_when": [
    "Condition 1",
    "Condition 2"
  ],
  "why_not_other_tasks": [
    "Why this beats pipeline polish",
    "Why this beats generic refactor"
  ]
}
```

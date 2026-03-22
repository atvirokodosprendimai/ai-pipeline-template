---
name: block-manual-pr-merge
enabled: true
event: bash
pattern: ^\s*gh\s+pr\s+merge\b
action: block
---

**BLOCKED: Manual PR merge detected**

You must not merge PRs manually. All merges go through `company/scripts/pr-review-merge.sh` which enforces Copilot review + guardrails.

This rule exists because you repeatedly merged PRs before review comments were addressed (PR #70, #73, #74).

**What to do instead:**
- Let the workflow call `bash company/scripts/pr-review-merge.sh`
- The script polls for review, checks guardrails, and merges only when safe

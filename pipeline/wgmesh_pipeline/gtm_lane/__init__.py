"""GTM-execution lane — drains the surface:service decision queue by dispatching
approved low-risk GTM jobs to a rented-human provider, verifying the returned
work fail-closed, and closing the item.

See docs/plans/2026-06-25-001-feat-gtm-rent-a-human-executor-plan.md.
"""

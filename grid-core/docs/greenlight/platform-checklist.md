# Platform checklist — required-vs-missing asset spec (draft)

> The requirements matrix feeding **GL-15** (per-platform required-vs-missing asset checklist).
> Requirements become `rulebook.json` entries keyed by platform — data, not code.
>
> **This sheet is the draft, not the source of truth.** Confirm the requirements with the media
> team before lifting anything into `rulebook.json`.

Evaluation inputs, per GL-15: the manifest's **code-measured** media metadata (never
filename-derived dimensions) plus the extraction. A platform on the plan with zero materials
renders as missing-everything, not absent; missing items feed findings so they surface in
`report.md` and chase drafts.

## LinkedIn Ads

**Required assets:** lead-gen form sheet (copy approved) · Insight Tag implementation sheet with
test confirmed · statics 1200x1200 (v1..vN) · TAL audience CSVs where targeted · UTMs on ad
destinations.

**Naming / rules:** campaign/ad-set naming carries geo + month tokens; daily budget ≥ $10/day
floor per rulebook.

**Notes (grounded in the NEL dump):** DC Charging LGF workbook,
`Insight_Tag_Implementation.xlsx` (test unconfirmed = Live-stage flag), 3 static versions,
2 persona TAL CSVs.

## The Trade Desk

**Required assets:** creative bulk-upload sheet · statics per geo at 300x600 + 320x100 · UTM
links doc · approval recorded on the content tracker.

**Naming / rules:** ad-group naming carries tactic + market; geo id prefixes consistent (NZ must
not carry AU ids).

**Notes (grounded in the NEL dump):** `TTD_Creative_Bulk_Upload.xlsx` plus AU/NZ renamed statics;
the NZ-carries-AU-ids case is a real screenshot finding.

## Meta

**Required assets:** statics/videos per placement ratio · copy sheet approved · pixel/CAPI where
the objective needs it.

**Naming / rules:** campaign naming resolves the client slug unambiguously (2–3 char keys are
substring-fragile).

**Notes:** requirements to be confirmed with the media team; geocon-family clients are the
template.

## DV360

**Required assets:** creatives per size matrix · floodlight where needed.

**Naming / rules:** advertiser naming resolves; country parse from names where no geo column.

**Notes:** the read-side probe cannot verify data without running a Bid Manager query (a write) —
treat as **warn**.

## GA4 / Web

**Required assets:** property id supplied · key events defined · insight/site tags verified.

**Naming / rules:** UTM month tokens consistent; source/medium map per rulebook
`platform_source_map`.

**Notes:** a missing property id is the most common blocker across clients — render it as its own
reason.

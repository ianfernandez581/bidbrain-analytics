# client_STT — intake / pre-build notes

**Client:** STT GDC (ST Telemedia Global Data Centres) · **Agency:** Transmission
**Campaign:** Always On — SOW 2 · FY25-26 (Jun 2025 → May 2026) · plan currency **SGD**
**Status:** _On hold — waiting on Transmission to confirm scope (see message below). Data is already flowing; no build started yet._

---

## Verdict

The data we need is **already in `raw_snowflake`** for every channel the media plan uses. We are
**not** blocked on missing account names / campaign IDs — those exist. What's outstanding is a set of
**scoping decisions** only Transmission/the client can confirm before we build the per-client filter views.

The dashboard follows the `client_mongodb` template: filter each shared raw table by the STT
identifier, then derive market/phase/objective from the campaign-name convention.

## What the plan uses vs. what we found

| Plan channel | Raw table | STT identifier(s) | Coverage |
|---|---|---|---|
| Search | `raw_snowflake.google_ads_apac` | `STT (USD)` (acct 1641370256) → `STT GDC_SGD` (acct 4825242697) | Jun 2025 → May 2026 |
| Social / Awareness + Lead Gen | `raw_snowflake.linkedin_ads_apac` | `APAC - STT GDC - SGD ` (acct 515691430, **note trailing space**) → `STTGDC_TransmissionSG_USD` (acct 511609128) | Jun 2025 → Jun 2026 |
| Programmatic Display | `raw_snowflake.dv360_apac` | `APAC \| STT GDC - SGD` (adv 7572338345) → `APAC \| STTelemdia GDC` (adv 6466367438) | Jun 2025 → May 2026 |

Resolved by the data (no need to ask):
- **TradeDesk** has no STT rows (only Cloudflare/HireRight/MongoDB/PropTrack/Schneider) → programmatic = **DV360 only**.
- **Salesforce CS leads** table (`salesforce_cs_apac_all`) has **zero** STT rows → that feed is MongoDB-specific, not STT's lead source.

Campaign-naming notes for modelling later:
- Google Ads encodes market + phase: `1663_GAW_STT_FY25Q2_AlwaysOn26_<MARKET>_Keywords_Awareness_...`, plus `FY26Q1` and `DemandNurture` phases. Markets: SG, MY, IN, PH, ID, TH, VN, JP, KR (+ "JP local").
- LinkedIn carries Awareness vs. LeadGen and per-market DemandNurture campaigns; naming is inconsistent (`PO1663_ST Telemedia GDC_...`, `POTBC_STT GDC_...`, generic `PO1626_Client_...`). Some FY24 / "Organic Boosting" activity present — may be out of SOW 2 scope.
- DV360 does **not** encode market in the campaign name — market lives in `COUNTRY_NAME` / insertion order.

## Open questions for Transmission (the real gaps)

1. **Dual account / currency** — each platform flips from a USD account (Jun–Aug 2025) to an SGD account (Sep 2025 on), looks like a mid-campaign billing migration. Confirm both are in scope, the reporting currency (SGD?), and the FX rate for the USD period.
2. **SOW 2 boundary** — which POs/campaigns are SOW 2 vs. SOW 1 / organic? (LinkedIn USD account has older FY24 + PO1626 "Organic Boosting".)
3. **Leads / conversions source** — platform-native (LinkedIn lead forms + Google conversions) or a CRM/Salesforce export we'd need access to?
4. **"Data Center Map" USA line** (~US$25k, USA-targeted) — in scope for this APAC dashboard, and does it sit in DV360?
5. **Targets** — confirm this PDF is the final approved plan; ideally send the source spreadsheet so we don't OCR the PDF.

---

## Message to Transmission (ready to send)

> **Subject: STT GDC dashboard — a few confirmations before we build**
>
> Hi team,
>
> We're setting up the reporting dashboard for STT GDC against the FY25-26 Always On (SOW 2) media plan. The platform data is all flowing in (Google Ads, LinkedIn, DV360), so we're close — just need you to confirm a few things so we slice it correctly:
>
> 1. **Accounts & currency** — we see each platform move from a USD account to an SGD account around Sept 2025 (Google Ads `STT (USD)` → `STT GDC_SGD`; LinkedIn `STTGDC_TransmissionSG_USD` → `APAC - STT GDC - SGD`; DV360 `APAC | STTelemdia GDC` → `APAC | STT GDC - SGD`). Can you confirm both belong to this campaign, what reporting currency you want (SGD?), and the FX rate we should apply to the USD period?
> 2. **SOW 2 scope** — which POs/campaigns count as SOW 2? We're seeing some older FY24 and "Organic Boosting" (PO1626) activity on the LinkedIn account that may be out of scope.
> 3. **Programmatic** — we can confirm programmatic ran on DV360 (no Trade Desk activity for STT). Correct?
> 4. **Leads / conversions** — where should reported leads come from: LinkedIn lead-gen forms + Google Ads conversions, or is there a CRM/Salesforce export you can share access to?
> 5. **"Data Center Map" (USA-targeted, ~US$25k)** — is that line part of this dashboard, and does it sit in DV360?
> 6. **Targets** — can you send the final approved media plan as a spreadsheet? We'll drive the budget/impression/CPC/CPM targets from it.
>
> Once we have these, the dashboard is straightforward to stand up. Thanks!

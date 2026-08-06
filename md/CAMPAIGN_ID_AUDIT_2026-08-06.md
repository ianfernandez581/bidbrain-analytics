# Campaign / Ad Group ID Audit - Codebase vs Media-Team Reference Sheet

**Date:** 2026-08-06
**Reference:** `Campaign_AdGroup_Reference_LinkedIn_TTD.xlsx` (generated 2026-08-04 by the media buying team)
**Codebase:** `bidbrain-analytics` monorepo (all clients, ingest, platform, status pipeline - 1,057 text/config/code files scanned)

## Reference file contents

| Tab | Rows | Unique campaign IDs | Unique ad set / ad group IDs | Accounts covered |
|---|---|---|---|---|
| LinkedIn | 109 | 35 | 109 | STT GDC, Cloudflare APAC, MongoDB Inc., PropTrack, Schneider Electric |
| TTD | 195 | 54 | 195 | Cloudflare, MongoDB (+ Schneider & PropTrack rows with blank Account) |
| Google Ads | 115 | 28 | 115 | Cloudflare (JP YouTube) + Schneider (Search/AET/MEA, blank Account) |

536 unique IDs in total. Many TTD and all Schneider/PropTrack-TTD and most Google Ads rows have a **blank Account cell** (expected, per the export); where blank, the client attribution below is inferred from the campaign name / brief-number prefix.

## TL;DR

1. **No wrong-client mappings found.** Every ID that exists in both the codebase and the reference agrees on account and campaign name (14 IDs checked, listed in Section 3).
2. **MongoDB's scope-pin seed is in perfect sync with the sheet**: all 8 TTD + 2 LinkedIn campaign IDs in `clients/client_mongodb/targets/campaign_ids.csv` are in the reference, and the reference contains no MongoDB campaign that isn't seeded. Zero stale, zero missing.
3. **Almost all other reference IDs are absent from the codebase - and that is by design, not rot.** Only MongoDB pins scope to per-campaign IDs. Every other dashboard filters at the account/advertiser level or by name tokens (details in Section 2), so the 103 campaign IDs and 419 ad set/ad group IDs "missing" from the codebase are not gaps in those pipelines.
4. **No live code or config keys on ad-group/ad-set IDs anywhere** (LinkedIn ad sets, TTD ad groups, Google Ads ad groups). Ad-group-level splits are parsed from *names* in staging SQL, never keyed by ID. The only ad-group-level IDs in the repo at all sit inside two **binary intake snapshots** under `clients/client_schneiderlqai/raw_files/` - and every one of them (17 campaigns, 6 LinkedIn ad sets, 58 TTD ad groups) matches the reference exactly.
5. **Real follow-ups found** (Section 4): the Caltex TTD campaign is missing from the reference sheet; the Cloudflare JP YouTube Google Ads campaign in the sheet is documented in our repo as absent from all our raw feeds; the sheet lists Schneider liquid-cooling **Search** campaigns while the LQAI dashboard still treats Search as planned-not-live; Schneider EntIT TTD campaigns remain intentionally excluded everywhere.

---

## 1. IDs in the codebase but NOT in the reference file

None of these look stale or wrong - they fall into two classes the reference sheet simply does not cover.

### 1a. Campaign/advertiser/pixel IDs for clients or platforms outside the sheet's scope

| ID | Type | Client | Where | Why it's not in the sheet |
|---|---|---|---|---|
| `85k1vmm` | TTD campaign | caltex | [clients/client_caltex/README.md](clients/client_caltex/README.md), sql, lineage | Caltex (100% Digital seat, advertiser `0lw3hp6`) isn't in the TTD export - **ask the media team to add it** |
| `0lw3hp6` | TTD advertiser | caltex | sql scope filter, pixel snippets | Advertiser-level ID; sheet has no advertiser column |
| `z3eu6oa`, `7y9naeh`, `8za7r9n`, `4tyuvnj` | TTD universal pixels | caltex | [clients/client_caltex/README.md](clients/client_caltex/README.md) | Pixel IDs, out of the sheet's scope |
| `9c1w83i` | TTD advertiser | mongodb | [clients/client_mongodb/sql/11_stg_tradedesk_pixel.sql](clients/client_mongodb/sql/11_stg_tradedesk_pixel.sql) | Advertiser-level pixel scope filter, not a campaign |
| `mor6pp1` | TTD advertiser | tlm | [clients/client_tlm/README.md](clients/client_tlm/README.md) | TLM isn't in the TTD export; advertiser-level anyway |
| `ekse5e8` / `951901366` | TTD + LinkedIn campaigns | schneiderlqai | [clients/client_schneiderlqai/INTAKE.md](clients/client_schneiderlqai/INTAKE.md) (prose only; the SQL scopes on the `%LQAIDC%` name substring) | These two ARE in the reference - listed here only to note the dashboards don't key on them |

### 1b. Account-level numeric IDs (different ID class - never expected in a campaign/ad-group sheet)

Google Ads **customer IDs** (`2617916504` City Perfume, `1054407474` ResetData, `1869745895` TLM, `5196596415`, `8509313407`, MCC `3451896252`) in [ingest/dts_data_pull/sql/perf_google_ads.sql](ingest/dts_data_pull/sql/perf_google_ads.sql); LinkedIn **account IDs** (`515691430`/`511609128` STT, `517045062` Schneider, `510177932`, `516746102` ResetData, `502299829` broken Windsor MongoDB connector); DV360 **advertiser IDs** (`7572338345`/`6466367438` STT); GA4 **property IDs** (`318963196`, `516276493`, `287370621`). All verified as account/property scoping, not campaign references - no action.

**Out of scope, confirmed untouched:** Salesforce campaign IDs (`701...`) in `clients/client_cloudflare/definitions.json`, `clients/client_schneider/data/media_plan.csv` and the mongodb/schneider CS lanes - the reference covers ad platforms only. Schneider's `internal_campaign_id` values (`eba`, `heavy`, ...) are internal slugs, not platform IDs.

---

## 2. IDs in the reference file but NOT in the codebase

**Campaign level: 103 of 117 reference campaign IDs are absent from the codebase** (full lists in the Appendix; the 14 present are in Section 3). **Ad set / ad group level: none of the 419 appear in any code or config** (64 of them - the Schneider LQAI-era LinkedIn ad sets and TTD ad groups - do sit inside the binary intake snapshots noted below, fully consistent with the reference). Before treating any of this as a defect, note how each pipeline scopes its data:

| Client | How the pipeline scopes delivery | Reference campaign IDs absent | Verdict |
|---|---|---|---|
| **mongodb** | **Per-campaign ID seed** (`targets/campaign_ids.csv`, INNER JOIN scope pin) | **0 of 10** | **In sync - nothing to do** |
| cloudflare | Account (`ACCOUNT_NAME = 'Cloudflare APAC'` / `ADVERTISER_NAME = 'Cloudflare'`) + normalised name parsing; single-campaign dashes key on exact `CAMPAIGN_GROUP_NAME` | 9 LinkedIn + 28 TTD (+ its 1 Google Ads campaign appears in README prose only) | By design (no ID seed). The Q3 `2479_` campaigns flow in via name parsing already |
| schneider | `campaign_map` name-token matching (`STRPOS`), account 517045062 | 16 LinkedIn + 15 TTD + ~27 Google Ads | By design. Google Ads: **no Schneider dashboard has a Google Ads lane at all** - see Section 4 |
| schneiderlqai | `%LQAIDC%` name substring | (its 2 campaign IDs appear in INTAKE.md prose) | By design |
| stt | LinkedIn `ACCOUNT_ID IN ('515691430','511609128')` | 4 LinkedIn | By design |
| proptrack | TTD advertiser name `PopTrack`, LinkedIn account `PropTrack_TransmissionSG_AUD` | 2 LinkedIn + 2 TTD | By design |

Ad-group/ad-set IDs: no dashboard keys on them anywhere - ad-group splits (market, tactic, country) are parsed from **names** in staging SQL. Since TTD ad group names aren't even in the platform export, keeping those IDs in the repo would add nothing today. If the team ever wants ID-level pinning below campaign level (the mongodb model), this sheet is the seed source.

**Binary intake snapshots verified separately:** `clients/client_schneiderlqai/raw_files/SCHNEIDER LQAI LINKEDIN CAMPAIGN IDS.xlsx` (campaign `951901366` + 6 country ad sets `849331486`/`849341616`/`849381656`/`849411616`/`849411646`/`849470916`) and `...TRADEDESK CAMPAIGN IDS.xlsx` (actually a **full Schneider TTD export**: 16 campaigns incl. EntIT/NEL/EBA/WaterEnv/EcoStruxure/AirSeT/IndEdge, 58 ad groups) - **100% of their IDs are in the reference, zero conflicts**. Side note for the media team: that TTD export DOES carry an Ad Group Name column, so ad-group names for Schneider TTD exist even though the reference sheet marks them "(not provided in TTD export)".

Sanity check on the sample IDs from the task brief: `de6m2ub` (Cloudflare DOOH campaign), `5h8f56n` (its ad group), `830201396` (STT Organic Boosting LinkedIn campaign), `22872037438` (`1130_MEA_Finance #2` Google Ads) are all in the reference and none appears anywhere in the codebase - each falls under a by-design account/name-scoped pipeline above.

---

## 3. Cross-mapping check - every overlapping ID agrees

All 14 IDs present in both places map to the same account and campaign name (no wrong-client, no wrong-name):

| ID | Platform | Codebase says | Reference says | Match |
|---|---|---|---|---|
| `4l7ib47` | TTD | mongodb, IDC ANZ | MongoDB, `2265_MONGODB_2026-Q2_IDC_APJ_DEMAND-GENERATION_ANZ` | OK |
| `baz7v1b` | TTD | mongodb, IDC ASEAN | MongoDB, `..._IDC_..._ASEAN` | OK |
| `wmz7jza` | TTD | mongodb, IDC INDIA | MongoDB, `..._IDC_..._INDIA` | OK |
| `37o75q3` | TTD | mongodb, IDC KR-HK-TW | MongoDB, `..._IDC_..._KR-HK-TW` | OK |
| `q74u9xp` | TTD | mongodb, IDE ANZ | MongoDB, `..._IDE_..._ANZ` | OK |
| `amaf13d` | TTD | mongodb, IDE ASEAN | MongoDB, `..._IDE_..._ASEAN` | OK |
| `sf35fze` | TTD | mongodb, IDE INDIA | MongoDB, `..._IDE_..._INDIA` | OK |
| `357odo1` | TTD | mongodb, IDE KR-HK-TW | MongoDB, `..._IDE_..._KR-HK-TW` | OK |
| `1151909984` | LinkedIn | mongodb, IDC APJ | MongoDB Inc., `2265_MONGODB_2026-Q2_IDC_APJ_DEMAND-GENERATION_LINKEDIN` | OK |
| `1159829644` | LinkedIn | mongodb, AWS Immersion Day AU | MongoDB Inc., `2265_MONGODB_2026-Q3_AWS-IMMERSION-DAY_AU_LEAD-GENERATION_LINKEDIN` | OK |
| `1186555246` | LinkedIn | schneider, Heavy Industries ANZ | Schneider Electric, `2281_HeavyIndustries_LinkedIn_ANZ` | OK |
| `951901366` | LinkedIn | schneiderlqai, LQAIDC TOFU | Schneider Electric, `2306_SE_LQAIDC_LI_TOFU_May26` | OK |
| `ekse5e8` | TTD | schneiderlqai, LQAIDC TOFU | (blank account), `2306_SE_LQAIDC_TTD_TOFU_May26` | OK |
| `24037386856` | Google Ads | cloudflare README: JP YouTube, noted as **absent from our raw data** | Cloudflare, `CF_JP_Q3_TOFU_YouTube_VideoViews_Prospecting` | OK (see Section 4) |

---

## 4. Follow-ups worth raising with the team

1. **Three live clients are missing from the reference sheet entirely.** Caltex (TTD campaign `85k1vmm`, advertiser `0lw3hp6`, "Caltex Star Card | QLD+WA | Jul-Oct 2026"), HireRight (TTD + LinkedIn account `513554482` + DV360) and TLM (TTD advertiser `mor6pp1`). Ask the media team to include the 100% Digital seat and the HireRight account in the next export so this audit stays complete.
2. **Cloudflare JP YouTube (`24037386856`) is in the sheet but not in our data.** [clients/client_cloudflare/README.md](clients/client_cloudflare/README.md) already documents that this campaign appears in none of our raw feeds - the sheet confirms it exists platform-side. The ingestion gap (no Google Ads feed for the Cloudflare JP account) is still open.
3. **Schneider liquid-cooling Search campaigns exist in Google Ads** (7 `...liquidcoolingdatacenter2026` SEM campaigns across AU/IN/BR/CL/UAE/SA in the sheet), but the LQAI dashboard treats Search as a planned-not-live plan line. Worth checking whether Search has started delivering and should be wired in.
4. **No Schneider dashboard consumes Google Ads at all** (AET brand campaigns, Active KPX, MEA segment campaigns are all in the sheet). If those belong to any of our dashboards' scopes (AET = Advancing Energy Technology = the global_rebrand program), that's a channel gap to decide on - currently global_rebrand only carries LinkedIn delivery.
5. **Blank Account cells make the TTD/Google Ads tabs ambiguous** - client attribution had to be inferred from name prefixes. If the media team can populate Account on all rows, future audits can be fully mechanical.

---

## 5. Method

- Parsed all 3 tabs of the xlsx (IDs preserved as text); 536 unique IDs extracted.
- Scanned 1,057 files (`.py .sql .html .js .json .csv .ps1 .md .yaml .env` etc., excluding `.git`, venvs, `node_modules`, base64 blobs) for every reference ID with word-boundary matching.
- Independently swept the repo for ID-shaped values near campaign/ad-group/advertiser context: numeric 9-12 digit tokens and TTD-style 7-char alphanumerics, plus structural extraction of every ID-named column in tracked CSV seeds and JSON configs.
- Matching is on IDs only (TTD ad-group names aren't in the export, as noted).

---

## Appendix - reference campaign IDs not present in the codebase

Ad set / ad group IDs (419) are omitted here: none are used in code (see Section 2). Accounts in parentheses are inferred from the campaign name because the Account cell is blank in the export.

### LinkedIn - 31 campaign IDs not found in the codebase

| Account | Campaign Name | Campaign ID |
|---|---|---|
| APAC - STT GDC - SGD | PO1626_Client_LI_FY26Q1_Organic Boosting | `830201396` |
| APAC - STT GDC - SGD | PO1663_ST Telemedia GDC_LI_FY25Q2_Always On 2025-2026_Awareness | `779559386` |
| APAC - STT GDC - SGD | PO1663_ST Telemedia GDC_LI_FY26_AI Infrastructure Readiness_TH | `1184851136` |
| APAC - STT GDC - SGD | PO1663_ST Telemedia GDC_LI_FY26_DemandNurture_ID_2026 | `834208706` |
| Cloudflare APAC | 2103_CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_DOC_APAC-ASEAN_ASEAN_BOFU_GENERAL_X_LEAD-GEN_ASEAN-CORE-DG | `856000666` |
| Cloudflare APAC | 2103_CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-ASEAN_SGMYID_MOFU_GENERAL_X_AWR_SIM-CORE-DG | `856400716` |
| Cloudflare APAC | 2103_CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_IN-CORE-DG | `856100646` |
| Cloudflare APAC | 2413_CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_CF1-Integrated | `953411036` |
| Cloudflare APAC | 2446_CLOUD_ACQ_2026-Q2_DNB_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-DNB | `1184360316` |
| Cloudflare APAC | 2479_CLOUD_ACQ_2026-Q3_MDS_LINKEDIN_GENERAL_GENERAL_APAC-ANZ_ANZ_GENERAL_GENERAL_X_GENERAL_ANZ-COREDG-Q3 | `1185316886` |
| Cloudflare APAC | 2479_CLOUD_ACQ_2026-Q3_MDS_LINKEDIN_GENERAL_GENERAL_APAC-ASEAN_ASEAN_GENERAL_GENERAL_X_GENERAL_ASEAN-COREDG-Q3 | `1185206876` |
| Cloudflare APAC | 2479_CLOUD_ACQ_2026-Q3_MDS_LINKEDIN_GENERAL_GENERAL_APAC-IN_IN_GENERAL_GENERAL_X_GENERAL_IN-COREDG-Q3 | `1185167386` |
| Cloudflare APAC | 2479_CLOUD_ACQ_2026-Q3_MDS_LINKEDIN_GENERAL_GENERAL_APAC-TCN_HK_GENERAL_GENERAL_X_GENERAL_HK-COREDG-Q3 | `1185237676` |
| PropTrack_TransmissionSG_AUD | 2011_PropTrack_Banking ABM_AU_Awareness | `952607206` |
| PropTrack_TransmissionSG_AUD | 2011_PropTrack_Banking ABM_AU_Leadgen | `955005996` |
| SchneiderElectric_TransmissionSG_AUD | 1958_SE_EntIT_2026_India | `944108666` |
| SchneiderElectric_TransmissionSG_AUD | 1958_SE_EntIT_2026_MEA | `944408416` |
| SchneiderElectric_TransmissionSG_AUD | 1958_SE_EntIT_2026_PAC | `943708726` |
| SchneiderElectric_TransmissionSG_AUD | 1958_SE_EntIT_2026_SAM | `942108786` |
| SchneiderElectric_TransmissionSG_AUD | 2040 SE_Microgrid_Awareness_July2026-AU | `1187582556` |
| SchneiderElectric_TransmissionSG_AUD | 2053_SE_NEL_2026_ANZ_LI_Awareness | `1183400146` |
| SchneiderElectric_TransmissionSG_AUD | 2053_SE_NEL_2026_ANZ_LI_Consideration | `1183520236` |
| SchneiderElectric_TransmissionSG_AUD | 2053_SE_NEL_2026_ANZ_LI_Conversion | `1183590086` |
| SchneiderElectric_TransmissionSG_AUD | 2061_SE_AET_2026_ANZ_LI_Awareness | `1173716013` |
| SchneiderElectric_TransmissionSG_AUD | 2061_SE_AET_2026_ANZ_LI_Consideration | `1185548546` |
| SchneiderElectric_TransmissionSG_AUD | 2223_SE AirSeT 2026 – Retargeting LeadGen | `796245996` |
| SchneiderElectric_TransmissionSG_AUD | 2226_SE_WaterEnv_P2_2026_Apr-Dec | `938102176` |
| SchneiderElectric_TransmissionSG_AUD | 2279_SE_EcoConsult_ECAA_2026_ANZ_Awareness | `1186910376` |
| SchneiderElectric_TransmissionSG_AUD | 2279_SE_EcoConsult_ECAA_2026_ANZ_Consideration | `1189008726` |
| SchneiderElectric_TransmissionSG_AUD | 2305_ANZ_SE Software First EcoStruxure - AWR | `1183603866` |
| SchneiderElectric_TransmissionSG_AUD | 2463_SE_ANZ Industrial Edge W3 Prefab | `1185364926` |

### The Trade Desk - 45 campaign IDs not found in the codebase

| Account | Campaign Name | Campaign ID |
|---|---|---|
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWARENESS_ANZ-CORE-DG | `c0tlqar` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-ASEAN_ASEAN_MOFU_GENERAL_X_LEAD-GEN_ASEAN-CORE-DG | `yhtifwv` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-ASEAN_SGMYID_MOFU_GENERAL_X_AWARENESS_ASEAN-SIM-CORE-DG | `28zgxar` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-ASEAN_VNPHID_MOFU_GENERAL_X_AWARENESS_ASEAN-ROA-CORE-DG | `ikbl3zl` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-EN_ALL_MOFU_GENERAL_X_AWARENESS_RIG-CORE-DG | `4daxlt2` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-EN_ALL_MOFU_GENERAL_X_AWARENESS_RIG-CORE-DG - 1 | `mitpi05` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-KOR_KR_MOFU_GENERAL_X_AWARENESS_KR-CORE-DG | `xom7vh9` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-SAARC_IN_MOFU_GENERAL_X_AWARENESS_IN-CORE-DG | `2dbwk93` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-TCN_CN_MOFU_GENERAL_X_AWARENESS_CN-CORE-DG | `wzg3th2` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-TCN_HKTW_MOFU_GENERAL_X_AWARENESS_HK-CORE-DG | `x8234t8` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-TCN_HKTW_MOFU_GENERAL_X_AWARENESS_TW-CORE-DG | `1cy0ron` |
| (blank - Cloudflare by name) | 2103_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_JAPAN-JPN_JP_MOFU_GENERAL_X_AWARENESS_JP-CORE-DG | `7mhmxrf` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-ANZ_ANZ_GENERAL_GENERAL_X_GENERAL_ANZ-COREDG-Q3 | `91dwzps` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-ASEAN_ASEAN_GENERAL_GENERAL_X_GENERAL_ASEAN-COREDG-Q3 | `3k9c97w` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-IN_IN_GENERAL_GENERAL_X_GENERAL_IN-COREDG-Q3 | `wfs2u7v` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-KR_KR_GENERAL_GENERAL_X_GENERAL_KR-COREDG-Q3 | `1uhu9q8` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-SCN_CN_GENERAL_GENERAL_X_GENERAL_CN-COREDG-Q3 | `6kvyyrp` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-TCN_HK_GENERAL_GENERAL_X_GENERAL_HK-COREDG-Q3 | `k2bok57` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_APAC-TCN_TW_GENERAL_GENERAL_X_GENERAL_TW-COREDG-Q3 | `uk4clyr` |
| (blank - Cloudflare by name) | 2479_CLOUD_ACQ_2026-Q3_MDS_TTD_GENERAL_GENERAL_JAPAN-JPN_JP_GENERAL_GENERAL_X_GENERAL_JP-COREDG-Q3 | `rdhqbdd` |
| (blank - PropTrack by name) | PROPTRACK_BANKING-ABM_MAY-JUN2026_DISPLAY_AU | `jnabcr5` |
| (blank - PropTrack by name) | PROPTRACK_BANKING-ABM_MAY-JUN2026_VIDEO_AU | `chj5guv` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_India | `zyw1s9p` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_MEA | `29491pb` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_PAC | `zuu7ia5` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_S2_India | `ir4w3qe` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_S2_MEA | `vd4w7u5` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_S2_SAM | `94jb7c5` |
| (blank - Schneider by name) | 1958_SE_EntIT_2026_SAM | `cqwsxtp` |
| (blank - Schneider by name) | 2053_SE_NEL_TTD_AWR_AU_Jun26 | `749buhh` |
| (blank - Schneider by name) | 2053_SE_NEL_TTD_AWR_NZ_Jun26 | `ohloko3` |
| (blank - Schneider by name) | 2079_SE_EBA_Activate_AWR_June4 | `8z7idow` |
| (blank - Schneider by name) | 2223_SE AirSeT_ANZ_HighImpact_AWR_2026 | `x90uvl5` |
| (blank - Schneider by name) | 2226_SE_WaterEnv_P2_AWR - AU | `sjktslp` |
| (blank - Schneider by name) | 2226_SE_WaterEnv_P2_AWR - NZ | `g0zsz2g` |
| (blank - Schneider by name) | 2305_SE_EcoStruxureIT_AWR_2026 | `e6k949n` |
| (blank - Schneider by name) | 2463_SE_ANZ Industrial Edge W3 Prefab_Programmatic_Awareness | `zkmk99a` |
| Cloudflare | 1160_CLOUD_ACQ_2026-Q2-DOOH - AU | `de6m2ub` |
| Cloudflare | 1160_CLOUD_ACQ_2026-Q2-DOOH - NZ | `x9z4zq2` |
| Cloudflare | 1160_CLOUD_ACQ_2026-Q2-High Impact--HyperlocalGeo - ANZ | `npg01t7` |
| Cloudflare | 2193_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-ANZ_AUNZ_MOFU_GENERAL_X_AWARENESS_ANZ-SURROUND-ABM | `6cm53fr` |
| Cloudflare | 2193_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-ASEAN_SGMYIDPHTH_MOFU_GENERAL_X_AWARENESS_ASEAN-SURROUND-ABM | `y2kxvxf` |
| Cloudflare | 2193_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-GCR_HKTW_MOFU_GENERAL_X_AWARENESS_GCR-SURROUND-ABM | `9lg1jx3` |
| Cloudflare | 2193_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-KOR_KR_MOFU_GENERAL_X_AWARENESS_KR-SURROUND-ABM | `on8odve` |
| Cloudflare | 2193_CLOUD_ACQ_2026-Q2_CNC_TTD_GENERAL_SI_APAC-SAARC_IN_MOFU_GENERAL_X_AWARENESS_IN-SURROUND-ABM | `hebzbzj` |

### Google Ads - 27 campaign IDs not found in the codebase

| Account | Campaign Name | Campaign ID |
|---|---|---|
| (blank - Schneider by name) | 1896_SE_ANZ_2025_Active KPX_AU | `23212180737` |
| (blank - Schneider by name) | 1896_SE_ANZ_2025_Active KPX_NZ | `23224662611` |
| (blank - Schneider by name) | 2026_May_AU_sp_ecsp_google_awareness_sem_global-bu_liquidcoolingdatacenter2026 | `23854812607` |
| (blank - Schneider by name) | 2026_May_IN_sp_ecsp_google_awareness_sem_global-bu_liquidcoolingdatacenter2026 | `23850315722` |
| (blank - Schneider by name) | 2026_may_BR_sp_ecsp_google_awareness_sem_global-bu_liquidcoolingdatacenter2026 | `23850338093` |
| (blank - Schneider by name) | 2026_may_CL_sp_ecsp_google_awareness_sem_global-bu_liquidcoolingdatacenter2026 | `23850352448` |
| (blank - Schneider by name) | 2026_may_UAE_sp_ecsp_google_awareness_sem_global-bu_liquidcoolingdatacenter2026 | `23844906945` |
| (blank - Schneider by name) | AET - Electrification & Automation - AU | `23994285343` |
| (blank - Schneider by name) | AET - Electrification & Automation - NZ | `23994285346` |
| (blank - Schneider by name) | AET - Energy Management - AU | `23984735928` |
| (blank - Schneider by name) | AET - Energy Management - NZ | `23984735931` |
| (blank - Schneider by name) | AET - Energy Technology Category - AU | `23984735916` |
| (blank - Schneider by name) | AET - Energy Technology Category - NZ | `23984735919` |
| (blank - Schneider by name) | AET - Schneider Electric Branded - AU | `23984735922` |
| (blank - Schneider by name) | AET - Schneider Electric Branded - NZ | `23984735925` |
| (blank - Schneider by name) | AET - Sustainability & Net Zero - AU | `23994285349` |
| (blank - Schneider by name) | AET - Sustainability & Net Zero - NZ | `23994285352` |
| (blank - Schneider by name) | name2026_may_SA_sp_ecsp_google_awareness_sem_global-bu_liquidcoolingdatacenter2026 | `23854845817` |
| (blank - unclassified) | 1130_MEA_Finance #2 | `22872037438` |
| (blank - unclassified) | 2353_MEA_CPG | `22824647641` |
| (blank - unclassified) | 2353_MEA_Finance | `22831398653` |
| (blank - unclassified) | 2353_MEA_Healthcare | `22738921368` |
| (blank - unclassified) | 2353_MEA_Healthcare. | `23785376781` |
| (blank - unclassified) | 2353v2_MEA_Finance | `22875342142` |
| (blank - unclassified) | CPG Test | `22738923258` |
| (blank - unclassified) | MEA_CPG | `22824734314` |
| (blank - unclassified) | Manufacturing Test | `22748860480` |

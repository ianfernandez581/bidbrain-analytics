-- tier_mapping_cleaned: account -> tier lookup with a fuzzy join key.
-- BigQuery port of CLOUDFLARE_SANDBOX.CS_REPORTING.V_TIER_MAPPING_CLEANED, now over
-- the static seed client_cloudflare.seed_tiers (from data/tiers.csv).
-- JOIN_NAME's suffix-stripping regex MUST stay identical to the COMPANY_NAME cleaning
-- in pacing_model (they join on it). Snowflake REGEXP_REPLACE(...,'i') -> RE2 (?i) flag.
CREATE OR REPLACE VIEW `client_cloudflare.tier_mapping_cleaned` AS
SELECT
    ACCOUNT_NAME,
    WEBSITE,
    L1,
    L2,
    -- strip protocol + www + trailing slash from the website
    LOWER(REGEXP_REPLACE(REGEXP_REPLACE(WEBSITE, r'^(https?://)?(www\.)?', ''), r'/$', '')) AS JOIN_DOMAIN,
    -- strip a trailing legal suffix from the account name (case-insensitive)
    LOWER(REGEXP_REPLACE(TRIM(ACCOUNT_NAME), r'(?i)( pty| ltd| inc| corp| limited| pte| corporation| co| ltd\.)$', '')) AS JOIN_NAME,
    CASE
        WHEN TIER LIKE '%Tier 2%' THEN 'Tier 2'
        WHEN TIER LIKE '%Tier 3%' THEN 'Tier 3'
        ELSE 'Other'
    END AS CLEAN_TIER
FROM `client_cloudflare.seed_tiers`;

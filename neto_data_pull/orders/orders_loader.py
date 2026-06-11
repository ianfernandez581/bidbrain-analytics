r"""
Neto / Maropost Commerce Cloud -> BigQuery loader (orders).

Lives in:  neto_data_pull/orders/orders_loader.py
Runtime artifacts (window cache, log, temp NDJSON, backfill checkpoints) -> _run/
next to this script (anchored to __file__, gitignored), so nothing scatters into
the repo root.

This is the Neto sibling of windsor_data_pull / snowflake_data_pull: a DUMB raw
mirror of the source into a shared `raw_<source>` dataset (`raw_neto`). NO per-client
filter, NO business logic here -- every client dashboard reads this raw layer and
applies its own WHERE / rollups in BigQuery views (e.g. client_cityperfume/sql/).
City Perfume is the first (only) Neto store today, but the layer stays client-neutral.

ONE table, raw_neto.orders. The order already carries everything we need about the
buyer -- email, username, bill/ship address fields, customer_ref1 -- so there is NO
separate customers table; customer attributes ride along on each order, and the
reporting views resolve customer identity from the order's email (see ../reporting/).

Auth, the Secret Manager helper, structured logging, the staging->MERGE idempotency,
and the crash-safe/resumable backfill all mirror windsor_data_pull/ga4/ga4_loader.py.
The CLI is argparse (the flags below).

================================================================================
CONFIRMED NETO API FACTS (smoke-tested live against www.cityperfume.com.au, 2026-06)
================================================================================
TRANSPORT
  * HTTP POST to {STORE_URL}/do/WS/NetoAPI (STORE_URL from $NETO_STORE_URL, default
    https://www.cityperfume.com.au, --store-url overrides; trailing slash stripped).
  * Headers: NETOAPI_ACTION (GetOrder), NETOAPI_KEY (Secret Manager
    secret `neto-api-key` via ADC), Accept + Content-Type = application/json.
  * NETOAPI_USERNAME is OPTIONAL: only sent if a Secret Manager secret
    `neto-api-username` EXISTS. City Perfume uses a global key that authenticates on
    the key alone -- the username secret is absent and we must NOT fail on that.

REQUEST / PAGINATION
  * Body: {"Filter": { <filters>, "Page": <int>, "Limit": 200, "OutputSelector":[...] }}.
  * Page is 0-INDEXED. Walk 0,1,2,... until the response array is empty/absent
    (confirmed: an out-of-range page returns Ack=Success with "Order": []).
  * Get* REQUIRES a real selecting filter -- Limit alone returns ZERO rows
    (Ack=Success, no array). We always pass a date filter (see watermark/backfill).
  * NO UpdateResults block is ever sent: it mutates each order's export state and
    must never touch fulfillment. This loader is strictly read-only.
  * Response envelope: {"Order": [...], "Ack": "...", "CurrentTime": "..."}.
    Ack != "Success" (or a populated Messages.Error) is a HARD failure, logged loudly.

TYPES (from live data)
  * Money comes back as strings -- 8-dp on line items ("300.00000000") and 2-dp on
    totals ("270.00"). Cast to NUMERIC, passing the STRING through (not float) so we
    keep full precision.
  * Quantities are strings ("1") -> INT64.
  * Datetimes are store-LOCAL (Australia/Sydney), "YYYY-MM-DD HH:MM:SS". DateInvoiced
    / DateCompleted sometimes come back DATE-only ("2026-05-08") -- the parser accepts
    both. Empty/absent fields are simply omitted from the JSON (so .get() -> None).
  * Order Email is frequently empty; Username is often "noreg" (guest/POS) or a
    scrambled system handle -- stored AS-IS, never cleaned.
  * ID == OrderID on every order seen; order_id := OrderID is the PK.

TIMEZONE CONVENTION (documented; see README)
  Neto filters and timestamps are store-local with no offset. We keep the whole
  watermark loop in store-local wall-clock to match filter semantics exactly:
    - *_raw STRING columns hold the source string verbatim (source of truth).
    - the parsed TIMESTAMP columns hold that same wall-clock (loaded WITHOUT a TZ
      offset, so BigQuery stores the store-local clock; they are NOT UTC instants).
    - the next DateUpdatedFrom is FORMAT_TIMESTAMP(MAX(date_updated)) minus an
      overlap -- which round-trips back to the original store-local string.
  Only "now" (the DateUpdatedTo bound) is taken from the Australia/Sydney wall-clock.

ADDRESS PII (real data finding -- NOT a bug)
  The order-level Bill* / Ship* address fields are REQUESTED (the raw layer mirrors
  the source) but currently return EMPTY for this store/key -- verified across ~4,000
  orders spanning POS / Website / eBay / marketplace channels. The columns are kept
  (forward-compat; they'd populate for a store/key that exposes them); buyer identity
  is carried by email / username / customer_ref1 instead. See README.

================================================================================
MODES
================================================================================
  INCREMENTAL (default) -- normal / scheduled. Read MAX(date_updated) from the table,
  subtract INCREMENTAL_OVERLAP_DAYS, pass as DateUpdatedFrom; DateUpdatedTo = now.
  Brand-new (empty) table bootstraps the last BOOTSTRAP_DAYS and warns you to run
  --backfill for full history.

  --backfill --since YYYY-MM-DD -- full history. Chunked by CALENDAR MONTH on
  DatePlaced. Each completed month is written to a checkpoint file, so a crash
  resumes from the next month (and the MERGE makes a redo harmless either way).

CLI
  python neto_data_pull/orders/orders_loader.py                      # incremental
  python neto_data_pull/orders/orders_loader.py --backfill --since 2015-01-01
  ... --store-url URL | --limit N | --dry-run | --force
  --dry-run: fetch page 0 + parse + log counts and a sample row; NO BigQuery reads/writes.
"""
import argparse
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from google.api_core import exceptions as gexc
from google.api_core.exceptions import NotFound
from google.cloud import bigquery, secretmanager, storage

# Transient errors worth retrying on the BigQuery / GCS side (network blips, 5xx,
# 429, deadline/retry timeouts). Permanent 4xx (BadRequest schema error, NotFound,
# Forbidden) are deliberately NOT here -- those should fail fast, not loop.
_TRANSIENT_BQ = (
    gexc.RetryError, gexc.ServiceUnavailable, gexc.InternalServerError,
    gexc.GatewayTimeout, gexc.TooManyRequests, gexc.DeadlineExceeded, gexc.BadGateway,
    requests.exceptions.ConnectionError, requests.exceptions.Timeout,
    ConnectionError, TimeoutError,
)

# ---------- Config ----------
PROJECT_ID = "bidbrain-analytics"
LOCATION = "australia-southeast1"
DATASET = "raw_neto"
GCS_BUCKET = "bidbrain-analytics-staging"        # shared NDJSON staging bucket (same as Windsor loaders)

DEFAULT_STORE_URL = "https://www.cityperfume.com.au"
STORE_URL_ENV = os.environ.get("NETO_STORE_URL") or DEFAULT_STORE_URL
SECRET_API_KEY = "neto-api-key"
SECRET_USERNAME = "neto-api-username"            # OPTIONAL -- only used if it exists
STORE_TZ = ZoneInfo("Australia/Sydney")          # used ONLY to stamp "now" in store-local wall-clock

PAGE_LIMIT = 200                                 # Neto Filter.Limit per page (overridable with --limit)
INCREMENTAL_OVERLAP_DAYS = 2                     # re-pull this many days before MAX(date_updated)
BOOTSTRAP_DAYS = 7                               # empty-table incremental window (history needs --backfill)
BACKFILL_DEFAULT_SINCE = date(2015, 1, 1)        # --since default for --backfill

# Resilience. Exponential backoff + jitter on 429/5xx; throttle well under Neto's
# 500 requests/minute (target ~300/min => >=0.2s between request starts).
MIN_REQUEST_INTERVAL = 0.2
TIMEOUT_SEC = 120
RETRY_BASE = 2.0
RETRY_MAX = 60.0
MAX_ATTEMPTS = 12

# All runtime artifacts live under _run/ next to THIS script (gitignored), never cwd.
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = WORK_DIR / "windows"
LOG_FILE = WORK_DIR / "orders_loader.log"

# ---------- Logging (same shape as the Windsor loaders) ----------
class FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8"),
        FlushingStreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("neto_orders_loader")

# ---------- Secrets (Secret Manager via ADC -- identical helper to ga4_loader) ----------
def get_secret(name):
    """Read the latest version of a Secret Manager secret via Application Default
    Credentials -- the same ADC the BigQuery/Storage clients use. Runs identically
    locally (after `gcloud auth application-default login`) and on Cloud Run/Build."""
    log.info(f"Fetching secret '{name}' from Secret Manager...")
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    val = client.access_secret_version(name=path).payload.data.decode("utf-8").strip()
    log.info(f"  got secret (length {len(val)})")
    return val

def get_secret_optional(name):
    """Like get_secret but returns None if the secret does not exist. Used for the
    OPTIONAL NETOAPI_USERNAME -- City Perfume's global key authenticates alone, so
    the `neto-api-username` secret is absent and that must NOT be an error."""
    try:
        return get_secret(name)
    except (NotFound, gexc.PermissionDenied, gexc.Forbidden):
        # Absent locally surfaces as NotFound; on Cloud Run the runtime SA has no
        # binding on a non-existent secret, so GCP returns PermissionDenied/403 instead
        # (it won't reveal whether the secret exists). For an OPTIONAL secret both mean
        # the same thing: no username -> omit the header.
        log.info(f"  optional secret '{name}' absent or no access -- omitting NETOAPI_USERNAME header")
        return None

def build_headers(api_key, api_username):
    headers = {
        "NETOAPI_KEY": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if api_username:
        headers["NETOAPI_USERNAME"] = api_username
    return headers

# ---------- Type coercion (store the source faithfully; nulls stay null) ----------
def to_num(v):
    """Money/decimal -> a normalised NUMERIC-safe STRING (NOT float, to keep the 8-dp
    precision Neto sends). None for empty/non-numeric. format(d,'f') keeps plain
    fixed-point form -- str(Decimal('0.00000000')) would render '0E-8'."""
    if v in (None, "", "null"):
        return None
    try:
        return format(Decimal(str(v)), "f")
    except (InvalidOperation, ValueError):
        return None

def to_int(v):
    if v in (None, "", "null"):
        return None
    try:
        return int(Decimal(str(v)))
    except (InvalidOperation, ValueError):
        return None

def to_bool(v):
    """Neto sends TaxInclusive as the string 'True'/'False'. None for empty."""
    if v in (None, "", "null"):
        return None
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")

def to_ts(v):
    """Neto datetime ('YYYY-MM-DD HH:MM:SS' or DATE-only 'YYYY-MM-DD') -> a normalised
    'YYYY-MM-DD HH:MM:SS' string for the TIMESTAMP load. Kept as store-local wall-clock
    (no TZ offset) on purpose -- see the module's TIMEZONE CONVENTION note. None for
    empty/unparseable."""
    if not v:
        return None
    s = str(v).strip()
    # Neto uses '0000-00-00' / '0000-00-00 00:00:00' as an empty-date sentinel
    # (e.g. DatePaid / DateCompleted on un-completed orders) -- treat as NULL.
    if s.startswith("0000-00-00"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    log.warning(f"  unparseable datetime {s!r} -- storing NULL parsed (raw kept)")
    return None

def as_list(v):
    """Neto repeated nodes come back as a list; defensively wrap a lone dict."""
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    return list(v)

# ---------- HTTP: one page, with throttle + exponential backoff + jitter ----------
_last_request = 0.0

def _throttle():
    global _last_request
    wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()

def neto_request(store_url, headers, action, filt):
    """POST one request to NetoAPI and return the parsed JSON envelope. Retries
    transient errors (timeouts, 429, 5xx) with exponential backoff + jitter; fails
    fast and loud on permanent 4xx or an Ack/Messages.Error in the body."""
    url = f"{store_url}/do/WS/NetoAPI"
    req_headers = dict(headers, NETOAPI_ACTION=action)
    body = json.dumps({"Filter": filt})
    attempt = 0
    while True:
        attempt += 1
        _throttle()
        try:
            t0 = time.monotonic()
            r = requests.post(url, headers=req_headers, data=body, timeout=TIMEOUT_SEC)
            elapsed = time.monotonic() - t0
            r.raise_for_status()
            payload = r.json()
            ack = payload.get("Ack")
            msgs = payload.get("Messages") or {}
            err = msgs.get("Error") if isinstance(msgs, dict) else msgs
            if ack != "Success" or err:
                raise RuntimeError(
                    f"{action} returned Ack={ack!r} with errors {err!r}. Filter sent: "
                    f"{json.dumps({k: v for k, v in filt.items() if k != 'OutputSelector'})}"
                )
            return payload, elapsed
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429 or (status is not None and status >= 500):
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError(f"{action}: gave up after {attempt} attempts on transient HTTP {status}.")
                sleep = min(RETRY_BASE * (2 ** (attempt - 1)), RETRY_MAX) + random.uniform(0, 1)
                log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} transient HTTP {status}; retrying in {sleep:.1f}s")
                time.sleep(sleep)
                continue
            body_txt = e.response.text[:500] if e.response is not None else ""
            raise RuntimeError(
                f"{action} got permanent HTTP {status} -- will NOT recover by retrying "
                f"(bad filter, auth, or store URL). Body:\n{body_txt}"
            )
        except requests.exceptions.RequestException as e:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(f"{action}: gave up after {attempt} attempts ({type(e).__name__}: {e}).")
            sleep = min(RETRY_BASE * (2 ** (attempt - 1)), RETRY_MAX) + random.uniform(0, 1)
            log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} FAILED ({type(e).__name__}); retrying in {sleep:.1f}s")
            time.sleep(sleep)

def paginate(store_url, headers, action, response_key, base_filter, output_selector,
             page_limit, label="", max_pages=None):
    """Walk Page 0,1,2,... (0-indexed) until the response array is empty/absent.
    Returns (records, pages_walked). max_pages caps the walk (dry-run peek).
    Logs every request so a long run is visible page-by-page."""
    key = response_key.lower()
    filt_summary = " ".join(f"{k}={v}" for k, v in base_filter.items())
    log.info(f"  -> walking pages [{label}] | {action} filter: {filt_summary} | page size {page_limit}")
    records = []
    page = 0
    t0 = time.monotonic()
    while True:
        filt = dict(base_filter, Page=page, Limit=page_limit, OutputSelector=output_selector)
        payload, elapsed = neto_request(store_url, headers, action, filt)
        batch = payload.get(response_key) or []
        if not batch:
            log.info(f"      page {page:>4}: HTTP 200 in {elapsed:4.1f}s -- 0 {key}s -> end of window")
            break
        records.extend(batch)
        log.info(f"      page {page:>4}: HTTP 200 in {elapsed:4.1f}s -- {len(batch):>3} {key}s "
                 f"(window running total: {len(records)})")
        page += 1
        if max_pages is not None and page >= max_pages:
            log.info(f"      (stopping after {max_pages} page(s) -- dry-run / capped)")
            break
    log.info(f"  <- [{label}] done: {page} page(s) walked, {len(records)} {key}s fetched in {time.monotonic()-t0:.1f}s")
    return records, page

# ================================================================================
# Orders spec: OutputSelector + schema + transform. The fetch/load/MERGE machinery
# below is generic and driven by the ORDERS dict, so a second source could be added
# later without touching it.
# ================================================================================
ORDER_OUTPUT_SELECTOR = [
    "ID", "OrderID", "OrderStatus", "OrderType", "CompleteStatus", "SalesChannel",
    "Username", "Email", "PurchaseOrderNumber", "SalesPerson", "DefaultPaymentType",
    "PaymentTerms", "TaxInclusive", "OrderTax", "ProductSubtotal", "ShippingTotal",
    "ShippingTax", "SurchargeTotal", "CouponCode", "CouponDiscount", "GrandTotal",
    "DatePlaced", "DateInvoiced", "DatePaid", "DateUpdated", "DateCompleted",
    "BillFirstName", "BillLastName", "BillCompany", "BillStreetLine1", "BillStreetLine2",
    "BillCity", "BillState", "BillPostCode", "BillCountry", "BillPhone",
    "ShipFirstName", "ShipLastName", "ShipCompany", "ShipStreetLine1", "ShipStreetLine2",
    "ShipCity", "ShipState", "ShipPostCode", "ShipCountry", "ShipPhone",
    "CustomerRef1",
    "OrderLine", "OrderLine.SKU", "OrderLine.ProductName", "OrderLine.Quantity",
    "OrderLine.UnitPrice", "OrderLine.Tax", "OrderLine.TaxCode", "OrderLine.CostPrice",
    "OrderLine.PercentDiscount", "OrderLine.ProductDiscount", "OrderLine.OrderLineID",
    "OrderLine.WarehouseName",
    "OrderPayment", "OrderPayment.Id", "OrderPayment.Amount", "OrderPayment.PaymentType",
    "OrderPayment.DatePaid",
]

def _addr_fields(prefix):
    cols = ["first_name", "last_name", "company", "street_line1", "street_line2",
            "city", "state", "post_code", "country", "phone"]
    return [bigquery.SchemaField(f"{prefix}_{c}", "STRING") for c in cols]

ORDERS_SCHEMA = [
    bigquery.SchemaField("order_id", "STRING", mode="REQUIRED",
        description="Neto OrderID (== ID). PK / MERGE key."),
    bigquery.SchemaField("id", "STRING", description="Neto internal order ID (mirrors OrderID)."),
    bigquery.SchemaField("order_status", "STRING"),
    bigquery.SchemaField("order_type", "STRING"),
    bigquery.SchemaField("complete_status", "STRING"),
    bigquery.SchemaField("sales_channel", "STRING", description="e.g. Neto POS / Website / eBay / BigW / Amazon AU."),
    bigquery.SchemaField("username", "STRING", description="Neto Username; often 'noreg' or a scrambled handle. AS-IS."),
    bigquery.SchemaField("email", "STRING", description="Order Email (frequently empty). AS-IS."),
    bigquery.SchemaField("purchase_order_number", "STRING"),
    bigquery.SchemaField("sales_person", "STRING"),
    bigquery.SchemaField("default_payment_type", "STRING"),
    bigquery.SchemaField("payment_terms", "STRING"),
    bigquery.SchemaField("tax_inclusive", "BOOL"),
    # ---- Financials (NUMERIC; source strings parsed without float loss) ----
    bigquery.SchemaField("order_tax", "NUMERIC"),
    bigquery.SchemaField("product_subtotal", "NUMERIC"),
    bigquery.SchemaField("shipping_total", "NUMERIC"),
    bigquery.SchemaField("shipping_tax", "NUMERIC"),
    bigquery.SchemaField("surcharge_total", "NUMERIC"),
    bigquery.SchemaField("coupon_code", "STRING"),
    bigquery.SchemaField("coupon_discount", "NUMERIC"),
    bigquery.SchemaField("grand_total", "NUMERIC"),
    # ---- Dates (store-local wall-clock TIMESTAMP + raw source string) ----
    bigquery.SchemaField("date_placed", "TIMESTAMP", description="Store-local wall-clock (Australia/Sydney), not UTC. See README."),
    bigquery.SchemaField("date_placed_raw", "STRING"),
    bigquery.SchemaField("date_invoiced", "TIMESTAMP"),
    bigquery.SchemaField("date_invoiced_raw", "STRING"),
    bigquery.SchemaField("date_paid", "TIMESTAMP"),
    bigquery.SchemaField("date_paid_raw", "STRING"),
    bigquery.SchemaField("date_updated", "TIMESTAMP", description="Watermark field. Store-local wall-clock."),
    bigquery.SchemaField("date_updated_raw", "STRING"),
    bigquery.SchemaField("date_completed", "TIMESTAMP"),
    bigquery.SchemaField("date_completed_raw", "STRING"),
    # ---- Addresses (mirrored from source; empty for this store/key -- see README) ----
    *_addr_fields("bill"),
    *_addr_fields("ship"),
    bigquery.SchemaField("customer_ref1", "STRING", description="Often the marketplace handle (eBay/Amazon username)."),
    # ---- Nested line items / payments ----
    bigquery.SchemaField("order_lines", "RECORD", mode="REPEATED", fields=[
        bigquery.SchemaField("sku", "STRING"),
        bigquery.SchemaField("product_name", "STRING"),
        bigquery.SchemaField("quantity", "INT64"),
        bigquery.SchemaField("unit_price", "NUMERIC"),
        bigquery.SchemaField("tax", "NUMERIC"),
        bigquery.SchemaField("tax_code", "STRING"),
        bigquery.SchemaField("cost_price", "NUMERIC"),
        bigquery.SchemaField("percent_discount", "NUMERIC"),
        bigquery.SchemaField("product_discount", "NUMERIC"),
        bigquery.SchemaField("order_line_id", "STRING"),
        bigquery.SchemaField("warehouse_name", "STRING"),
    ]),
    bigquery.SchemaField("order_payments", "RECORD", mode="REPEATED", fields=[
        bigquery.SchemaField("id", "STRING"),
        bigquery.SchemaField("amount", "NUMERIC"),
        bigquery.SchemaField("payment_type", "STRING"),
        bigquery.SchemaField("date_paid", "TIMESTAMP"),
        bigquery.SchemaField("date_paid_raw", "STRING"),
    ]),
    # ---- Provenance ----
    bigquery.SchemaField("_loaded_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("_raw", "JSON", description="Full original Neto order object (forward-compat)."),
]

def _addr_map(rec, prefix_src, prefix_dst):
    g = rec.get
    return {
        f"{prefix_dst}_first_name": g(f"{prefix_src}FirstName"),
        f"{prefix_dst}_last_name": g(f"{prefix_src}LastName"),
        f"{prefix_dst}_company": g(f"{prefix_src}Company"),
        f"{prefix_dst}_street_line1": g(f"{prefix_src}StreetLine1"),
        f"{prefix_dst}_street_line2": g(f"{prefix_src}StreetLine2"),
        f"{prefix_dst}_city": g(f"{prefix_src}City"),
        f"{prefix_dst}_state": g(f"{prefix_src}State"),
        f"{prefix_dst}_post_code": g(f"{prefix_src}PostCode"),
        f"{prefix_dst}_country": g(f"{prefix_src}Country"),
        f"{prefix_dst}_phone": g(f"{prefix_src}Phone"),
    }

def transform_order(o, loaded_at):
    g = o.get
    row = {
        "order_id": g("OrderID") or g("ID"),
        "id": g("ID"),
        "order_status": g("OrderStatus"),
        "order_type": g("OrderType"),
        "complete_status": g("CompleteStatus"),
        "sales_channel": g("SalesChannel"),
        "username": g("Username"),
        "email": g("Email"),
        "purchase_order_number": g("PurchaseOrderNumber"),
        "sales_person": g("SalesPerson"),
        "default_payment_type": g("DefaultPaymentType"),
        "payment_terms": g("PaymentTerms"),
        "tax_inclusive": to_bool(g("TaxInclusive")),
        "order_tax": to_num(g("OrderTax")),
        "product_subtotal": to_num(g("ProductSubtotal")),
        "shipping_total": to_num(g("ShippingTotal")),
        "shipping_tax": to_num(g("ShippingTax")),
        "surcharge_total": to_num(g("SurchargeTotal")),
        "coupon_code": g("CouponCode"),
        "coupon_discount": to_num(g("CouponDiscount")),
        "grand_total": to_num(g("GrandTotal")),
        "date_placed": to_ts(g("DatePlaced")), "date_placed_raw": g("DatePlaced"),
        "date_invoiced": to_ts(g("DateInvoiced")), "date_invoiced_raw": g("DateInvoiced"),
        "date_paid": to_ts(g("DatePaid")), "date_paid_raw": g("DatePaid"),
        "date_updated": to_ts(g("DateUpdated")), "date_updated_raw": g("DateUpdated"),
        "date_completed": to_ts(g("DateCompleted")), "date_completed_raw": g("DateCompleted"),
        "customer_ref1": g("CustomerRef1"),
        "order_lines": [{
            "sku": l.get("SKU"),
            "product_name": l.get("ProductName"),
            "quantity": to_int(l.get("Quantity")),
            "unit_price": to_num(l.get("UnitPrice")),
            "tax": to_num(l.get("Tax")),
            "tax_code": l.get("TaxCode"),
            "cost_price": to_num(l.get("CostPrice")),
            "percent_discount": to_num(l.get("PercentDiscount")),
            "product_discount": to_num(l.get("ProductDiscount")),
            "order_line_id": l.get("OrderLineID"),
            "warehouse_name": l.get("WarehouseName"),
        } for l in as_list(g("OrderLine"))],
        "order_payments": [{
            "id": p.get("Id"),
            "amount": to_num(p.get("Amount")),
            "payment_type": p.get("PaymentType"),
            "date_paid": to_ts(p.get("DatePaid")),
            "date_paid_raw": p.get("DatePaid"),
        } for p in as_list(g("OrderPayment"))],
        "_loaded_at": loaded_at,
        # Embed the source object directly (NOT json.dumps) so the JSON column is a
        # navigable object -- JSON_VALUE(_raw,'$.Field') works for forward-compat.
        "_raw": o,
    }
    row.update(_addr_map(o, "Bill", "bill"))
    row.update(_addr_map(o, "Ship", "ship"))
    return row

ORDERS = {
    "action": "GetOrder",
    "response_key": "Order",
    "table": "orders",
    "schema": ORDERS_SCHEMA,
    "output_selector": ORDER_OUTPUT_SELECTOR,
    "merge_key": "order_id",
    "transform": transform_order,
    "backfill_date_field": "DatePlaced",   # initial historical sweep filters on DatePlaced
    "table_desc": "Raw Neto orders (header + buyer/address fields + nested line items + payments), one row per OrderID.",
}

# ---------- BigQuery: ensure dataset/table, watermark, load + MERGE ----------
def ensure_dataset(bq):
    ds = bigquery.Dataset(f"{PROJECT_ID}.{DATASET}")
    ds.location = LOCATION
    ds.description = "Raw Neto / Maropost Commerce Cloud mirror (orders). Dumb copy; clients filter in views."
    bq.create_dataset(ds, exists_ok=True)
    log.info(f"Dataset ready: {PROJECT_ID}.{DATASET}")

def ensure_table(bq, spec):
    table_id = f"{PROJECT_ID}.{DATASET}.{spec['table']}"
    try:
        t = bq.get_table(table_id)
        log.info(f"Table exists: {table_id} ({t.num_rows} rows, {len(t.schema)} columns)")
        return t
    except NotFound:
        table = bigquery.Table(table_id, schema=spec["schema"])
        table.description = spec["table_desc"]
        table = bq.create_table(table)
        log.info(f"Created table {table_id} ({len(table.schema)} columns)")
        return table

def read_watermark(bq, table):
    """MAX(date_updated) of an existing (possibly empty) table, formatted as the
    store-local 'YYYY-MM-DD HH:MM:SS' string. None if empty. FORMAT_TIMESTAMP defaults
    to UTC, and because date_updated is stored as the store-local wall-clock (no offset),
    that formatting yields the original store-local string -- no TZ math, no DST bugs."""
    sql = (f"SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(date_updated)) AS wm "
           f"FROM `{PROJECT_ID}.{DATASET}.{table}`")
    row = list(bq.query(sql, location=LOCATION).result())[0]
    return row["wm"]

def with_retries(what, fn):
    """Run a BigQuery/GCS network op with exponential backoff + jitter on TRANSIENT
    errors (network blips, 5xx, 429, retry/deadline timeouts). Permanent errors
    (BadRequest schema, NotFound, Forbidden) propagate immediately. Safe because every
    op we wrap is idempotent: blob upload overwrites, staging load is WRITE_TRUNCATE,
    and the MERGE keys on order_id (a redo just re-updates, never duplicates)."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except _TRANSIENT_BQ as e:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(f"{what}: gave up after {attempt} attempts ({type(e).__name__}: {e}).")
            sleep = min(RETRY_BASE * (2 ** (attempt - 1)), RETRY_MAX) + random.uniform(0, 1)
            log.warning(f"    {what}: attempt {attempt}/{MAX_ATTEMPTS} transient {type(e).__name__}; retrying in {sleep:.1f}s")
            time.sleep(sleep)

def load_window_to_bq(bq, storage_client, spec, schema, records, loaded_at, tag):
    """Transform -> dedup on the MERGE key -> NDJSON -> GCS -> staging (WRITE_TRUNCATE)
    -> MERGE into the main table on the key -> clean up. Idempotent: re-loading any
    window never duplicates rows. The GCS upload + staging load + MERGE are each
    wrapped in with_retries so a transient network/5xx blip can't kill a long run."""
    if not records:
        log.info(f"  BQ LOAD [{tag}]: 0 records fetched -> nothing to load, skipping")
        return 0, 0

    log.info(f"  BQ LOAD [{tag}]: starting ({len(records)} records fetched)")
    key = spec["merge_key"]
    transform = spec["transform"]

    t = time.monotonic()
    transformed = [transform(r, loaded_at) for r in records]
    dropped = [r for r in transformed if not r.get(key)]
    if dropped:
        log.warning(f"    [transform] dropping {len(dropped)} record(s) with NULL {key}")
    by_key = {r[key]: r for r in transformed if r.get(key)}   # last occurrence wins
    rows = list(by_key.values())
    log.info(f"    [transform] {len(records)} -> {len(rows)} rows "
             f"({len(transformed) - len(rows)} deduped/dropped on {key}) in {time.monotonic()-t:.1f}s")

    run_id = uuid.uuid4().hex[:8]
    local_path = WORK_DIR / f"load_{spec['table']}_{run_id}.ndjson"
    t = time.monotonic()
    with local_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    log.info(f"    [ndjson] wrote {len(rows)} rows ({local_path.stat().st_size/1024:.1f} KB) "
             f"to {local_path.name} in {time.monotonic()-t:.1f}s")

    gcs_path = f"loads/neto/{spec['table']}/{tag}_{run_id}.ndjson"
    gcs_uri = f"gs://{GCS_BUCKET}/{gcs_path}"
    t = time.monotonic()
    # Fresh blob handle per attempt + a generous per-request timeout (large months are
    # tens of MB; the default 120s deadline is what bit us mid-backfill).
    with_retries("gcs upload", lambda: storage_client.bucket(GCS_BUCKET).blob(gcs_path)
                 .upload_from_filename(str(local_path), timeout=600))
    log.info(f"    [gcs] uploaded -> {gcs_uri} in {time.monotonic()-t:.1f}s")

    staging_ref = f"{PROJECT_ID}.{DATASET}.{spec['table']}_staging"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
    )
    t = time.monotonic()
    def _stage():
        j = bq.load_table_from_uri(gcs_uri, staging_ref, job_config=job_config, location=LOCATION)
        log.info(f"    [staging] load job {j.job_id} started, waiting...")
        j.result()
        return j
    load_job = with_retries("staging load", _stage)
    log.info(f"    [staging] loaded {load_job.output_rows} rows into {spec['table']}_staging in {time.monotonic()-t:.1f}s")

    set_cols = [f.name for f in schema if f.name != key]
    set_clause = ",\n        ".join(f"{c} = S.{c}" for c in set_cols)
    merge_sql = f"""
    MERGE `{PROJECT_ID}.{DATASET}.{spec['table']}` T
    USING `{staging_ref}` S
    ON  T.{key} = S.{key}
    WHEN MATCHED THEN UPDATE SET
        {set_clause}
    WHEN NOT MATCHED THEN INSERT ROW
    """
    t = time.monotonic()
    log.info(f"    [merge] MERGE on {key} into {spec['table']}...")
    def _merge():
        j = bq.query(merge_sql, location=LOCATION)
        j.result()
        return j
    job = with_retries("merge", _merge)
    stats = job.dml_stats
    log.info(f"    [merge] inserted {stats.inserted_row_count}, updated {stats.updated_row_count} "
             f"in {time.monotonic()-t:.1f}s")

    bq.delete_table(staging_ref, not_found_ok=True)
    local_path.unlink(missing_ok=True)
    log.info(f"    [cleanup] dropped staging table + removed local NDJSON")
    log.info(f"  BQ LOAD [{tag}]: DONE -- +{stats.inserted_row_count} new / ~{stats.updated_row_count} updated")
    return stats.inserted_row_count, stats.updated_row_count

# ---------- Backfill checkpoint (crash-safe, resumable; mirrors GA4's resume intent) ----------
def _checkpoint_path(table):
    return WORK_DIR / f"{table}_backfill_done.json"

def load_checkpoint(table):
    p = _checkpoint_path(table)
    if p.exists():
        return set(json.loads(p.read_text(encoding="utf-8")))
    return set()

def save_checkpoint(table, done):
    _checkpoint_path(table).write_text(json.dumps(sorted(done)), encoding="utf-8")

def month_windows(since, until):
    """Yield (year, month, first_day, last_day) calendar months from `since` to `until`."""
    y, m = since.year, since.month
    while date(y, m, 1) <= until:
        first = date(y, m, 1)
        last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
        yield y, m, first, last
        y, m = y + (m == 12), (m % 12) + 1

# ---------- Drivers ----------
def run_backfill(bq, storage_client, spec, schema, since, until, loaded_at, page_limit, force):
    table = spec["table"]
    date_field = spec["backfill_date_field"]
    done = load_checkpoint(table) if not force else set()
    total_ins = total_upd = total_fetched = pages_total = 0
    months = list(month_windows(since, until))
    t_start = time.monotonic()
    log.info("#" * 60)
    log.info(f"BACKFILL PLAN: {len(months)} calendar month(s) {since} -> {until}, filtering on {date_field}")
    if done:
        log.info(f"  RESUMING: {len(done)} month(s) already checkpointed and will be skipped")
    log.info(f"  page size {page_limit} | MERGE key {spec['merge_key']} | force={force}")
    log.info("#" * 60)
    for i, (y, m, first, last) in enumerate(months, start=1):
        mk = f"{y:04d}-{m:02d}"
        if mk in done:
            log.info(f"[month {i:>3}/{len(months)}] {mk}: already done (checkpoint) -- skip")
            continue
        m_start = time.monotonic()
        log.info("=" * 60)
        log.info(f"[month {i:>3}/{len(months)}] {mk}  ({first} .. {last})")
        base_filter = {f"{date_field}From": f"{first} 00:00:00", f"{date_field}To": f"{last} 23:59:59"}
        cache_file = CACHE_DIR / f"{table}_{date_field}_{mk}.json"
        if cache_file.exists() and not force:
            records = json.loads(cache_file.read_text(encoding="utf-8"))
            pages = 0
            log.info(f"  CACHED: {len(records)} record(s) from {cache_file.name} (skipping fetch)")
        else:
            records, pages = paginate(STORE_URL, HEADERS, spec["action"], spec["response_key"],
                                      base_filter, spec["output_selector"], page_limit, label=f"{mk} backfill")
            cache_file.write_text(json.dumps(records), encoding="utf-8")
        total_fetched += len(records)
        pages_total += pages or 0
        ins, upd = load_window_to_bq(bq, storage_client, spec, schema, records, loaded_at, f"{table}_{mk}")
        total_ins += ins
        total_upd += upd
        done.add(mk)
        save_checkpoint(table, done)
        log.info(f"  -> {mk} done in {time.monotonic()-m_start:.1f}s "
                 f"(month: fetched {len(records)}, +{ins} new, ~{upd} updated)")
        log.info(f"  CUMULATIVE: {i}/{len(months)} months | fetched {total_fetched}, "
                 f"inserted {total_ins}, updated {total_upd} | {pages_total} pages | "
                 f"{(time.monotonic()-t_start)/60:.1f} min elapsed")
    log.info("#" * 60)
    log.info(f"BACKFILL COMPLETE: {len(months)} month(s) in {(time.monotonic()-t_start)/60:.1f} min")
    return total_fetched, total_ins, total_upd, pages_total

def run_incremental(bq, storage_client, spec, schema, loaded_at, page_limit):
    table = spec["table"]
    wm = read_watermark(bq, table)
    now_local = datetime.now(STORE_TZ).strftime("%Y-%m-%d %H:%M:%S")
    if wm:
        d_from = (datetime.strptime(wm, "%Y-%m-%d %H:%M:%S")
                  - timedelta(days=INCREMENTAL_OVERLAP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"[{table}] incremental: watermark MAX(date_updated)={wm} -> DateUpdatedFrom={d_from} (overlap {INCREMENTAL_OVERLAP_DAYS}d)")
    else:
        d_from = (datetime.now(STORE_TZ) - timedelta(days=BOOTSTRAP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        log.warning(f"[{table}] EMPTY table: bootstrapping last {BOOTSTRAP_DAYS}d ({d_from}..). "
                    f"Run with --backfill --since YYYY-MM-DD for full history.")
    base_filter = {"DateUpdatedFrom": d_from, "DateUpdatedTo": now_local}
    records, pages = paginate(STORE_URL, HEADERS, spec["action"], spec["response_key"],
                              base_filter, spec["output_selector"], page_limit, label="incremental")
    ins, upd = load_window_to_bq(bq, storage_client, spec, schema, records, loaded_at, f"{table}_incr")
    return len(records), ins, upd, pages, d_from

def run_dry(spec, since, page_limit):
    """Fetch page 0 (size=page_limit), parse, print a sample + counts. NO BigQuery I/O."""
    date_field = spec["backfill_date_field"]   # DatePlaced
    d_from = (since or (date.today() - timedelta(days=BOOTSTRAP_DAYS)))
    base_filter = {f"{date_field}From": f"{d_from} 00:00:00"}
    log.info(f"[{spec['table']}] DRY-RUN: {spec['action']} {date_field}From={d_from} page 0 (Limit {page_limit}), no BQ writes")
    records, _ = paginate(STORE_URL, HEADERS, spec["action"], spec["response_key"],
                          base_filter, spec["output_selector"], page_limit, label="dry-run", max_pages=1)
    loaded_at = datetime.now(STORE_TZ).strftime("%Y-%m-%d %H:%M:%S")
    parsed = [spec["transform"](r, loaded_at) for r in records]
    log.info(f"  fetched {len(records)} record(s); parsed {len(parsed)}")
    if parsed:
        sample = parsed[0]
        log.info(f"  sample order_id={sample['order_id']} email={sample['email']!r} "
                 f"username={sample['username']!r} lines={len(sample['order_lines'])} "
                 f"payments={len(sample['order_payments'])} grand_total={sample['grand_total']}")
        log.info("  --- parsed sample (pretty) ---\n" + json.dumps(sample, indent=2, default=str)[:3000])
    return len(records)

# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(description="Neto/Maropost -> BigQuery raw_neto.orders loader.")
    parser.add_argument("--backfill", action="store_true", help="Full history, calendar-month chunked + resumable.")
    parser.add_argument("--since", type=str, default=None, help="Backfill/dry-run start date YYYY-MM-DD.")
    parser.add_argument("--store-url", type=str, default=None, help=f"Override store URL (default {STORE_URL_ENV}).")
    parser.add_argument("--limit", type=int, default=PAGE_LIMIT, help=f"Neto page size / Filter.Limit (default {PAGE_LIMIT}).")
    parser.add_argument("--dry-run", action="store_true", help="Fetch+parse+log a sample; NO BigQuery reads/writes.")
    parser.add_argument("--force", action="store_true", help="Backfill: ignore the window cache + month checkpoint.")
    args = parser.parse_args()

    global STORE_URL, HEADERS
    STORE_URL = (args.store_url or STORE_URL_ENV).rstrip("/")
    since = date.fromisoformat(args.since) if args.since else None

    overall_start = time.monotonic()
    mode = "DRY-RUN" if args.dry_run else ("BACKFILL" if args.backfill else "INCREMENTAL")
    log.info("=" * 60)
    log.info(f"NETO ORDERS LOADER START ({mode})")
    log.info(f"  store URL ....... {STORE_URL}")
    log.info(f"  target .......... {PROJECT_ID}.{DATASET}.{ORDERS['table']}  (region {LOCATION})")
    log.info(f"  page size ....... {args.limit} (Neto Filter.Limit)")
    if args.backfill:
        log.info(f"  since ........... {since or BACKFILL_DEFAULT_SINCE}  (calendar-month chunks on DatePlaced)")
        log.info(f"  force ........... {args.force} (re-fetch cached months + ignore checkpoint)")
    elif not args.dry_run:
        log.info(f"  watermark ....... MAX(date_updated) - {INCREMENTAL_OVERLAP_DAYS}d overlap; empty table bootstraps {BOOTSTRAP_DAYS}d")
    log.info(f"  throttle ........ >= {MIN_REQUEST_INTERVAL}s between requests; retries {MAX_ATTEMPTS}x backoff on 429/5xx")
    log.info(f"  artifacts ....... {WORK_DIR}")
    log.info("=" * 60)

    log.info("Authenticating (Secret Manager via ADC)...")
    api_key = get_secret(SECRET_API_KEY)
    api_username = get_secret_optional(SECRET_USERNAME)
    HEADERS = build_headers(api_key, api_username)
    log.info(f"  headers ready: NETOAPI_KEY set, NETOAPI_USERNAME {'sent' if api_username else 'omitted (global key)'}")

    if args.dry_run:
        run_dry(ORDERS, since, args.limit)
        log.info("=" * 60)
        log.info(f"DRY-RUN DONE in {(time.monotonic()-overall_start)/60:.1f} min (no BigQuery writes)")
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    loaded_at = datetime.now(STORE_TZ).strftime("%Y-%m-%d %H:%M:%S")
    bq = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    storage_client = storage.Client(project=PROJECT_ID)
    ensure_dataset(bq)
    schema = ensure_table(bq, ORDERS).schema

    if args.backfill:
        until = datetime.now(STORE_TZ).date()
        bf_since = since or BACKFILL_DEFAULT_SINCE
        fetched, ins, upd, pages = run_backfill(bq, storage_client, ORDERS, schema, bf_since, until,
                                                loaded_at, args.limit, args.force)
        window = f"{bf_since}..{until} on {ORDERS['backfill_date_field']}"
    else:
        fetched, ins, upd, pages, d_from = run_incremental(bq, storage_client, ORDERS, schema, loaded_at, args.limit)
        window = f"DateUpdatedFrom={d_from}"

    elapsed = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"NETO ORDERS LOADER DONE in {elapsed:.1f} min")
    log.info(f"  {mode}: pages walked={pages}, fetched={fetched}, "
             f"inserted={ins}, updated={upd} | window: {window}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()

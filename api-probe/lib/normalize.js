// The ONE normalized row shape every connector returns. This is the contract
// the real executive-dashboard app will reuse, so keep it stable:
//
//   { campaign, channel, spend, clientSpent, impressions, budget, start, end }
//
//   campaign     – campaign name (string) or null
//   channel      – the media channel / platform label (string)
//   spend        – media cost in the account currency (number)
//   clientSpent  – what the client is billed; == spend unless there's a markup
//                  (e.g. ResetData bills Reddit at 2× — a per-connector rule)
//   impressions  – integer
//   budget       – campaign/line budget if the report exposes it, else null
//   start, end   – ISO yyyy-mm-dd bounds of the reporting window

export function normalizeRow({
  campaign = null,
  channel,
  spend = 0,
  clientSpent = null,
  impressions = 0,
  budget = null,
  start,
  end,
}) {
  const spendNum = toNum(spend);
  return {
    campaign: campaign ?? null,
    channel,
    spend: spendNum,
    clientSpent: clientSpent == null ? spendNum : toNum(clientSpent),
    impressions: Math.round(toNum(impressions)),
    budget: budget == null ? null : toNum(budget),
    start,
    end,
  };
}

function toNum(v) {
  if (v == null) return 0;
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/[, ]/g, ''));
  return Number.isFinite(n) ? n : 0;
}

const db = require('better-sqlite3')('data/brain-historical.db');
const r = db.prepare("UPDATE campaigns SET endDate='2026-05-28' WHERE name='Q2 PubSec' AND channel='LinkedIn'").run();
const check = db.prepare("SELECT name, channel, startDate, endDate FROM campaigns WHERE name='Q2 PubSec'").get();
console.log('changes:', r.changes, 'now:', check);
db.close();

'use strict';
/*
 * state-restore.js — download the Grid's SQLite state from GCS to a local path.
 *
 * Runs as a CHILD PROCESS (execFileSync from src/brain/persist.js) for one reason:
 * src/brain/db.js opens the database at require() time, and half the server's modules
 * require it at module scope, so the download has to finish BEFORE that first open.
 * @google-cloud/storage is async-only, so a synchronous child process is the ordering
 * guarantee. Restructuring server.js into an async boot would ripple through every
 * module that requires db.js.
 *
 *   node scripts/state-restore.js <bucket> <object> <destPath>
 *
 * Exit 0 = destPath now holds the restored DB.
 * Exit 3 = no such object yet (a first run) — the caller starts a fresh DB, which is
 *          the pre-existing behaviour, so a brand-new deployment is never blocked.
 * Exit 1 = a real failure (auth, network, permission). The caller logs it LOUDLY and
 *          continues on an empty DB rather than refusing to serve.
 *
 * Prints the object generation on stdout so the parent can use it as the
 * ifGenerationMatch precondition on its first write-back.
 */
const { Storage } = require('@google-cloud/storage');

const [, , bucketName, objectName, dest] = process.argv;
if (!bucketName || !objectName || !dest) {
  console.error('usage: state-restore.js <bucket> <object> <destPath>');
  process.exit(1);
}

(async () => {
  const file = new Storage().bucket(bucketName).file(objectName);
  const [exists] = await file.exists();
  if (!exists) process.exit(3);
  await file.download({ destination: dest });
  const [md] = await file.getMetadata();
  process.stdout.write(String(md.generation || ''));
  process.exit(0);
})().catch(e => {
  console.error(String((e && e.message) || e).slice(0, 500));
  process.exit(1);
});

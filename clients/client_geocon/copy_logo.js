const fs = require('fs');
const src = 'c:/Users/DELL/bidbrain-analytics/clients/client_geocon/creatives/Gateway-Braddon-Logo.png';
const dst = 'c:/Users/DELL/bidbrain-analytics/clients/client_geocon/dash/logo.png';
try {
  fs.copyFileSync(src, dst);
  const stat = fs.statSync(dst);
  fs.writeFileSync('c:/Users/DELL/bidbrain-analytics/clients/client_geocon/_copy_result.txt', 'SUCCESS: copied ' + stat.size + ' bytes to ' + dst);
} catch(e) {
  fs.writeFileSync('c:/Users/DELL/bidbrain-analytics/clients/client_geocon/_copy_result.txt', 'ERROR: ' + e.message);
}
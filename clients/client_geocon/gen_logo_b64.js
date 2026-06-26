const fs = require('fs');
const logoPath = 'c:/Users/DELL/bidbrain-analytics/clients/client_geocon/creatives/Gateway-Braddon-Logo.png';
const boardPath = 'c:/Users/DELL/bidbrain-analytics/clients/client_geocon/creatives/Gateway-Braddon-Brand-Board.png';
const outPath = 'c:/Users/DELL/bidbrain-analytics/clients/client_geocon/_logo_b64_output.txt';

try {
  const logoB64 = fs.readFileSync(logoPath).toString('base64');
  const boardB64 = fs.readFileSync(boardPath).toString('base64');
  const output = 'LOGO_B64_START\n' + logoB64 + '\nLOGO_B64_END\nBOARD_B64_START\n' + boardB64 + '\nBOARD_B64_END\n';
  fs.writeFileSync(outPath, output, 'utf-8');
} catch(e) {
  fs.writeFileSync(outPath, 'ERROR: ' + e.message + '\n', 'utf-8');
}
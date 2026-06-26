const fs = require('fs');
const html = fs.readFileSync('clients/client_geocon/dash/dashboard.html', 'utf-8');
const blocks = [];
const regex = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
let m;
while ((m = regex.exec(html)) !== null) {
  blocks.push(m[1]);
}
let result = '';
let allOk = true;
for (let i = 0; i < blocks.length; i++) {
  const body = blocks[i].trim();
  if (!body) continue;
  try {
    new Function(body);
    result += `Block ${i}: OK\n`;
  } catch(e) {
    allOk = false;
    result += `Block ${i}: ERROR: ${e.message}\n`;
  }
}
result = (allOk ? 'ALL OK\n' : 'HAS ERRORS\n') + result + `Total blocks: ${blocks.length}`;
fs.writeFileSync('_js_validation.txt', result, 'utf-8');
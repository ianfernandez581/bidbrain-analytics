const fs = require('fs');
const path = require('path');

// Read the logo PNG and convert to base64
const logoPath = path.join(__dirname, 'clients', 'client_geocon', 'creatives', 'Gateway-Braddon-Logo.png');
const boardPath = path.join(__dirname, 'clients', 'client_geocon', 'creatives', 'Gateway-Braddon-Brand-Board.png');

console.log('Logo path:', logoPath);
console.log('Logo exists:', fs.existsSync(logoPath));
console.log('Board exists:', fs.existsSync(boardPath));

if (fs.existsSync(logoPath)) {
  const logoB64 = fs.readFileSync(logoPath).toString('base64');
  const boardB64 = fs.existsSync(boardPath) ? fs.readFileSync(boardPath).toString('base64') : '';
  
  // Write base64 data to a JS snippet file in the dash folder
  const jsContent = `// AUTO-GENERATED — logo base64 data\nconst LOGO_DATA_URI = "data:image/png;base64,${logoB64}";\nconst BOARD_DATA_URI = "data:image/png;base64,${boardB64}";\n`;
  const outPath = path.join(__dirname, 'clients', 'client_geocon', 'dash', '_logo_data.js');
  fs.writeFileSync(outPath, jsContent, 'utf-8');
  console.log('Wrote logo data to:', outPath, '(' + jsContent.length + ' chars)');
  
  // Also copy the logo.png to dash folder for static serving
  const logoCopyPath = path.join(__dirname, 'clients', 'client_geocon', 'dash', 'logo.png');
  fs.copyFileSync(logoPath, logoCopyPath);
  console.log('Copied logo.png to:', logoCopyPath);
} else {
  console.log('ERROR: Logo file not found');
}
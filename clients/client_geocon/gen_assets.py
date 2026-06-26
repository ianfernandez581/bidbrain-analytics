import base64, os, sys

base = r'c:\Users\DELL\bidbrain-analytics\clients\client_geocon\creatives'
logo_path = os.path.join(base, 'Gateway-Braddon-Logo.png')
board_path = os.path.join(base, 'Gateway-Braddon-Brand-Board.png')
out_path = r'c:\Users\DELL\bidbrain-analytics\clients\client_geocon\dash\_assets.js'

with open(logo_path, 'rb') as f:
    logo_b64 = base64.b64encode(f.read()).decode('ascii')

with open(board_path, 'rb') as f:
    board_b64 = base64.b64encode(f.read()).decode('ascii')

content = '// AUTO-GENERATED. Brand assets as base64.\n'
content += 'const LOGO_B64 = "data:image/png;base64,' + logo_b64 + '";\n'
content += 'const BOARD_B64 = "data:image/png;base64,' + board_b64 + '";\n'

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(content)

# Also extract colors using pure python - read PNG manually for basic color extraction
# Use a simpler approach - just get file sizes
print('Logo bytes:', os.path.getsize(logo_path))
print('Board bytes:', os.path.getsize(board_path))
print('Wrote:', out_path)
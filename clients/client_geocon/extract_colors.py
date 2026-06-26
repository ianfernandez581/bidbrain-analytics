from PIL import Image
import collections
import os

base = r'c:\Users\DELL\bidbrain-analytics\clients\client_geocon\creatives'
img_path = os.path.join(base, 'Gateway-Braddon-Brand-Board.png')
logo_path = os.path.join(base, 'Gateway-Braddon-Logo.png')
out_path = r'c:\Users\DELL\bidbrain-analytics\clients\client_geocon\dash\_brand_analysis.txt'

lines = []

# Brand board
img = Image.open(img_path).convert('RGB')
lines.append(f'Brand Board Size: {img.size}')
img_small = img.resize((100, 100))
pixels = list(img_small.getdata())
counter = collections.Counter()
for r, g, b in pixels:
    qr, qg, qb = (r//16)*16, (g//16)*16, (b//16)*16
    counter[(qr, qg, qb)] += 1
lines.append('')
lines.append('Top 30 brand board colors (quantized /16):')
for color, count in counter.most_common(30):
    hexc = '#{:02X}{:02X}{:02X}'.format(*color)
    pct = count / len(pixels) * 100
    lines.append(f'  {hexc}  rgb{color}  {pct:.1f}%')

# Logo
logo = Image.open(logo_path).convert('RGBA')
lines.append('')
lines.append(f'Logo Size: {logo.size}')
logo_small = logo.resize((100, 100))
lpixels = list(logo_small.getdata())
lcounter = collections.Counter()
for r, g, b, a in lpixels:
    if a < 128:
        continue
    qr, qg, qb = (r//16)*16, (g//16)*16, (b//16)*16
    lcounter[(qr, qg, qb)] += 1
lines.append('')
lines.append('Top 20 logo colors (non-transparent, quantized /16):')
for color, count in lcounter.most_common(20):
    hexc = '#{:02X}{:02X}{:02X}'.format(*color)
    pct = count / sum(lcounter.values()) * 100
    lines.append(f'  {hexc}  rgb{color}  {pct:.1f}%')

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Done')
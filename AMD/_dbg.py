import re, sys
sys.path.insert(0, r'e:\Quant\Quant\Investment Research\research_app')
from pathlib import Path
from core.text_mining import _extract_main_doc
from core.concentration import _parse_segments, _parse_concentration, KNOWN_SEGMENTS

path = Path(r'e:\Quant\Quant\Investment Research\AMD\10Q_10K\amd\10-K\0000002488-26-000018.txt')
raw  = path.read_text(encoding='utf-8', errors='ignore')
text = _extract_main_doc(raw)

# 1. Check what text surrounds the segment table
idx = text.find('Data Center')
sys.stdout.buffer.write(b'--- Context around "Data Center" ---\n')
sys.stdout.buffer.write(text[idx:idx+300].encode('utf-8', errors='replace'))
sys.stdout.buffer.write(b'\n\n')

# 2. Manual regex test
pat = re.compile(r'Data Center\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)', re.IGNORECASE)
m = pat.search(text)
sys.stdout.buffer.write(f'Segment regex match: {m}\n'.encode())
if m:
    sys.stdout.buffer.write(f'Groups: {m.groups()}\n'.encode())

# 3. Check concentration pattern
cpat = re.compile(r'accounted\s+for\s+(?:approximately\s+)?(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)
for m2 in cpat.finditer(text):
    ctx = text[max(0, m2.start()-100):m2.end()+100]
    sys.stdout.buffer.write(b'Conc: ')
    sys.stdout.buffer.write(ctx.encode('utf-8', errors='replace'))
    sys.stdout.buffer.write(b'\n')

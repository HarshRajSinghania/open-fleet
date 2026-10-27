import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
REPO = GEN_DIR.parents[3]


def load_mission_specs() -> list[dict]:
    sys.path.insert(0, str(GEN_DIR))
    import specs as _specs
    from specs_missions import MISSIONS
    _ = _specs
    return MISSIONS


def esc(s: str) -> str:
    return (
        str(s)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split(' ')
    lines: list[str] = []
    cur = ''
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += ' ' + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def palette(theme: str) -> dict[str, str]:
    dark = theme == 'dark'
    return {
        'dark': '1' if dark else '',
        'bg': '#0B1220' if dark else '#F5F8FF',
        'nodeFill': '#121B2D' if dark else '#FFFFFF',
        'textPrimary': '#F2F6FF' if dark else '#0B1220',
        'textSecondary': '#8A9BB8' if dark else '#4F5E78',
        'blue': '#4C8DFF' if dark else '#2F6FEB',
        'green': '#3DDC84' if dark else '#1F9D55',
        'amber': '#FFB84C' if dark else '#C77700',
        'red': '#FF5C5C' if dark else '#D93B3B',
        'grey': '#8A9BB8' if dark else '#4F5E78',
        'hexFillGreen': '#0E2420' if dark else '#EBFBEE',
        'hexFillAmber': '#231D14' if dark else '#FFF8EB',
        'hexFillRed': '#26151B' if dark else '#FFF0F0',
        'hexFillGrey': '#172236' if dark else '#F0F4FA',
        'constLine': '#1E3152' if dark else '#D0DDF2',
        'constDot': '#3B6BC4' if dark else '#6A94E0',
    }


def render_hex_badge(x: float, y: float, w: float, h: float, label: str, color_name: str, p: dict[str, str], font_size: float) -> str:
    stroke = p.get(color_name, p['blue'])
    fill_map = {
        'green': p['hexFillGreen'],
        'amber': p['hexFillAmber'],
        'red': p['hexFillRed'],
        'grey': p['hexFillGrey'],
    }
    fill = fill_map.get(color_name, p['nodeFill'])
    tip = 14.0
    cy = y + h / 2.0
    pts = f"{x:.1f},{cy:.1f} {x + tip:.1f},{y:.1f} {x + w - tip:.1f},{y:.1f} {x + w:.1f},{cy:.1f} {x + w - tip:.1f},{y + h:.1f} {x + tip:.1f},{y + h:.1f}"
    return f'''
    <polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="2.2" stroke-linejoin="round" />
    <text x="{x + w / 2.0:.1f}" y="{cy + font_size * 0.35:.1f}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="{font_size:.1f}" font-weight="700" fill="{stroke}">{esc(label)}</text>'''


def build_mission_svg(spec: dict, theme: str) -> str:
    p = palette(theme)
    dark = bool(p['dark'])
    c = spec['contract']
    mid = spec['id'].removeprefix('missions/')
    outcome = c['outcome']

    # Single-line title sizing so `<id> — <outcome>` never wraps to 2 lines
    full_title = f"{mid} — {outcome}"
    if len(full_title) <= 68:
        title_fs = 27.0
    elif len(full_title) <= 78:
        title_fs = 24.5
    elif len(full_title) <= 88:
        title_fs = 22.0
    else:
        title_fs = 19.8

    # Wrap large body text for panels 1, 2, 4 (panel inner width = 646px)
    give_lines = wrap_text(c['give'], 37)
    gates_lines = wrap_text(c['gates'], 37)
    stops_lines = wrap_text(c['stops'], 37)

    def render_body_lines(lines: list[str], x: float, panel_y: float) -> str:
        n = len(lines)
        fs = 24.5 if n <= 3 else 22.0
        lh = 36.0 if n <= 3 else 32.0
        # Center vertically in [panel_y + 78 .. panel_y + 298] -> center_y = panel_y + 188
        total_h = (n - 1) * lh
        start_y = panel_y + 190.0 - total_h / 2.0
        tp = p['textPrimary']
        return '\n  '.join(
            f'<text x="{x}" y="{start_y + i * lh:.1f}" font-family="\'JetBrains Mono\', monospace" font-size="{fs}" font-weight="700" fill="{tp}">{esc(line)}</text>'
            for i, line in enumerate(lines)
        )

    # Panel 3: YOU GET BACK -> Hexagon state row(s) + wrapped muted artifacts
    states = re.findall(r'a hexagon ([A-Z0-9_-]+) outlined (green|amber|red|grey)', spec['prompt'])
    assert states, f"Failed to parse states from: {spec['prompt']}"
    total_chars = sum(len(s[0]) for s in states)
    if total_chars <= 26:
        hex_fs = 16.0
        char_w = 10.0
        pad_x = 32.0
        gap = 12.0
        hex_h = 44.0
    elif total_chars <= 38:
        hex_fs = 14.5
        char_w = 9.0
        pad_x = 28.0
        gap = 10.0
        hex_h = 40.0
    else:
        hex_fs = 13.5
        char_w = 8.3
        pad_x = 24.0
        gap = 10.0
        hex_h = 38.0

    hex_elems = []
    cur_x = 100.0
    hex_y = 524.0
    max_x = 746.0
    rows_used = 1
    for st_label, st_color in states:
        w = len(st_label) * char_w + pad_x
        if cur_x > 100.0 and cur_x + w > max_x:
            cur_x = 100.0
            hex_y += hex_h + 10.0
            rows_used += 1
        hex_elems.append(render_hex_badge(cur_x, hex_y, w, hex_h, st_label, st_color, p, hex_fs))
        cur_x += w + gap

    art_lines = wrap_text(c['artifacts'], 48)
    art_fs = 17.5 if (len(art_lines) <= 3 and rows_used == 1) else 16.0
    art_lh = 26.0 if (len(art_lines) <= 3 and rows_used == 1) else 23.5
    art_start_y = hex_y + hex_h + (36.0 if rows_used == 1 else 26.0)
    ts = p['textSecondary']
    art_svg = '\n  '.join(
        f'<text x="100" y="{art_start_y + i * art_lh:.1f}" font-family="\'JetBrains Mono\', monospace" font-size="{art_fs}" font-weight="400" fill="{ts}">{esc(line)}</text>'
        for i, line in enumerate(art_lines)
    )

    phases = c['phases']
    if len(phases) <= 78:
        phase_fs = 16.5
    elif len(phases) <= 92:
        phase_fs = 15.0
    else:
        phase_fs = 13.8

    tl_nodes = [[1472, 24], [1528, 18], [1496, 58], [1564, 48]]
    tl_edges = [[0, 1], [0, 2], [1, 2], [1, 3], [2, 3]]
    br_nodes = [[28, 868], [76, 842], [114, 875]]
    br_edges = [[0, 1], [1, 2]]

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <filter id="glowBlue" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="{6 if dark else 4}" flood-color="{p['blue']}" flood-opacity="{0.26 if dark else 0.14}" />
    </filter>
  </defs>

  <rect width="1600" height="900" fill="{p['bg']}" />

  <!-- Subtle corner constellation -->
  <g stroke="{p['constLine']}" stroke-width="1.2" opacity="0.55">
    {''.join(f'<line x1="{tl_nodes[a][0]}" y1="{tl_nodes[a][1]}" x2="{tl_nodes[b][0]}" y2="{tl_nodes[b][1]}" />' for a, b in tl_edges)}
    {''.join(f'<line x1="{br_nodes[a][0]}" y1="{br_nodes[a][1]}" x2="{br_nodes[b][0]}" y2="{br_nodes[b][1]}" />' for a, b in br_edges)}
  </g>
  <g fill="{p['constDot']}" opacity="0.55">
    {''.join(f'<circle cx="{x}" cy="{y}" r="2.2" />' for x, y in tl_nodes + br_nodes)}
  </g>

  <!-- Single-line top-left mission title -->
  <text x="68" y="72" xml:space="preserve" font-family="'JetBrains Mono', monospace" font-size="{title_fs}" font-weight="700" fill="{p['textPrimary']}">{esc(mid)}<tspan font-weight="400" fill="{p['textSecondary']}"> &#8212; {esc(outcome)}</tspan></text>

  <!-- Panel 1: YOU GIVE IT (top-left) -->
  <rect x="68" y="108" width="710" height="320" rx="16" fill="{p['nodeFill']}" stroke="{p['blue']}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="100" y="152" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="600" fill="{p['textSecondary']}" letter-spacing="1.2">YOU GIVE IT</text>
  {render_body_lines(give_lines, 100, 108)}

  <!-- Panel 2: IT INTERRUPTS YOU FOR (top-right) -->
  <rect x="822" y="108" width="710" height="320" rx="16" fill="{p['nodeFill']}" stroke="{p['blue']}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="854" y="152" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="600" fill="{p['textSecondary']}" letter-spacing="1.2">IT INTERRUPTS YOU FOR</text>
  {render_body_lines(gates_lines, 854, 108)}

  <!-- Panel 3: YOU GET BACK (bottom-left) -->
  <rect x="68" y="458" width="710" height="320" rx="16" fill="{p['nodeFill']}" stroke="{p['blue']}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="100" y="502" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="600" fill="{p['textSecondary']}" letter-spacing="1.2">YOU GET BACK</text>
  {''.join(hex_elems)}
  {art_svg}

  <!-- Panel 4: IT STOPS AT (bottom-right) -->
  <rect x="822" y="458" width="710" height="320" rx="16" fill="{p['nodeFill']}" stroke="{p['blue']}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="854" y="502" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="600" fill="{p['textSecondary']}" letter-spacing="1.2">IT STOPS AT</text>
  {render_body_lines(stops_lines, 854, 458)}

  <!-- Bottom phase strip -->
  <text x="800" y="838" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="{phase_fs}" font-weight="500" fill="{p['textSecondary']}" letter-spacing="0.6">{esc(phases)}</text>

  <!-- Bottom-right 3-node constellation signature mark -->
  <g stroke="{p['blue']}" stroke-width="1.5" opacity="{0.65 if dark else 0.55}">
    <line x1="1532" y1="868" x2="1552" y2="854" />
    <line x1="1552" y1="854" x2="1574" y2="863" />
  </g>
  <g fill="{p['blue']}" opacity="{0.85 if dark else 0.75}">
    <circle cx="1532" cy="868" r="2.6" />
    <circle cx="1552" cy="854" r="3.1" />
    <circle cx="1574" cy="863" r="2.6" />
  </g>
</svg>'''


def main() -> None:
    jobs = []
    for spec in load_mission_specs():
        dark_out = str(REPO / spec['out'])
        light_out = dark_out[:-4] + '-light.jpg'
        jobs.append({'out': dark_out, 'svg': build_mission_svg(spec, 'dark')})
        jobs.append({'out': light_out, 'svg': build_mission_svg(spec, 'light')})

    node_script = """
const sharp = require('sharp');
const fs = require('fs');
async function run() {
  const jobs = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
  for (const j of jobs) {
    await sharp(Buffer.from(j.svg))
      .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
      .toFile(j.out);
  }
  console.log(`Rendered ${jobs.length} mission contract cards successfully.`);
}
run().catch(e => { console.error(e); process.exit(1); });
"""
    env = os.environ.copy()
    local_node_modules = str(GEN_DIR / 'node_modules')
    existing_node_path = env.get('NODE_PATH', '')
    env['NODE_PATH'] = (
        f'{local_node_modules}{os.pathsep}{existing_node_path}'
        if existing_node_path
        else local_node_modules
    )

    with tempfile.NamedTemporaryFile(
        mode='w',
        prefix='mission_svg_jobs_',
        suffix='.json',
        delete=False,
        encoding='utf-8',
    ) as tmp_file:
        json.dump(jobs, tmp_file)
        jobs_path = Path(tmp_file.name)

    try:
        subprocess.run(
            ['node', '-e', node_script, str(jobs_path)],
            cwd=str(GEN_DIR),
            env=env,
            check=True,
        )
    finally:
        jobs_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

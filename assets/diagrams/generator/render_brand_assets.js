const sharp = require('sharp');
const path = require('path');

const REPO = path.resolve(__dirname, '../../..');

function hexPoints(cx, cy, r, rotationDeg = 0) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = ((rotationDeg + i * 60) * Math.PI) / 180;
    pts.push(`${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`);
  }
  return pts.join(' ');
}

function renderVessel(cx, cy, scale, angleDeg, theme) {
  // Sleek multi-faceted autonomous-agent diamond-hexagonal vessel pointing right (+x before rotation)
  const isDark = theme === 'dark';
  const stroke = isDark ? '#4C8DFF' : '#2F6FEB';
  const brightStroke = isDark ? '#8AB8FF' : '#1D4ED8';
  const fillTop = isDark ? '#182642' : '#FFFFFF';
  const fillBottom = isDark ? '#0F182B' : '#EAF1FF';
  const fillRear = isDark ? '#121D33' : '#DCE8FF';
  const coreFill = isDark ? '#68A8FF' : '#2F6FEB';
  const trailGradId = `trail_${theme}`;

  // Vessel local coordinates (nose at +46*s, tail at -44*s, wingtips at y=+-24*s)
  const s = scale;
  const nose = `${48 * s},0`;
  const topShoulder = `${10 * s},${-23 * s}`;
  const botShoulder = `${10 * s},${23 * s}`;
  const topRear = `${-30 * s},${-15 * s}`;
  const botRear = `${-30 * s},${15 * s}`;
  const tailNotch = `${-18 * s},0`;
  const midSpine = `${14 * s},0`;

  return `
  <g transform="translate(${cx}, ${cy}) rotate(${angleDeg})">
    <!-- Velocity trail -->
    <polygon points="${-155 * s},${-6 * s} ${-22 * s},${-13 * s} ${-16 * s},0 ${-22 * s},${13 * s} ${-155 * s},${6 * s}" fill="url(#${trailGradId})" opacity="${isDark ? 0.78 : 0.65}" />
    <line x1="${-175 * s}" y1="0" x2="${-20 * s}" y2="0" stroke="${stroke}" stroke-width="${1.8 * s}" stroke-dasharray="${8 * s} ${6 * s}" opacity="${isDark ? 0.7 : 0.55}" />
    <line x1="${-125 * s}" y1="${-9 * s}" x2="${-30 * s}" y2="${-9 * s}" stroke="${stroke}" stroke-width="${1.1 * s}" opacity="${isDark ? 0.45 : 0.35}" />
    <line x1="${-125 * s}" y1="${9 * s}" x2="${-30 * s}" y2="${9 * s}" stroke="${stroke}" stroke-width="${1.1 * s}" opacity="${isDark ? 0.45 : 0.35}" />

    <!-- Outer glow silhouette -->
    <polygon points="${nose} ${topShoulder} ${topRear} ${tailNotch} ${botRear} ${botShoulder}"
      fill="none" stroke="${stroke}" stroke-width="${3.2 * s}" opacity="${isDark ? 0.45 : 0.25}" filter="url(#blueGlow)" />

    <!-- Facet 1: Top forward wing -->
    <polygon points="${nose} ${topShoulder} ${midSpine}"
      fill="${fillTop}" stroke="${brightStroke}" stroke-width="${1.8 * s}" stroke-linejoin="round" />
    <!-- Facet 2: Bottom forward wing -->
    <polygon points="${nose} ${midSpine} ${botShoulder}"
      fill="${fillBottom}" stroke="${stroke}" stroke-width="${1.8 * s}" stroke-linejoin="round" />
    <!-- Facet 3: Top rear hull -->
    <polygon points="${topShoulder} ${topRear} ${tailNotch} ${midSpine}"
      fill="${fillRear}" stroke="${stroke}" stroke-width="${1.6 * s}" stroke-linejoin="round" />
    <!-- Facet 4: Bottom rear hull -->
    <polygon points="${midSpine} ${tailNotch} ${botRear} ${botShoulder}"
      fill="${fillBottom}" stroke="${stroke}" stroke-width="${1.6 * s}" stroke-linejoin="round" />

    <!-- Inner cockpit core diamond -->
    <polygon points="${24 * s},0 ${8 * s},${-7 * s} ${-4 * s},0 ${8 * s},${7 * s}"
      fill="${coreFill}" opacity="${isDark ? 0.9 : 0.85}" />
    <circle cx="${10 * s}" cy="0" r="${2.6 * s}" fill="${isDark ? '#E6F1FF' : '#FFFFFF'}" />
  </g>`;
}

function renderVerifiedSeal(cx, cy, scale, theme) {
  const isDark = theme === 'dark';
  const green = isDark ? '#3DDC84' : '#1F9D55';
  const innerFill = isDark ? '#0E2422' : '#E8FBF0';
  const coreFill = isDark ? '#12312C' : '#D3F8E2';
  const s = scale;

  // Tick mark points relative to center
  const p1 = `${cx - 22 * s},${cy + 2 * s}`;
  const p2 = `${cx - 6 * s},${cy + 18 * s}`;
  const p3 = `${cx + 26 * s},${cy - 16 * s}`;

  return `
  <g>
    <!-- Outer dashed orbital ring -->
    <circle cx="${cx}" cy="${cy}" r="${88 * s}" fill="none" stroke="${green}" stroke-width="${1.4 * s}" stroke-dasharray="${6 * s} ${6 * s}" opacity="${isDark ? 0.5 : 0.45}" />

    <!-- Outer hexagon ring -->
    <polygon points="${hexPoints(cx, cy, 74 * s, 30)}"
      fill="${innerFill}" stroke="${green}" stroke-width="${3.2 * s}" stroke-linejoin="round" filter="url(#greenGlow)" />

    <!-- Middle hexagon facet lines -->
    <polygon points="${hexPoints(cx, cy, 58 * s, 30)}"
      fill="${coreFill}" stroke="${green}" stroke-width="${1.8 * s}" stroke-linejoin="round" opacity="0.92" />

    <!-- Subtle corner vertex nodes on outer hex -->
    ${[0, 1, 2, 3, 4, 5].map(i => {
      const a = ((30 + i * 60) * Math.PI) / 180;
      const vx = (cx + 74 * s * Math.cos(a)).toFixed(2);
      const vy = (cy + 74 * s * Math.sin(a)).toFixed(2);
      return `<circle cx="${vx}" cy="${vy}" r="${3.2 * s}" fill="${isDark ? '#A7F3D0' : '#1F9D55'}" />`;
    }).join('\n    ')}

    <!-- Crisp geometric checkmark -->
    <polyline points="${p1} ${p2} ${p3}"
      fill="none" stroke="${isDark ? '#E6FFF2' : '#0F6E38'}" stroke-width="${7.5 * s}" stroke-linecap="round" stroke-linejoin="round" filter="url(#greenGlow)" />
    <polyline points="${p1} ${p2} ${p3}"
      fill="none" stroke="${isDark ? '#FFFFFF' : '#15803D'}" stroke-width="${4.5 * s}" stroke-linecap="round" stroke-linejoin="round" />
  </g>`;
}

function buildHeroSvg(theme) {
  const isDark = theme === 'dark';
  const bg = isDark ? '#0B1220' : '#F5F8FF';
  const textPrimary = isDark ? '#F2F6FF' : '#0B1220';
  const textSecondary = isDark ? '#8A9BB8' : '#4F5E78';
  const blue = isDark ? '#4C8DFF' : '#2F6FEB';
  const green = isDark ? '#3DDC84' : '#1F9D55';
  const constLine = isDark ? '#243B61' : '#C5D5F0';
  const constDot = isDark ? '#4C8DFF' : '#5B8DEF';

  // Constellation background points on right half (identical positions in dark & light)
  const cNodes = [
    [980, 140], [1140, 95], [1310, 130], [1480, 88], [1690, 125], [1860, 175],
    [1040, 290], [1230, 250], [1430, 225], [1610, 260], [1820, 310],
    [960, 560], [1160, 610], [1380, 575], [1590, 620], [1790, 565], [1900, 460],
    [1080, 735], [1290, 755], [1510, 730], [1730, 745], [1885, 695],
  ];
  const cEdges = [
    [0, 1], [1, 2], [2, 3], [3, 4], [4, 5],
    [0, 6], [1, 7], [2, 8], [3, 8], [4, 9], [5, 10],
    [6, 7], [7, 8], [8, 9], [9, 10],
    [11, 12], [12, 13], [13, 14], [14, 15], [15, 16],
    [11, 17], [12, 18], [13, 19], [14, 19], [15, 20], [15, 21],
    [17, 18], [18, 19], [19, 20], [20, 21],
    [6, 11], [10, 16]
  ];

  const sealX = 1745;
  const sealY = 424;

  // 4 vessels converging left-to-right toward the verified seal
  const vessels = [
    { x: 1190, y: 195, scale: 0.95, angle: 16, path: `M 1235 208 C 1410 255, 1545 340, 1648 392` },
    { x: 1055, y: 345, scale: 1.08, angle: 7,  path: `M 1108 351 C 1310 375, 1490 402, 1642 414` },
    { x: 1125, y: 515, scale: 1.05, angle: -7, path: `M 1176 508 C 1355 482, 1500 452, 1642 435` },
    { x: 1240, y: 665, scale: 0.92, angle: -18, path: `M 1283 650 C 1440 595, 1555 512, 1648 456` },
  ];

  return `<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="848" viewBox="0 0 2000 848">
  <defs>
    <linearGradient id="trail_${theme}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${blue}" stop-opacity="0" />
      <stop offset="100%" stop-color="${blue}" stop-opacity="${isDark ? 0.55 : 0.42}" />
    </linearGradient>
    <linearGradient id="dagStroke_${theme}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${blue}" stop-opacity="${isDark ? 0.75 : 0.65}" />
      <stop offset="75%" stop-color="${blue}" stop-opacity="${isDark ? 0.95 : 0.85}" />
      <stop offset="100%" stop-color="${green}" stop-opacity="${isDark ? 0.95 : 0.9}" />
    </linearGradient>
    <filter id="blueGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <filter id="greenGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="7" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <filter id="greenHalo" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="28" />
    </filter>
    <marker id="arrow_${theme}" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${green}" />
    </marker>
  </defs>

  <!-- Canvas background -->
  <rect width="2000" height="848" fill="${bg}" />

  <!-- Constellation node-graph on right half -->
  <g stroke="${constLine}" stroke-width="1.2" opacity="${isDark ? 0.55 : 0.65}">
    ${cEdges.map(([a, b]) => `<line x1="${cNodes[a][0]}" y1="${cNodes[a][1]}" x2="${cNodes[b][0]}" y2="${cNodes[b][1]}" />`).join('\n    ')}
  </g>
  <g fill="${constDot}" opacity="${isDark ? 0.55 : 0.5}">
    ${cNodes.map(([x, y], idx) => `<circle cx="${x}" cy="${y}" r="${idx % 3 === 0 ? 3.5 : 2.3}" />`).join('\n    ')}
  </g>

  <!-- Directed DAG convergence trajectories -->
  <g fill="none" stroke="url(#dagStroke_${theme})" stroke-width="2.4" marker-end="url(#arrow_${theme})">
    ${vessels.map(v => `<path d="${v.path}" />`).join('\n    ')}
  </g>
  <!-- Secondary fine telemetry arcs between vessels -->
  <g fill="none" stroke="${blue}" stroke-width="1.2" stroke-dasharray="5 6" opacity="${isDark ? 0.42 : 0.35}">
    <path d="M 1190 195 L 1055 345 L 1125 515 L 1240 665" />
    <path d="M 1395 272 L 1365 385 L 1390 475 L 1445 572" />
  </g>
  <g fill="${blue}" opacity="${isDark ? 0.85 : 0.75}">
    <circle cx="1395" cy="272" r="3.5" />
    <circle cx="1365" cy="385" r="3.5" />
    <circle cx="1390" cy="475" r="3.5" />
    <circle cx="1445" cy="572" r="3.5" />
  </g>

  <!-- 4 Autonomous-agent vessels -->
  ${vessels.map(v => renderVessel(v.x, v.y, v.scale, v.angle, theme)).join('\n')}

  <!-- Glowing emerald verified hexagonal seal -->
  ${renderVerifiedSeal(sealX, sealY, 1.18, theme)}

  <!-- Left half typography: identical positions and line-breaks in dark and light -->
  <text x="135" y="388" font-family="'JetBrains Mono', monospace" font-size="96" font-weight="700" fill="${textPrimary}" letter-spacing="-1.5">open-fleet</text>
  <text x="138" y="468" font-family="'JetBrains Mono', monospace" font-size="27" font-weight="400" fill="${textSecondary}">Give a mission a goal. Come back to an</text>
  <text x="138" y="510" font-family="'JetBrains Mono', monospace" font-size="27" font-weight="400" fill="${textSecondary}">evidence-verified end state.</text>
</svg>`;
}

function buildSocialPreviewSvg() {
  const theme = 'dark';
  const bg = '#0B1220';
  const blue = '#4C8DFF';
  const green = '#3DDC84';
  const constLine = '#22385E';
  const constDot = '#4C8DFF';

  // Constellation nodes around outer margin
  const cNodes = [
    [180, 140], [360, 95], [540, 165], [240, 310], [450, 290],
    [2020, 120], [2230, 95], [2390, 160], [2120, 285], [2330, 310],
    [170, 960], [340, 1080], [560, 1020], [260, 820], [470, 860],
    [2010, 1040], [2210, 1095], [2390, 980], [2100, 850], [2310, 820]
  ];
  const cEdges = [
    [0, 1], [1, 2], [0, 3], [1, 4], [2, 4], [3, 4],
    [5, 6], [6, 7], [5, 8], [6, 8], [7, 9], [8, 9],
    [10, 11], [11, 12], [10, 13], [13, 14], [12, 14], [11, 14],
    [15, 16], [16, 17], [15, 18], [18, 19], [17, 19], [16, 18]
  ];

  const sealX = 1690;
  const sealY = 825;

  const vessels = [
    { x: 960,  y: 635, scale: 1.05, angle: 14,  path: `M 1010 648 C 1220 700, 1410 755, 1572 795` },
    { x: 810,  y: 765, scale: 1.15, angle: 5,   path: `M 868 770 C 1120 792, 1360 808, 1565 816` },
    { x: 860,  y: 915, scale: 1.12, angle: -6,  path: `M 915 908 C 1150 882, 1365 858, 1565 836` },
    { x: 1010, y: 1040, scale: 1.0, angle: -16, path: `M 1058 1025 C 1255 968, 1425 905, 1572 856` },
  ];

  return `<svg xmlns="http://www.w3.org/2000/svg" width="2560" height="1280" viewBox="0 0 2560 1280">
  <defs>
    <linearGradient id="trail_dark" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${blue}" stop-opacity="0" />
      <stop offset="100%" stop-color="${blue}" stop-opacity="0.55" />
    </linearGradient>
    <linearGradient id="dagStroke_dark" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${blue}" stop-opacity="0.78" />
      <stop offset="75%" stop-color="${blue}" stop-opacity="0.95" />
      <stop offset="100%" stop-color="${green}" stop-opacity="0.95" />
    </linearGradient>
    <filter id="blueGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <filter id="greenGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <filter id="greenHalo" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="32" />
    </filter>
    <marker id="arrow_dark" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${green}" />
    </marker>
  </defs>

  <rect width="2560" height="1280" fill="${bg}" />

  <!-- Outer constellation corners -->
  <g stroke="${constLine}" stroke-width="1.4" opacity="0.55">
    ${cEdges.map(([a, b]) => `<line x1="${cNodes[a][0]}" y1="${cNodes[a][1]}" x2="${cNodes[b][0]}" y2="${cNodes[b][1]}" />`).join('\n    ')}
  </g>
  <g fill="${constDot}" opacity="0.55">
    ${cNodes.map(([x, y], idx) => `<circle cx="${x}" cy="${y}" r="${idx % 2 === 0 ? 3.8 : 2.5}" />`).join('\n    ')}
  </g>

  <!-- Centered Wordmark and Tagline -->
  <text x="1280" y="310" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="132" font-weight="700" fill="#F2F6FF" letter-spacing="-2">open-fleet</text>
  <text x="1280" y="405" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="34" font-weight="400" fill="#8A9BB8">Autonomous engineering fleets for coding agents — SHA-verified outcomes</text>

  <!-- Directed DAG convergence trajectories -->
  <g fill="none" stroke="url(#dagStroke_dark)" stroke-width="2.8" marker-end="url(#arrow_dark)">
    ${vessels.map(v => `<path d="${v.path}" />`).join('\n    ')}
  </g>
  <g fill="none" stroke="${blue}" stroke-width="1.4" stroke-dasharray="6 7" opacity="0.42">
    <path d="M 960 635 L 810 765 L 860 915 L 1010 1040" />
    <path d="M 1220 704 L 1175 790 L 1195 876 L 1265 955" />
  </g>
  <g fill="${blue}" opacity="0.85">
    <circle cx="1220" cy="704" r="4" />
    <circle cx="1175" cy="790" r="4" />
    <circle cx="1195" cy="876" r="4" />
    <circle cx="1265" cy="955" r="4" />
  </g>

  <!-- 4 Autonomous-agent vessels -->
  ${vessels.map(v => renderVessel(v.x, v.y, v.scale, v.angle, theme)).join('\n')}

  <!-- Glowing emerald verified hexagonal seal -->
  ${renderVerifiedSeal(sealX, sealY, 1.32, theme)}

  <!-- Subtle bottom-right 3-node constellation signature mark -->
  <g stroke="#4C8DFF" stroke-width="1.5" opacity="0.55">
    <line x1="2465" y1="1232" x2="2490" y2="1215" />
    <line x1="2490" y1="1215" x2="2518" y2="1226" />
  </g>
  <g fill="#4C8DFF" opacity="0.75">
    <circle cx="2465" cy="1232" r="3.2" />
    <circle cx="2490" cy="1215" r="3.8" />
    <circle cx="2518" cy="1226" r="3.2" />
  </g>
</svg>`;
}

function buildPluginIconSvg() {
  const theme = 'dark';
  const bg = '#0B1220';
  const blue = '#4C8DFF';
  const green = '#3DDC84';

  const sealX = 512;
  const sealY = 235;

  // 4 vessels in symmetric V-formation converging upward toward the emerald hexagonal seal
  const vessels = [
    { x: 215, y: 745, scale: 1.32, angle: -65, path: `M 235 695 C 295 545, 365 420, 445 318` },
    { x: 405, y: 650, scale: 1.42, angle: -78, path: `M 418 592 C 445 480, 468 395, 488 332` },
    { x: 619, y: 650, scale: 1.42, angle: -102, path: `M 606 592 C 579 480, 556 395, 536 332` },
    { x: 809, y: 745, scale: 1.32, angle: -115, path: `M 789 695 C 729 545, 659 420, 579 318` },
  ];

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="trail_dark" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${blue}" stop-opacity="0" />
      <stop offset="100%" stop-color="${blue}" stop-opacity="0.6" />
    </linearGradient>
    <linearGradient id="dagStroke_icon" x1="0%" y1="100%" x2="0%" y2="0%">
      <stop offset="0%" stop-color="${blue}" stop-opacity="0.75" />
      <stop offset="70%" stop-color="${blue}" stop-opacity="0.95" />
      <stop offset="100%" stop-color="${green}" stop-opacity="0.95" />
    </linearGradient>
    <filter id="blueGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <filter id="greenGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <filter id="greenHalo" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="28" />
    </filter>
    <marker id="arrow_icon" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${green}" />
    </marker>
  </defs>

  <!-- Seamless full-bleed 1024x1024 deep-navy canvas -->
  <rect width="1024" height="1024" fill="${bg}" />

  <!-- Subtle outer hexagonal frame -->
  <polygon points="${hexPoints(512, 512, 460, 30)}" fill="#0E1729" stroke="#1E3256" stroke-width="3" />
  <polygon points="${hexPoints(512, 512, 436, 30)}" fill="none" stroke="#294575" stroke-width="1.5" stroke-dasharray="10 8" opacity="0.65" />

  <!-- Formation telemetry arcs -->
  <path d="M 215 745 L 405 650 L 619 650 L 809 745" fill="none" stroke="${blue}" stroke-width="2" stroke-dasharray="8 8" opacity="0.45" />
  <path d="M 300 540 L 445 480 L 579 480 L 724 540" fill="none" stroke="${blue}" stroke-width="1.6" stroke-dasharray="6 7" opacity="0.4" />

  <!-- Directed convergence trajectories -->
  <g fill="none" stroke="url(#dagStroke_icon)" stroke-width="3.5" marker-end="url(#arrow_icon)">
    ${vessels.map(v => `<path d="${v.path}" />`).join('\n    ')}
  </g>

  <!-- 4 Autonomous-agent vessels -->
  ${vessels.map(v => renderVessel(v.x, v.y, v.scale, v.angle, theme)).join('\n')}

  <!-- Top emerald verified hexagonal seal -->
  ${renderVerifiedSeal(sealX, sealY, 1.38, theme)}
</svg>`;
}

async function main() {
  await sharp(Buffer.from(buildHeroSvg('dark')))
    .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
    .toFile(path.join(REPO, 'assets/hero-dark.jpg'));

  await sharp(Buffer.from(buildHeroSvg('light')))
    .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
    .toFile(path.join(REPO, 'assets/hero-light.jpg'));

  await sharp(Buffer.from(buildSocialPreviewSvg()))
    .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
    .toFile(path.join(REPO, 'assets/social-preview.jpg'));

  await sharp(Buffer.from(buildPluginIconSvg()))
    .png({ compressionLevel: 9 })
    .toFile(path.join(REPO, '.claude-plugin/icon.png'));

  console.log('Rendered 4 brand assets successfully.');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});

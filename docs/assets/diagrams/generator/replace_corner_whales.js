const sharp = require('sharp');
const path = require('path');

const REPO = path.resolve(__dirname, '../../../..');

const CONCEPT_DIAGRAMS = [
  'three-layers',
  'fleet-topology',
  'evidence-protocol',
  'decision-gates',
  'merge-train',
  'attention-budget',
  'reviewed-sha-freshness',
  'liveness-resume',
  'sandbox-profiles',
  'one-router-per-worker',
  'mission-chaining',
  'first-run',
  'mission-map',
  'run-timeline',
  'you-say',
  'negative-control',
  'gates-terminal',
  'artifacts-map',
  'mission-handoffs',
  'proof-ladder',
  'mission-identity',
  'threat-boundaries',
];

function buildCornerPatchSvg(bgHex, isDark) {
  // Patch dimensions: width=132, height=92 (placed at left=1468, top=808 on 1600x900)
  // Local coordinates: x_local = x_global - 1468, y_local = y_global - 808
  const blue = isDark ? '#4C8DFF' : '#2F6FEB';
  const constLine = isDark ? '#1E3152' : '#D0DDF2';
  const constDot = isDark ? '#3B6BC4' : '#6A94E0';

  return `<svg xmlns="http://www.w3.org/2000/svg" width="132" height="92" viewBox="0 0 132 92">
  <defs>
    <!-- Soft 10px edge feather on left and top so patch blends invisibly into JPEG background -->
    <linearGradient id="fadeX" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="white" stop-opacity="0" />
      <stop offset="10%" stop-color="white" stop-opacity="1" />
      <stop offset="100%" stop-color="white" stop-opacity="1" />
    </linearGradient>
    <linearGradient id="fadeY" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="white" stop-opacity="0" />
      <stop offset="14%" stop-color="white" stop-opacity="1" />
      <stop offset="100%" stop-color="white" stop-opacity="1" />
    </linearGradient>
    <mask id="featherMask">
      <rect width="132" height="92" fill="url(#fadeX)" />
      <rect width="132" height="92" fill="url(#fadeY)" style="mix-blend-mode: multiply;" />
    </mask>
  </defs>

  <g mask="url(#featherMask)">
    <rect width="132" height="92" fill="${bgHex}" />

    <!-- Faint decorative corner constellation lines -->
    <g stroke="${constLine}" stroke-width="1.2" opacity="0.6">
      <line x1="18" y1="64" x2="52" y2="38" />
      <line x1="52" y1="38" x2="88" y2="70" />
    </g>
    <g fill="${constDot}" opacity="0.6">
      <circle cx="18" cy="64" r="2.2" />
      <circle cx="52" cy="38" r="2.2" />
      <circle cx="88" cy="70" r="2.2" />
    </g>

    <!-- 3-node geometric constellation signature mark -->
    <g stroke="${blue}" stroke-width="1.5" opacity="${isDark ? 0.68 : 0.58}">
      <line x1="64" y1="60" x2="84" y2="46" />
      <line x1="84" y1="46" x2="106" y2="55" />
    </g>
    <g fill="${blue}" opacity="${isDark ? 0.88 : 0.78}">
      <circle cx="64" cy="60" r="2.6" />
      <circle cx="84" cy="46" r="3.1" />
      <circle cx="106" cy="55" r="2.6" />
    </g>
  </g>
</svg>`;
}

function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
}

async function processDiagram(filePath, isDark) {
  const inputBuf = await sharp(filePath).toBuffer();
  const { data, info } = await sharp(inputBuf).raw().toBuffer({ resolveWithObject: true });

  // Sample clean background color near (x=1450, y=885)
  const sampleX = 1450;
  const sampleY = 885;
  const idx = (sampleY * info.width + sampleX) * info.channels;
  const bgHex = rgbToHex(data[idx], data[idx + 1], data[idx + 2]);

  const patchSvg = buildCornerPatchSvg(bgHex, isDark);
  const patchBuf = await sharp(Buffer.from(patchSvg)).png().toBuffer();

  await sharp(inputBuf)
    .composite([{ input: patchBuf, left: 1468, top: 808 }])
    .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
    .toFile(filePath);
}

async function main() {
  let count = 0;
  for (const name of CONCEPT_DIAGRAMS) {
    const darkPath = path.join(REPO, `docs/assets/diagrams/${name}.jpg`);
    const lightPath = path.join(REPO, `docs/assets/diagrams/${name}-light.jpg`);
    await processDiagram(darkPath, true);
    await processDiagram(lightPath, false);
    count += 2;
  }
  console.log(`Replaced bottom-right Orca whale with 3-node constellation mark on ${count} concept diagram files.`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});

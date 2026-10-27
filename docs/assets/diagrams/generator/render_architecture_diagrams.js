const sharp = require('sharp');
const path = require('path');

const REPO = path.resolve(__dirname, '../../../..');

function escapeXml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function getPalette(theme) {
  const isDark = theme === 'dark';
  return {
    isDark,
    bg: isDark ? '#0B1220' : '#F5F8FF',
    nodeFill: isDark ? '#121B2D' : '#FFFFFF',
    containerFill: isDark ? '#0E1626' : '#EDF3FF',
    containerStroke: isDark ? '#283E64' : '#B8CCF0',
    textPrimary: isDark ? '#F2F6FF' : '#0B1220',
    textSecondary: isDark ? '#8A9BB8' : '#4F5E78',
    blue: isDark ? '#4C8DFF' : '#2F6FEB',
    brightBlue: isDark ? '#7EB0FF' : '#1D4ED8',
    green: isDark ? '#3DDC84' : '#1F9D55',
    amber: isDark ? '#FFB84C' : '#C77700',
    red: isDark ? '#FF5C5C' : '#D93B3B',
    constLine: isDark ? '#1E3152' : '#D0DDF2',
    constDot: isDark ? '#3B6BC4' : '#6A94E0',
    badgeFillAmber: isDark ? '#241D14' : '#FFF6E5',
    badgeFillGreen: isDark ? '#10261E' : '#E8FBF0',
    badgeFillRed: isDark ? '#28151B' : '#FEECEC',
  };
}

function commonDefsAndBackdrop(p) {
  // Subtle decorative constellation corners (top-left and bottom-right) + 3-node signature mark
  const tlNodes = [[28, 28], [88, 22], [54, 66], [122, 54]];
  const tlEdges = [[0, 1], [0, 2], [1, 2], [1, 3], [2, 3]];
  const brNodes = [[1460, 868], [1508, 842], [1545, 875]];
  const brEdges = [[0, 1], [1, 2]];

  return `
  <defs>
    <filter id="glowBlue" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="${p.isDark ? 6 : 4}" flood-color="${p.blue}" flood-opacity="${p.isDark ? 0.28 : 0.14}" />
    </filter>
    <filter id="glowBrightBlue" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="${p.isDark ? 9 : 6}" flood-color="${p.blue}" flood-opacity="${p.isDark ? 0.5 : 0.25}" />
    </filter>
    <filter id="glowGreen" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="${p.isDark ? 6 : 4}" flood-color="${p.green}" flood-opacity="${p.isDark ? 0.3 : 0.16}" />
    </filter>
    <filter id="glowAmber" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="${p.isDark ? 6 : 4}" flood-color="${p.amber}" flood-opacity="${p.isDark ? 0.28 : 0.16}" />
    </filter>
    <filter id="glowRed" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="${p.isDark ? 6 : 4}" flood-color="${p.red}" flood-opacity="${p.isDark ? 0.28 : 0.16}" />
    </filter>
    <marker id="arrowBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${p.blue}" />
    </marker>
    <marker id="arrowGreen" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${p.green}" />
    </marker>
    <marker id="arrowRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${p.red}" />
    </marker>
    <marker id="arrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${p.amber}" />
    </marker>
  </defs>

  <rect width="1600" height="900" fill="${p.bg}" />

  <!-- Decorative top-left constellation -->
  <g stroke="${p.constLine}" stroke-width="1.2" opacity="0.55">
    ${tlEdges.map(([a, b]) => `<line x1="${tlNodes[a][0]}" y1="${tlNodes[a][1]}" x2="${tlNodes[b][0]}" y2="${tlNodes[b][1]}" />`).join('\n    ')}
    ${brEdges.map(([a, b]) => `<line x1="${brNodes[a][0]}" y1="${brNodes[a][1]}" x2="${brNodes[b][0]}" y2="${brNodes[b][1]}" />`).join('\n    ')}
  </g>
  <g fill="${p.constDot}" opacity="0.55">
    ${tlNodes.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.2" />`).join('\n    ')}
    ${brNodes.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.2" />`).join('\n    ')}
  </g>

  <!-- Bottom-right 3-node constellation signature mark -->
  <g stroke="${p.blue}" stroke-width="1.5" opacity="${p.isDark ? 0.65 : 0.55}">
    <line x1="1532" y1="868" x2="1552" y2="854" />
    <line x1="1552" y1="854" x2="1574" y2="863" />
  </g>
  <g fill="${p.blue}" opacity="${p.isDark ? 0.85 : 0.75}">
    <circle cx="1532" cy="868" r="2.6" />
    <circle cx="1552" cy="854" r="3.1" />
    <circle cx="1574" cy="863" r="2.6" />
  </g>`;
}

function buildVerifyGateSvg(theme) {
  const p = getPalette(theme);

  // Top row geometry: 3 main boxes + 2 stacked outcome boxes, vertically centered at y=195 (height 190, y=100..290)
  // Box 1: x=56, w=340 -> 56..396
  // Arrow 1: 396 -> 436
  // Box 2: x=436, w=300 -> 436..736
  // Arrow 2: 736 -> 776
  // Box 3: x=776, w=430 -> 776..1206
  // Arrows 3a/3b: 1206 -> 1256
  // Outcome 1 (green): x=1256, y=100, w=288, h=82
  // Outcome 2 (red):   x=1256, y=208, w=288, h=82

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  ${commonDefsAndBackdrop(p)}

  <!-- TOP ROW -->
  <!-- Box 1 -->
  <rect x="56" y="100" width="340" height="190" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="226" y="152" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">the coordinator sets</text>
  <text x="226" y="178" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">the gate env</text>
  <text x="226" y="222" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14" font-weight="400" fill="${p.textSecondary}">OPEN_FLEET_MANIFEST · contract</text>
  <text x="226" y="246" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14" font-weight="400" fill="${p.textSecondary}">source + digest · unit class</text>

  <!-- Arrow 1 -> 2 -->
  <line x1="396" y1="195" x2="432" y2="195" stroke="${p.blue}" stroke-width="2.2" marker-end="url(#arrowBlue)" />

  <!-- Box 2 -->
  <rect x="436" y="100" width="300" height="190" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="586" y="172" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">Stop / TaskCompleted</text>
  <text x="586" y="200" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">hook fires</text>
  <text x="586" y="228" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.blue}">verify-gate.sh</text>

  <!-- Arrow 2 -> 3 -->
  <line x1="736" y1="195" x2="772" y2="195" stroke="${p.blue}" stroke-width="2.2" marker-end="url(#arrowBlue)" />

  <!-- Box 3 -->
  <rect x="776" y="100" width="430" height="190" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="991" y="142" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="19.5" font-weight="700" fill="${p.textPrimary}">verify.py re-derives</text>
  <text x="991" y="182" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14" font-weight="400" fill="${p.textSecondary}">scope from the frozen contract ·</text>
  <text x="991" y="206" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14" font-weight="400" fill="${p.textSecondary}">review from GitHub · negative control</text>
  <text x="991" y="230" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14" font-weight="400" fill="${p.textSecondary}">read, or replayed in a throwaway</text>
  <text x="991" y="254" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14" font-weight="400" fill="${p.textSecondary}">worktree when OPEN_FLEET_EXECUTE_NC is set</text>

  <!-- Branching Arrows 3 -> Outcomes -->
  <path d="M 1206 175 L 1228 175 L 1228 141 L 1252 141" fill="none" stroke="${p.green}" stroke-width="2.2" marker-end="url(#arrowGreen)" />
  <path d="M 1206 215 L 1228 215 L 1228 249 L 1252 249" fill="none" stroke="${p.red}" stroke-width="2.2" marker-end="url(#arrowRed)" />

  <!-- Outcome 1: green -->
  <rect x="1256" y="100" width="288" height="82" rx="12" fill="${p.nodeFill}" stroke="${p.green}" stroke-width="2.2" filter="url(#glowGreen)" />
  <text x="1400" y="148" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.green}">exit 0 — allow</text>

  <!-- Outcome 2: red -->
  <rect x="1256" y="208" width="288" height="82" rx="12" fill="${p.nodeFill}" stroke="${p.red}" stroke-width="2.2" filter="url(#glowRed)" />
  <text x="1400" y="244" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18" font-weight="700" fill="${p.red}">exit 2 — BLOCK,</text>
  <text x="1400" y="268" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="16" font-weight="500" fill="${p.textPrimary}">with feedback</text>

  <!-- Caption under top row -->
  <text x="800" y="348" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">fail-closed — a missing manifest, a missing contract, or a verifier error blocks (ORCA_* legacy aliases also accepted)</text>

  <!-- Subtle divider line -->
  <line x1="120" y1="392" x2="1480" y2="392" stroke="${p.containerStroke}" stroke-width="1.2" stroke-dasharray="6 6" opacity="0.65" />

  <!-- BOTTOM HALF -->
  <text x="800" y="446" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="22" font-weight="700" fill="${p.textPrimary}" letter-spacing="1.5">WHERE THE VERDICT IS SOUND</text>

  <!-- Card 1: Amber outline -->
  <rect x="86" y="485" width="684" height="240" rx="16" fill="${p.nodeFill}" stroke="${p.amber}" stroke-width="2.2" filter="url(#glowAmber)" />
  <text x="428" y="555" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="20" font-weight="700" fill="${p.amber}">native hook, inside the worker's own session</text>
  <line x1="146" y1="585" x2="710" y2="585" stroke="${p.amber}" stroke-width="1" opacity="0.35" />
  <text x="428" y="632" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="16.5" font-weight="400" fill="${p.textSecondary}">the worker can set OPEN_FLEET_* / ORCA_* itself —</text>
  <text x="428" y="664" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18" font-weight="700" fill="${p.textPrimary}">ADVISORY, defence in depth</text>

  <!-- Card 2: Green outline -->
  <rect x="830" y="485" width="684" height="240" rx="16" fill="${p.nodeFill}" stroke="${p.green}" stroke-width="2.2" filter="url(#glowGreen)" />
  <text x="1172" y="555" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="20" font-weight="700" fill="${p.green}">CI · MCP-Task · SDK subprocess</text>
  <line x1="890" y1="585" x2="1454" y2="585" stroke="${p.green}" stroke-width="1" opacity="0.35" />
  <text x="1172" y="632" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="16.5" font-weight="400" fill="${p.textSecondary}">the coordinator owns the env —</text>
  <text x="1172" y="664" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18" font-weight="700" fill="${p.textPrimary}">SOUND</text>

  <!-- Footer -->
  <text x="800" y="825" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="16" font-weight="400" fill="${p.textSecondary}">keep the differentiation in verify.py, not in the hook</text>
</svg>`;
}

function buildInstallStackSvg(theme) {
  const p = getPalette(theme);

  // Left 2/3: x=56..1016 (width=960), 5 stacked layers from top (Layer 5) to bottom (Layer 1)
  // y positions: 76, 220, 364, 508, 652 (each height=118, gap=26 -> total 5*118 + 4*26 = 694, y=76..770)
  const layers = [
    {
      y: 76,
      title: 'upstream worker packs',
      caption: 'mattpocock/skills · garrytan/gstack · addyosmani/agent-skills — one pack per worker, never two',
      bright: false,
    },
    {
      y: 220,
      title: 'open-fleet missions',
      caption: 'skills/ — outcome-named workflows with SHA-bound definitions of done',
      bright: true,
    },
    {
      y: 364,
      title: 'runtime policies + verifier',
      caption: 'worktree isolation · ro / rw / danger sandboxes · merge train · verify.py + verify-gate.sh',
      bright: false,
    },
    {
      y: 508,
      title: 'runtime provider interface (14 runtimes)',
      caption: 'orca (default) · posix (standalone SQLite + worktrees) · auto · overstory · t3code · ao · +9 more',
      bright: false,
    },
    {
      y: 652,
      title: 'coding-agent harnesses',
      caption: 'claude · codex · gemini · opencode · omp · pi · jcode · goose · hermes · crush · openhands',
      bright: false,
    },
  ];

  // Right 1/3: x=1064..1544 (width=480)
  // Header at y=104: THREE INSTALL PATHS
  // 3 cards at y=132, 354, 576 (each height=194, gap=28 -> 132..770)
  const cards = [
    {
      y: 132,
      title: 'sh scripts/install.sh (symlink)',
      lines: [
        '~/.claude/skills or --skills-dir for',
        'Codex / Gemini / OpenCode ·',
        'paste settings snippet',
      ],
      badge: 'wire the gate',
      badgeColor: p.amber,
      badgeFill: p.badgeFillAmber,
    },
    {
      y: 354,
      title: 'Claude Code plugin',
      lines: [
        'lean dist bundle · completion gate',
        'ON by construction',
      ],
      badge: 'gate on',
      badgeColor: p.green,
      badgeFill: p.badgeFillGreen,
    },
    {
      y: 576,
      title: 'skills CLI (repo root copy)',
      lines: [
        'copying skills/ severs ../../playbooks',
        '— use dist bundle instead',
      ],
      badge: 'use dist',
      badgeColor: p.red,
      badgeFill: p.badgeFillRed,
    },
  ];

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  ${commonDefsAndBackdrop(p)}

  <!-- Left 5 stacked layers -->
  ${layers.map(l => {
    const stroke = l.bright ? p.brightBlue : p.blue;
    const sw = l.bright ? 2.8 : 2;
    const filter = l.bright ? 'url(#glowBrightBlue)' : 'url(#glowBlue)';
    return `
  <g>
    <rect x="56" y="${l.y}" width="960" height="118" rx="14" fill="${p.nodeFill}" stroke="${stroke}" stroke-width="${sw}" filter="${filter}" />
    <text x="536" y="${l.y + 48}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="22" font-weight="700" fill="${p.textPrimary}">${escapeXml(l.title)}</text>
    <text x="536" y="${l.y + 84}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14.2" font-weight="400" fill="${p.textSecondary}">${escapeXml(l.caption)}</text>
  </g>`;
  }).join('\n')}

  <!-- Right third header -->
  <text x="1304" y="104" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="21" font-weight="700" fill="${p.textPrimary}" letter-spacing="1.2">THREE INSTALL PATHS</text>

  <!-- Right 3 install cards -->
  ${cards.map(c => {
    const bw = c.badge.length * 10.2 + 26;
    const bx = 1544 - 20 - bw;
    const by = c.y + 16;
    return `
  <g>
    <rect x="1064" y="${c.y}" width="480" height="194" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
    <!-- Top-right pill badge -->
    <rect x="${bx}" y="${by}" width="${bw}" height="28" rx="14" fill="${c.badgeFill}" stroke="${c.badgeColor}" stroke-width="1.6" />
    <text x="${bx + bw / 2}" y="${by + 19}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="13" font-weight="700" fill="${c.badgeColor}">${escapeXml(c.badge)}</text>
    <!-- Card title placed cleanly below badge row -->
    <text x="1090" y="${c.y + 74}" font-family="'JetBrains Mono', monospace" font-size="19" font-weight="700" fill="${p.textPrimary}">${escapeXml(c.title)}</text>
    ${c.lines.map((line, i) => `<text x="1090" y="${c.y + 112 + i * 24}" font-family="'JetBrains Mono', monospace" font-size="14.5" font-weight="400" fill="${p.textSecondary}">${escapeXml(line)}</text>`).join('\n    ')}
  </g>`;
  }).join('\n')}

  <!-- Footer -->
  <text x="800" y="836" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">scripts/bundle.py builds self-contained missions in dist/ for copy installers</text>
</svg>`;
}

function buildRuntimeProvidersSvg(theme) {
  const p = getPalette(theme);

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  ${commonDefsAndBackdrop(p)}

  <!-- TOP BAND -->
  <rect x="60" y="52" width="1480" height="114" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2.2" filter="url(#glowBlue)" />
  <text x="800" y="98" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="22" font-weight="700" fill="${p.textPrimary}">MISSIONS (skills/) + PLAYBOOKS (playbooks/)</text>
  <text x="800" y="134" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14.2" font-weight="400" fill="${p.textSecondary}">zero vendor lock-in — workflows call neutral runtime/scripts/ entrypoints (spawn_worker.sh · task_ops.py · worker_ops.py · worktree_ops.py · send_msg.py)</text>

  <!-- Arrows from Top Band to Left & Right Panels -->
  <line x1="420" y1="166" x2="420" y2="204" stroke="${p.blue}" stroke-width="2.2" marker-end="url(#arrowBlue)" />
  <line x1="1180" y1="166" x2="1180" y2="204" stroke="${p.blue}" stroke-width="2.2" marker-end="url(#arrowBlue)" />

  <!-- MIDDLE LEFT PANEL: 14 RUNTIME PROVIDERS -->
  <rect x="60" y="210" width="720" height="432" rx="16" fill="${p.containerFill}" stroke="${p.containerStroke}" stroke-width="2" />
  <text x="420" y="248" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">14 RUNTIME PROVIDERS (OPEN_FLEET_RUNTIME)</text>

  <!-- Left Row 1: posix (green outline) -->
  <rect x="84" y="268" width="672" height="104" rx="12" fill="${p.nodeFill}" stroke="${p.green}" stroke-width="2" filter="url(#glowGreen)" />
  <text x="108" y="304" font-family="'JetBrains Mono', monospace" font-size="17.5" font-weight="700" fill="${p.green}">posix</text>
  <text x="172" y="304" font-family="'JetBrains Mono', monospace" font-size="14.5" font-weight="400" fill="${p.textSecondary}">— standalone zero-daemon SQLite WAL + local git</text>
  <text x="108" y="334" font-family="'JetBrains Mono', monospace" font-size="14.5" font-weight="400" fill="${p.textSecondary}">worktrees + tmux or headless subprocesses</text>

  <!-- Left Row 2: orca (blue outline) -->
  <rect x="84" y="388" width="672" height="104" rx="12" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="108" y="424" font-family="'JetBrains Mono', monospace" font-size="17.5" font-weight="700" fill="${p.textPrimary}">orca</text>
  <text x="162" y="424" font-family="'JetBrains Mono', monospace" font-size="14.5" font-weight="400" fill="${p.textSecondary}">— Orca desktop IDE + CLI worktrees, terminals,</text>
  <text x="108" y="454" font-family="'JetBrains Mono', monospace" font-size="14.5" font-weight="400" fill="${p.textSecondary}">native task DAG and issue-tracker bridge (default)</text>

  <!-- Left Row 3: 12 external orchestrators (blue outline) -->
  <rect x="84" y="508" width="672" height="114" rx="12" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="108" y="542" font-family="'JetBrains Mono', monospace" font-size="17" font-weight="700" fill="${p.textPrimary}">12 external orchestrators</text>
  <text x="108" y="570" font-family="'JetBrains Mono', monospace" font-size="13.8" font-weight="400" fill="${p.textSecondary}">overstory · t3code · ao · superset · gastown · worktrunk ·</text>
  <text x="108" y="596" font-family="'JetBrains Mono', monospace" font-size="13.8" font-weight="400" fill="${p.textSecondary}">jcode-swarm · emdash · vibe-kanban · paperclip · multiclaude · openhands</text>

  <!-- MIDDLE RIGHT PANEL: 15 CODING-AGENT HARNESSES -->
  <rect x="820" y="210" width="720" height="432" rx="16" fill="${p.containerFill}" stroke="${p.containerStroke}" stroke-width="2" />
  <text x="1180" y="248" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">15 CODING-AGENT HARNESSES (spawn_worker.sh [agent])</text>

  <!-- Right Row 1: harnesses list (blue outline) -->
  <rect x="844" y="268" width="672" height="166" rx="12" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="1180" y="316" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">claude · codex · gemini · opencode · omp · pi ·</text>
  <text x="1180" y="352" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="18.5" font-weight="700" fill="${p.textPrimary}">jcode · goose · hermes · crush · openhands</text>
  <text x="1180" y="396" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15" font-weight="400" fill="${p.textSecondary}">+ cursor · antigravity · grok · droid (rw only)</text>

  <!-- Right Row 2: uniform permission mapping (amber outline, clean navy/white fill) -->
  <rect x="844" y="456" width="672" height="166" rx="12" fill="${p.nodeFill}" stroke="${p.amber}" stroke-width="2.2" filter="url(#glowAmber)" />
  <text x="1180" y="510" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="19" font-weight="700" fill="${p.amber}">uniform permission mapping</text>
  <text x="1180" y="548" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15" font-weight="400" fill="${p.textSecondary}">PROFILE=ro (read-only) · rw (workspace-write) ·</text>
  <text x="1180" y="576" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15" font-weight="400" fill="${p.textSecondary}">danger (isolated sandbox only)</text>

  <!-- Arrows from Left & Right Panels to Bottom Band -->
  <line x1="420" y1="642" x2="420" y2="680" stroke="${p.green}" stroke-width="2.2" marker-end="url(#arrowGreen)" />
  <line x1="1180" y1="642" x2="1180" y2="680" stroke="${p.green}" stroke-width="2.2" marker-end="url(#arrowGreen)" />

  <!-- BOTTOM BAND -->
  <rect x="60" y="686" width="1480" height="114" rx="14" fill="${p.nodeFill}" stroke="${p.green}" stroke-width="2.4" filter="url(#glowGreen)" />
  <text x="800" y="732" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="21.5" font-weight="700" fill="${p.green}">INDEPENDENT SHA-BOUND VERIFIER (verify.py + verify-gate.sh + run_report.py)</text>
  <text x="800" y="768" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="14.8" font-weight="400" fill="${p.textSecondary}">git ancestry · content-bound test ledger · negative control · reviewed_sha == head_sha — identical proof on every runtime</text>

  <!-- Footer -->
  <text x="800" y="846" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">pick the orchestrator and the coding agent independently — the evidence contract never changes</text>
</svg>`;
}

function buildTrackerEnumerationSvg(theme) {
  const p = getPalette(theme);

  // Vertically centered left-to-right pipeline (center y = 420)
  // Left column: 3 source boxes at x=64..394 (w=330, h=116 each), y=182, 362, 542 (spanning 182..658, center=420)
  // Merge spine at x=428 -> arrow to Stage 1 at x=474
  // Stage 1 (T0 TWIN-QUERY): x=474..794 (w=320, h=250, y=295..545)
  // Arrow: 794 -> 840
  // Stage 2 (TRUST FENCE): x=840..1160 (w=320, h=250, y=295..545)
  // Arrow: 1160 -> 1206
  // Stage 3 (VERIFIED CLOSURE): x=1206..1536 (w=330, h=250, y=295..545)

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  ${commonDefsAndBackdrop(p)}

  <!-- Left Source Box 1: GITHUB (blue outline) -->
  <rect x="64" y="182" width="330" height="116" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="229" y="232" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="21" font-weight="700" fill="${p.textPrimary}">GITHUB</text>
  <text x="229" y="266" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15" font-weight="400" fill="${p.textSecondary}">gh issue list · gh pr list</text>

  <!-- Left Source Box 2: LINEAR (blue outline) -->
  <rect x="64" y="362" width="330" height="116" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="229" y="412" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="21" font-weight="700" fill="${p.textPrimary}">LINEAR</text>
  <text x="229" y="446" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15" font-weight="400" fill="${p.textSecondary}">orca linear list</text>

  <!-- Left Source Box 3: JIRA (blue outline — uniform with GITHUB and LINEAR) -->
  <rect x="64" y="542" width="330" height="116" rx="14" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2" filter="url(#glowBlue)" />
  <text x="229" y="592" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="21" font-weight="700" fill="${p.textPrimary}">JIRA</text>
  <text x="229" y="626" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15" font-weight="400" fill="${p.textSecondary}">orca jira list · orca jira search</text>

  <!-- Merging connector from 3 sources into Stage 1 -->
  <path d="M 394 240 L 432 240 L 432 600 L 394 600" fill="none" stroke="${p.blue}" stroke-width="2.2" />
  <line x1="394" y1="420" x2="468" y2="420" stroke="${p.blue}" stroke-width="2.2" marker-end="url(#arrowBlue)" />

  <!-- Stage 1: T0 TWIN-QUERY (blue outline) -->
  <rect x="474" y="295" width="320" height="250" rx="16" fill="${p.nodeFill}" stroke="${p.blue}" stroke-width="2.2" filter="url(#glowBlue)" />
  <text x="634" y="378" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="23" font-weight="700" fill="${p.textPrimary}">T0 TWIN-QUERY</text>
  <line x1="514" y1="404" x2="754" y2="404" stroke="${p.blue}" stroke-width="1" opacity="0.35" />
  <text x="634" y="444" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">page until truncated is false ·</text>
  <text x="634" y="474" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">reconcile two independent</text>
  <text x="634" y="504" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">workers</text>

  <!-- Arrow Stage 1 -> Stage 2 -->
  <line x1="794" y1="420" x2="834" y2="420" stroke="${p.blue}" stroke-width="2.2" marker-end="url(#arrowBlue)" />

  <!-- Stage 2: TRUST FENCE (amber outline) -->
  <rect x="840" y="295" width="320" height="250" rx="16" fill="${p.nodeFill}" stroke="${p.amber}" stroke-width="2.2" filter="url(#glowAmber)" />
  <text x="1000" y="378" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="23" font-weight="700" fill="${p.amber}">TRUST FENCE</text>
  <line x1="880" y1="404" x2="1120" y2="404" stroke="${p.amber}" stroke-width="1" opacity="0.35" />
  <text x="1000" y="444" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">guard_text.py normalizes text ·</text>
  <text x="1000" y="474" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">ticket text is data,</text>
  <text x="1000" y="504" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">never authority</text>

  <!-- Arrow Stage 2 -> Stage 3 -->
  <line x1="1160" y1="420" x2="1200" y2="420" stroke="${p.green}" stroke-width="2.2" marker-end="url(#arrowGreen)" />

  <!-- Stage 3: VERIFIED CLOSURE (green outline) -->
  <rect x="1206" y="295" width="330" height="250" rx="16" fill="${p.nodeFill}" stroke="${p.green}" stroke-width="2.4" filter="url(#glowGreen)" />
  <text x="1371" y="378" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="23" font-weight="700" fill="${p.green}">VERIFIED CLOSURE</text>
  <line x1="1246" y1="404" x2="1496" y2="404" stroke="${p.green}" stroke-width="1" opacity="0.35" />
  <text x="1371" y="444" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">single-attempt writeId +</text>
  <text x="1371" y="474" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">reference · proved by merged</text>
  <text x="1371" y="504" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="15.5" font-weight="400" fill="${p.textSecondary}">SHA in manifest</text>

  <!-- Footer -->
  <text x="800" y="790" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="16.5" font-weight="400" fill="${p.textSecondary}">a ticket reflects closure — it never proves it or authorizes writes</text>
</svg>`;
}

async function main() {
  const specs = [
    { name: 'verify-gate', fn: buildVerifyGateSvg },
    { name: 'install-stack', fn: buildInstallStackSvg },
    { name: 'runtime-providers', fn: buildRuntimeProvidersSvg },
    { name: 'tracker-enumeration', fn: buildTrackerEnumerationSvg },
  ];

  for (const s of specs) {
    await sharp(Buffer.from(s.fn('dark')))
      .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
      .toFile(path.join(REPO, `docs/assets/diagrams/${s.name}.jpg`));

    await sharp(Buffer.from(s.fn('light')))
      .jpeg({ quality: 95, mozjpeg: true, chromaSubsampling: '4:4:4' })
      .toFile(path.join(REPO, `docs/assets/diagrams/${s.name}-light.jpg`));
  }

  console.log('Rendered 8 architecture diagram files successfully.');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});

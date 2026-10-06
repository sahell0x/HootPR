/**
 * Radial "code graph" visual for the Context section. Pure SVG, deterministic layout
 * (seeded PRNG + Prim MST at module load) so server and client render identically.
 */

const SIZE = 600;
const C = SIZE / 2;
const DISC = 226; // nodes live inside this radius
const RING_ORANGE = 268;
const RING_MINT = 254;
const RING_VIOLET = 242;

const AMBER = "#ffc53d";
const MINT = "#46e1a5";
const VIOLET = "#687ff5";
const RED = "#ff6467";
const ORANGE = "#ff570a";

type Pt = { x: number; y: number };
type Edge = [number, number];

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const r1 = (n: number) => Math.round(n * 10) / 10;

function buildGraph() {
  const rand = mulberry32(20260930);
  const nodes: Pt[] = [];
  let guard = 0;
  while (nodes.length < 290 && guard < 20000) {
    guard++;
    const ang = rand() * Math.PI * 2;
    const rad = Math.sqrt(rand()) * DISC;
    const p = { x: r1(C + Math.cos(ang) * rad), y: r1(C + Math.sin(ang) * rad) };
    if (nodes.every((q) => (q.x - p.x) ** 2 + (q.y - p.y) ** 2 > 16 * 16)) nodes.push(p);
  }
  const n = nodes.length;
  const d2 = (i: number, j: number) => (nodes[i]!.x - nodes[j]!.x) ** 2 + (nodes[i]!.y - nodes[j]!.y) ** 2;

  // Prim's MST: gives the branching, tree-like look.
  const inTree = new Array<boolean>(n).fill(false);
  const best = new Array<number>(n).fill(Infinity);
  const parent = new Array<number>(n).fill(-1);
  best[0] = 0;
  const edges: Edge[] = [];
  for (let k = 0; k < n; k++) {
    let u = -1;
    for (let i = 0; i < n; i++) if (!inTree[i] && (u === -1 || best[i]! < best[u]!)) u = i;
    inTree[u] = true;
    if (parent[u]! >= 0) edges.push([parent[u]!, u]);
    for (let v = 0; v < n; v++) {
      if (!inTree[v]) {
        const dd = d2(u, v);
        if (dd < best[v]!) {
          best[v]! = dd;
          parent[v] = u;
        }
      }
    }
  }
  // Drop the longest MST links so the graph reads as neighbourhoods, then add a few short loops.
  const kept = edges.filter(([a, b]) => d2(a, b) < 34 * 34);
  const have = new Set(kept.map(([a, b]) => `${Math.min(a, b)}-${Math.max(a, b)}`));
  for (let i = 0; i < n; i++) {
    if (rand() > 0.22) continue;
    let bj = -1;
    for (let j = 0; j < n; j++) {
      if (j === i || have.has(`${Math.min(i, j)}-${Math.max(i, j)}`)) continue;
      if (bj === -1 || d2(i, j) < d2(i, bj)) bj = j;
    }
    if (bj >= 0 && d2(i, bj) < 30 * 30) {
      kept.push([i, bj]);
      have.add(`${Math.min(i, bj)}-${Math.max(i, bj)}`);
    }
  }
  const adj: number[][] = Array.from({ length: n }, () => []);
  for (const [a, b] of kept) {
    adj[a]!.push(b);
    adj[b]!.push(a);
  }
  return { nodes, edges: kept, adj };
}

const G = buildGraph();

function nearest(x: number, y: number, minDegree = 2) {
  let bi = 0;
  let bd = Infinity;
  G.nodes.forEach((p, i) => {
    const d = (p.x - x) ** 2 + (p.y - y) ** 2;
    if (d < bd && G.adj[i]!.length >= minDegree) {
      bd = d;
      bi = i;
    }
  });
  return bi;
}

const polar = (deg: number, rad: number) => ({
  x: C + Math.cos((deg * Math.PI) / 180) * rad,
  y: C + Math.sin((deg * Math.PI) / 180) * rad,
});

type HNode = { i: number; color: string; depth: number };
type HEdge = { a: number; b: number; color: string; depth: number };
type Label = { text: string; deg: number; color: string };
type Highlight = { nodes: HNode[]; edges: HEdge[]; labels: Label[]; kept?: number[] };

function bfs(seed: number, limit: number, color: string, taken: Set<number>, into: Highlight) {
  const depth = new Map<number, number>([[seed, 0]]);
  const queue = [seed];
  taken.add(seed);
  into.nodes.push({ i: seed, color, depth: 0 });
  let count = 1;
  while (queue.length && count < limit) {
    const u = queue.shift()!;
    for (const v of G.adj[u]!) {
      if (count >= limit) break;
      if (taken.has(v)) continue;
      taken.add(v);
      const dv = depth.get(u)! + 1;
      depth.set(v, dv);
      queue.push(v);
      into.nodes.push({ i: v, color, depth: dv });
      into.edges.push({ a: u, b: v, color, depth: dv });
      count++;
    }
  }
}

function seedAt(deg: number, rad: number) {
  const p = polar(deg, rad);
  return nearest(p.x, p.y);
}

function build(spec: { deg: number; rad: number; limit: number; color: string; label?: string }[], labels: Label[] = []) {
  const h: Highlight = { nodes: [], edges: [], labels: [...labels] };
  const taken = new Set<number>();
  for (const s of spec) {
    bfs(seedAt(s.deg, s.rad), s.limit, s.color, taken, h);
    if (s.label) h.labels.push({ text: s.label, deg: s.deg, color: s.color });
  }
  return h;
}

const AGENTS = build([
  { deg: 215, rad: 130, limit: 26, color: MINT, label: "correctness" },
  { deg: 315, rad: 135, limit: 26, color: VIOLET, label: "security" },
  { deg: 40, rad: 130, limit: 26, color: AMBER, label: "performance" },
  { deg: 130, rad: 135, limit: 26, color: RED, label: "tests" },
]);

const JUDGE: Highlight = (() => {
  const h: Highlight = {
    nodes: AGENTS.nodes.map((nd) => ({ ...nd, color: "#6f6b75" })),
    edges: AGENTS.edges.map((e) => ({ ...e, color: "#4a4550" })),
    labels: [
      { text: "posted", deg: 330, color: ORANGE },
      { text: "dropped", deg: 165, color: "#6f6b75" },
    ],
  };
  // Keep a handful: the deepest node of each agent's subgraph plus two more.
  const picks: number[] = [];
  for (let k = 0; k < 4; k++) {
    const part = AGENTS.nodes.slice(k * 26, (k + 1) * 26);
    const deep = [...part].sort((a, b) => b.depth - a.depth);
    picks.push(deep[0]!.i);
    if (k % 2 === 0 && deep[5]!) picks.push(deep[5]!.i);
  }
  h.kept = picks;
  return h;
})();

export const STAGE_HIGHLIGHTS: Highlight[] = [
  // Sandboxed tools: scattered small hits across the diff.
  build([
    { deg: 200, rad: 150, limit: 7, color: AMBER, label: "eslint" },
    { deg: 250, rad: 90, limit: 6, color: AMBER, label: "ruff" },
    { deg: 300, rad: 170, limit: 7, color: AMBER, label: "semgrep" },
    { deg: 10, rad: 120, limit: 6, color: AMBER, label: "gitleaks" },
    { deg: 70, rad: 175, limit: 7, color: AMBER, label: "trivy" },
    { deg: 140, rad: 110, limit: 6, color: AMBER, label: "shellcheck" },
  ]),
  // Code graph: one symbol, fanning out to callers, callees and importers.
  build([{ deg: 0, rad: 0, limit: 95, color: MINT }], [
    { text: "callers", deg: 320, color: MINT },
    { text: "callees", deg: 30, color: MINT },
    { text: "imports", deg: 150, color: MINT },
    { text: "types", deg: 220, color: MINT },
  ]),
  // Learnings & path instructions: repo knowledge along the rim.
  build([
    { deg: 160, rad: 190, limit: 20, color: VIOLET, label: "learnings" },
    { deg: 215, rad: 195, limit: 20, color: VIOLET, label: ".hootpr.yaml" },
    { deg: 270, rad: 190, limit: 18, color: VIOLET, label: "path instructions" },
    { deg: 330, rad: 190, limit: 18, color: VIOLET, label: "ast-grep rules" },
  ]),
  AGENTS,
  JUDGE,
];

const STYLE = `
@keyframes cg-draw { to { stroke-dashoffset: 0; } }
@keyframes cg-pop { from { opacity: 0; transform: scale(.2); } to { opacity: 1; transform: scale(1); } }
@keyframes cg-spin { to { transform: rotate(360deg); } }
@keyframes cg-halo { 0%,100% { opacity: .15; transform: scale(1); } 50% { opacity: .55; transform: scale(1.6); } }
@keyframes cg-fade { from { opacity: 0; } to { opacity: 1; } }
.cg-spin { transform-box: view-box; transform-origin: ${C}px ${C}px; animation: cg-spin 120s linear infinite; }
.cg-spin-r { transform-box: view-box; transform-origin: ${C}px ${C}px; animation: cg-spin 160s linear infinite reverse; }
.cg-pop, .cg-halo { transform-box: fill-box; transform-origin: center; }
@media (prefers-reduced-motion: reduce) { .cg-spin, .cg-spin-r, .cg-halo { animation: none; } }
`;

export function CodeGraph({ stage }: { stage: number }) {
  const h = STAGE_HIGHLIGHTS[stage] ?? STAGE_HIGHLIGHTS[0]!;
  const step = 55;
  return (
    <svg viewBox="-110 -10 820 620" className="h-auto w-full" aria-hidden role="presentation">
      <style>{STYLE}</style>
      <defs>
        <radialGradient id="cg-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ff570a" stopOpacity="0.07" />
          <stop offset="70%" stopColor="#ff570a" stopOpacity="0.02" />
          <stop offset="100%" stopColor="#ff570a" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="cg-ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ff7e37" />
          <stop offset="55%" stopColor="#ff570a" />
          <stop offset="100%" stopColor="#c43a00" />
        </linearGradient>
      </defs>

      <circle cx={C} cy={C} r={RING_ORANGE + 30} fill="url(#cg-glow)" />
      <circle cx={C} cy={C} r={RING_ORANGE} fill="none" stroke="url(#cg-ring)" strokeWidth="3" />
      <circle
        className="cg-spin"
        cx={C}
        cy={C}
        r={RING_MINT}
        fill="none"
        stroke={MINT}
        strokeOpacity="0.8"
        strokeWidth="1.5"
        strokeDasharray="7 5"
      />
      <circle
        className="cg-spin-r"
        cx={C}
        cy={C}
        r={RING_VIOLET}
        fill="none"
        stroke={VIOLET}
        strokeOpacity="0.7"
        strokeWidth="1.2"
        strokeDasharray="4 5"
      />

      {/* Base graph */}
      <g stroke="#3d3843" strokeWidth="1">
        {G.edges.map(([a, b]) => (
          <line key={`${a}-${b}`} x1={G.nodes[a]!.x} y1={G.nodes[a]!.y} x2={G.nodes[b]!.x} y2={G.nodes[b]!.y} />
        ))}
      </g>
      <g fill="#141116" stroke="#5b5561" strokeWidth="1">
        {G.nodes.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="2.6" />
        ))}
      </g>

      {/* Highlighted subgraph; re-keyed per stage so it draws in again. */}
      <g key={stage}>
        <g strokeWidth="1.4" fill="none">
          {h.edges.map((e) => (
            <line
              key={`${e.a}-${e.b}`}
              x1={G.nodes[e.a]!.x}
              y1={G.nodes[e.a]!.y}
              x2={G.nodes[e.b]!.x}
              y2={G.nodes[e.b]!.y}
              stroke={e.color}
              pathLength={1}
              strokeDasharray="1"
              strokeDashoffset="1"
              style={{ animation: `cg-draw 420ms ease-out ${e.depth * step}ms forwards` }}
            />
          ))}
        </g>
        <g fill="#141116" strokeWidth="1.4">
          {h.nodes.map((nd) => (
            <circle
              key={nd.i}
              className="cg-pop"
              cx={G.nodes[nd.i]!.x}
              cy={G.nodes[nd.i]!.y}
              r={nd.depth === 0 && stage !== 4 ? 4.2 : 3}
              stroke={nd.color}
              fill={nd.depth === 0 && stage !== 4 ? nd.color : "#141116"}
              style={{ opacity: 0, animation: `cg-pop 360ms ease-out ${nd.depth * step + 80}ms forwards` }}
            />
          ))}
        </g>
        {h.kept?.map((i, k) => (
          <g key={`kept-${i}`}>
            <circle
              className="cg-halo"
              cx={G.nodes[i]!.x}
              cy={G.nodes[i]!.y}
              r="9"
              fill={ORANGE}
              style={{ animation: `cg-halo 2.4s ease-in-out ${600 + k * 180}ms infinite` }}
            />
            <circle
              className="cg-pop"
              cx={G.nodes[i]!.x}
              cy={G.nodes[i]!.y}
              r="5"
              fill={ORANGE}
              stroke="#ffb38a"
              strokeWidth="1"
              style={{ opacity: 0, animation: `cg-pop 400ms ease-out ${500 + k * 120}ms forwards` }}
            />
          </g>
        ))}
        {h.labels.map((l, k) => {
          const a = polar(l.deg, RING_ORANGE + 16);
          const t = polar(l.deg, RING_ORANGE + 26);
          const cos = Math.cos((l.deg * Math.PI) / 180);
          const anchor = cos > 0.25 ? "start" : cos < -0.25 ? "end" : "middle";
          const dy = Math.abs(cos) <= 0.25 ? (Math.sin((l.deg * Math.PI) / 180) > 0 ? 12 : -4) : 4;
          return (
            <g key={l.text} style={{ opacity: 0, animation: `cg-fade 500ms ease-out ${300 + k * 90}ms forwards` }}>
              <circle cx={r1(a.x)} cy={r1(a.y)} r="2.5" fill={l.color} />
              <text
                x={r1(t.x)}
                y={r1(t.y + dy)}
                textAnchor={anchor}
                fill="#b5b2b9"
                fontSize="13"
                fontFamily="var(--font-code), ui-monospace, monospace"
              >
                {l.text}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

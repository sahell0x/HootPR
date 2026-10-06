import {
  ChevronDown,
  Database,
  FileCode2,
  GitMerge,
  Layers,
  LayoutPanelLeft,
  Lightbulb,
  MessagesSquare,
  Paperclip,
  SendHorizontal,
  Server,
  ExternalLink,
  PanelsTopLeft,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { OwlAvatar, Sev, StatusPill } from "./b-frame";

type LayerDef = {
  n: string;
  t: string;
  icon: ReactNode;
  files: [string, number, number, number][];
};
const LAYERS: LayerDef[] = [
  {
    n: "01",
    t: "Add the invitation data model",
    icon: <Database className="size-3" />,
    files: [
      ["db/schema/invites.ts", 24, 0, 0],
      ["db/migrations/0042.sql", 18, 0, 0],
    ],
  },
  {
    n: "02",
    t: "Add the API and emails",
    icon: <Server className="size-3" />,
    files: [
      ["src/server/invites/service.ts", 31, 2, 1],
      ["src/api/invites/route.ts", 44, 0, 0],
      ["emails/invite.tsx", 52, 0, 0],
    ],
  },
  {
    n: "03",
    t: "Build the invite & members UI",
    icon: <PanelsTopLeft className="size-3" />,
    files: [["app/settings/members.tsx", 96, 12, 0]],
  },
];

/* Unified diff of src/server/invites/service.ts; `f` marks lines a finding is anchored to. */
const DIFF: { n: number | null; t: string; k?: "add" | "del"; f?: boolean }[] =
  [
    { n: null, t: "export async function invite(email) {", k: "del" },
    { n: null, t: "  return db.invite.create({ email });", k: "del" },
    { n: 21, t: "export async function invite(org, email, role) {", k: "add" },
    { n: 22, t: "  assertAdmin(org, ctx.user);", k: "add" },
    { n: 23, t: "  const token = randomToken(32);", k: "add" },
    { n: 24, t: "  const expires = addDays(now(), 7);", k: "add" },
    { n: 25, t: "  const row = await db.invite.create({", k: "add" },
    { n: 26, t: "    org, email, role, token, expires,", k: "add", f: true },
    { n: 27, t: "  });", k: "add" },
    { n: 28, t: "  await sendMail('invite', { email, token });", k: "add" },
    { n: 29, t: "  return row;", k: "add" },
    { n: 30, t: "}" },
    { n: 31, t: "" },
    { n: 32, t: "export async function accept(token) {", k: "add" },
    {
      n: 33,
      t: "  const row = await db.invite.find({ token });",
      k: "add",
      f: true,
    },
    {
      n: 34,
      t: "  if (!row || row.expires < now()) throw new Expired();",
      k: "add",
    },
  ];

const DIFF0: typeof DIFF = [
  "import { table, text, enumType, timestamp } from './core';",
  "",
  "export const Role = enumType('role', ['admin', 'member']);",
  "",
  "export const invites = table('invites', {",
  "  id: text('id').primaryKey(),",
  "  org: text('org_id').notNull(),",
  "  email: text('email').notNull(),",
  "  role: Role('role').default('member'),",
  "  token: text('token').notNull(),",
  "  expires: timestamp('expires_at').notNull(),",
  "});",
].map((t, i) => ({ n: i + 1, t, k: "add" as const }));

function Kw({ t }: { t: string }) {
  // tiny syntax tint: keywords and strings
  const parts = t.split(
    /(\b(?:export|async|function|return|const|await|throw|new|if)\b|'[^']*')/g,
  );
  return (
    <>
      {parts.map((p, i) =>
        /^(export|async|function|return|const|await|throw|new|if)$/.test(p) ? (
          <span key={i} className="text-[#8b9cf6]">
            {p}
          </span>
        ) : p.startsWith("'") ? (
          <span key={i} className="text-[#ffc53d]">
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

export function ChangeStackMock({ active }: { active: number }) {
  const layer = active === 0 ? 0 : 1;
  const L = LAYERS[layer] ?? LAYERS[0]!;
  const showFinding = active === 2;
  return (
    <div className="flex h-full flex-col text-[11px]">
      {/* App top bar (breadcrumb) */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-[#2a262d] bg-[#141116] px-3 text-[11px] text-[#8f8a96]">
        <LayoutPanelLeft className="size-3.5" />
        <span>acme</span>/<span className="hidden sm:inline">Change Stack</span>
        <span className="hidden sm:inline">/</span>
        <span className="truncate text-[#efedf0]">
          Team invitations with roles
        </span>
        <span
          className={cn(
            "ml-auto inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-[10.5px] font-medium transition-all duration-500",
            active === 4
              ? "bg-[#efedf0] text-[#141116]"
              : "border border-[#3a3640] text-[#efedf0]",
          )}
        >
          Submit review <ChevronDown className="size-3" />
        </span>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-w-0 flex-1 flex-col px-3 pt-3 sm:px-4">
          {/* PR header */}
          <p className="truncate text-[17px] font-medium tracking-[-0.01em] text-[#efedf0]">
            Team invitations with roles{" "}
            <span className="text-[#6f6b75]">#231</span>
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-[#b5b2b9]">
            <StatusPill>Open</StatusPill>
            <span>@maya-r wants to merge</span>
            <code className="rounded bg-[#2a262d] px-1 font-mono text-[10.5px]">
              feat/invites
            </code>{" "}
            into
            <code className="rounded bg-[#2a262d] px-1 font-mono text-[10.5px]">
              main
            </code>
            <span className="hidden items-center gap-0.5 text-[#ff8a3d] md:inline-flex">
              Open on GitHub <ExternalLink className="size-2.5" />
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[10.5px] text-[#8f8a96]">
            Snapshot
            <span className="rounded border border-[#3a3640] px-1.5 py-0.5 font-mono text-[10px] text-[#d9d6dc]">
              c41e9a2 · auto · 3 findings · current ▾
            </span>
          </div>
          <p className="mt-2.5 flex items-center gap-1.5 text-[13px] font-medium text-[#efedf0]">
            <ChevronDown className="size-3.5" /> Changes{" "}
            <span className="rounded bg-[#2a262d] px-1.5 font-mono text-[10px] text-[#a9a4ae]">
              3
            </span>
          </p>

          {/* Two-pane workspace */}
          <div className="mt-2 flex min-h-0 flex-1 overflow-hidden rounded-t-md border border-b-0 border-[#2e2a31]">
            {/* Layers */}
            <aside
              className={cn(
                "hidden w-[178px] shrink-0 flex-col border-r border-[#2a262d] bg-[#18151a] transition-shadow duration-500 sm:flex",
                active === 0 && "shadow-[inset_0_0_0_1px_#ff570a66]",
              )}
            >
              <div className="flex items-center justify-between border-b border-[#2a262d] px-2.5 py-1.5">
                <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#efedf0]">
                  <Layers className="size-3" /> Layers
                </span>
                <span className="font-mono text-[9.5px] text-[#6f6b75]">
                  6 files
                </span>
              </div>
              <div className="space-y-1.5 p-1.5">
                {LAYERS.map((l, i) => (
                  <div
                    key={l.n}
                    className={cn(
                      "b-in rounded px-1.5 py-1 transition-colors duration-500",
                      i === layer && "bg-[#221e26]",
                    )}
                    style={{ animationDelay: `${i * 140}ms` }}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-[#8f8a96]">{l.icon}</span>
                      <span className="font-mono text-[9.5px] text-[#6f6b75]">
                        {l.n}
                      </span>
                      <span
                        className={cn(
                          "truncate text-[10.5px] font-medium",
                          i === layer ? "text-[#efedf0]" : "text-[#bdb8c2]",
                        )}
                      >
                        {l.t}
                      </span>
                    </div>
                    {i === layer && (
                      <div className="mt-1 space-y-0.5 border-l border-[#3a3640] pl-2 ml-1.5">
                        {l.files.map(([f, a, d, fi], j) => (
                          <div
                            key={f}
                            className={cn(
                              "b-in flex items-center gap-1 rounded-sm px-1 py-0.5 font-mono text-[9.5px]",
                              j === 0
                                ? "bg-[#2a262d] text-[#efedf0] shadow-[-9px_0_0_-7px_#ff570a]"
                                : "text-[#a9a4ae]",
                            )}
                            style={{ animationDelay: `${200 + j * 90}ms` }}
                          >
                            <FileCode2 className="size-2.5 shrink-0" />
                            <span className="truncate">
                              {f.split("/").pop()}
                            </span>
                            <span className="ml-auto text-[#7ef0b8]">+{a}</span>
                            <span className="text-[#ff9aa6]">-{d}</span>
                            {fi > 0 && (
                              <span className="rounded-sm border border-[#ff570a]/70 px-0.5 text-[#ff8a3d]">
                                {fi}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </aside>

            {/* File diff */}
            <div className="relative flex min-w-0 flex-1 flex-col bg-[#161318]">
              <div className="flex items-center gap-2 border-b border-[#2a262d] px-2.5 py-1.5 font-mono text-[10.5px]">
                <FileCode2 className="size-3 text-[#8f8a96]" />
                <span className="truncate text-[#d9d6dc]">
                  {layer === 0 ? L.files[0]?.[0] : "service.ts"}
                </span>
                <span className="ml-auto text-[#7ef0b8]">
                  +{L.files[0]?.[1]}
                </span>
                <span className="text-[#ff9aa6]">-{L.files[0]?.[2]}</span>
                <span className="hidden rounded border border-[#3a3640] px-1 text-[9.5px] text-[#a9a4ae] md:inline">
                  Modified
                </span>
              </div>
              <div
                key={layer}
                className="b-in min-h-0 flex-1 overflow-hidden py-1"
              >
                {(layer === 0 ? DIFF0 : DIFF).map((d, i) => (
                  <div key={i}>
                    <div
                      className={cn(
                        "flex font-mono text-[10.5px] leading-[18px] whitespace-pre",
                        d.k === "add" && "bg-[#0f3a26]/70",
                        d.k === "del" && "bg-[#4a1520]/70",
                        d.f && showFinding && "b-glow",
                      )}
                      style={
                        d.f && showFinding
                          ? { animationDelay: "200ms" }
                          : undefined
                      }
                    >
                      <span className="flex w-4 shrink-0 items-center justify-center">
                        {d.f && (
                          <span
                            className={cn(
                              "size-[7px] rounded-full bg-[#ff570a]",
                              showFinding && "b-pulse",
                            )}
                          />
                        )}
                      </span>
                      <span className="w-6 shrink-0 pr-1 text-right text-[#5f5a66]">
                        {d.n ?? ""}
                      </span>
                      <span className="w-3 shrink-0 text-[#5f5a66]">
                        {d.k === "add" ? "+" : d.k === "del" ? "-" : ""}
                      </span>
                      <span
                        style={{ whiteSpace: "pre" }}
                        className={cn(
                          "truncate",
                          d.k === "del"
                            ? "text-[#ff9aa6]/90"
                            : "text-[#d9d6dc]",
                        )}
                      >
                        <Kw t={d.t} />
                      </span>
                    </div>
                    {showFinding && d.n === 26 && (
                      <div
                        className="b-pop mx-2 my-1.5 rounded-md border border-[#ff8a3d]/50 bg-[#1f1b23] p-2 shadow-[0_0_24px_-10px_#ff570a]"
                        style={{ animationDelay: "350ms" }}
                      >
                        <div className="flex items-center gap-1.5">
                          <OwlAvatar className="size-4 rounded-[3px] [&_svg]:size-3" />
                          <span className="truncate text-[11px] font-semibold text-[#efedf0]">
                            Invite token stored in plain text
                          </span>
                          <span className="ml-auto">
                            <Sev level="major" />
                          </span>
                        </div>
                        <p className="mt-1 text-[10.5px] leading-[1.45] text-[#a9a4ae]">
                          Anyone with read access to the invites table can
                          accept a pending invite. Store a hash and compare it
                          in accept().
                        </p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 border-t border-[#2a262d] px-2.5 py-1.5 text-[10.5px] font-medium text-[#efedf0]">
                Findings in this file
                <span className="rounded bg-[#2a262d] px-1.5 font-mono text-[9.5px] text-[#a9a4ae]">
                  {layer === 0 ? 0 : 2}
                </span>
              </div>

              {/* Layer popover (depends on) */}
              {active === 1 && (
                <div className="b-pop absolute top-8 left-2 z-10 w-[262px] rounded-md border border-[#3a3640] bg-[#1f1b23] p-3 shadow-[0_24px_48px_-12px_rgba(0,0,0,.85)] sm:-left-6">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-[#2a262d] px-1 font-mono text-[10px] text-[#a9a4ae]">
                      02
                    </span>
                    <span className="text-[12px] font-semibold text-[#efedf0]">
                      Add the API and emails
                    </span>
                    <span className="ml-auto rounded-full bg-[#ffc53d]/15 px-1.5 text-[10px] text-[#ffc53d]">
                      3 files
                    </span>
                  </div>
                  <p className="mt-2 text-[10.5px] leading-[1.5] text-[#b5b2b9]">
                    Endpoints to create, list and accept invitations; token
                    generation; the invitation email; the admin-only permission
                    gate.
                  </p>
                  <div className="mt-2.5 flex items-center gap-1.5 border-t border-[#2e2a31] pt-2 text-[10px] text-[#8f8a96]">
                    <span className="font-mono tracking-wide">DEPENDS ON</span>{" "}
                    →
                    <span className="rounded bg-[#2a262d] px-1 font-mono">
                      01
                    </span>
                    <span className="truncate text-[#d9d6dc]">
                      Add the invitation data model
                    </span>
                  </div>
                  <div className="mt-2 flex justify-end gap-1.5">
                    <span className="rounded-full bg-[#ff6467]/15 px-1.5 text-[10px] text-[#ff9aa6]">
                      ● 2 findings
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Submit review dropdown */}
          {active === 4 && (
            <div className="b-pop absolute top-0 right-2 z-20 w-[240px] rounded-md border border-[#3a3640] bg-[#1f1b23] p-2.5 shadow-[0_24px_48px_-12px_rgba(0,0,0,.85)]">
              <div className="rounded border border-[#3a3640] bg-[#151217] px-2 py-1.5 text-[10.5px] text-[#8f8a96]">
                <span
                  className="b-type inline-block"
                  style={{ animationDelay: "250ms" }}
                >
                  Looks good once the token is hashed.
                </span>
              </div>
              {(
                [
                  ["Comment", false],
                  ["Approve", true],
                  ["Request changes", false],
                ] as const
              ).map(([t, on]) => (
                <div
                  key={t}
                  className="mt-1.5 flex items-center gap-2 text-[11px] text-[#d9d6dc]"
                >
                  <span
                    className={cn(
                      "grid size-3 place-items-center rounded-full border",
                      on ? "border-[#46e1a5]" : "border-[#5f5a66]",
                    )}
                  >
                    {on && (
                      <span className="size-1.5 rounded-full bg-[#46e1a5]" />
                    )}
                  </span>
                  {t}
                </div>
              ))}
              <div className="mt-2.5 flex gap-1.5">
                <span className="flex flex-1 items-center justify-center gap-1 rounded bg-[#efedf0] py-1 text-[10.5px] font-medium text-[#141116]">
                  Submit review
                </span>
                <span
                  className="b-pop flex flex-1 items-center justify-center gap-1 rounded bg-[#1f7a52] py-1 text-[10.5px] font-medium text-white"
                  style={{ animationDelay: "900ms" }}
                >
                  <GitMerge className="size-3" /> Merge
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Chat about this change */}
        <aside
          className={cn(
            "hidden w-[208px] shrink-0 flex-col border-l border-[#2a262d] bg-[#141116] transition-shadow duration-500 lg:flex",
            active === 3 && "shadow-[inset_0_0_0_1px_#8b7cf666]",
          )}
        >
          <div className="flex items-center gap-1.5 border-b border-[#2a262d] px-3 py-2 text-[11.5px] font-medium text-[#efedf0]">
            <MessagesSquare className="size-3.5" /> Chat about this change
          </div>
          <div className="flex items-center gap-2 px-3 pt-2 text-[9.5px] text-[#8f8a96]">
            <span className="h-px flex-1 bg-[#2a262d]" /> Snapshot c41e9a2{" "}
            <span className="h-px flex-1 bg-[#2a262d]" />
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-hidden p-2.5">
            <div className="rounded-md border border-dashed border-[#3a3640] p-2 text-[10.5px] leading-[1.45] text-[#b5b2b9]">
              <OwlAvatar className="mb-1 size-4 rounded-[3px] [&_svg]:size-3" />
              Ask HootPR about the diff, a finding, or the file you are looking
              at.
            </div>
            {active === 3 && (
              <>
                <div
                  className="b-in ml-5 rounded-md bg-[#26222b] px-2 py-1.5 text-[10.5px] text-[#efedf0]"
                  style={{ animationDelay: "200ms" }}
                >
                  Does layer 03 depend on the invite email?
                </div>
                <div
                  className="b-in flex gap-1.5"
                  style={{ animationDelay: "700ms" }}
                >
                  <OwlAvatar className="size-4 rounded-[3px] [&_svg]:size-3" />
                  <p
                    className="b-wipe text-[10.5px] leading-[1.45] text-[#bdb8c2]"
                    style={{ animationDelay: "800ms" }}
                  >
                    No. members.tsx only calls{" "}
                    <span className="font-mono text-[#d9d6dc]">
                      POST /invites
                    </span>
                    ; the email is sent inside invite() in layer 02.
                  </p>
                </div>
              </>
            )}
          </div>
          <div className="border-t border-[#2a262d] p-2">
            <div className="mb-1.5 flex items-center justify-between text-[9.5px] text-[#8f8a96]">
              <span className="flex items-center gap-1">
                <Lightbulb className="size-3" /> Pinned to this PR
              </span>
              <span className="flex items-center gap-1 rounded border border-[#ff570a]/70 px-1 py-0.5 font-mono text-[9px] text-[#efedf0]">
                <Paperclip className="size-2.5" /> service.ts
              </span>
            </div>
            <div className="flex items-start gap-1 rounded-md border border-[#3a3640] p-1.5 text-[10px] text-[#8f8a96]">
              <span className="flex-1">Why is this change needed?</span>
              <span className="grid size-5 place-items-center rounded bg-[#ff570a]/80 text-white">
                <SendHorizontal className="size-3" />
              </span>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

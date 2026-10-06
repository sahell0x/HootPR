"use client";

import { FeatureBlock } from "./b-frame";
import { ChangeStackMock } from "./b-mock-changestack";
import { ReviewMock } from "./b-mock-review";
import { SecurityMock } from "./b-mock-security";
import { WalkthroughMock } from "./b-mock-walkthrough";

export function FeatureSections() {
  return (
    <div className="flex flex-col border-t border-border/60">
      <FeatureBlock
        id="review"
        eyebrow="01 Review"
        title="AI code reviews that catch what matters."
        intro="Linters, scanners and a code graph feed specialist reviewers, then a separate judge drops the noise. What reaches your PR is worth reading."
        items={[
          {
            title: "Inline findings with fixes",
            body: "Each finding has a severity, a one-line reason and a suggested change you can commit.",
          },
          {
            title: "Judge-filtered noise",
            body: "A separate judge model checks every candidate and drops false positives before posting.",
            dotted: true,
          },
          {
            title: "Learns your conventions",
            body: "Reply to a comment to teach it. Learnings apply to future reviews of that repo.",
            dotted: true,
          },
          {
            title: "Chat with @hootpr",
            body: "Ask about the change, its blast radius, or have it write docstrings and unit tests.",
          },
          {
            title: "Configurable via .hootpr.yaml",
            body: "Path instructions, ast-grep rules, tools and checks per repo, on top of org defaults.",
            dotted: true,
          },
        ]}
        cta={{ label: "Get started", href: "/login" }}
        mock={(a) => <ReviewMock active={a} />}
      />
      <FeatureBlock
        id="walkthrough"
        eyebrow="02 Walkthrough"
        title="Understand every PR at a glance."
        intro="Every pull request and merge request gets a walkthrough comment, so reviewers know what changed and why before they open a single file."
        items={[
          {
            title: "A summary in plain words",
            body: "What the change does and why, written for the humans reviewing it.",
          },
          {
            title: "Changes, file by file",
            body: "A table of every file or cohort with a short summary of what moved.",
            dotted: true,
          },
          {
            title: "Sequence diagrams",
            body: "See how the new code flows between components when it matters.",
            dotted: true,
          },
          {
            title: "Review effort estimate",
            body: "A 1 to 5 score and time estimate so you can plan who reviews what.",
          },
          {
            title: "Checks before merge",
            body: "Pre-merge checks and a HootPR status check you can make required.",
          },
        ]}
        cta={{ label: "See how it works", href: "#context" }}
        mock={(a) => <WalkthroughMock active={a} />}
      />
      <FeatureBlock
        id="change-stack"
        eyebrow="03 Change Stack"
        title="Review massive diffs layer by layer."
        intro="Change Stack regroups a large PR into ordered layers, from data model to UI, so you review the story of the change instead of an alphabetical file list."
        items={[
          {
            title: "Layers, not a file list",
            body: "The diff is split into numbered layers you can read in dependency order.",
          },
          {
            title: "Know what each layer needs",
            body: "Each layer lists its files, what it does and which layers it depends on.",
            dotted: true,
          },
          {
            title: "Findings inline",
            body: "HootPR's findings sit right next to the lines they are about.",
          },
          {
            title: "Pinned chat",
            body: "Ask questions about the PR without losing your place in the diff.",
            dotted: true,
          },
          {
            title: "Submit review and merge",
            body: "Approve, request changes or merge from the same screen.",
          },
        ]}
        cta={{ label: "Get started", href: "/login" }}
        mock={(a) => <ChangeStackMock active={a} />}
      />
      <FeatureBlock
        id="security"
        eyebrow="04 Security"
        title="Security review on every change."
        intro="Scanners run in a sealed sandbox on every PR, and attack surface maps and security reviews show your posture across repositories."
        items={[
          {
            title: "Attack surface maps",
            body: "Every repo's entry points, auth checks, outbound calls, secrets usage and exposure, mapped.",
            dotted: true,
          },
          {
            title: "Security architecture review",
            body: "An AI report with prioritized risks, from critical to low, and concrete fixes.",
          },
          {
            title: "@hootpr security review",
            body: "Ask for a focused security review on any pull request, right in the thread.",
          },
          {
            title: "Blast radius in walkthroughs",
            body: "Each walkthrough shows which endpoints and attack surface a change touches.",
            dotted: true,
          },
          {
            title: "Scanners on every PR",
            body: "Semgrep, Gitleaks, Trivy and Checkov run in a sealed sandbox before the model reviews.",
          },
        ]}
        cta={{ label: "Get started", href: "/login" }}
        mock={(a) => <SecurityMock active={a} />}
      />
    </div>
  );
}

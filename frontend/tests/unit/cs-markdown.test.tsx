import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CsMarkdown } from "@/components/cr/cs-markdown";

describe("CsMarkdown", () => {
  it("renders code fences, lists, bold and inline code as elements (no raw markers)", () => {
    const { container } = render(
      <CsMarkdown source={"Intro **bold** and `x()`\n\n1. one\n2. two\n\n```py\nprint(1)\n```\n\n> quoted <script>"} />,
    );
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("x()").tagName).toBe("CODE");
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelector("pre")?.textContent).toBe("print(1)");
    expect(container.querySelector("blockquote")?.textContent).toContain("<script>");
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).not.toContain("```");
  });
});

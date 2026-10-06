import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Button } from "@/components/ui/button";

test("ui kit renders", () => {
  render(<Button>Review</Button>);
  expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
});

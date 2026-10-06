import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { YamlValidator } from "@/components/yaml-validator";
import { jsonResponse, renderWithQuery } from "../utils";

test("shows line-numbered errors", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ valid: false, effective: null,
    errors: [{ line: 3, path: "reviews.profile", message: "Input should be 'chill' or 'assertive'" }] })));
  renderWithQuery(<YamlValidator />);
  await userEvent.type(screen.getByRole("textbox", { name: /hootpr\.yaml/i }), "reviews:\n  profile: x");
  await userEvent.click(screen.getByRole("button", { name: /validate/i }));
  expect(await screen.findByText(/Line 3 · reviews.profile/)).toBeInTheDocument();
});

test("shows valid state", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ valid: true, errors: [], effective: { language: "en-US" } })));
  renderWithQuery(<YamlValidator />);
  await userEvent.click(screen.getByRole("button", { name: /validate/i }));
  expect(await screen.findByText(/valid configuration/i)).toBeInTheDocument();
});

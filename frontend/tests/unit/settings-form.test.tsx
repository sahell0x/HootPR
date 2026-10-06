import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { SettingsForm } from "@/components/settings-form";
import { configSchema } from "../fixtures/config-schema";

test("saves only overridden keys", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<SettingsForm schema={configSchema} value={{ language: "fr-FR" }} onSave={onSave} />);
  await userEvent.click(screen.getByRole("switch", { name: /poem/i }));
  await userEvent.click(screen.getByRole("button", { name: /reset language/i }));
  await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith({ reviews: { poem: true } }));
});

test("list fields split lines and commas", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<SettingsForm schema={configSchema} value={{}} onSave={onSave} />);
  const box = screen.getByRole("textbox", { name: /^labels$/i });
  await userEvent.type(box, "review-me, !skip");
  await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith({ reviews: { auto_review: { labels: ["review-me", "!skip"] } } }));
});

test("read only disables inputs and shows errors", () => {
  render(<SettingsForm schema={configSchema} value={{}} onSave={vi.fn()} readOnly
    errors={[{ line: null, path: "reviews.profile", message: "Input should be 'chill' or 'assertive'" }]} />);
  expect(screen.getByRole("switch", { name: /poem/i })).toBeDisabled();
  expect(screen.getByText(/should be 'chill'/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /add path instruction/i })).not.toBeInTheDocument();
});

test("path instructions: add a row and save", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<SettingsForm schema={configSchema} value={{}} onSave={onSave} />);
  await userEvent.click(screen.getByRole("button", { name: "Add path instruction" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Path instruction 1 path" }), "src/api/**");
  await userEvent.type(screen.getByRole("textbox", { name: "Path instruction 1 instructions" }), "Check auth.");
  await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith(
    { reviews: { path_instructions: [{ path: "src/api/**", instructions: "Check auth." }] } }));
});

test("object-list rows can be removed and keep their own values", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<SettingsForm schema={configSchema} onSave={onSave}
    value={{ reviews: { path_instructions: [{ path: "a/**", instructions: "A" }, { path: "b/**", instructions: "B" }] } }} />);
  expect(screen.getByRole("textbox", { name: "Path instruction 2 path" })).toHaveValue("b/**");
  await userEvent.click(screen.getByRole("button", { name: "Remove path instruction 1" }));
  expect(screen.getByRole("textbox", { name: "Path instruction 1 path" })).toHaveValue("b/**");
  await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith({ reviews: { path_instructions: [{ path: "b/**", instructions: "B" }] } }));
});

test("ast-grep rule YAML is parsed; invalid YAML blocks saving", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<SettingsForm schema={configSchema} value={{}} onSave={onSave} />);
  await userEvent.click(screen.getByRole("button", { name: "Add ast-grep instruction" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Ast-grep instruction 1 id" }), "no-print");
  await userEvent.type(screen.getByRole("textbox", { name: "Ast-grep instruction 1 language" }), "python");
  await userEvent.type(screen.getByRole("textbox", { name: "Ast-grep instruction 1 message" }), "Use logging.");
  const rule = screen.getByRole("textbox", { name: "Ast-grep instruction 1 rule" });
  await userEvent.type(rule, "pattern: [[unclosed");
  expect(await screen.findByText(/Invalid YAML/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  await userEvent.clear(rule);
  await userEvent.type(rule, "pattern: print($$$A)");
  expect(screen.queryByText(/Invalid YAML/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith({ reviews: { ast_grep_instructions: [
    { id: "no-print", language: "python", message: "Use logging.", rule: { pattern: "print($$$A)" } }] } }));
});

test("existing YAML values render as YAML text", () => {
  render(<SettingsForm schema={configSchema} onSave={vi.fn()} value={{ reviews: { ast_grep_instructions: [
    { id: "x", language: "go", message: "m", rule: { pattern: "fmt.Println($A)" } }] } }} />);
  expect(screen.getByRole("textbox", { name: "Ast-grep instruction 1 rule" })).toHaveValue("pattern: fmt.Println($A)\n");
});

test("removing a row with invalid YAML unblocks saving", async () => {
  render(<SettingsForm schema={configSchema} value={{}} onSave={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Add ast-grep instruction" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Ast-grep instruction 1 rule" }), "a: [[");
  expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Remove ast-grep instruction 1" }));
  expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
});

test("groups are collapsible sections", () => {
  render(<SettingsForm schema={configSchema} value={{}} onSave={vi.fn()} />);
  for (const g of ["General", "Reviews", "AST-grep", "Tools", "Knowledge base"])
    expect(screen.getByText(g, { selector: "summary" })).toBeInTheDocument();
  expect(screen.getByText("General", { selector: "summary" }).closest("details")).toHaveAttribute("open");
  expect(screen.getByText("Tools", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
});

test("a group with overrides opens, and nested errors show under the list field", () => {
  render(<SettingsForm schema={configSchema} onSave={vi.fn()} value={{ reviews: { tools: { semgrep: { enabled: false } } } }}
    errors={[{ line: null, path: "reviews.path_instructions.0.path", message: "String should have at least 1 character" }]} />);
  expect(screen.getByText("Tools", { selector: "summary" }).closest("details")).toHaveAttribute("open");
  expect(screen.getByText(/at least 1 character/)).toBeInTheDocument();
});

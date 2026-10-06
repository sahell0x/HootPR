import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

export function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Pick an option in the app's Dropdown (Radix Select): open the trigger, then click the option by its label. */
export async function pickOption(trigger: HTMLElement, label: string | RegExp) {
  const { default: userEvent } = await import("@testing-library/user-event");
  const { screen } = await import("@testing-library/react");
  await userEvent.click(trigger);
  await userEvent.click(await screen.findByRole("option", { name: label }));
}

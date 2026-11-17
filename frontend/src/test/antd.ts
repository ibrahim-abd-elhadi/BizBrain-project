// Helpers for Ant Design controls, which aren't native <select> or labelled file inputs.
import { screen, waitFor } from "@testing-library/react";
import userEvent, { PointerEventsCheckLevel } from "@testing-library/user-event";
import { expect } from "vitest";

/**
 * A user-event session without the pointer-events check. jsdom applies Ant Design's
 * `.ant-spin-container::after { pointer-events: none }` rule to the container itself, so every
 * table cell would look unclickable. Real browsers don't do this, and the live-stack run clicks
 * the same buttons in Chromium.
 */
export function user() {
  return userEvent.setup({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

/** Opens an Ant Design Select and picks the option whose label matches. */
export async function chooseOption(select: HTMLElement, label: string | RegExp) {
  await user().click(select);
  const option = await waitFor(() => {
    const found = [...document.querySelectorAll<HTMLElement>(".ant-select-item-option")].find(
      (el) => (typeof label === "string" ? el.title === label : label.test(el.title)),
    );
    expect(found, `option ${String(label)}`).toBeTruthy();
    return found!;
  });
  await user().click(option);
}

/** The hidden <input type="file"> inside an Ant Design Upload. */
export function fileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  return input;
}

/** The modal dialog that is open now. */
export async function openDialog(name: string | RegExp) {
  return screen.findByRole("dialog", { name });
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

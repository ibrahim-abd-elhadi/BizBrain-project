import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Browser APIs jsdom lacks but Ant Design uses (responsive grid, table scroll measurement).
if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// Ant Design's Select dropdown measures itself with ResizeObserver, which jsdom lacks.
if (!("ResizeObserver" in window)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, "ResizeObserver", { writable: true, value: ResizeObserverStub });
  Object.defineProperty(globalThis, "ResizeObserver", { writable: true, value: ResizeObserverStub });
}

// jsdom doesn't implement getComputedStyle for pseudo-elements; ignore the pseudo-element.
const computedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (element: Element) => computedStyle(element);

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

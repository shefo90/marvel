import '@testing-library/jest-dom/vitest';

// jsdom implements neither, and Ant Design's responsive components call both.
// Without these every test that renders a Layout or a Table dies on an
// unrelated TypeError.
global.matchMedia =
  global.matchMedia ||
  ((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }));

global.ResizeObserver =
  global.ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

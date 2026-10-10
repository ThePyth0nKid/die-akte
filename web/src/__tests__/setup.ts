import "@testing-library/jest-dom/vitest"

// Mock ResizeObserver (not available in jsdom)
class ResizeObserverMock {
  private callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver

// Mock IntersectionObserver
class IntersectionObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver

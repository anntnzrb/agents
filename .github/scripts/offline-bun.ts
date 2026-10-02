// Extension tests must replace HTTP transport with fixtures.
// Keep this preload outside installed harness sources.
globalThis.fetch = async () => {
  throw new Error("CI requires mocked HTTP transport; live requests are forbidden");
};

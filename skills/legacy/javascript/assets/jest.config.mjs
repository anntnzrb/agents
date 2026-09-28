/** @type {import('jest').Config} */
const config = {
  testEnvironment: "node",
  clearMocks: true,
  restoreMocks: true,
  collectCoverageFrom: ["src/**/*.js", "!src/**/*.d.ts"],
};

export default config;

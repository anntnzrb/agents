declare module "@earendil-works/pi-coding-agent" {
  export type ExtensionAPI = {
    registerCommand: (name: string, command: unknown) => void;
  };
}

declare module "node:fs/promises" {
  type FileHandle = {
    writeFile: (content: string, encoding?: string) => Promise<void>;
    sync: () => Promise<void>;
    close: () => Promise<void>;
    read: (
      buffer: Buffer,
      offset: number,
      length: number,
      position: number,
    ) => Promise<{ readonly bytesRead: number }>;
  };

  export function access(path: string): Promise<void>;
  export function lstat(path: string): Promise<unknown>;
  export function mkdir(path: string, options?: unknown): Promise<void>;
  export function mkdtemp(prefix: string): Promise<string>;
  export function open(path: string, flags: string, mode?: number): Promise<FileHandle>;
  export function readFile(path: string): Promise<Buffer>;
  export function readFile(path: string, encoding: string): Promise<string>;
  export function readlink(path: string): Promise<string>;
  export function rename(oldPath: string, newPath: string): Promise<void>;
  export function rm(path: string, options?: unknown): Promise<void>;
  export function symlink(target: string, path: string): Promise<void>;
  export function unlink(path: string): Promise<void>;
  export function writeFile(path: string, content: string, options?: unknown): Promise<void>;
}

declare module "node:os" {
  export function tmpdir(): string;
}

declare module "node:path" {
  export const join: (...parts: string[]) => string;
  export const resolve: (...parts: string[]) => string;
  export const sep: string;
}

declare const process: {
  readonly pid: number;
  readonly platform: string;
  exitCode: number | undefined;
};

declare const console: {
  readonly log: (...args: unknown[]) => void;
  readonly error: (...args: unknown[]) => void;
};

declare interface Buffer extends Uint8Array {
  readonly byteLength: number;
  toString(encoding?: string): string;
}

declare interface BufferConstructor {
  alloc(size: number): Buffer;
  byteLength(value: string, encoding?: string): number;
}

declare const Buffer: BufferConstructor;

declare class TextDecoder {
  constructor(label?: string, options?: { readonly fatal?: boolean });
  decode(input?: Uint8Array): string;
}

declare module "bun:test" {
  interface Expectation<T = unknown> {
    readonly not: Expectation<T>;
    readonly rejects: Expectation<unknown>;
    readonly resolves: Expectation<Awaited<T>>;
    toBe(expected: unknown): void;
    toBeGreaterThan(expected: number): void;
    toContain(expected: unknown): void;
    toEqual(expected: unknown): void;
    toHaveLength(expected: number): void;
    toMatch(expected: RegExp | string): void;
    toBeNull(): void;
    toThrow(expected?: unknown): void;
  }

  interface ExpectFactory {
    <T>(actual: T): Expectation<T>;
    any(constructor: unknown): unknown;
    arrayContaining(values: readonly unknown[]): unknown;
  }

  export const describe: (name: string, callback: () => void) => void;
  export const expect: ExpectFactory;
  export const test: (name: string, callback: () => void | Promise<void>) => void;
}

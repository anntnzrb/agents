export function panicMessage(payload: unknown): string {
  if (typeof payload === "string") {
    return payload;
  }
  if (payload instanceof Error) {
    return payload.message;
  }
  return "panic";
}

export function err(message: string): void {
  console.error(`sync: ${message}`);
}

export function warn(message: string): void {
  console.error(`sync: warning: ${message}`);
}

export const isErrno = (error: unknown, code: string): boolean =>
  typeof error === "object" &&
  error !== null &&
  "code" in error &&
  (error as { code?: unknown }).code === code;

export function assertNever(value: never): never {
  throw new Error(`unhandled variant: ${JSON.stringify(value)}`);
}

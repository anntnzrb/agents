export function panicMessage(payload: unknown): string {
  if (typeof payload === "string") {
    return payload;
  }
  if (payload instanceof Error) {
    return payload.message;
  }
  return "panic";
}

export const isErrno = (error: unknown, code: string): boolean =>
  typeof error === "object" &&
  error !== null &&
  "code" in error &&
  (error as { code?: unknown }).code === code;

export const asString = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);

export const asPositiveInteger = (value: unknown): number | undefined =>
	typeof value === "number" && Number.isInteger(value) && value > 0 ? value : undefined;

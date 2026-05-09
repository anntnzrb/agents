import { Text } from "@earendil-works/pi-tui";

export type ColorTheme = {
	fg: (token: string, text: string) => string;
};

export type RenderTheme = ColorTheme & {
	bold: (text: string) => string;
};

export const renderSeparator = (theme: ColorTheme): string => theme.fg("dim", " · ");

export const joinRenderSegments = (segments: readonly string[], theme: ColorTheme): string => segments.join(renderSeparator(theme));

export const getReusableText = (lastComponent: unknown): Text =>
	lastComponent instanceof Text ? lastComponent : new Text("", 0, 0);

export const pluralize = (count: number, singular: string, plural = `${singular}s`): string =>
	count === 1 ? singular : plural;

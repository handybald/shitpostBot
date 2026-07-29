import {z} from 'zod';

export const wordTimingSchema = z.object({
	text: z.string(),
	start: z.number(), // seconds, relative to voiceover start
	end: z.number(),
});

export const backgroundClipSchema = z.object({
	src: z.string(), // absolute path or file:// URL to a QC-accepted clip
	startFrom: z.number().default(0), // seconds to trim from the start of the source clip
	durationInSeconds: z.number(),
});

export const reelPropsSchema = z.object({
	fps: z.number().default(30),
	width: z.number().default(1080),
	height: z.number().default(1920),

	backgroundClips: z.array(backgroundClipSchema).min(1),

	voiceoverSrc: z.string(),
	words: z.array(wordTimingSchema),

	musicSrc: z.string().nullable(),
	musicVolume: z.number().default(0.22), // linear 0-1, ducked under voiceover
	musicFadeSeconds: z.number().default(1.5),

	outroPaddingSeconds: z.number().default(0.6),

	theme: z.object({
		accentColor: z.string().default('#FFD700'), // hook/payoff highlight color
		baseColor: z.string().default('#FFFFFF'),
		fontFamily: z.string().default('Impact, Haettenschweiler, sans-serif'),
		contrast: z.number().default(1.15),
		brightness: z.number().default(0),
	}),

	// Words are grouped into short on-screen lines (~3-5 words) for readability;
	// the renderer does this automatically from `words`, but callers may override
	// the max words per line for pacing.
	maxWordsPerLine: z.number().default(4),
});

export type ReelProps = z.infer<typeof reelPropsSchema>;
export type WordTiming = z.infer<typeof wordTimingSchema>;
export type BackgroundClip = z.infer<typeof backgroundClipSchema>;

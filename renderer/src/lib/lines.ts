import {WordTiming} from '../types';

export interface CaptionLine {
	words: WordTiming[];
	startSec: number;
	endSec: number;
}

/**
 * Groups word-level timestamps (from the TTS provider) into short on-screen
 * lines. Breaks early on sentence-ending punctuation so a line never spans
 * two thoughts, even if that means fewer than maxWordsPerLine words.
 */
export function groupWordsIntoLines(
	words: WordTiming[],
	maxWordsPerLine: number,
): CaptionLine[] {
	const lines: CaptionLine[] = [];
	let current: WordTiming[] = [];

	const flush = () => {
		if (current.length === 0) return;
		lines.push({
			words: current,
			startSec: current[0].start,
			endSec: current[current.length - 1].end,
		});
		current = [];
	};

	for (const word of words) {
		current.push(word);
		const endsSentence = /[.!?]$/.test(word.text.trim());
		if (current.length >= maxWordsPerLine || endsSentence) {
			flush();
		}
	}
	flush();

	return lines;
}

import {staticFile} from 'remotion';

/**
 * Remotion's renderer refuses to load bare absolute filesystem paths or
 * file:// URLs for OffthreadVideo/Audio — it only serves assets out of its
 * configured public dir. The Python orchestrator stages each render job's
 * clips/voiceover/music into a fresh per-job directory and invokes
 * `remotion render --public-dir=<that dir>`; props then reference assets by
 * filename relative to that dir, resolved here via staticFile().
 *
 * Remote (http/https) URLs are passed through unchanged for cases where an
 * asset hasn't been staged locally.
 */
export function toAssetUrl(pathOrFilename: string): string {
	if (pathOrFilename.startsWith('http://') || pathOrFilename.startsWith('https://')) {
		return pathOrFilename;
	}
	return staticFile(pathOrFilename);
}

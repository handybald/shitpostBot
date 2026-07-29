import React from 'react';
import {AbsoluteFill, CalculateMetadataFunction} from 'remotion';
import {ReelProps, reelPropsSchema} from './types';
import {Background} from './components/Background';
import {Captions} from './components/Captions';
import {AudioMix} from './components/AudioMix';

/**
 * Duration is derived from the actual voiceover length (last word's end
 * timestamp + a short outro pad), not a fixed number — this is the fix for
 * the old pipeline's hardcoded 13s timing that didn't match the content.
 */
export const calculateReelMetadata: CalculateMetadataFunction<
	ReelProps
> = ({props}) => {
	const lastWordEnd = props.words.length
		? props.words[props.words.length - 1].end
		: 0;
	const durationInSeconds = lastWordEnd + props.outroPaddingSeconds;

	return {
		fps: props.fps,
		width: props.width,
		height: props.height,
		durationInFrames: Math.max(1, Math.round(durationInSeconds * props.fps)),
	};
};

export const Reel: React.FC<ReelProps> = (props) => {
	const {backgroundClips, words, maxWordsPerLine, theme} = props;

	return (
		<AbsoluteFill style={{backgroundColor: 'black'}}>
			<Background clips={backgroundClips} theme={theme} />
			<Captions words={words} maxWordsPerLine={maxWordsPerLine} theme={theme} />
			<AudioMix
				voiceoverSrc={props.voiceoverSrc}
				musicSrc={props.musicSrc}
				musicVolume={props.musicVolume}
				musicFadeSeconds={props.musicFadeSeconds}
			/>
		</AbsoluteFill>
	);
};

export {reelPropsSchema};

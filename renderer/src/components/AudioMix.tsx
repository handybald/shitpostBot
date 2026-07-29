import React from 'react';
import {Audio, interpolate, useVideoConfig} from 'remotion';
import {ReelProps} from '../types';
import {toAssetUrl} from '../lib/asset-url';

export const AudioMix: React.FC<{
	voiceoverSrc: string;
	musicSrc: string | null;
	musicVolume: number;
	musicFadeSeconds: number;
}> = ({voiceoverSrc, musicSrc, musicVolume, musicFadeSeconds}) => {
	const {fps, durationInFrames} = useVideoConfig();
	const fadeFrames = Math.round(musicFadeSeconds * fps);

	return (
		<>
			<Audio src={toAssetUrl(voiceoverSrc)} volume={1} />
			{musicSrc ? (
				<Audio
					src={toAssetUrl(musicSrc)}
					volume={(frame) =>
						interpolate(
							frame,
							[
								0,
								fadeFrames,
								durationInFrames - fadeFrames,
								durationInFrames,
							],
							[0, musicVolume, musicVolume, 0],
							{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
						)
					}
				/>
			) : null}
		</>
	);
};

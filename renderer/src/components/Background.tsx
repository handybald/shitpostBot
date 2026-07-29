import React from 'react';
import {OffthreadVideo, Sequence, useVideoConfig} from 'remotion';
import {BackgroundClip, ReelProps} from '../types';
import {toAssetUrl} from '../lib/asset-url';

export const Background: React.FC<{
	clips: BackgroundClip[];
	theme: ReelProps['theme'];
}> = ({clips, theme}) => {
	const {fps} = useVideoConfig();

	let cursorFrames = 0;
	const segments = clips.map((clip) => {
		const durationInFrames = Math.round(clip.durationInSeconds * fps);
		const segment = {
			clip,
			from: cursorFrames,
			durationInFrames,
		};
		cursorFrames += durationInFrames;
		return segment;
	});

	return (
		<>
			{segments.map((segment, i) => (
				<Sequence
					key={`${segment.clip.src}-${i}`}
					from={segment.from}
					durationInFrames={segment.durationInFrames}
					layout="none"
				>
					<div
						style={{
							position: 'absolute',
							inset: 0,
							overflow: 'hidden',
							filter: `contrast(${theme.contrast}) brightness(${
								1 + theme.brightness
							})`,
						}}
					>
						<OffthreadVideo
							src={toAssetUrl(segment.clip.src)}
							startFrom={Math.round(segment.clip.startFrom * fps)}
							muted
							style={{
								width: '100%',
								height: '100%',
								objectFit: 'cover',
							}}
						/>
					</div>
				</Sequence>
			))}
			{/* Vignette: keeps the edges dark so bright/busy stock footage doesn't
			    fight with the caption text on top of it. */}
			<div
				style={{
					position: 'absolute',
					inset: 0,
					background:
						'radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 100%)',
				}}
			/>
		</>
	);
};

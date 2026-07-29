import React from 'react';
import {registerRoot, Composition} from 'remotion';
import {Reel, calculateReelMetadata} from './Reel';
import {reelPropsSchema} from './types';

const defaultProps = {
	fps: 30,
	width: 1080,
	height: 1920,
	backgroundClips: [{src: '', startFrom: 0, durationInSeconds: 3}],
	voiceoverSrc: '',
	words: [{text: 'placeholder', start: 0, end: 1}],
	musicSrc: null,
	musicVolume: 0.22,
	musicFadeSeconds: 1.5,
	outroPaddingSeconds: 0.6,
	theme: {
		accentColor: '#FFD700',
		baseColor: '#FFFFFF',
		fontFamily: 'Impact, Haettenschweiler, sans-serif',
		contrast: 1.15,
		brightness: 0,
	},
	maxWordsPerLine: 4,
};

const Root: React.FC = () => {
	return (
		<Composition
			id="Reel"
			component={Reel}
			calculateMetadata={calculateReelMetadata}
			schema={reelPropsSchema}
			fps={30}
			width={1080}
			height={1920}
			durationInFrames={30}
			defaultProps={defaultProps}
		/>
	);
};

registerRoot(Root);

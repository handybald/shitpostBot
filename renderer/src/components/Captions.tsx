import React, {useMemo} from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {ReelProps} from '../types';
import {groupWordsIntoLines} from '../lib/lines';

const HOLD_AFTER_LINE_SECONDS = 0.15;
const ENTRANCE_SECONDS = 0.18;

export const Captions: React.FC<
	Pick<ReelProps, 'words' | 'maxWordsPerLine' | 'theme'>
> = ({words, maxWordsPerLine, theme}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const t = frame / fps;

	const lines = useMemo(
		() => groupWordsIntoLines(words, maxWordsPerLine),
		[words, maxWordsPerLine],
	);

	const activeLine = lines.find(
		(line) => t >= line.startSec && t < line.endSec + HOLD_AFTER_LINE_SECONDS,
	);

	if (!activeLine) return null;

	const entrance = interpolate(
		t,
		[activeLine.startSec, activeLine.startSec + ENTRANCE_SECONDS],
		[0, 1],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
	);

	const scale = 0.94 + entrance * 0.06;
	const opacity = entrance;

	return (
		<div
			style={{
				position: 'absolute',
				left: 60,
				right: 60,
				bottom: 320,
				display: 'flex',
				flexWrap: 'wrap',
				justifyContent: 'center',
				gap: '0 14px',
				transform: `scale(${scale})`,
				opacity,
			}}
		>
			{activeLine.words.map((word, i) => {
				const isActive = t >= word.start && t < word.end;
				const isPast = t >= word.end;
				const color = isActive || isPast ? theme.accentColor : theme.baseColor;
				const wordScale = isActive
					? interpolate(
							t,
							[word.start, Math.min(word.start + 0.08, word.end)],
							[1, 1.12],
							{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
					  )
					: 1;
				const isLast = i === activeLine.words.length - 1;

				return (
					<span
						key={`${word.text}-${i}`}
						style={{
							display: 'inline-block',
							fontFamily: theme.fontFamily,
							fontSize: 88,
							fontWeight: 900,
							color,
							textTransform: 'uppercase',
							WebkitTextStroke: '3px rgba(0,0,0,0.85)',
							paintOrder: 'stroke fill',
							textShadow: '0 6px 18px rgba(0,0,0,0.55)',
							transform: `scale(${wordScale})`,
							marginRight: isLast ? 0 : 26,
							transition: 'none',
						}}
					>
						{word.text}
					</span>
				);
			})}
		</div>
	);
};

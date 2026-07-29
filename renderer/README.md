# ShitPostBot Renderer

Remotion-based reel renderer. Replaces the old raw-ffmpeg composition in
`src/processors/video_generator.py`. The Python orchestrator calls this via
subprocess, passing a JSON props file that matches `src/types.ts`.

## Install

```bash
cd renderer
npm install
```

## Render a reel

The Python side (`RemotionRenderer` in `src/processors/video_generator.py`)
invokes this automatically. To run it manually for debugging:

```bash
npx remotion render src/index.tsx Reel out/reel.mp4 --props=/path/to/props.json
```

`props.json` must match the `reelPropsSchema` in `src/types.ts`:

- `backgroundClips`: sequence of QC-accepted local video files to fill the timeline
- `voiceoverSrc` + `words`: ElevenLabs voiceover audio and its word-level timestamps
  (this is what drives all timing — there is no fixed duration)
- `musicSrc`: background music, auto-ducked under the voiceover
- `theme`: per-content-theme colors/font/contrast

## Preview in the browser (Remotion Studio)

```bash
npm run preview
```

Useful for iterating on caption animation/timing without a full render.

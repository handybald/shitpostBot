import {existsSync} from 'fs';
import {Config} from '@remotion/cli/config';

// Some sandboxed/CI environments block Remotion's own Chrome download and
// instead ship a pre-installed headless Chrome (e.g. for Playwright) at this
// path. If present, use it; otherwise let Remotion manage its own browser
// download as normal (the default on a real server/dev machine).
const sandboxHeadlessShell =
	process.env.REMOTION_BROWSER_EXECUTABLE ||
	'/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';

if (existsSync(sandboxHeadlessShell)) {
	Config.setBrowserExecutable(sandboxHeadlessShell);
}

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);

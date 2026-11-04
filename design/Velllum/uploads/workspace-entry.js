import {createTerminalWorkspace} from '../../../frontend/ui/terminal/terminal-workspace.js';
window.VellumUI=Object.assign(window.VellumUI||{}, {createTerminalWorkspace});
window.dispatchEvent(new Event('vellum:workspace-transport-ready'));

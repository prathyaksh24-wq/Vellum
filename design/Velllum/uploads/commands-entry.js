import commands from '../../../desktop/electron/commands.cjs';
window.VellumCommands=Object.assign(window.VellumCommands||{},commands);
window.dispatchEvent(new Event('vellum:commands-ready'));

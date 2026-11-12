import {createDroplets, supportsHtmlInCanvas} from './components/canvasui/DropletsVanilla';

// The legacy shell owns React 18. Share the original renderer, not React roots.
window.VellumDroplets = {createDroplets, supportsHtmlInCanvas};
window.dispatchEvent(new Event('vellum:droplets-ready'));

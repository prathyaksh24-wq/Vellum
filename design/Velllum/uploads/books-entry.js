import * as graphics from './components/books-graphics.js';
window.VellumBooksGraphics = graphics;
window.dispatchEvent(new Event('vellum:books-graphics-ready'));

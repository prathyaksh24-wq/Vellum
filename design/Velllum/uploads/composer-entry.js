import {composerComponent} from './components/composer-editor.js';
import {referenceProviders,referenceAttachments,componentsForPlugin} from './components/composer-providers.js';
import './components/composer-editor.css';

window.VellumComposer={component:composerComponent,referenceProviders,referenceAttachments,componentsForPlugin};
window.dispatchEvent(new Event('vellum:composer-ready'));

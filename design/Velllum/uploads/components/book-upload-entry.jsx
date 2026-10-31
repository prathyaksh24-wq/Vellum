import React from 'react';
import {createRoot} from 'react-dom/client';
import {AttachmentUpload} from './attachment-upload';
import './attachment-upload.css';

// The legacy shell uses React 18 globals. Give the supplied module and Motion
// their own React 19 root, without passing components or hooks between runtimes.
window.VellumBookUpload = {
  mount(host, props) {
    const root = createRoot(host);
    const render = next => root.render(<AttachmentUpload {...next}/>);
    render(props);
    return {update:render, unmount:() => root.unmount()};
  },
};
window.dispatchEvent(new Event('vellum:book-upload-ready'));

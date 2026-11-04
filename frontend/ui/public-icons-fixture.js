// The classic UI loads this dependency before its isolated JSX modules.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/app-icons.js'),'utf8');
export function loadPublicIcons(React) {
  const script={src:'http://localhost/design-uploads/components/app-icons.js'};
  Function('React','window','document',source)(React,window,{currentScript:script});
}

// Desktop-only compilation of the canonical preview's legacy Babel scripts.
// The served development entry stays untouched. All desktop React code shares
// the existing frontend dependency instead of loading a second React from CDN.
import {mergeConfig, transformWithEsbuild} from 'vite';
import {readFileSync} from 'node:fs';
import {dirname, isAbsolute, relative, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import base from './vite.config.mjs';

const uploads=resolve(dirname(fileURLToPath(import.meta.url)),'../design/Velllum/uploads');

export function desktopWorkspaceBuild(root=uploads) {
  const prefix='virtual:vellum-desktop/', sources=[];
  return {
    name:'vellum-desktop-workspace',apply:'build',enforce:'pre',
    transformIndexHtml:{order:'pre',handler(html){
      sources.length=0;
      let output=html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi,(tag,attributes,body)=>{
        const src=/\bsrc\s*=\s*["']([^"']+)["']/i.exec(attributes)?.[1];
        if(src && /^https:\/\/unpkg\.com\/(?:react(?:-dom)?@|@babel\/standalone@)/.test(src))return '';
        if(!/\btype\s*=\s*["']text\/(?:babel|jsx)["']/i.test(attributes))return tag;
        if(src){
          if(/^(?:https?:|\/\/)/i.test(src))throw new Error('Desktop JSX must come from the local workspace source.');
          const file=resolve(root,decodeURIComponent(src.split('?')[0]).replace(/^\//,''));
          const inside=relative(root,file);
          if(inside.startsWith('..')||isAbsolute(inside))throw new Error('Desktop JSX is outside the UI source folder.');
          sources.push({file,code:readFileSync(file,'utf8')});
        }else sources.push({file:'workspace-inline.jsx',code:body});
        return '';
      });
      // Fonts have local/system fallbacks; startup must not wait on a CDN.
      output=output.replace(/<link\b[^>]*href=["']https:\/\/(?:fonts\.googleapis\.com|fonts\.gstatic\.com|api\.fontshare\.com)[^>]*>/gi,'');
      output=output.replace(/<title>[\s\S]*?<\/title>/i,'<title>Vellum</title>');
      output=output.replace('<div id="root"></div>','<div id="root"><div role="status" aria-live="polite" style="display:grid;min-height:100vh;place-content:center;gap:12px;text-align:center;font-family:system-ui"><strong style="font-size:28px">Vellum</strong><span style="opacity:.65">Opening your workspace…</span></div></div>');
      return output.replace('</head>','<script type="module">import "'+prefix+'boot";</script>\n</head>');
    }},
    resolveId(id){if(id.startsWith(prefix))return '\0'+id;},
    async load(id){
      if(id==='\0'+prefix+'boot'){
        const imports=sources.map((_,index)=>'import init'+index+' from "'+prefix+'init/'+index+'";').join('\n');
        return `import * as React from 'react';
          import * as DOM from 'react-dom';
          import {createRoot,hydrateRoot} from 'react-dom/client';
          ${imports}
          window.React=React;
          window.ReactDOM={...DOM,createRoot,hydrateRoot};
          async function initializeWorkspace(){
            try {
              if(window.VellumDesktop?.runtime==='electron')await window.VellumDesktop.invoke('workspace_ready');
              ${sources.map((_,index)=>'init'+index+'();').join('\n')}
            } catch(error){
              const root=document.getElementById('root');
              const message=document.createElement('p');
              message.setAttribute('role','alert');message.textContent='Vellum could not finish opening. Use Open startup logs in the Vellum menu for details.';
              root.replaceChildren(message);console.error('Workspace initialization failed.');
            }
          }
          if(document.readyState==='complete')initializeWorkspace();
          else document.addEventListener('DOMContentLoaded',initializeWorkspace,{once:true});`;
      }
      if(id.startsWith('\0'+prefix+'init/')){
        const index=Number(id.slice(('\0'+prefix+'init/').length));
        const source=sources[index];
        if(!source)throw new Error('Unknown desktop UI initializer.');
        if(isAbsolute(source.file))this.addWatchFile(source.file);
        const compiled=await transformWithEsbuild(source.code,source.file,{loader:'jsx',jsx:'transform',jsxFactory:'React.createElement',jsxFragment:'React.Fragment',target:'es2022'});
        return 'export default function initialize(){\n'+compiled.code+'\n}';
      }
    },
  };
}

export default mergeConfig(base,{plugins:[desktopWorkspaceBuild()]});

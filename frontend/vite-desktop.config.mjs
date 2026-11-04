// Desktop-only compilation of the canonical preview's legacy Babel scripts.
// The served development entry stays untouched. All desktop React code shares
// the existing frontend dependency instead of loading a second React from CDN.
import {mergeConfig, transformWithEsbuild} from 'vite';
import {readFileSync} from 'node:fs';
import {dirname, isAbsolute, relative, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {parse,parseFragment,serialize} from 'parse5';
import base from './vite.config.mjs';

const uploads=resolve(dirname(fileURLToPath(import.meta.url)),'../design/Velllum/uploads');

export function desktopWorkspaceBuild(root=uploads) {
  const prefix='virtual:vellum-desktop/', sources=[];
  return {
    name:'vellum-desktop-workspace',apply:'build',enforce:'pre',
    transformIndexHtml:{order:'pre',handler(html){
      sources.length=0;
      const document=parse(html),nodes=[];
      const visit=node=>{nodes.push(node);for(const child of node.childNodes||[])visit(child);};
      visit(document);
      const attribute=(node,name)=>node.attrs?.find(item=>item.name===name)?.value;
      const remove=node=>{node.parentNode.childNodes=node.parentNode.childNodes.filter(child=>child!==node);};
      const append=(parent,markup)=>{
        for(const node of parseFragment(markup).childNodes){node.parentNode=parent;parent.childNodes.push(node);}
      };
      for(const node of nodes.filter(node=>node.tagName==='script')){
        const src=attribute(node,'src');
        if(src && /^https:\/\/unpkg\.com\/(?:react(?:-dom)?@|@babel\/standalone@)/.test(src)){remove(node);continue;}
        if(!['text/babel','text/jsx'].includes((attribute(node,'type')||'').trim().toLowerCase()))continue;
        if(src){
          if(/^(?:https?:|\/\/)/i.test(src))throw new Error('Desktop JSX must come from the local workspace source.');
          const file=resolve(root,decodeURIComponent(src.split('?')[0]).replace(/^\//,''));
          const inside=relative(root,file);
          if(inside.startsWith('..')||isAbsolute(inside))throw new Error('Desktop JSX is outside the UI source folder.');
          sources.push({file,code:readFileSync(file,'utf8')});
        }else sources.push({file:'workspace-inline.jsx',code:node.childNodes.map(child=>child.value||'').join('')});
        remove(node);
      }
      // Fonts have local/system fallbacks; startup must not wait on a CDN.
      for(const node of nodes.filter(node=>node.tagName==='link')){
        try {const url=new URL(attribute(node,'href'));if(url.protocol==='https:'&&['fonts.googleapis.com','fonts.gstatic.com','api.fontshare.com'].includes(url.hostname))remove(node);}catch{}
      }
      const title=nodes.find(node=>node.tagName==='title');
      if(title){title.childNodes=[];append(title,'Vellum');}
      const rootNode=nodes.find(node=>attribute(node,'id')==='root');
      if(rootNode && !rootNode.childNodes.length)append(rootNode,'<div role="status" aria-live="polite" style="display:grid;min-height:100vh;place-content:center;gap:12px;text-align:center;font-family:system-ui"><strong style="font-size:28px">Vellum</strong><span style="opacity:.65">Opening your workspace…</span></div>');
      append(nodes.find(node=>node.tagName==='head'),'<script type="module">import "'+prefix+'boot";</script>');
      // Serialize the parsed tree so removing a node cannot join surrounding
      // text into fresh executable HTML on the browser's subsequent parse.
      return serialize(document);
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

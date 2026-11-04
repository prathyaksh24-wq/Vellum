import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {readFileSync} from 'node:fs';
import {expect,test} from 'vitest';
import {loadPublicIcons} from './public-icons-fixture.js';

test('the production entry loads the shared icon renderer before its consumers',()=>{
  const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
  const source='src="components/app-icons.js"';
  expect(html).toContain(source);
  for(const consumer of ['components/browser-panel.jsx','components/plugin-workspace.jsx']){
    expect(html.indexOf(source)).toBeLessThan(html.indexOf('src="'+consumer+'"'));
  }
});

test('shared icon names used by browser and Plugins resolve in the shipped sprite',()=>{
  loadPublicIcons(React);
  const root='../design/Velllum/uploads/';
  const sprite=readFileSync(root+'assets/icons/openai/sprite.svg','utf8');
  for(const [file,mapping] of [['browser-panel.jsx','browserIcons'],['plugin-workspace.jsx','pluginIcons']]){
    const source=readFileSync(root+'components/'+file,'utf8');
    const names=JSON.parse(new RegExp('const '+mapping+'=(\\{[^;]+\\});').exec(source)[1]);
    for(const name of Object.values(names)){
      expect(sprite).toContain('id="'+name+'"');
      expect(renderToStaticMarkup(React.createElement(window.VellumUI.AppIcon,{name}))).toContain('#'+name);
    }
  }
});

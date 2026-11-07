import {readFileSync} from 'node:fs';
import {beforeEach,expect,test,vi} from 'vitest';
const source=readFileSync('../design/Velllum/uploads/components/workspace-resources.js','utf8');
beforeEach(()=>{window.VellumUI={};Function('window',source)(window);});

test('summary derives live resources and latest step state without placeholder sections',()=>{
  const chat={id:'main',thread_id:'main',messages:[
    {id:'one',attachments:[{id:'input',name:'Notes.pdf'}],activity:[{id:'step',type:'plan_step',label:'Read notes',status:'in_progress'}]},
    {id:'two',role:'assistant',artifacts:[{id:'output',name:'Report',type:'site',url:'https://example.org/report'}],sources:[{url:'https://example.org',title:'Source',source_type:'web'}],activity:[{id:'step',type:'plan_step',label:'Read notes',status:'completed'},{id:'agent',type:'sub_agent_completed',name:'Research Agent',status:'completed'}]},
  ]};
  const result=window.VellumUI.taskResources(chat,{chats:[{id:'side',parent_conversation_id:'main',title:'Side task'}],automations:[{id:'unrelated',thread_id:'other'}]});
  expect(result.progress).toHaveLength(1);expect(result.progress[0].status).toBe('completed');
  expect(result.inputs[0].label).toBe('Notes.pdf');expect(result.outputs[0].kind).toBe('url');
  expect(result.sources).toHaveLength(1);expect(result.chats[0].reference).toBe('side');
  expect(result.agents[0].meta).toBe('completed');expect(result.automations).toEqual([]);
});

test('empty tasks do not inherit unrelated schedules or side chats',()=>{
  const result=window.VellumUI.taskResources(null,{chats:[{id:'one'}],automations:[{id:'schedule'}]});
  expect(Object.values(result).every(rows=>rows.length===0)).toBe(true);
});

test('launcher shows available workspace tools without listing installed integrations',()=>{
  const open=vi.fn(),tools=window.VellumUI.workspaceTools({open,browserAvailable:false,terminalAvailable:true,directoryAvailable:false,catalogState:{loaded:true},plugins:[{id:'ready',name:'Connected app',installed:true,enabled:true,apps:[{}]},{id:'disabled',installed:true,enabled:false,apps:[{}]}]});
  expect(tools.map(tool=>tool.id)).toEqual(['files','chat','terminal']);
  tools.at(-1).open();expect(open).toHaveBeenCalledWith('terminal');
});

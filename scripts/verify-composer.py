"""Disposable headless composer checks using fake data and blocked networking.

Does not attach to a browser, read conversations, launch the app or call its API.
Uses the actual served editor/providers and attachment contract/envelope builder.
"""
import ast
import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.scratch/composer'
OUT.mkdir(parents=True, exist_ok=True)
NODE = shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
PACKAGES = ['prosemirror-model','prosemirror-state','prosemirror-view','prosemirror-keymap','prosemirror-commands','prosemirror-history']

def metadata_fixture():
    sys.path.insert(0,str(ROOT/'backend'))
    from agent.plugins.registry import PluginRegistry
    from agent.plugins.sources import CodexPluginSource
    with tempfile.TemporaryDirectory(dir=OUT) as temporary:
        root=Path(temporary);plugins=root/'plugins';native=plugins/'linear';native.mkdir(parents=True)
        (native/'plugin.yaml').write_text('id: linear\nname: Linear\ntype: connector\ncategory: Productivity\nmcp_connectors:\n  - name: linear-server\n    type: http\n    url: https://example.test/mcp\n')
        bundle=plugins/'support';(bundle/'skills/review').mkdir(parents=True)
        (bundle/'plugin.yaml').write_text('''id: support
name: Support
type: bundle
category: Productivity
relationships:
  canonicalAppId: tickets
  remotePluginId: remote-support
provenance:
  marketplace_id: team-market
  source_id: support-source
apps:
  - id: tickets
    name: Tickets
    connected: false
mcp_connectors:
  - name: support-server
    type: http
    url: https://example.test/support
    app_id: tickets
''')
        (bundle/'skills/review/SKILL.md').write_text('---\nname: review-issue\ndescription: Review an issue.\n---\nUse the approved issue workflow.\n')
        external=root/'external';(external/'.codex-plugin').mkdir(parents=True)
        (external/'.codex-plugin/plugin.json').write_text(json.dumps({'name':'external','apps':'apps.json','canonicalAppId':'external-app','remotePluginId':'remote-external','provenance':{'marketplace_id':'declared-market'}}))
        (external/'apps.json').write_text(json.dumps({'apps':{'external-app':{'name':'External app'}}}))
        registry=PluginRegistry(plugins,state_path=root/'state.json',sources=[CodexPluginSource([external])])
        records=registry.catalog(runtime_statuses=[{'id':'linear','configured':True,'metadata':{'connection':{'connected':False}}}],mcp_servers=[{'name':'standalone','configured':True,'status':'configured'}])
        by_id={row['id']:row for row in records}
        assert by_id['linear']['relationships']['canonical_app_id']=='linear'
        linear=by_id['linear']['relationships']['components']
        assert {row['kind'] for row in linear}=={'app','mcp'}
        assert next(row for row in linear if row['kind']=='app')['connected'] is False
        assert by_id['support']['relationships']['remote_plugin_id']=='remote-support'
        assert by_id['support']['provenance']['marketplace_id']=='team-market'
        assert by_id['support']['provenance']['source']=='portable'
        assert {row['kind'] for row in by_id['support']['relationships']['components']}=={'app','mcp','skill'}
        assert by_id['external']['relationships']['canonical_app_id']=='external-app'
        assert by_id['external']['provenance']['marketplace_id']=='declared-market'
        assert by_id['standalone']['relationships']['is_package'] is False
        assert {row['kind'] for row in by_id['standalone']['relationships']['components']}=={'mcp'}
        disabled=registry.set_enabled('support',False)
        assert all(not row['enabled'] for row in disabled['relationships']['components'])
        # Exercise the real declarative archive importer with only fake files.
        import base64, io, zipfile, yaml
        from agent.contracts.plugin_setup import PluginSetup
        payload={'id':'original','type':'bundle','category':'Personal','apps':[{'id':'imported-app','name':'Imported app'}],
            'mcp_connectors':[{'name':'imported-server','url':'https://example.test/imported','app_id':'imported-app'}],
            'relationships':{'canonicalAppId':'imported-app','remotePluginId':'remote-imported'},
            'provenance':{'marketplace_id':'declared-market'}}
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as package:
            package.writestr('plugin.yaml',yaml.safe_dump(payload))
        imported=registry.add(PluginSetup(kind='archive',name='Imported bundle',archive_b64=base64.b64encode(archive.getvalue()).decode('ascii')))
        assert imported['relationships']['remote_plugin_id']=='remote-imported'
        assert imported['relationships']['canonical_app_id']=='imported-app'
        assert imported['provenance']['marketplace_id']=='declared-market'
        assert next(row for row in imported['relationships']['components'] if row['kind']=='mcp')['canonical_id']=='imported-app'
        return records
FIXTURE = r'''
import React,{useState,useRef} from '../../frontend/node_modules/react/index.js';
import * as DOM from '../../frontend/node_modules/react-dom/index.js';
import {createRoot} from '../../frontend/node_modules/react-dom/client.js';
import '../../design/Velllum/uploads/components/morphic-ui.js';
window.React=React;
import {composerComponent,popupGeometry,rankCandidates} from '../../design/Velllum/uploads/components/composer-editor.js';
import {referenceProviders,referenceAttachments,referenceUrl} from '../../design/Velllum/uploads/components/composer-providers.js';
window.fixture={submits:[],commands:[],pastes:[],geometry:popupGeometry,rank:rankCandidates,referenceUrl,referenceAttachments,providerCalls:[]};
const Editor=composerComponent(React,DOM);
const commands=[{k:'web',kind:'command',run:'web',label:'Search the web',aliases:['internet'],description:'Search using the existing action'}, {k:'file',kind:'command',run:'file',label:'Attach file',description:'Choose a file'}, {k:'compact',kind:'command',run:'compact',label:'Compact',description:'Prepare compact command'}];
commands.push(...Array.from({length:24},(_,i)=>({k:'fixture-'+i,kind:'command',run:'fixture',label:'Fixture command '+(i+1)})));
const library=[{id:'file1',name:'Example.txt',attachment:{name:'Example.txt',text_content:'Fake prepared content',egress_scope:'current_turn',metadata_stripped:true}},{id:'seed',name:'Placeholder'}];
const providers=referenceProviders({library,apps:[{id:'linear',name:'Linear'},{id:'notion',name:'Notion'},{id:'product-hunt',name:'Product Hunt'},...Array.from({length:24},(_,i)=>({id:'fixture-app-'+i,name:'Fixture app '+(i+1)}))],skills:[{id:'code-review',name:'Code Review'}],chats:[{id:'chat1',title:'Example conversation'}],browserTabs:[{id:'tab1',title:'Example page',url:'https://example.test/page?token=secret&view=1'}]});
providers.push({id:'remote',label:'Remote',search:async(query,{signal})=>{fixture.providerCalls.push(query);await new Promise(resolve=>setTimeout(resolve,query==='slow'?180:5));return signal.aborted?[]:[{id:'remote:'+query,label:'Remote '+query,reference:{kind:'page',id:query||'empty',label:'Remote '+query,url:'https://example.test/'}}];}});
function Fixture(){
 const [catalogVersion,setCatalogVersion]=useState(0),[value,setValue]=useState(''),[preferred,setPreferred]=useState('up'),[version,setVersion]=useState(0),editor=useRef(null);
 fixture.refreshCatalog=()=>setCatalogVersion(n=>n+1);fixture.value=value;fixture.setValue=setValue;fixture.api=()=>editor.current;fixture.preferred=setPreferred;fixture.remount=()=>setVersion(n=>n+1);
 return <section className="cpill"><Editor key={version} editorRef={editor} value={value} onChange={setValue} commands={commands.map(item=>({...item}))} providers={providers.map(provider=>({...provider}))} preferred={preferred}
 onCommand={item=>{fixture.commands.push(item.k);editor.current.replaceActiveToken(item.run==='compact'?'/compact':'');}}
 onSubmit={()=>fixture.submits.push({text:value,attachments:referenceAttachments(editor.current.getReferences(),library)})}
 referenceIcon={reference=>reference.kind==='app'?({'linear':'assets/plugins/linear.png','notion':'assets/plugins/notion.png','product-hunt':'assets/plugins/producthunt.svg'}[reference.id] || ''):''}
 onPasteFiles={files=>fixture.pastes.push([...files].map(file=>file.name))}/></section>;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
'''

def compile_fixture():
    (OUT/'metadata.json').write_text(json.dumps(metadata_fixture()),encoding='utf8')
    fixture=FIXTURE.replace("window.fixture={", "import metadataCatalog from './metadata.json';\nwindow.fixture={")
    fixture=fixture.replace("const Editor=composerComponent", "fixture.metadataProviders=referenceProviders({apps:metadataCatalog});\nconst Editor=composerComponent")
    fixture=fixture.replace("const [catalogVersion", "const [metadataMode,setMetadataMode]=useState(false);fixture.metadataMode=setMetadataMode;\n const [catalogVersion")
    fixture=fixture.replace("providers={providers.map(provider", "providers={(metadataMode?fixture.metadataProviders:providers).map(provider")
    (OUT/'fixture.jsx').write_text(fixture,encoding='utf8')
    aliases={name:str(ROOT/'frontend/node_modules'/name) for name in PACKAGES}
    script="const esbuild=require("+json.dumps(str(ROOT/'frontend/node_modules/esbuild'))+");esbuild.buildSync("+json.dumps({'entryPoints':[str(OUT/'fixture.jsx')],'bundle':True,'outfile':str(OUT/'fixture.js'),'alias':aliases,'logLevel':'warning'})+");"
    (OUT/'build.cjs').write_text(script,encoding='utf8')
    subprocess.run([NODE,str(OUT/'build.cjs')],cwd=ROOT,check=True)
    source=(ROOT/'design/Velllum/uploads/Vellum Default Re-designed.html').read_text(encoding='utf8')
    pieces=[source[source.index('const SLASH_ITEMS ='):source.index('// Both legacy web React')],source[source.index('const RichComposerEditor ='):source.index('const ChatHeadMenu =')],source[source.index('const Composer ='):source.index('const MsgActions =')]]
    pieces.insert(0,source[source.index('const SIMPLE_ICON_ROOT ='):source.index('const ConnLogo =')])
    body='\n'.join(pieces)
    icons=sorted(set(re.findall(r'\bIc[A-Z]\w*',body)))
    integration=r'''
import React,{useState,useEffect,useRef} from '../../frontend/node_modules/react/index.js';
import * as ReactDOM from '../../frontend/node_modules/react-dom/index.js';
import {createRoot} from '../../frontend/node_modules/react-dom/client.js';
import '../../design/Velllum/uploads/components/morphic-ui.js';
window.React=React;
import {composerComponent,referenceProviders,referenceAttachments} from '../../design/Velllum/uploads/composer-entry.js';
'''.replace("import {composerComponent,referenceProviders,referenceAttachments} from '../../design/Velllum/uploads/composer-entry.js';", "import '../../design/Velllum/uploads/composer-entry.js';")
    integration+='\nconst '+','.join(icon+'=()=>null' for icon in icons)+';\n'
    integration+="const MODELS=[],AGENTS=[],TRENDING=[],COMPOSER_PLACEHOLDER='Message',API={voice:{}},AttachmentRuntime={actionEffect:()=>null},ModelLogo=()=>null,modelLabel=id=>id;\n"
    integration+=body+r'''
window.integration={sends:[],openedPlugins:[]};
function Fixture(){const [text,setText]=useState('');integration.text=text;integration.setText=setText;
return <Composer text={text} setText={setText} model="fake" setModel={()=>{}} models={[]} library={[]} projects={[]} apps={[{id:'linear',name:'Linear'},{id:'asana',name:'Asana',type:'connector',mcp_connectors:[{name:'asana-server',display_name:'Asana MCP'}]},{id:'opaque-owner',name:'Asana',source:'mcp_configuration',mcp_connectors:[{name:'opaque-server',display_name:'Work tracker'}]}]} skills={[{id:'code-review',name:'Code Review'},...Array.from({length:12},(_,i)=>({id:'workflow-'+i,name:'Fixture workflow '+(i+1)}))]}
chats={[{id:'fixture-chat',title:'Fixture conversation'}]} memoryEnabled={true} onMemoryChange={()=>{throw Error('Memory control must be absent');}}
onOpenPlugins={plugin=>integration.openedPlugins.push(plugin?.id || plugin?.name || 'manage')} onSend={(text,attachments,options)=>integration.sends.push({text,attachments,options})}/>;}
createRoot(document.getElementById('root')).render(<Fixture/>);
'''
    (OUT/'integration.jsx').write_text(integration,encoding='utf8')
    script=script.replace('fixture.jsx','integration.jsx').replace('fixture.js','integration.js')
    (OUT/'build-integration.cjs').write_text(script,encoding='utf8')
    subprocess.run([NODE,str(OUT/'build-integration.cjs')],cwd=ROOT,check=True)
    plugin_source=(ROOT/'design/Velllum/uploads/components/plugin-workspace.jsx').read_text(encoding='utf8')
    settings=plugin_source[plugin_source.index('  function Settings({'):plugin_source.index('  function ToolGroups({')]
    settings_entry=r'''
import React,{useState} from '../../frontend/node_modules/react/index.js';
import {createRoot} from '../../frontend/node_modules/react-dom/client.js';
import '../../design/Velllum/uploads/composer-entry.js';
import catalog from './metadata.json';
const name=x=>x.display_name||x.normalized_name||x.name||x.id;
const components=p=>window.VellumComposer.componentsForPlugin(p);
const Ic=({n})=><i data-icon={n}/>;
const Tile=({p})=><span aria-hidden="true">{p.name.slice(0,1)}</span>;
const Add=()=>null;
const Search=({q,setQ,ph})=><input aria-label={ph} value={q} onChange={event=>setQ(event.target.value)}/>;
const Sw=({value,label,disabled,onChange})=><button role="switch" aria-label={label} aria-checked={value} disabled={disabled} onClick={()=>onChange(!value)}/>;
const ActionLink=({children,onClick,...props})=><button onClick={onClick} {...props}>{children}</button>;
const SkillRow=({s})=><div className="fixture-skill">{name(s)}</div>;
const Detail=()=>null;
let context;const useX=()=>context;
__SETTINGS__
window.settingsFixture={};
function Fixture(){const [tab,setTab]=useState('plugins');context={plugins:catalog,skills:catalog.flatMap(p=>p.skills||[]),skillsLoaded:true,go:r=>r.tab&&setTab(r.tab),setDlg:()=>{},changePlugin:()=>{},busy:false};return <Settings key={tab} tab={tab}/>;}
createRoot(document.getElementById('root')).render(<Fixture/>);
'''.replace('__SETTINGS__',settings)
    (OUT/'settings.jsx').write_text(settings_entry,encoding='utf8')
    (OUT/'build-settings.cjs').write_text(script.replace('integration.jsx','settings.jsx').replace('integration.js','settings.js'),encoding='utf8')
    subprocess.run([NODE,str(OUT/'build-settings.cjs')],cwd=ROOT,check=True)

def verify_contract():
    sys.path.insert(0,str(ROOT/'backend'))
    from agent.app_actions.attachments import ConversationAttachment
    from pydantic import ValidationError
    tree=ast.parse((ROOT/'backend/agent/api.py').read_text(encoding='utf8'))
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_agent_content_with_attachments')
    namespace={'Any':Any,'ChatAttachment':ConversationAttachment}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'attachment-envelope','exec'),namespace)
    make=namespace[fn.name]
    record=ConversationAttachment.model_validate({'kind':'reference','reference':{'kind':'browser_tab','id':'tab1','label':'Example page','url':'https://example.test/page?token=private&view=1#secret'}})
    envelope=make('Read this',[record])
    assert 'private' not in json.dumps(envelope) and '#secret' not in json.dumps(envelope)
    assert envelope[1]['metadata_stripped'] is True and envelope[1]['egress_scope']=='current_turn'
    assert 'not been fetched' in envelope[1]['text']
    assert record.reference.model_dump()==ConversationAttachment.model_validate(record.model_dump()).reference.model_dump()
    for url in ['javascript:alert(1)','file:///private','https://user:pass@example.test/']:
        try: ConversationAttachment.model_validate({'reference':{'kind':'page','id':'1','label':'Example','url':url}})
        except ValidationError: pass
        else: raise AssertionError('Unsafe reference URL accepted')
    file=ConversationAttachment(name='Example.txt',text_content='Fake content',egress_scope='current_turn',metadata_stripped=True)
    assert make('hello',[file])[1]['text']=='Fake content'
    assert make('hello',[])=='hello'
    source=(ROOT/'design/Velllum/uploads/Vellum Default Re-designed.html').read_text(encoding='utf8')
    composer=source[source.index('const Composer ='):source.index('const Composer =')+26000]
    assert 'Turn memory ' not in composer and '<textarea ref={taRef}' not in composer
    assert 'referenceAttachments(taRef.current?.getReferences()' in composer
    return 'typed references, URL safety, attachment compatibility, metadata envelope, memory button removal'

async def verify_picker(context):
    """Exercise the production Composer callbacks, not a replacement selector."""
    page=await context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    css='\n'.join((ROOT/'design/Velllum/uploads/components'/name).read_text(encoding='utf-8') for name in ['composer-editor.css','agent-composer.css'])
    await page.set_content('<base href="https://fixture.test/"><style>:root{--txt:#eee;--txt2:#eee;--dim:#aaa;--line2:#555;--active:#3a3a3a;--modal:#242424}body{margin:0;background:#171717;color:#eee;font:14px system-ui}.cpill{position:absolute;left:40px;bottom:40px;width:700px;border:1px solid #555;border-radius:20px;padding:16px}</style><style>'+css+'</style><div id="root"></div>')
    await page.add_script_tag(content=(OUT/'integration.js').read_text(encoding='utf-8'))
    editor=page.get_by_role('combobox',name='Message');await editor.wait_for()
    report={}
    async def draft(text):
        await editor.focus();await editor.press('Control+A');await editor.press('Backspace');await editor.press_sequentially(text)
        await page.wait_for_timeout(100)
    for scope,kind,label in [('plugins','plugin','Asana'),('mcps','mcp','Asana MCP'),('apps','app','Asana')]:
        await draft('/'+scope+':Asana')
        option=page.get_by_role('option').filter(has=page.locator('strong',has_text=label)).first;await option.wait_for()
        report[scope+'Logo']=await option.locator('img[src="assets/plugins/asana.svg"]').count()==1
        opened=await page.evaluate('integration.openedPlugins.length')
        await editor.press('Tab');await page.wait_for_timeout(80)
        report[scope+'Inserted']=await page.locator('.composer-reference[data-reference-kind="'+kind+'"]').count()==1
        report[scope+'NoNavigation']=await page.evaluate('integration.openedPlugins.length')==opened
        if report[scope+'Inserted']:
            count=await page.evaluate('integration.sends.length')
            await page.get_by_role('button',name='Send',exact=True).click()
            await page.wait_for_function('(count)=>integration.sends.length>count',arg=count)
            reference=await page.evaluate('integration.sends.at(-1).attachments[0].reference')
            report[scope+'Identity']=reference['kind']==kind and reference['owner_plugin_id']=='asana' and bool(reference['id'])
            if kind=='mcp':report['mcpComponent']=reference['component_id']=='asana-server'
        await draft('/'+scope+':Asana')
        await page.get_by_role('option').filter(has=page.locator('strong',has_text=label)).first.click()
        report[scope+'ClickInserted']=await page.locator('.composer-reference[data-reference-kind="'+kind+'"]').count()==1 and await page.evaluate('integration.openedPlugins.length')==opened
    await draft('/mcps:Work')
    opaque=page.get_by_role('option').filter(has=page.locator('strong',has_text='Work tracker')).first
    await opaque.wait_for();report['mcpOwnerLogo']=await opaque.locator('img[src="assets/plugins/asana.svg"]').count()==1
    await draft('/plugins')
    await page.get_by_role('option').filter(has=page.locator('strong',has_text='Manage plugins')).first.click()
    report['managePluginsStillNavigates']=await page.evaluate('integration.openedPlugins.at(-1)')=='manage'
    await draft('Compare @')
    await page.get_by_role('option').filter(has=page.locator('strong',has_text='Skills')).click()
    await page.wait_for_function('integration.text==="Compare @skills:"')
    await editor.press('Escape');await page.wait_for_timeout(80)
    report['escapeReturnsToCategories']=await page.locator('[data-composer-popup]').count()==1 and await page.evaluate('integration.text')=='Compare @'
    await draft('Compare @')
    await page.get_by_role('option').filter(has=page.locator('strong',has_text='MCPs')).click()
    await page.wait_for_function('integration.text==="Compare @mcps:"')
    await editor.press('Escape');await page.wait_for_timeout(80)
    report['escapeFromMcp']=await page.locator('[data-composer-popup]').count()==1 and await page.evaluate('integration.text')=='Compare @'
    await editor.press('Escape');await page.wait_for_timeout(80)
    report['escapeAtRootDismisses']=await page.locator('[data-composer-popup]').count()==0
    await draft('/skills:')
    await editor.press('Escape');await page.wait_for_timeout(80)
    report['slashEscapeReturnsToRoot']=await page.locator('[data-composer-popup]').count()==1 and await page.evaluate('integration.text')=='/'
    await draft('@apps:Asana')
    await page.get_by_role('option').filter(has=page.locator('strong',has_text='Asana')).first.wait_for();await editor.press('Tab');await editor.press_sequentially('x')
    report['caretGeometry']=await page.locator('.ProseMirror').evaluate('''node=>{const label=node.querySelector('.composer-reference>span');const text=document.createRange();text.selectNodeContents(label);const selection=getSelection().getRangeAt(0);return {labelTop:text.getBoundingClientRect().top,caretTop:selection.getBoundingClientRect().top}}''')
    report['caretAligned']=abs(report['caretGeometry']['labelTop']-report['caretGeometry']['caretTop'])<1
    await page.screenshot(path=str(OUT/('picker-before.png' if '--baseline' in sys.argv else 'picker-after.png')))
    report['pageErrors']=errors
    (OUT/'picker-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    failures=[key for key,value in report.items() if value is False]
    assert not failures and not errors,failures or errors
    await page.close()
    return ['production slash plugin/app/MCP vendor logos and structured Tab selection without page navigation','scoped Escape returns to categories and root Escape dismisses without changing prefix','connector-label and adjacent text/caret share their baseline']

async def run():
    from playwright.async_api import async_playwright
    results=[];errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',headless=True,args=['--mute-audio','--disable-extensions','--no-first-run'])
        context=await browser.new_context(viewport={'width':1000,'height':760})
        await context.route('**/*',lambda route:route.abort())
        def asset_handler(asset):
            async def fulfill(route):
                await route.fulfill(path=str(ROOT/'design/Velllum/uploads/assets/plugins'/asset))
            return fulfill
        for asset in ['linear.png','notion.png','producthunt.svg','asana.svg']:
            await context.route('https://fixture.test/assets/plugins/'+asset,asset_handler(asset))
        if '--picker-only' in sys.argv:
            results=await verify_picker(context)
            await context.close();await browser.close()
            return results
        page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        css=(ROOT/'design/Velllum/uploads/components/composer-editor.css').read_text()+'\n'+(ROOT/'design/Velllum/uploads/components/agent-composer.css').read_text()
        await page.set_content('<base href="https://fixture.test/"><style>:root{--txt:#ddd;--txt2:#eee;--dim:#aaa;--line2:#555;--active:#3a3a3a;--modal:#242424}body{margin:0;background:#171717;color:#eee;font:14px system-ui}.cpill{position:absolute;left:40px;bottom:40px;width:500px;border:1px solid #555;padding:16px}.composer-editor-host{overflow:hidden}</style><style>'+css+'</style><div id="root"></div>')
        await page.add_script_tag(content=(OUT/'fixture.js').read_text(encoding='utf8'))
        editor=page.get_by_role('combobox',name='Message')
        await editor.wait_for()
        async def draft(text,caret=None):
            await page.evaluate('(text)=>fixture.setValue(text)',text)
            await page.wait_for_function('(text)=>fixture.api()?.getText()===text',arg=text)
            await page.evaluate('(pos)=>fixture.api().setSelection(pos)',len(text) if caret is None else caret)
            await page.wait_for_timeout(80)
        async def option(label):
            row=page.get_by_role('option').filter(has=page.locator('strong',has_text=label))
            await row.first.wait_for();return row.first
        async def no_menu():
            await page.wait_for_function('()=>!document.querySelector("[data-composer-popup]")')
        await draft('/internet')
        await option('Search the web')
        assert await page.get_by_role('option').count()==1
        measured=await page.evaluate('''()=>{const input=document.querySelector('.cpill').getBoundingClientRect(),popup=document.querySelector('[data-composer-popup]').getBoundingClientRect();return {input:{left:input.left,width:input.width,top:input.top},popup:{left:popup.left,width:popup.width,bottom:popup.bottom}};}''')
        assert abs(measured['input']['width']-measured['popup']['width'])<1,measured
        assert abs(measured['input']['left']-measured['popup']['left'])<1,measured
        assert measured['popup']['bottom']<=measured['input']['top']-7,measured
        results.append('suggestion menu matches the full input-box width and sits above its edge')
        await editor.press('Enter')
        await page.wait_for_function('()=>fixture.commands.includes("web")')
        assert await page.evaluate('fixture.submits.length')==0
        results.append('slash aliases and Enter select without sending')
        await draft('Before /weBAD after',10)
        await editor.press('Tab')
        await page.wait_for_function('()=>fixture.value==="Before  after"')
        results.append('caret detection replaces full mid-message token and preserves suffix')
        for text in ['mail@example.test','https://example.test/page','`/web','```\n/web','ordinary text']:
            await draft(text);await no_menu()
        results.append('URLs, email, code and unrelated text do not trigger menus')
        await draft('/')
        await editor.press('Escape');await no_menu()
        await editor.press('w');await option('Search the web')
        results.append('Escape dismisses; editing query reopens')
        await draft('@tabs:Example')
        await (await option('Example page')).click()
        await no_menu()
        assert (await page.evaluate('fixture.api().getReferences()'))[0]['id']=='tab1'
        await editor.press('Enter')
        sent=await page.evaluate('fixture.submits.at(-1)')
        assert sent['attachments'][0]['reference']['url']=='https://example.test/page?view=1'
        await page.evaluate('fixture.setValue(fixture.value+"dictated text")')
        await page.wait_for_function('()=>fixture.api().getText().endsWith("dictated text")')
        assert len(await page.evaluate('fixture.api().getReferences()'))==1
        results.append('atomic reference, structured send and external dictation append')
        await draft('')
        assert await page.evaluate('fixture.api().getReferences().length')==0
        await draft('@files:Example');await editor.press('Tab')
        await editor.press('Enter')
        assert (await page.evaluate('fixture.submits.at(-1)'))['attachments'][0]['text_content']=='Fake prepared content'
        results.append('prepared file reference follows existing attachment payload')
        await page.wait_for_timeout(550)  # Separate the edit from the insertion's normal undo group.
        await editor.press('Backspace');await editor.press('Backspace')
        # ProseMirror selects an atom first; the next backspace removes it.
        if await page.evaluate('fixture.api().getReferences().length'):
            await editor.press('Backspace')
        assert await page.evaluate('fixture.api().getReferences().length')==0
        await editor.press('Control+z')
        assert await page.evaluate('fixture.api().getReferences().length')==1
        results.append('atomic reference deletion and undo restore its identity')
        await draft('@apps:Linear');await editor.press('Tab')
        await page.wait_for_function('()=>document.querySelector(".composer-reference img")?.naturalWidth>0')
        mention=page.locator('.composer-reference')
        assert await mention.inner_text()=='Linear'
        assert await mention.evaluate('(el)=>getComputedStyle(el).borderTopWidth')=='0px'
        assert await mention.evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgba(0, 0, 0, 0)'
        assert (await page.evaluate('fixture.api().getReferences()'))[0]['id']=='linear'
        await page.screenshot(path=str(OUT/'composer-inline-logo.png'))
        results.append('borderless inline Linear logo/name preserves structured reference')
        await draft('')
        for query,label,count in [('apps:Notion','Notion',1),('apps:Linear','Linear',2),('apps:Product','Product Hunt',3),('skills:Code','Code Review',4)]:
            await editor.press_sequentially('@'+query)
            await option(label);await editor.press('Tab')
            await page.wait_for_function('(count)=>document.querySelectorAll(".composer-reference").length===count',arg=count)
        await page.wait_for_function('()=>[...document.querySelectorAll(".composer-reference img")].every(img=>img.naturalWidth>0)')
        appearances=await page.locator('.composer-reference').evaluate_all('(nodes)=>nodes.map(node=>({kind:node.dataset.referenceKind,color:getComputedStyle(node).color,border:getComputedStyle(node).borderTopWidth,text:node.textContent}))')
        assert len(set(row['color'] for row in appearances))>1,appearances
        assert all(row['border']=='0px' for row in appearances)
        assert await page.locator('[data-reference-icon="skill"]').count()==1
        assert len(await page.evaluate('fixture.api().getReferences()'))==4
        await page.locator('.cpill').screenshot(path=str(OUT/'composer-multiple-references.png'))
        results.append('multiple connector colours, bundled logos and skill cube coexist inline')

        await draft('@')
        await (await option('Browser tabs')).click()
        await page.wait_for_function('()=>fixture.value==="@tabs:"')
        await option('Example page')
        results.append('mention scope opens scoped provider results')
        await draft('@slow');await draft('@fast')
        await page.wait_for_timeout(230)
        assert 'Remote fast' in await page.get_by_role('listbox').inner_text()
        assert 'Remote slow' not in await page.get_by_role('listbox').inner_text()
        results.append('stale asynchronous provider responses cannot replace current query')
        await draft('@remote:slow')
        count=await page.evaluate('fixture.submits.length')
        await editor.press('Enter')
        assert await page.evaluate('fixture.submits.length')==count
        await page.wait_for_timeout(130)
        results.append('pending reference query does not accidentally submit')
        for query in ['/', '@apps:Fixture']:
            await draft(query)
            await page.wait_for_function('()=>document.querySelectorAll("[role=option]").length>=20')
            for _ in range(12): await editor.press('ArrowDown')
            selected=await page.locator('[role=option][aria-selected=true] strong').inner_text()
            for _ in range(3):
                await page.evaluate('fixture.refreshCatalog()');await page.wait_for_timeout(100)
                assert await page.locator('[role=option][aria-selected=true] strong').inner_text()==selected
            for _ in range(40): await editor.press('ArrowDown')
            state=await page.locator('[data-composer-popup]').evaluate('''el=>{const options=[...el.querySelectorAll('[role=option]')],selected=el.querySelector('[aria-selected=true]'),a=selected.getBoundingClientRect(),b=el.getBoundingClientRect();return {last:options.at(-1)===selected,scroll:el.scrollTop,visible:a.top>=b.top && a.bottom<=b.bottom};}''')
            assert state['last'] and state['scroll']>0 and state['visible'],state
            selected=await page.locator('[role=option][aria-selected=true] strong').inner_text()
            await page.evaluate('fixture.refreshCatalog()');await page.wait_for_timeout(250)
            assert await page.locator('[role=option][aria-selected=true] strong').inner_text()==selected
        results.append('slash and mention arrows reach the bottom and retain selection through repeated catalog refreshes')
        for query in ['/', '@apps:Fixture']:
            await draft(query)
            await page.wait_for_function('()=>document.querySelectorAll("[role=option]").length>=20')
            menu=page.locator('[data-composer-popup]');box=await menu.bounding_box()
            await page.mouse.move(box['x']+box['width']-9,box['y']+box['height']/2)
            await page.mouse.wheel(0,450);await page.wait_for_timeout(120)
            down=await menu.evaluate('(el)=>el.scrollTop');assert down>200,down
            await page.evaluate('fixture.refreshCatalog()');await page.wait_for_timeout(180)
            assert abs(await menu.evaluate('(el)=>el.scrollTop')-down)<2
            await page.mouse.wheel(0,-180);await page.wait_for_timeout(120)
            up=await menu.evaluate('(el)=>el.scrollTop');assert up<down,{'up':up,'down':down}
            await page.wait_for_timeout(160)
            assert abs(await menu.evaluate('(el)=>el.scrollTop')-up)<2
            assert await menu.locator('[data-shared-layout-group] > .hlb').count()==1
        results.append('trackpad-style wheel scrolling in both lists stays put through refresh and uses the shared row background')

        await draft('line one');await editor.press('Shift+Enter');await editor.press('A')
        assert await page.evaluate('fixture.value')=='line one\nA'
        await editor.press('Control+z')
        assert not (await page.evaluate('fixture.value')).endswith('A')
        results.append('multiline input and undo')
        await draft('')
        await editor.dispatch_event('paste',{'clipboardData':None})
        await page.evaluate(r'''()=>{const e=fixture.api().dom(),data=new DataTransfer();data.setData('text/plain','first\nsecond');e.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));}''')
        await page.wait_for_function('()=>fixture.value==="first\\nsecond"')
        await page.evaluate('''()=>{const data=new DataTransfer();data.items.add(new File(['fake'],'Example.txt',{type:'text/plain'}));fixture.api().dom().dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));}''')
        assert await page.evaluate('fixture.pastes.at(-1)[0]')=='Example.txt'
        results.append('plain multiline paste and existing file-paste callback')
        await draft('/web')
        before=await page.evaluate('fixture.submits.length')
        await editor.dispatch_event('compositionstart')
        await no_menu()
        await editor.dispatch_event('keydown',{'key':'Enter','isComposing':True,'keyCode':229})
        assert await page.evaluate('fixture.submits.length')==before
        await editor.dispatch_event('compositionend');await option('Search the web')
        results.append('IME does not submit or select during composition')
        await draft('/')
        await page.evaluate('''()=>{const root=document.getElementById('root');root.style.cssText='position:relative;width:650px;height:760px';document.querySelector('.cpill').style.cssText='position:absolute;right:0;bottom:40px;width:500px;padding:16px';}''')
        await page.wait_for_timeout(80)
        await page.evaluate('document.getElementById("root").style.width="900px"')
        await page.wait_for_function('''()=>Math.abs(document.querySelector('.cpill').getBoundingClientRect().left-document.querySelector('[data-composer-popup]').getBoundingClientRect().left)<1''')
        results.append('full-width menu follows parent resizing even when input width stays fixed')
        await page.evaluate('document.getElementById("root").removeAttribute("style")')
        await page.set_viewport_size({'width':390,'height':400})
        await page.evaluate('document.querySelector(".cpill").style.cssText="position:absolute;left:10px;top:15px;bottom:auto;width:330px;padding:10px"')
        await draft('/')
        await page.wait_for_timeout(100)
        geometry=await page.locator('[data-composer-popup]').evaluate('(el)=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,side:el.dataset.placement}}')
        assert geometry['side']=='down' and geometry['left']>=0 and geometry['right']<=390 and geometry['bottom']<=400,geometry
        await page.screenshot(path=str(OUT/'composer-narrow.png'))
        results.append('portal flips below caret and fits narrow viewport')
        await page.set_viewport_size({'width':1000,'height':760})
        await page.evaluate('document.querySelector(".cpill").style.cssText="position:absolute;left:40px;bottom:40px;width:500px;padding:16px"')
        await draft('@tabs:Example')
        await page.screenshot(path=str(OUT/'composer-reference.png'))
        await page.evaluate('fixture.metadataMode(true)')
        await draft('@')
        for label in ['Plugins','Apps','MCPs','Skills','Conversations','Files']:
            await option(label)
        assert 'Sites' not in await page.get_by_role('listbox').inner_text()
        await draft('@Linear')
        await option('Linear')
        assert await page.get_by_role('option').count()==1
        assert await page.locator('.composer-suggestion-heading').inner_text()=='Apps'
        await draft('@plugins:Linear');await option('Linear')
        assert await page.locator('.composer-suggestion-heading').inner_text()=='Plugins'
        await editor.press('Tab')
        assert (await page.evaluate('fixture.api().getReferences()'))[0]['kind']=='plugin'
        await draft('@mcps:linear');await option('linear-server');await editor.press('Tab')
        reference=(await page.evaluate('fixture.api().getReferences()'))[0]
        assert reference['kind']=='mcp' and reference['owner_plugin_id']=='linear' and reference['component_id']=='linear-server'
        await draft('@skills:review');await option('review-issue');await editor.press('Tab')
        assert (await page.evaluate('fixture.api().getReferences()'))[0]['owner_plugin_id']=='support'
        results.append('categorized providers use actual registry metadata, suppress linked duplicates and preserve scoped package/MCP/skill identities')
        await draft('@plugins:')
        await page.screenshot(path=str(OUT/'composer-categories.png'))
        radius=await page.locator('[data-composer-popup]').evaluate('el=>({outer:getComputedStyle(el).borderTopLeftRadius,inset:getComputedStyle(el).paddingTop,row:getComputedStyle(el.querySelector("[role=option]")).borderTopLeftRadius,highlight:getComputedStyle(el.querySelector(".hlb")).borderTopLeftRadius})')
        assert radius=={'outer':'20px','inset':'4px','row':'16px','highlight':'16px'},radius
        results.append('coordinated outer/inset/row/shared-highlight corner geometry')
        await page.close()
        page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        await page.set_content('<base href="https://fixture.test/"><style>'+css+'</style><div id="root"></div>')
        await page.add_script_tag(content=(OUT/'integration.js').read_text(encoding='utf8'))
        editor=page.get_by_role('combobox',name='Message');await editor.wait_for()
        assert await page.get_by_role('button',name=re.compile('memory',re.I)).count()==0
        await editor.press_sequentially('/')
        await page.get_by_role('option').filter(has_text='More skills').wait_for()
        headings=await page.locator('.composer-suggestion-heading').all_inner_texts()
        assert all(label in headings for label in ['Commands','Skills','Plugins','Apps']),headings
        await page.get_by_role('option').filter(has_text='More skills').click()
        await page.wait_for_function('()=>integration.text==="/skills:"')
        assert await page.locator('.composer-suggestion-heading').inner_text()=='Skills'
        await page.wait_for_function('()=>document.querySelectorAll("[role=option]").length===13')
        await editor.press('Control+A');await editor.press('Backspace')
        results.append('production slash menu groups registered workflows and browses a category without running it')

        await editor.press_sequentially('@chats:Fixture')
        await page.get_by_role('option').filter(has_text='Fixture conversation').wait_for()
        await editor.press('Enter')
        assert await page.locator('.composer-reference').count()==1
        await page.get_by_role('button',name='Send',exact=True).click()
        await page.wait_for_function('()=>integration.sends.length===1 && integration.text===""')
        sent=await page.evaluate('integration.sends[0]')
        assert sent['attachments'][0]['reference']['id']=='fixture-chat'
        assert sent['options']['deliveryMode']=='send'
        await editor.press_sequentially('@apps:Linear')
        await page.get_by_role('option').filter(has_text='Linear').wait_for();await editor.press('Tab')
        await page.wait_for_function('()=>document.querySelector(".composer-reference img")?.naturalWidth>0')
        assert await page.locator('.composer-reference').inner_text()=='Linear'
        await page.get_by_role('button',name='Send',exact=True).click()
        await page.wait_for_function('()=>integration.sends.length===2 && integration.text===""')
        await editor.press_sequentially('/Code')
        await page.get_by_role('option').filter(has_text='Code Review').wait_for();await editor.press('Tab')
        await page.locator('[data-reference-icon="skill"]').wait_for()
        assert await page.locator('.composer-reference').inner_text()=='Code Review'
        await page.get_by_role('button',name='Send',exact=True).click()
        await page.wait_for_function('()=>integration.sends.length===3 && integration.text===""')
        assert await page.evaluate('integration.sends[2].attachments[0].reference.kind')=='skill'
        results.append('production slash skill selection inserts a structured inline skill reference')
        await editor.press_sequentially('Find /web')
        await page.get_by_role('option').filter(has_text='Web search').wait_for()
        await editor.press('Tab')
        await page.get_by_title('Turn off web search',exact=True).wait_for(timeout=3000)
        assert await page.evaluate('integration.text')=='Find '
        await editor.press_sequentially('example');await editor.press('Enter')
        await page.wait_for_function('()=>integration.sends.length===4')
        assert await page.evaluate('integration.sends[3].options.forceWebSearch') is True
        results.append('production Composer callbacks: reference Send, clear, web mode and memory button absent')
        results.extend(await verify_picker(context))
        await page.close()
        page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        await page.set_content('<style>body{background:#171717;color:#eee;font:14px system-ui}.li{display:flex;gap:12px;padding:14px}.pl{display:flex;gap:12px}.pl button{padding:10px}</style><div id="root"></div>')
        await page.add_script_tag(content=(OUT/'settings.js').read_text(encoding='utf8'))
        await page.get_by_role('button',name=re.compile('^Apps')).click()
        assert await page.locator('.li').count()==3
        await page.get_by_role('switch',name='Enable Linear',exact=True).wait_for()
        await page.get_by_role('button',name=re.compile('^MCPs')).click()
        await page.get_by_role('button',name='standalone',exact=True).wait_for()
        await page.get_by_role('button',name='linear-server',exact=True).wait_for()
        assert await page.get_by_role('switch',name='Enable standalone',exact=True).is_disabled()
        await page.get_by_role('button',name=re.compile('^Skills')).click()
        await page.locator('.fixture-skill',has_text='review-issue').wait_for()
        await page.get_by_role('button',name=re.compile('^Plugins')).click()
        assert await page.locator('.li').count()==3
        assert 'standalone' not in await page.locator('.lc').inner_text()
        assert 'marketplace_id' not in await page.locator('body').inner_text()
        results.append('existing Plugins settings tabs share package/app/MCP/skill classification without exposing a metadata panel')
        assert not errors,errors
        await context.close();await browser.close()
    return results

if __name__=='__main__':
    compile_fixture()
    results=asyncio.run(run())
    results.append(verify_contract())
    (OUT/'results.json').write_text(json.dumps({'checks':results,'count':len(results),'data':'fake only','network':'blocked'},indent=2),encoding='utf8')
    print(json.dumps({'passed':len(results),'checks':results},indent=2))

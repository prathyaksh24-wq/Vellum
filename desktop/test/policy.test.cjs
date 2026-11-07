const {test} = require('node:test');
const assert = require('node:assert/strict');
const {workspaceURL, conversationTarget, trustedWorkspace, validateCommand} = require('../electron/policy.cjs');

test('desktop workspace accepts only loopback and uses the canonical entry', () => {
  assert.match(workspaceURL(), /^http:\/\/127\.0\.0\.1:5173\/design-uploads\/.*desktop=1$/);
  for (const value of ['https://example.org', 'file:///C:/private', 'http://user@localhost', 'http://localhost.evil.org']) {
    assert.throws(() => workspaceURL(value));
  }
});

test('detached conversations reuse one window without interpreting IDs as URLs', () => {
  const base = workspaceURL();
  const one = conversationTarget(base, 'chat / one & two');
  assert.deepEqual(conversationTarget(base, 'chat / one & two'), one);
  assert.equal(new URL(one.url).searchParams.get('conversation_id'), 'chat / one & two');
  assert.equal(new URL(one.url).origin, new URL(base).origin);
  assert.notEqual(conversationTarget(base, 'another').key, one.key);
  for (const id of ['', '  ', 'chat\nother', 'a'.repeat(161), null]) assert.throws(() => conversationTarget(base, id));
});

test('the native bridge rejects other origins and other pages on the local server', () => {
  const base = workspaceURL();
  assert.equal(trustedWorkspace(conversationTarget(base, 'chat').url, base), true);
  for (const url of ['about:blank', 'https://example.org', 'http://127.0.0.1:5173/other.html',
    base.replace(':5173', ':8000'), base.replace('127.0.0.1', '127.0.0.1.evil.org')]) {
    assert.equal(trustedWorkspace(url, base), false);
  }
});

test('desktop commands cannot become an arbitrary IPC or process-execution interface', () => {
  for(const command of ['workspace_ready','protected_audio_ready']){
    assert.deepEqual(validateCommand(command,{}),{});
    assert.throws(()=>validateCommand(command,{url:'https://example.com'}));
  }
  assert.deepEqual(validateCommand('set_overlay', {enabled: true}), {enabled: true});
  validateCommand('open_conversation_window', {conversationId: 'chat'});
  for (const [command, args] of [['exec', {}], ['set_overlay', {enabled: 'yes'}],
    ['open_vellum_window', {url: 'file:///private'}], ['open_conversation_window', {conversationId: ''}],
    ['backend_health', []]]) assert.throws(() => validateCommand(command, args));
});

test('skill file actions accept registered identifiers rather than paths or commands',()=>{
  assert.deepEqual(validateCommand('skill_file',{name:'my-skill',operation:'reveal'}),{name:'my-skill',operation:'reveal'});
  for(const args of [{name:'../private',operation:'open'},{name:'skill',operation:'exec'},
    {name:'skill',operation:'open',path:'C:/private.txt'},{name:'skill\ncommand',operation:'open'}]){
    assert.throws(()=>validateCommand('skill_file',args));
  }
});


test('workspace files expose only bounded read operations through the desktop bridge',()=>{
  assert.deepEqual(validateCommand('workspace_files',{operation:'list',relativePath:''}),{operation:'list',relativePath:''});
  for(const args of [{operation:'write',relativePath:'a'},{operation:'read',relativePath:42},
    {operation:'read',relativePath:'a',command:'execute'}])assert.throws(()=>validateCommand('workspace_files',args));
});

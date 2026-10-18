const {createHash} = require('node:crypto');

const ENTRY = '/design-uploads/Vellum%20Default%20Re-designed.html';
const COMMANDS = new Set(['backend_health', 'open_vellum_window', 'open_conversation_window', 'set_overlay']);

function workspaceURL(base = 'http://127.0.0.1:5173') {
  const url = new URL(base);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password) {
    throw new Error('The desktop workspace must use a loopback HTTP address.');
  }
  url.pathname = ENTRY;
  url.search = '?desktop=1';
  url.hash = '';
  return url.href;
}

function conversationTarget(base, conversationId) {
  if (typeof conversationId !== 'string') throw new Error('Invalid conversation ID.');
  const clean = conversationId.trim();
  if (!clean || clean.length > 160 || /[\u0000-\u001f\u007f]/.test(clean)) throw new Error('Invalid conversation ID.');
  const url = new URL(base);
  url.searchParams.set('conversation_id', clean);
  return {key: 'conversation-' + createHash('sha256').update(clean).digest('hex').slice(0, 24), url: url.href};
}

function trustedWorkspace(candidate, base) {
  try {
    const url = new URL(candidate);
    const expected = new URL(base);
    return url.origin === expected.origin && url.pathname === expected.pathname && !url.username && !url.password;
  } catch { return false; }
}

function validateCommand(command, args) {
  if (!COMMANDS.has(command)) throw new Error('Unknown desktop command.');
  if (args === undefined) args = {};
  if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error('Invalid desktop arguments.');
  const keys = command === 'open_conversation_window' ? ['conversationId'] : command === 'set_overlay' ? ['enabled'] : [];
  if (Object.keys(args).some(key => !keys.includes(key))) throw new Error('Unexpected desktop argument.');
  if (command === 'set_overlay' && typeof args.enabled !== 'boolean') throw new Error('Expected an overlay state.');
  if (command === 'open_conversation_window') conversationTarget('http://127.0.0.1/', args.conversationId);
  return args;
}

module.exports = {ENTRY, workspaceURL, conversationTarget, trustedWorkspace, validateCommand};

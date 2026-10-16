import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {test,expect} from 'vitest';

const source=readFileSync(resolve('../backend/agent/mcp/dedicated_browser.py'),'utf8');
const script=source.match(/ELEMENT_DESCRIPTOR = r"""([\s\S]*?)"""/)[1];
const describe=Function('return ('+script+')')();

test('page observations show current search text and focus without exposing secret fields',()=>{
  const root=document.createElement('div');document.body.append(root);
  root.innerHTML='<input type="search" aria-label="Search Wikipedia"><input type="password" aria-label="Search account password"><input name="q" autocomplete="one-time-code"><input type="text" aria-label="Search topics"><input type="text" name="card-number">';
  const [search,password,otp,topics,card]=root.querySelectorAll('input');
  search.value='streetfighter movie';password.value='private-password';otp.value='123456';topics.value='black holes';card.value='private-card';
  search.focus();
  expect(describe(search)).toMatchObject({value:'streetfighter movie',focused:true});
  expect(describe(topics).value).toBe('black holes');
  for(const secret of [password,otp,card])expect(describe(secret).value).toBe('');
  search.value='a'.repeat(2000);expect(describe(search).value).toHaveLength(1000);
  root.remove();
});

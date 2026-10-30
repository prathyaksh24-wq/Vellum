import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createHmac} from 'node:crypto';
import {handle,maintenance} from '../src/worker.mjs';

const require=createRequire(import.meta.url);
const wranglerRequire=createRequire(require.resolve('wrangler'));
const {Miniflare,convertV4MiniflareOptions}=wranglerRequire('miniflare');

test('Cloudflare workerd and D1 persist a signed callback and serve authenticated catch-up',async()=>{
  const secret='b'.repeat(64),token='t'.repeat(43),bearer='A'.repeat(43),channel='UC'+'a'.repeat(22);
  const mf=new Miniflare(convertV4MiniflareOptions({modules:true,scriptPath:fileURLToPath(new URL('../src/worker.mjs',import.meta.url)),
    compatibilityDate:'2026-10-12',d1Databases:{DB:'runtime-test'},
    bindings:{PUBLIC_ORIGIN:'https://personal.example.workers.dev',VELLUM_RELAY_TOKEN:bearer}}));
  try {
    const db=await mf.getD1Database('DB');
    const schema=readFileSync(new URL('../migrations/0001_relay.sql',import.meta.url),'utf8');
    // Cloudflare's exec accepts complete statements; keep trigger bodies intact.
    await db.exec(schema.replace(/--[^\n]*/g,'').replace(/\s+/g,' '));
    const response=await mf.dispatchFetch('https://personal.example.workers.dev/v1/channels',{method:'PUT',
      headers:{Authorization:'Bearer '+bearer},body:JSON.stringify({contract_version:1,channels:[{channel_id:channel,token,secret}]})});
    assert.equal(response.status,200);
    const now=Math.floor(Date.now()/1000);
    await db.prepare("UPDATE channels SET requested_at=?,mode='subscribe' WHERE channel_id=?").bind(now,channel).run();
    const params=new URLSearchParams({'hub.mode':'subscribe','hub.topic':'https://www.youtube.com/xml/feeds/videos.xml?channel_id='+channel,
      'hub.challenge':'real-runtime-challenge','hub.lease_seconds':'864000'});
    const challenge=await mf.dispatchFetch('https://personal.example.workers.dev/youtube/websub/'+token+'?'+params);
    assert.equal(challenge.status,200);assert.equal(await challenge.text(),'real-runtime-challenge');
    const body=`<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>abcdefghijk</yt:videoId><yt:channelId>${channel}</yt:channelId><title>Runtime upload</title><published>${new Date().toISOString()}</published></entry></feed>`;
    const signature='sha256='+createHmac('sha256',secret).update(body).digest('hex');
    for(let replay=0;replay<2;replay++)assert.equal((await mf.dispatchFetch('https://personal.example.workers.dev/youtube/websub/'+token,
      {method:'POST',body,headers:{'X-Hub-Signature':signature}})).status,204);
    assert.equal((await mf.dispatchFetch('https://personal.example.workers.dev/v1/events')).status,401);
    const page=await (await mf.dispatchFetch('https://personal.example.workers.dev/v1/events?after=0',
      {headers:{Authorization:'Bearer '+bearer}})).json();
    assert.equal(page.events.length,1);assert.equal(page.events[0].body,body);
    assert.equal((await mf.dispatchFetch('https://personal.example.workers.dev/api/automations')).status,404);
  } finally {await mf.dispose();}
});

test('idle retention maintenance does not scan the unexpired upload backlog',async()=>{
  const mf=new Miniflare(convertV4MiniflareOptions({modules:true,scriptPath:fileURLToPath(new URL('../src/worker.mjs',import.meta.url)),
    compatibilityDate:'2026-10-17',d1Databases:{DB:'query-budget-test'}}));
  try {
    const db=await mf.getD1Database('DB'),now=Math.floor(Date.now()/1000);
    await db.exec(readFileSync(new URL('../migrations/0001_relay.sql',import.meta.url),'utf8').replace(/--[^\n]*/g,'').replace(/\s+/g,' '));
    await db.prepare(`WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000)
      INSERT INTO events(channel_id,digest,body,received_at,bytes) SELECT 'channel',CAST(x AS TEXT),'body',?,4 FROM n`).bind(now).run();
    let reads=0;
    const record=result=>{reads+=result.meta.rows_read;return result;};
    const wrap=statement=>({bind:(...args)=>wrap(statement.bind(...args)),
      run:async()=>record(await statement.run()),all:async()=>record(await statement.all()),
      first:async()=>{const result=record(await statement.all());return result.results[0]??null;}});
    const DB={prepare:sql=>wrap(db.prepare(sql)),batch:async statements=>{
      const values=[];for(const statement of statements)values.push(await statement.run());return values;
    }};
    await maintenance({DB,VELLUM_RELAY_TOKEN:'A'.repeat(43),PUBLIC_ORIGIN:'https://personal.example.workers.dev'},{now});
    assert.ok(reads<100,`Idle cleanup scanned ${reads} rows for 10,000 unexpired events`);
    assert.equal((await db.prepare('SELECT event_count FROM relay_state').first()).event_count,10000);
    const epoch=(await db.prepare('SELECT epoch FROM relay_state').first()).epoch;
    const response=await handle(new Request('https://personal.example.workers.dev/v1/ack',{method:'POST',
      headers:{Authorization:'Bearer '+'A'.repeat(43)},body:JSON.stringify({contract_version:1,epoch,after:10000})}),
      {DB:db,VELLUM_RELAY_TOKEN:'A'.repeat(43)},{now:now+86401});
    assert.equal(response.status,200);
    assert.equal((await response.json()).pruned,500,'Count deleted events, not D1 trigger changes');
    assert.equal((await db.prepare('SELECT event_count FROM relay_state').first()).event_count,9500);
  } finally {await mf.dispose();}
});

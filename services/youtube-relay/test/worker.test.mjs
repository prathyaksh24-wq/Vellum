import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {createHmac,randomBytes} from 'node:crypto';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {handle,maintenance} from '../src/worker.mjs';

const ORIGIN='https://vellum.example.workers.dev',NOW=1792231200;
const channel=n=>'UC'+String(n).padStart(22,'0');
const xml=id=>`<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>abcdefghijk</yt:videoId><yt:channelId>${id}</yt:channelId><title>Real title</title><published>2026-10-17T10:00:00Z</published></entry></feed>`;

class D1 {
  constructor(){this.db=new DatabaseSync(':memory:');this.db.exec(readFileSync(new URL('../migrations/0001_relay.sql',import.meta.url),'utf8'));}
  prepare(sql){
    const db=this.db;
    const build=(args=[])=>({
      bind:(...values)=>build(values),
      async first(){return db.prepare(sql).get(...args)??null;},
      async all(){return {success:true,results:db.prepare(sql).all(...args)};},
      async run(){
        if(/\bRETURNING\b/.test(sql)){const results=db.prepare(sql).all(...args);return {success:true,results,meta:{changes:results.length}};}
        const result=db.prepare(sql).run(...args);return {success:true,meta:{changes:Number(result.changes),last_row_id:Number(result.lastInsertRowid)}};}
    });return build();
  }
  async batch(statements){this.db.exec('BEGIN');try{const values=[];for(const statement of statements)values.push(await statement.run());this.db.exec('COMMIT');return values;}catch(error){this.db.exec('ROLLBACK');throw error;}}
}

function setup(t) {
  const DB=new D1();t.after(()=>DB.db.close());
  const env={DB,PUBLIC_ORIGIN:ORIGIN,VELLUM_RELAY_TOKEN:randomBytes(32).toString('base64url')};
  const send=(method,path,body,headers={},now=NOW)=>handle(new Request(ORIGIN+path,{method,
    headers:{Authorization:'Bearer '+env.VELLUM_RELAY_TOKEN,...headers},...(body===undefined?{}:{body:typeof body==='string'?body:JSON.stringify(body)})}),env,{now});
  const targets=Array.from({length:302},(_,index)=>({channel_id:channel(index),token:randomBytes(32).toString('base64url'),secret:randomBytes(32).toString('hex')}));
  const verify=async (url,options)=>{
    assert.equal(url,'https://pubsubhubbub.appspot.com/subscribe');assert.equal(options.redirect,'manual');
    const values=options.body,callback=new URL(values.get('hub.callback'));
    for(const key of ['hub.mode','hub.topic'])callback.searchParams.set(key,values.get(key));
    callback.searchParams.set('hub.challenge','google-challenge');callback.searchParams.set('hub.lease_seconds','864000');
    const result=await handle(new Request(callback),env,{now:NOW});
    assert.equal(result.status,200);assert.equal(await result.text(),'google-challenge');
    return new Response(null,{status:202});
  };
  const publish=(target,body=xml(target.channel_id),now=NOW)=>send('POST','/youtube/websub/'+target.token,body,
    {'X-Hub-Signature':'sha1='+createHmac('sha1',target.secret).update(body).digest('hex')},now);
  return {env,send,targets,verify,publish};
}

test('private routes are authenticated, unknown routes stay absent, secrets are redacted',async t=>{
  const {send,env}=setup(t);
  assert.equal((await send('GET','/api/automations')).status,404);
  assert.equal((await send('GET','/docs')).status,404);
  assert.equal((await send('GET','/v1/events',undefined,{Authorization:'Bearer incorrect'})).status,401);
  assert.equal((await send('GET','/v1/status',undefined,{Authorization:''})).status,401);
  const status=await (await send('GET','/v1/status')).text();
  assert.ok(!status.includes(env.VELLUM_RELAY_TOKEN));assert.ok(!status.includes('secret'));
});

test('an exhausted daily D1 allowance has a sanitized public failure code',async t=>{
  const {env,send}=setup(t);
  env.DB.prepare=()=>{throw new Error("Your account has exceeded D1's free tier daily row read limit. PRIVATE");};
  const response=await send('GET','/v1/status');
  assert.equal(response.status,503);
  const body=await response.json();assert.equal(body.code,'daily_database_limit');
  assert.ok(!JSON.stringify(body).includes('PRIVATE'));
});

test('all 302 channels register and renew without a local backend or its OAuth token',async t=>{
  const {env,send,targets,verify}=setup(t);
  assert.equal((await send('PUT','/v1/channels',{contract_version:1,channels:targets})).status,200);
  for(let tick=0;tick<13;tick++)await maintenance(env,{now:NOW+tick,fetcher:verify});
  const status=await (await send('GET','/v1/status')).json();
  assert.equal(status.active_channels,302);assert.equal(status.desired_channels,302);
  for(const row of targets){assert.ok(!JSON.stringify(status).includes(row.token));assert.ok(!JSON.stringify(status).includes(row.secret));}
  // A later Cron invocation renews leases even when the laptop has never polled.
  let renewals=0;
  await maintenance(env,{now:NOW+700000,fetcher:async()=>{renewals++;return new Response(null,{status:202});}});
  assert.equal(renewals,24);
});

test('signed events commit before 204, survive worker reconstruction, and deduplicate replay',async t=>{
  const {env,send,targets,verify,publish}=setup(t);const target=targets[0];
  await send('PUT','/v1/channels',{contract_version:1,channels:[target]});await maintenance(env,{now:NOW,fetcher:verify});
  assert.equal((await publish(target)).status,204);assert.equal((await publish(target)).status,204);
  const page=await (await send('GET','/v1/events?after=0')).json();
  assert.equal(page.events.length,1);assert.equal(page.events[0].body,xml(target.channel_id));
  assert.equal(page.next_after,page.events[0].id);assert.equal(page.gap,false);
  assert.equal((await (await send('GET','/v1/events?after='+page.next_after)).json()).events.length,0);
  const changed={...env};
  const status=await handle(new Request(ORIGIN+'/v1/status',{headers:{Authorization:'Bearer '+changed.VELLUM_RELAY_TOKEN}}),changed,{now:NOW});
  assert.equal((await status.json()).buffered_events,1);
});

test('forgery, oversized streams, DTD and invalid verification are rejected',async t=>{
  const {env,send,targets,verify,publish}=setup(t);const target=targets[0];
  await send('PUT','/v1/channels',{contract_version:1,channels:[target]});await maintenance(env,{now:NOW,fetcher:verify});
  assert.equal((await send('POST','/youtube/websub/'+target.token,xml(target.channel_id))).status,403);
  assert.equal((await publish(target,'x'.repeat(262145))).status,413);
  assert.equal((await publish(target,'<!DOCTYPE feed><feed/>')).status,400);
  assert.equal((await send('GET','/youtube/websub/'+target.token+'?hub.mode=subscribe&hub.topic=evil&hub.challenge=bad&hub.lease_seconds=100')).status,404);
});

test('full replacement disables removed channels; invalid manifests preserve the prior list',async t=>{
  const {env,send,targets,verify,publish}=setup(t);
  await send('PUT','/v1/channels',{contract_version:1,channels:targets.slice(0,2)});await maintenance(env,{now:NOW,fetcher:verify});
  assert.equal((await send('PUT','/v1/channels',{contract_version:1,channels:[null]})).status,400);
  assert.equal((await (await send('GET','/v1/status')).json()).desired_channels,2);
  await send('PUT','/v1/channels',{contract_version:1,channels:targets.slice(0,1)});
  assert.equal((await publish(targets[1])).status,404);
  assert.equal((await publish(targets[0])).status,204);
  assert.equal((await (await send('GET','/v1/status')).json()).desired_channels,1);
});

test('seven-day retention reports a checkpoint gap and preserves accurate capacity counters',async t=>{
  const {env,send,targets,verify,publish}=setup(t);const target=targets[0];
  await send('PUT','/v1/channels',{contract_version:1,channels:[target]});await maintenance(env,{now:NOW,fetcher:verify});
  await publish(target);
  await maintenance(env,{now:NOW+7*86400+1,fetcher:async()=>new Response(null,{status:202})});
  const page=await (await send('GET','/v1/events?after=0')).json();
  assert.equal(page.gap,true);assert.ok(page.retention_floor>0);assert.equal(page.next_after,page.retention_floor);
  const status=await (await send('GET','/v1/status')).json();assert.equal(status.buffered_events,0);assert.equal(status.stored_bytes,0);
});

test('rotation removes only durably acknowledged events older than one day and is safe to retry',async t=>{
  const {env,send,targets,verify,publish}=setup(t);const target=targets[0];
  await send('PUT','/v1/channels',{contract_version:1,channels:[target]});await maintenance(env,{now:NOW,fetcher:verify});
  for(let index=0;index<3;index++)await publish(target,xml(target.channel_id).replace('Real title','Upload '+index),NOW+index);
  const page=await (await send('GET','/v1/events?after=0')).json(),after=page.events[1].id;
  const ack=(epoch=page.epoch,id=after,now=NOW+86402)=>send('POST','/v1/ack',{contract_version:1,epoch,after:id},{},now);
  assert.equal((await ack('wrong')).status,409);
  assert.equal((await ack(page.epoch,999999)).status,400);
  assert.equal((await ack(page.epoch,after,NOW+60)).status,200);
  assert.equal((await (await send('GET','/v1/status')).json()).buffered_events,3);
  assert.equal((await ack()).status,200);assert.equal((await ack()).status,200);
  const remaining=await (await send('GET','/v1/events?after=0')).json();
  assert.equal(remaining.gap,true);assert.equal(remaining.retention_floor,after);
  assert.deepEqual(remaining.events.map(row=>row.id),[page.events[2].id]);
  const status=await (await send('GET','/v1/status')).json();
  assert.equal(status.buffered_events,1);assert.equal(status.stored_bytes,new TextEncoder().encode(remaining.events[0].body).length);
  assert.equal((await send('POST','/v1/ack',{contract_version:1,epoch:page.epoch,after},{Authorization:''})).status,401);
});

test('a full buffer returns retryable 503 without acknowledging a lost event',async t=>{
  const {env,send,targets,verify,publish}=setup(t);const target=targets[0];
  await send('PUT','/v1/channels',{contract_version:1,channels:[target]});await maintenance(env,{now:NOW,fetcher:verify});
  env.DB.db.exec('UPDATE relay_state SET stored_bytes=67108864 WHERE id=1');
  assert.equal((await publish(target)).status,503);
  assert.equal((await (await send('GET','/v1/events?after=0')).json()).events.length,0);
});

test('hub failures use durable backoff and never expose the provider response',async t=>{
  const {env,send,targets}=setup(t);let calls=0;
  await send('PUT','/v1/channels',{contract_version:1,channels:targets.slice(0,1)});
  const fail=async()=>{calls++;throw new Error('PRIVATE PROVIDER BODY');};
  await maintenance(env,{now:NOW,fetcher:fail});await maintenance(env,{now:NOW+1,fetcher:fail});
  assert.equal(calls,1);assert.ok(!(await (await send('GET','/v1/status')).text()).includes('PRIVATE PROVIDER BODY'));
  await maintenance(env,{now:NOW+121,fetcher:fail});assert.equal(calls,2);
});

/** Personal, self-hosted WebSub transport. No Google OAuth or private user data. */
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const TOKEN=/^[A-Za-z0-9_-]{43}$/;
const SECRET=/^[a-f0-9]{64}$/;
const TOPIC='https://www.youtube.com/xml/feeds/videos.xml?channel_id=';
const HUB='https://pubsubhubbub.appspot.com/subscribe';
const MAX_BODY=262144;
const RETENTION=7*86400;
const json=(value,status=200)=>Response.json(value,{status,headers:{'Cache-Control':'no-store'}});
const seconds=()=>Math.floor(Date.now()/1000);
const hex=bytes=>Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
class RequestError extends Error {constructor(status,message){super(message);this.status=status;}}
const reject=(status,message)=>{throw new RequestError(status,message);};

async function boundedBody(request) {
  const reader=request.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks=[];let length=0;
  const deadline=Date.now()+15000;
  try {
    for (;;) {
      let timer;
      const part=await Promise.race([reader.read(),new Promise((_,fail)=>{
        timer=setTimeout(()=>fail(new RequestError(408,'Request deadline exceeded.')),Math.max(1,deadline-Date.now()));
      })]).finally(()=>clearTimeout(timer));
      if (part.done) break;
      length+=part.value.length;
      if (length>MAX_BODY) reject(413,'Request body too large.');
      chunks.push(part.value);
    }
  } catch (error) {await reader.cancel().catch(()=>{});throw error;}
  const body=new Uint8Array(length);let offset=0;
  for (const chunk of chunks){body.set(chunk,offset);offset+=chunk.length;}
  return body;
}

async function authenticate(request,env) {
  if (!TOKEN.test(env.VELLUM_RELAY_TOKEN||'')) reject(503,'Receiver credentials are not configured.');
  const supplied=request.headers.get('Authorization')||'';
  const digest=async text=>hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)));
  // Hash both strings before comparison; the 256-bit bearer secret never enters a URL.
  if (await digest(supplied)!==await digest('Bearer '+env.VELLUM_RELAY_TOKEN)) reject(401,'Unauthorized.');
}

async function verifySignature(raw,signature,secret) {
  const match=/^(sha1|sha256)=([a-f0-9]+)$/.exec(signature||'');
  if (!match||match[2].length!==(match[1]==='sha1'?40:64)) return false;
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),
    {name:'HMAC',hash:match[1]==='sha1'?'SHA-1':'SHA-256'},false,['verify']);
  return crypto.subtle.verify('HMAC',key,Uint8Array.from(match[2].match(/../g),value=>parseInt(value,16)),raw);
}

async function callback(request,env,token,now) {
  const row=await env.DB.prepare('SELECT * FROM channels WHERE token=?').bind(token).first();
  if (!row) reject(404,'Unknown subscription.');
  const params=new URL(request.url).searchParams;
  if (request.method==='GET') {
    const mode=params.get('hub.mode'),challenge=params.get('hub.challenge')||'';
    if (mode!==row.mode||!['subscribe','unsubscribe'].includes(mode)||
        params.get('hub.topic')!==TOPIC+row.channel_id||!row.requested_at||Math.abs(now-row.requested_at)>600)
      reject(404,'Unknown verification request.');
    if (!/^[\x20-\x7e]{1,1024}$/.test(challenge)) reject(400,'Invalid challenge.');
    const lease=Number(params.get('hub.lease_seconds'));
    if (mode==='subscribe'&&(!Number.isInteger(lease)||lease<1||lease>31*86400)) reject(400,'Invalid lease.');
    if (mode==='subscribe'&&!row.desired) reject(404,'Inactive subscription.');
    const expires=mode==='subscribe'?now+lease:0,renew=mode==='subscribe'?now+Math.floor(lease*0.8):0;
    await env.DB.prepare("UPDATE channels SET lease_expires=?,renew_at=?,next_at=?,failures=0,error='' WHERE token=?")
      .bind(expires,renew,mode==='subscribe'?renew:now+864000,token).run();
    return new Response(challenge,{headers:{'Content-Type':'text/plain','Cache-Control':'no-store'}});
  }
  if (request.method!=='POST') reject(405,'Method not allowed.');
  if (!row.desired||row.lease_expires<=now) reject(404,'Inactive subscription.');
  const raw=await boundedBody(request);
  if (!await verifySignature(raw,request.headers.get('X-Hub-Signature'),row.secret)) reject(403,'Invalid signature.');
  let body;
  try {body=new TextDecoder('utf-8',{fatal:true}).decode(raw);} catch {reject(400,'Invalid UTF-8.');}
  if (!body||/\u0000|<!DOCTYPE|<!ENTITY/i.test(body)) reject(400,'Unsupported XML.');
  // Keep the original signed bytes as UTF-8. The canonical local parser validates
  // XML structure, exact video/channel IDs and dates before local ingestion.
  const digest=hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(row.channel_id+'\n'+body)));
  try {
    await env.DB.prepare('INSERT OR IGNORE INTO events(channel_id,digest,body,received_at,bytes) VALUES(?,?,?,?,?)')
      .bind(row.channel_id,digest,body,now,raw.length).run();
  } catch {reject(503,'Event storage unavailable; retry later.');}
  return new Response(null,{status:204});
}

async function replaceTargets(request,env) {
  let payload;
  try {payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await boundedBody(request)));}
  catch(error){if(error instanceof RequestError) throw error;reject(400,'Invalid target manifest.');}
  if (payload?.contract_version!==1||!Array.isArray(payload.channels)||payload.channels.length>1000)
    reject(400,'Expected at most 1000 channels.');
  const channels=payload.channels;
  if (channels.some(row=>!row||typeof row!=='object')||
      new Set(channels.map(row=>row.channel_id)).size!==channels.length||new Set(channels.map(row=>row.token)).size!==channels.length||
      channels.some(row=>!CHANNEL.test(row.channel_id)||!TOKEN.test(row.token)||!SECRET.test(row.secret)))
    reject(400,'Invalid channel credentials.');
  const normalized=channels.map(({channel_id,token,secret})=>({channel_id,token,secret})).sort((a,b)=>a.channel_id.localeCompare(b.channel_id));
  const revision=hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(normalized))));
  const state=await env.DB.prepare('SELECT revision FROM relay_state WHERE id=1').first();
  if (state.revision===revision) return json({contract_version:1,revision,desired_channels:channels.length});
  const statements=[];
  // At most 100 bound parameters per statement, and <50 statements per free invocation.
  for (let offset=0;offset<channels.length;offset+=25) {
    const chunk=channels.slice(offset,offset+25);
    statements.push(env.DB.prepare(`INSERT INTO channels(channel_id,token,secret,desired,revision) VALUES
      ${chunk.map(()=>'(?,?,?,1,?)').join(',')}
      ON CONFLICT(channel_id) DO UPDATE SET
        lease_expires=CASE WHEN channels.token=excluded.token AND channels.secret=excluded.secret AND channels.desired=1 THEN channels.lease_expires ELSE 0 END,
        renew_at=CASE WHEN channels.token=excluded.token AND channels.secret=excluded.secret AND channels.desired=1 THEN channels.renew_at ELSE 0 END,
        next_at=CASE WHEN channels.token=excluded.token AND channels.secret=excluded.secret AND channels.desired=1 THEN channels.next_at ELSE 0 END,
        token=excluded.token,secret=excluded.secret,desired=1,revision=excluded.revision`)
      .bind(...chunk.flatMap(row=>[row.channel_id,row.token,row.secret,revision])));
  }
  statements.push(env.DB.prepare("UPDATE channels SET desired=0,next_at=0 WHERE desired=1 AND revision<>?").bind(revision));
  statements.push(env.DB.prepare('UPDATE relay_state SET revision=? WHERE id=1').bind(revision));
  // D1 batch is atomic: a failed full replacement cannot disable the previous list.
  await env.DB.batch(statements);
  return json({contract_version:1,revision,desired_channels:channels.length});
}

async function status(env,now) {
  const rows=(await env.DB.prepare('SELECT channel_id,desired,lease_expires,error FROM channels').all()).results;
  const state=await env.DB.prepare('SELECT * FROM relay_state WHERE id=1').first();
  const desired=rows.filter(row=>row.desired);
  return {contract_version:1,epoch:state.epoch,revision:state.revision,
    desired_channels:desired.length,active_channels:desired.filter(row=>row.lease_expires>now).length,
    last_received_at:state.last_received_at,last_maintenance:state.last_maintenance,
    buffered_events:state.event_count,stored_bytes:state.stored_bytes,retention_days:7,
    warnings:[...new Set([state.error,...desired.map(row=>row.error)].filter(Boolean))],
    channels:desired.map(row=>({channel_id:row.channel_id,lease_expires:row.lease_expires}))};
}

async function events(request,env) {
  const params=new URL(request.url).searchParams;
  const value=params.get('after')||'0',limitValue=params.get('limit')||'20';
  if (!/^\d{1,15}$/.test(value)) reject(400,'Invalid checkpoint.');
  if(!/^[1-9]\d{0,2}$/.test(limitValue)||Number(limitValue)>100)reject(400,'Invalid page limit.');
  const limit=Number(limitValue);
  const after=Number(value),state=await env.DB.prepare('SELECT epoch,retention_floor FROM relay_state WHERE id=1').first();
  const rows=(await env.DB.prepare('SELECT id,channel_id,body,received_at,bytes FROM events WHERE id>? ORDER BY id LIMIT ?').bind(after,limit+1).all()).results;
  const selected=[];let size=0;
  for (const row of rows.slice(0,limit)) {if(size+row.bytes>1048576) break;selected.push(row);size+=row.bytes;}
  return json({contract_version:1,epoch:state.epoch,retention_floor:state.retention_floor,
    gap:after<state.retention_floor,events:selected,next_after:selected.at(-1)?.id??Math.max(after,state.retention_floor),
    has_more:rows.length>selected.length});
}

async function rotateEvents(env,cutoff,after=Number.MAX_SAFE_INTEGER) {
  // MAX(id) otherwise prefers the rowid index and scans the entire fresh
  // backlog when nothing has expired. Force the existing timestamp index,
  // and bound deletion work while advancing the gap marker atomically.
  const eligible=`SELECT id FROM events INDEXED BY events_retention
    WHERE received_at<? AND id<=? ORDER BY received_at,id LIMIT 500`;
  const results=await env.DB.batch([
    env.DB.prepare(`UPDATE relay_state SET retention_floor=MAX(retention_floor,
      COALESCE((SELECT MAX(id) FROM (${eligible})),0)) WHERE id=1`).bind(cutoff,after),
    env.DB.prepare(`DELETE FROM events WHERE id IN (${eligible}) RETURNING id`).bind(cutoff,after)
  ]);
  // D1 meta.changes includes the counter trigger's UPDATE as well as DELETEs.
  return results[1].results.length;
}

async function acknowledge(request,env,now) {
  let payload;
  try {payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await boundedBody(request)));}
  catch(error){if(error instanceof RequestError)throw error;reject(400,'Invalid checkpoint.');}
  if(payload?.contract_version!==1||typeof payload.epoch!=='string'||payload.epoch.length>128||
    !Number.isSafeInteger(payload.after)||payload.after<0)reject(400,'Invalid checkpoint.');
  const state=await env.DB.prepare('SELECT epoch,retention_floor,COALESCE((SELECT MAX(id) FROM events),0) AS latest FROM relay_state WHERE id=1').first();
  if(payload.epoch!==state.epoch)reject(409,'Receiver history changed.');
  if(payload.after>Math.max(state.latest,state.retention_floor))reject(400,'Checkpoint exceeds receiver history.');
  const pruned=await rotateEvents(env,now-86400,payload.after);
  return json({contract_version:1,epoch:state.epoch,after:payload.after,pruned});
}

export async function maintenance(env,{now=seconds(),fetcher=fetch}={}) {
  if (!TOKEN.test(env.VELLUM_RELAY_TOKEN||'')||!/^https:\/\/[^/?#]+$/.test(env.PUBLIC_ORIGIN||'')) return;
  const lease=await env.DB.prepare('UPDATE relay_state SET job_until=? WHERE id=1 AND job_until<?').bind(now+120,now).run();
  if (!lease.meta.changes) return;
  try {
    await rotateEvents(env,now-RETENTION);
    await env.DB.prepare("DELETE FROM channels WHERE desired=0 AND lease_expires=0 AND next_at>?").bind(now).run();
    const due=(await env.DB.prepare(`SELECT * FROM channels WHERE next_at<=? AND
      ((desired=1 AND renew_at<=?) OR (desired=0 AND (lease_expires>0 OR mode<>'unsubscribe')))
      ORDER BY next_at,channel_id LIMIT 24`).bind(now,now).all()).results;
    if (due.length) {
      await env.DB.prepare(`UPDATE channels SET mode=CASE WHEN desired=1 THEN 'subscribe' ELSE 'unsubscribe' END,
        requested_at=?,next_at=?,error='Awaiting YouTube callback verification.'
        WHERE channel_id IN (${due.map(()=>'?').join(',')})`).bind(now,now+600,...due.map(row=>row.channel_id)).run();
      for (let offset=0;offset<due.length;offset+=4) {
        await Promise.all(due.slice(offset,offset+4).map(async row=>{
          try {
            const response=await fetcher(HUB,{method:'POST',redirect:'manual',signal:AbortSignal.timeout(8000),
              body:new URLSearchParams({'hub.mode':row.desired?'subscribe':'unsubscribe','hub.topic':TOPIC+row.channel_id,
                'hub.callback':env.PUBLIC_ORIGIN+'/youtube/websub/'+row.token,'hub.verify':'async',
                'hub.secret':row.secret,'hub.lease_seconds':'864000'})});
            await response.body?.cancel();
            if (response.status!==202) throw new Error('Hub unavailable');
          } catch {
            const failures=Math.min(row.failures+1,8);
            // A successful verification can arrive before a failed/late POST result.
            await env.DB.prepare("UPDATE channels SET failures=?,next_at=?,error='YouTube hub registration unavailable.' WHERE channel_id=? AND requested_at=? AND lease_expires<=?")
              .bind(failures,now+Math.min(60*2**failures,3600),row.channel_id,now,now).run();
          }
        }));
      }
    }
    await env.DB.prepare("UPDATE relay_state SET last_maintenance=?,error='' WHERE id=1").bind(now).run();
  } catch {await env.DB.prepare("UPDATE relay_state SET error='Receiver maintenance deferred.' WHERE id=1").run();}
  finally {await env.DB.prepare('UPDATE relay_state SET job_until=0 WHERE id=1').run();}
}

export async function handle(request,env,{now=seconds()}={}) {
  try {
    const url=new URL(request.url),match=/^\/youtube\/websub\/([A-Za-z0-9_-]{43})$/.exec(url.pathname);
    if (match) return await callback(request,env,match[1],now);
    if (!['/v1/status','/v1/events','/v1/channels','/v1/ack'].includes(url.pathname)) reject(404,'Not found.');
    await authenticate(request,env);
    if (url.pathname==='/v1/status'&&request.method==='GET') return json(await status(env,now));
    if (url.pathname==='/v1/events'&&request.method==='GET') return await events(request,env);
    if (url.pathname==='/v1/channels'&&request.method==='PUT') return await replaceTargets(request,env);
    if (url.pathname==='/v1/ack'&&request.method==='POST') return await acknowledge(request,env,now);
    reject(405,'Method not allowed.');
  } catch(error) {
    if (!(error instanceof RequestError)&&/exceeded D1's free tier daily row (?:read|write) limit/i.test(String(error?.message||'')))
      return json({code:'daily_database_limit',error:'Hosted database daily allowance exhausted; retry after the next UTC midnight.'},503);
    return json({error:error instanceof RequestError?error.message:'Receiver request deferred.'},error instanceof RequestError?error.status:503);
  }
}

export default {fetch:handle,async scheduled(_event,env,_ctx){await maintenance(env);}};

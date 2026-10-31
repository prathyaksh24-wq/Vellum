import {expect,test,vi} from 'vitest';

async function load(){
  vi.resetModules();
  const request=vi.fn(async()=>({status:'applied'}));
  window.VellumApi={client:{backendBase:()=> 'http://127.0.0.1:8000',request,jsonOptions:(method,body)=>({method,body:JSON.stringify(body)})},appActions:{dispatch:vi.fn()}};
  await import('../../../design/Velllum/uploads/api/local-music.js');
  return {api:window.VellumApi.localMusic,request};
}

test('local file upload sends the selected file and occurrence with the UI guard',async()=>{
  const {api,request}=await load(),file=new File(['audio'],'owned.wav',{type:'audio/wav'});
  await api.upload(file,'selected-entry');
  const [path,options]=request.mock.calls[0];expect(path).toBe('/api/music/local/files');expect(options.headers['X-Vellum-Music']).toBe('1');
  expect(options.body.get('file').name).toBe('owned.wav');expect(options.body.get('entry_id')).toBe('selected-entry');
});

test('local media URLs share the workspace loopback hostname for browser media requests',async()=>{
  const {api}=await load();const audio=new URL(api.audioUrl('entry'));
  expect(audio.hostname).toBe(location.hostname);expect(audio.port).toBe('8000');expect(audio.pathname).toBe('/api/music/local/audio/entry');
});


test('library embedded-artwork paths resolve through the local backend origin',async()=>{
  const {api,request}=await load();request.mockResolvedValue({collections:[{id:'imports',entries:[{id:'entry',artwork_url:'/api/music/local/artwork/entry'}]}]});
  const page=await api.library();expect(page.collections[0].entries[0].artwork_url).toBe(api.artworkUrl('entry'));
});

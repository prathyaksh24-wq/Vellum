import {describe,expect,test,vi} from 'vitest';
import {readFileSync} from 'node:fs';

const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
const createSource=html.slice(html.indexOf('  const createProject = async'),html.indexOf('  const projectMenuAction'));

function creationHandler(dispatch){
  const ref={current:null},newChat=vi.fn(),close=vi.fn(),move=vi.fn();
  const handler=new Function('projectCreationRef','dispatchConversationAction','setExpandedProj','setSecOpen','setCreateOpen','pendingMoveRef','moveToProject','newProjectChat',createSource+';return createProject;')(
    ref,dispatch,vi.fn(),vi.fn(),close,{current:null},move,newChat);
  return {handler,ref,newChat,close};
}

describe('project creation submission ownership',()=>{
  test('concurrent UI callbacks share one pending request and one navigation',async()=>{
    let resolve;
    const dispatch=vi.fn(()=>new Promise(done=>{resolve=done;}));
    const subject=creationHandler(dispatch);
    const requests=Array.from({length:3},()=>subject.handler({name:'Research',memory:'default'}));
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith('project.create',{name:'Research',memory:'default'});
    resolve({status:'applied',result:{project:{id:'project-1'}}});
    await Promise.all(requests);
    expect(subject.newChat).toHaveBeenCalledExactlyOnceWith('project-1');
    expect(subject.close).toHaveBeenCalledExactlyOnceWith(false);
    expect(subject.ref.current).toBeNull();
  });

  test('failure releases the submission guard for an explicit retry',async()=>{
    const dispatch=vi.fn().mockResolvedValueOnce({status:'failed',message:'Try again'})
      .mockResolvedValueOnce({status:'applied',result:{project:{id:'project-2'}}});
    const subject=creationHandler(dispatch);
    expect((await subject.handler({name:'Research',memory:'default'})).status).toBe('failed');
    expect(subject.newChat).not.toHaveBeenCalled();
    expect(subject.ref.current).toBeNull();
    await subject.handler({name:'Research',memory:'default'});
    expect(dispatch).toHaveBeenCalledTimes(2);
    expect(subject.newChat).toHaveBeenCalledExactlyOnceWith('project-2');
  });
});

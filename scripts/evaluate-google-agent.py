"""Run varied-language requests through Vellum's main graph with synthetic Google data.

Uses the selected model and real tool/action code. Never loads account credentials,
personal memory, other providers' tools, or a live Google transport. Does not confirm writes.
"""
import argparse
import asyncio
from contextlib import ExitStack, nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import RLock
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.app_actions.models import AppActionContext
from agent.app_actions.runtime import AppActionRuntime
from agent.graph import agent as graph
from agent.plugins.google_workspace import GoogleWorkspaceService, SERVICES, WRITE_SCOPES
from agent.plugins.google_workspace_controls import google_contribution
from agent.plugins.registry import PluginRegistry
from agent.tools.app_actions import app_action, app_action_session
from agent.tools.google_workspace import google_api_describe, published_google_tools, google_workspace_read
from agent.tools.registry import ToolRegistry, CapabilityAccess


CASES = [
    ("gmail","formal","read","Please check my latest email and tell me its subject. Read only one message."),
    ("gmail","slang","read","yo any fresh mail? peep the newest one pls"),
    ("gmail","typos","read","chek my gmial inbox, newest msg pls"),
    ("drive","formal","read","Please find one file in my Google Drive and tell me its name."),
    ("drive","slang","read","yo show me the newest file in my drive real quick"),
    ("drive","typos","read","find a flie in gogle drvie plz"),
    ("calendar","formal","read","Please list the next event in my primary Google Calendar."),
    ("calendar","slang","read","bro got any meets on my gcal tmrw?"),
    ("calendar","typos","read","chek my calender nxt meeting pls"),
    ("contacts","formal","read","Please find Casey Fixture in my Google Contacts."),
    ("contacts","slang","read","yo got Casey's number in my contacts?"),
    ("contacts","typos","read","find casey in my contcts plz"),
    ("gmail","formal","write","Create a draft email to friend@example.test, subject Fixture hello, body Hello from the test. Do not send it."),
    ("gmail","slang","write","yo mark Gmail message mail-1 as read pls"),
    ("drive","formal","write","Create a folder named Fixture folder in My Drive."),
    ("drive","typos","write","rename drvie file file-1 to Edited fixture.txt pls"),
    ("calendar","formal","write","Create a primary Google Calendar event called Fixture planning on 2026-10-25 from 15:00 to 15:30 Asia/Kolkata. No guests."),
    ("calendar","slang","write","drop event event-1 from my primary gcal, delete that one only"),
    ("contacts","formal","write","Create a Google contact named Casey Fixture with phone number +12025550123."),
    ("contacts","typos","write","delete contct people/contact-1 from google contacts pls, only that one"),
    ("drive","ambiguous","clarify","yo pull up a file from my drive real quick"),
    ("gmail","recovery","read","summarize today's mail"),
    ("gmail","pagination","paginate","Summarize all my emails from the last 24hrs. Cover the entire time range, tell me how many messages you reviewed, and continue through every page."),
]


class Store:
    def __init__(self):
        self.tokens = {"access_token":"fixture-access", "refresh_token":"fixture-refresh", "expires_at":time.time()+3600,
                       "scope":" ".join({scope for key in SERVICES for scope in SERVICES[key]["scopes"]+WRITE_SCOPES[key]})}
        self.metadata = {"google_account_id":"fixture-account", "google_email":"fixture@example.test", "scope":self.tokens["scope"]}
    def load_metadata(self): return dict(self.metadata)
    def load_tokens(self, required=True): return dict(self.tokens)


async def main(output, only):
    output.parent.mkdir(parents=True,exist_ok=True)
    fixture_root = output.parent / "fixture-plugins"
    for identifier in ["google-workspace",*[item["plugin_id"] for item in SERVICES.values()]]:
        folder=fixture_root/identifier;folder.mkdir(parents=True,exist_ok=True)
        (folder/"plugin.yaml").write_text(f"id: {identifier}\nname: {identifier}\ntype: connector\ncategory: Test\ncapabilities:\n  - google.connection.configure\n  - google.connection.disconnect\n  - google.api.execute\n")
    plugins=PluginRegistry(fixture_root,state_path=output.parent/"fixture-state.json")
    calls=[]
    active_case=[None]
    def request(method,url,**kwargs):
        calls.append({"method":method,"url":url})
        if method!="GET": raise AssertionError("A model attempted to bypass Google write confirmation")
        if 'gmail' in url and active_case[0]==22:
            if url.endswith('/messages'):
                offset=20 if kwargs.get('params',{}).get('pageToken')=='fixture-page-2' else 0
                size=min(20,kwargs.get('params',{}).get('maxResults',20))
                items=[{'id':f'mail-{n}'} for n in range(offset,min(offset+size,27))]
                data={'messages':items,**({'nextPageToken':'fixture-page-2'} if offset+size<27 else {})}
            else:
                identifier=url.rsplit('/',1)[-1]
                data={'id':identifier,'snippet':'Fixture-only project update','payload':{'headers':[{'name':'Subject','value':identifier+' project update'}]}}
        elif 'gmail' in url:
            data={"messages":[{"id":"mail-1","threadId":"thread-1"}]} if url.endswith('/messages') else {"id":"mail-1","snippet":"Fixture message only","payload":{"headers":[{"name":"Subject","value":"Fixture hello"},{"name":"From","value":"friend@example.test"}]}}
        elif '/drive/' in url:
            data={"files":[{"id":"file-1","name":"Fixture note.txt","mimeType":"text/plain"}]} if url.endswith('/files') else {"id":"file-1","name":"Fixture note.txt"}
        elif '/calendar/' in url:
            data={"items":[{"id":"event-1","summary":"Fixture planning","start":{"dateTime":"2026-10-25T15:00:00+05:30"},"end":{"dateTime":"2026-10-25T15:30:00+05:30"}}]} if '/events' in url else {"items":[{"id":"primary","summary":"Fixture calendar","primary":True}]}
        else:
            person={"resourceName":"people/contact-1","names":[{"displayName":"Casey Fixture"}],"phoneNumbers":[{"value":"+12025550123"}]}
            data={"results":[{"person":person}],"connections":[person]}
        return httpx.Response(200,json=data)
    service=GoogleWorkspaceService(store=Store(),registry=plugins,credentials=lambda:('fixture-client',''),request=request)
    runtime=AppActionRuntime(plugin_registry=plugins)
    runtime.register_plugin_contribution(google_contribution(service=service))
    registry=ToolRegistry()
    for tool in [google_workspace_read,google_api_describe,*published_google_tools(),app_action]:
        registry.register_langchain(tool,access=CapabilityAccess.READ if tool.name==google_workspace_read.name else CapabilityAccess.WRITE,allowed_agents=frozenset({'VellumAgent'}))
    tools=registry.langchain_tools(agent_name='VellumAgent')
    graph.get_provider_registry().refresh_local_models()
    model=graph.get_provider_registry().current_model().id
    print(json.dumps({'model':model,'cases':len(CASES),'fixture_only':True}),flush=True)
    results=[]
    with ExitStack() as stack:
        stack.enter_context(patch('agent.plugins.google_workspace.google_service',lambda:service))
        stack.enter_context(patch('agent.plugins.google_api.google_service',lambda:service))
        stack.enter_context(patch('agent.personalization.use_personal_memory',lambda *args:False))
        stack.enter_context(patch('agent.personalization.personalization_instructions',lambda:''))
        stack.enter_context(patch('agent.memory.memory_context.load_soul',lambda:''))
        stack.enter_context(patch.object(graph,'build_skill_activation_block',lambda *args,**kwargs:''))
        stack.enter_context(patch.object(graph,'_specialist_directory_block',lambda:''))
        compiled=graph._build_agent_runtime(llm=graph.build_llm(model),tools=tools,
            deferred_names={tool.name for tool in tools if tool.name not in {'google_workspace_read','app_action'}},
            checkpointer=InMemorySaver(),runtime_model=model)
        print(json.dumps({'stage':'runtime_ready'}),flush=True)
        for index,(service_id,style,expected,prompt) in enumerate(CASES):
            if only and index not in only:continue
            calls.clear();active_case[0]=index;started=time.monotonic()
            print(json.dumps({'stage':'case_start','case':index}),flush=True)
            context=AppActionContext(source='nlp',store_to_memory=False)
            try:
                with app_action_session(context,f'google-fixture-{index}',runtime) as session:
                    messages=([HumanMessage(content='what is on my email?'),AIMessage(content='I do not have access to your email account. There is no email-specific agent or tool connected.')] if index==21 else [])+[HumanMessage(content=prompt)]
                    state=await asyncio.wait_for(compiled.ainvoke({'messages':messages},
                        {'configurable':{'thread_id':f'google-fixture-{index}'},'recursion_limit':24}),timeout=120)
                    tool_calls=[{'name':call['name'],'service':call.get('args',{}).get('service'),'operation':call.get('args',{}).get('operation'),
                                 'method_id':call.get('args',{}).get('method_id')} for message in state['messages'] for call in getattr(message,'tool_calls',[])]
                    receipts=[event['receipt'] for event in session.emitted]
                    marker={'gmail':'gmail.googleapis.com','drive':'/drive/','calendar':'/calendar/','contacts':'people.googleapis.com'}[service_id]
                    reads=bool(calls) and all(call['method']=='GET' for call in calls) and any(marker in call['url'] for call in calls)
                    review=next((receipt for receipt in receipts if receipt.get('status')=='confirmation_required' and receipt.get('result',{}).get('google_review',{}).get('service')==service_id),None)
                    response=str(state['messages'][-1].content)
                    refused=any(text in response.casefold() for text in ['no specialist','no tools','no tool available','do not have access','don’t have access',"don't have access"])
                    expected_method={12:'gmail.users.drafts.create',13:'gmail.users.messages.modify',14:'drive.files.create',15:'drive.files.update',16:'calendar.events.insert',17:'calendar.events.delete',18:'people.people.createContact',19:'people.people.deleteContact'}.get(index)
                    if expected=='write':
                        required={12:['friend@example.test','Fixture hello','Hello from the test.'],13:['mail-1','UNREAD'],
                            14:['Fixture folder','application/vnd.google-apps.folder'],15:['file-1','Edited fixture.txt'],
                            16:['Fixture planning','2026-10-25'],17:['event-1','primary'],
                            18:['Casey','Fixture','+12025550123'],19:['people/contact-1']}[index]
                        fields=json.dumps(review['result']['google_review']['fields']) if review else ''
                        passed=bool(review) and review['result']['google_review']['method_id']==expected_method and all(value.casefold() in fields.casefold() for value in required)
                    elif expected=='paginate':
                        message_reads={call['url'].rsplit('/',1)[-1] for call in calls if '/messages/mail-' in call['url']}
                        passed=reads and len(message_reads)==27 and ('27' in response or 'twenty-seven' in response.lower())
                    elif expected=='clarify':
                        passed=not refused and (reads or ('?' in response and 'file' in response.casefold()))
                    else:
                        passed=reads and not refused
                    row={'case':index,'service':service_id,'style':style,'expected':expected,'prompt':prompt,'passed':passed,
                         'tool_calls':tool_calls,'read_calls':len(calls),'review_prepared':bool(review),'refused_access':refused,
                         'seconds':round(time.monotonic()-started,2)}
                    if review:row['review']=review['result']['google_review']
                    if not passed:
                        row['response_excerpt']=response[:2000]
                        row['tool_results']=[{'name':getattr(message,'name',None),'content':str(message.content)[:2500]} for message in state['messages'] if getattr(message,'type',None)=='tool']
            except Exception as exc:
                row={'case':index,'service':service_id,'style':style,'expected':expected,'prompt':prompt,'passed':False,'error_type':type(exc).__name__,'seconds':round(time.monotonic()-started,2)}
                snapshot=await compiled.aget_state({'configurable':{'thread_id':f'google-fixture-{index}'}})
                messages=snapshot.values.get('messages',[])
                row['tool_results']=[{'name':getattr(message,'name',None),'content':str(message.content)[:2500]} for message in messages if getattr(message,'type',None)=='tool']
                row['tool_calls']=[{'name':call['name'],'arguments':call.get('args',{})} for message in messages for call in getattr(message,'tool_calls',[])]
            results.append(row)
            report={'model':model,'fixture_only':True,'personal_context_disabled':True,'live_google_writes':0,
                    'passed':sum(row['passed'] for row in results),'total':len(results),'results':results}
            output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            print(json.dumps({key:value for key,value in row.items() if key not in {'tool_calls','prompt','response_excerpt','tool_results','review'}}),flush=True)
    return all(row['passed'] for row in results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cases',default='')
    args=parser.parse_args()
    raise SystemExit(0 if asyncio.run(main(args.output,{int(value) for value in args.cases.split(',') if value})) else 1)

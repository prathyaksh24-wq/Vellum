import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadClient(search = "") {
  vi.resetModules();
  window.VellumApi = {};
  window.history.replaceState({}, "", "/" + search);
  localStorage.clear();
  await import("../../../design/Velllum/uploads/api/client.js");
  return window.VellumApi.client;
}

describe("Vellum API client backend selection", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    localStorage.clear();
  });

  test("accepts an explicit loopback backend for isolated local previews", async () => {
    const client = await loadClient("?backend=http%3A%2F%2F127.0.0.1%3A8015");
    expect(client.backendBase()).toBe("http://127.0.0.1:8015");
  });

  test("ignores non-loopback query overrides", async () => {
    const client = await loadClient("?backend=https%3A%2F%2Fexample.com");
    expect(client.backendBase()).toBe("http://127.0.0.1:8000");
  });
});

test("API errors retain structured Calendar conflict details", async()=> {
  const client=await loadClient();
  const detail={message:"Conflict",availability:{available:false}};
  vi.stubGlobal("fetch",vi.fn(async()=>({ok:false,status:409,json:async()=>({detail})})));
  await expect(client.request("/api/plugins/google-calendar/events")).rejects.toMatchObject({status:409,message:"Conflict",detail});
  vi.unstubAllGlobals();
});

test("shows the last known list at once while the backend is still starting", async()=> {
  const client=await loadClient();
  localStorage.setItem("vellum-api-snapshot-v1:/api/plugins",JSON.stringify({saved_at:1,data:{plugins:[{id:"spotify"}]}}));
  let answer;
  vi.stubGlobal("fetch",vi.fn(()=>new Promise(resolve=>{answer=resolve;})));
  const refreshed=vi.fn();
  window.addEventListener("vellum:data-refreshed",refreshed);
  await expect(client.request("/api/plugins")).resolves.toEqual({plugins:[{id:"spotify"}]});
  answer({ok:true,status:200,text:async()=>JSON.stringify({plugins:[{id:"spotify"},{id:"discord"}]})});
  await vi.waitFor(()=>expect(refreshed).toHaveBeenCalledWith(expect.objectContaining({detail:{path:"/api/plugins"}})));
  expect(client.snapshot("/api/plugins")).toEqual({plugins:[{id:"spotify"},{id:"discord"}]});
  window.removeEventListener("vellum:data-refreshed",refreshed);
  vi.unstubAllGlobals();
});

test("reads wait for a backend that is not answering yet instead of failing", async()=> {
  const client=await loadClient();
  window.VELLUM_BACKEND_WAIT_MS=5000;
  let up=false;
  vi.stubGlobal("fetch",vi.fn(async url=>{
    if(!up){up=String(url).endsWith("/health");throw new TypeError("Failed to fetch");}
    return {ok:true,status:200,text:async()=>JSON.stringify({ok:true})};
  }));
  const online=vi.fn();
  window.addEventListener("vellum:backend-online",online);
  await expect(client.request("/api/automations/123")).resolves.toEqual({ok:true});
  expect(online).toHaveBeenCalled();
  window.removeEventListener("vellum:backend-online",online);
  delete window.VELLUM_BACKEND_WAIT_MS;
  vi.unstubAllGlobals();
});

test("writes are never re-sent after a network failure", async()=> {
  const client=await loadClient();
  window.VELLUM_BACKEND_WAIT_MS=5000;
  const fetch=vi.fn(async()=>{throw new TypeError("Failed to fetch");});
  vi.stubGlobal("fetch",fetch);
  await expect(client.request("/api/automations",client.jsonOptions("POST",{name:"x"}))).rejects.toThrow("Failed to fetch");
  expect(fetch.mock.calls.filter(call=>String(call[0]).endsWith("/api/automations"))).toHaveLength(1);
  delete window.VELLUM_BACKEND_WAIT_MS;
  vi.unstubAllGlobals();
});
